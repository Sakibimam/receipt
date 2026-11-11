"""Otari client: the OpenAI SDK pointed at Otari, recording every call into the session chain.

Non-streaming only (see otari#2727). With no OTARI_API_KEY the client falls back to the
clearly labelled MockGateway and every event carries `"mock": true`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

from receipt.chain import canonical, sha256_hex
from receipt.mock import MockGateway
from receipt.session import Session

DEFAULT_BASE_URL = "https://api.otari.ai/api/v1"
CAPTURED_HEADERS = (
    "Otari-Request-ID",
    "Otari-Model",
    "Otari-Provider",
    "Otari-Fallback",
    "Otari-Attempt-Count",
    "Otari-Response-Duration-Ms",
    "Otari-Budget-Scope",
    "Otari-Error-Code",
    "Otari-Container-Id",
    "Retry-After",
)
MAX_TEXT = 2000


def pick_headers(headers: Any) -> dict[str, str]:
    """Keep only Otari headers we care about. Never auth headers."""
    out: dict[str, str] = {}
    for name in CAPTURED_HEADERS:
        value = headers.get(name) if headers is not None else None
        if value is not None:
            out[name] = str(value)
    return out


def parse_cost(value: Any) -> float:
    """Otari returns usage.cost_usd as a six-decimal string; tolerate numbers too."""
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def summarize_tool_calls(calls: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in calls or []:
        entry = {k: c.get(k) for k in ("id", "type", "status", "query", "url", "exit_code", "name")}
        entry = {k: v for k, v in entry.items() if v is not None}
        if c.get("sources"):
            entry["sources"] = [
                {"url": s.get("url"), "title": s.get("title")} for s in c["sources"] if s
            ]
        for k in ("stdout", "stderr", "error", "output"):
            if c.get(k):
                entry[k] = str(c[k])[:MAX_TEXT]
        out.append(entry)
    return out


@dataclass
class CallResult:
    ok: bool
    status: int
    model: str
    content: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, Any] | None = None
    event: dict[str, Any] | None = None
    blocked: bool = False


class OtariClient:
    def __init__(
        self,
        session: Session,
        api_key: str | None = None,
        base_url: str | None = None,
        force_mock: bool = False,
        keep_content: bool = True,
    ) -> None:
        load_dotenv()
        self.session = session
        self.keep_content = keep_content
        self.base_url = base_url or os.environ.get("OTARI_BASE_URL") or DEFAULT_BASE_URL
        key = api_key or os.environ.get("OTARI_API_KEY") or ""
        self.mock = force_mock or not key
        self._mock_gw = MockGateway()
        self._sdk = None
        if not self.mock:
            from openai import OpenAI

            self._sdk = OpenAI(api_key=key, base_url=self.base_url, max_retries=0, timeout=120)

    @property
    def gateway(self) -> str:
        return "mock" if self.mock else "otari"

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        role: str = "",
        tools: list[dict[str, Any]] | None = None,
        user: str | None = None,
        end_user_budget: str | None = None,
        metadata: dict[str, str] | None = None,
        max_tokens: int | None = None,
    ) -> CallResult:
        request = {
            "model": model,
            "role": role,
            "messages": len(messages),
            "tools": [t.get("type") for t in tools or []],
            "user": user,
            "end_user_budget": end_user_budget,
            "metadata": metadata,
            # Content is committed by hash so receipts can be shared without leaking prompts.
            "messages_sha256": sha256_hex(canonical(messages)),
        }
        mandate = self.session.mandate
        if mandate is not None:
            # Map the mandate onto Otari enforcement: end-user tag + end-user budget.
            if mandate.end_user and not metadata:
                metadata = {"end_user": mandate.end_user}
                request["metadata"] = metadata
            if mandate.end_user_budget and not end_user_budget:
                end_user_budget = mandate.end_user_budget
                request["end_user_budget"] = end_user_budget
            if mandate.enforce:
                problems = mandate.precheck(
                    model,
                    [str(t) for t in request["tools"]],
                    self.session.spent_usd(),
                    self.session.requests(),
                )
                if problems:
                    event = self.session.record(
                        "violation_attempt",
                        {"gateway": self.gateway, "request": request, "problems": problems},
                    )
                    return CallResult(
                        ok=False,
                        status=0,
                        model=model,
                        blocked=True,
                        error={"code": "blocked_by_mandate", "detail": problems},
                        event=event,
                    )
        result = (
            self._mock_call(model, messages)
            if self.mock
            else self._live_call(
                model, messages, tools, user, end_user_budget, metadata, max_tokens
            )
        )
        data = {
            "gateway": self.gateway,
            "mock": self.mock,
            "request": request,
            "status": result.status,
            "headers": result.headers,
            "response_model": result.model,
            "usage": result.usage,
            "tool_calls": result.tool_calls,
            "content_sha256": sha256_hex(result.content),
            "content_preview": result.content[:MAX_TEXT] if self.keep_content else "",
        }
        if result.error:
            data["error"] = result.error
        result.event = self.session.record("llm_call" if result.ok else "llm_error", data)
        return result

    def _mock_call(self, model: str, messages: list[dict[str, Any]]) -> CallResult:
        r = self._mock_gw.chat(model, messages)
        return CallResult(
            ok=True,
            status=r["status"],
            model=model,
            content=r["content"],
            headers=r["headers"],
            usage=normalize_usage(r["usage"]),
            tool_calls=[],
        )

    def _live_call(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        user: str | None,
        end_user_budget: str | None,
        metadata: dict[str, str] | None,
        max_tokens: int | None,
    ) -> CallResult:
        from openai import APIStatusError

        assert self._sdk is not None
        extra_headers = {"Otari-End-User-Budget": end_user_budget} if end_user_budget else None
        extra_body: dict[str, Any] = {}
        if tools:
            extra_body["tools"] = tools
        if metadata:
            extra_body["metadata"] = metadata
        kwargs: dict[str, Any] = {"model": model, "messages": messages, "stream": False}
        if user:
            kwargs["user"] = user
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        try:
            raw = self._sdk.chat.completions.with_raw_response.create(
                **kwargs, extra_headers=extra_headers, extra_body=extra_body or None
            )
        except APIStatusError as exc:
            body: Any
            try:
                body = exc.response.json()
            except ValueError:
                body = {"detail": exc.response.text[:MAX_TEXT]}
            code = body.get("code") if isinstance(body, dict) else None
            detail = body.get("detail") if isinstance(body, dict) else body
            return CallResult(
                ok=False,
                status=exc.status_code,
                model=model,
                headers=pick_headers(exc.response.headers),
                error={"code": code, "detail": str(detail)[:MAX_TEXT]},
            )
        body = raw.http_response.json()
        choice = (body.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        return CallResult(
            ok=True,
            status=raw.http_response.status_code,
            model=body.get("model", model),
            content=content,
            headers=pick_headers(raw.headers),
            usage=normalize_usage(body.get("usage") or {}),
            tool_calls=summarize_tool_calls(body.get("otari_tool_calls")),
        )


def normalize_usage(usage: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
        "cost_usd": parse_cost(usage.get("cost_usd")),
        "cost_usd_raw": None if usage.get("cost_usd") is None else str(usage.get("cost_usd")),
        "pricing_source": usage.get("pricing_source"),
    }
