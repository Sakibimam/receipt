"""Mandate: the limits an agent session must stay inside, and the per-event checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from receipt.chain import canonical, sha256_hex

CALL_EVENTS = ("llm_call", "llm_error")
ENFORCED_ERROR_CODES = ("budget_exceeded", "guardrail_violation", "end_user_limit_reached")


class Mandate(BaseModel):
    name: str = "default"
    allowed_models: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    blocked_tools: list[str] = Field(default_factory=list)
    budget_usd: float = 0.0
    max_requests: int = 0
    end_user: str | None = None
    end_user_budget: str | None = None
    # Client-side pre-check before each call (blocked calls are still signed in as
    # violation_attempt events). Otari-side enforcement happens regardless.
    enforce: bool = True

    def digest(self) -> str:
        return sha256_hex(canonical(self.model_dump()))

    def model_allowed(self, model: str) -> bool:
        return model in self.allowed_models

    def tool_allowed(self, tool: str) -> bool:
        return tool not in self.blocked_tools and tool in self.allowed_tools

    def precheck(
        self, model: str, tools: list[str], spent_usd: float, requests: int
    ) -> list[dict[str, str]]:
        """Client-side check before a call is sent. Returns the rules it would break."""
        problems: list[dict[str, str]] = []
        if not self.model_allowed(model):
            problems.append({"rule": "allowed_models", "detail": f"model {model} not allowed"})
        for t in tools:
            if not self.tool_allowed(t):
                problems.append({"rule": "allowed_tools", "detail": f"tool {t} not allowed"})
        if self.max_requests and requests >= self.max_requests:
            problems.append(
                {"rule": "max_requests", "detail": f"limit {self.max_requests} reached"}
            )
        if self.budget_usd and spent_usd >= self.budget_usd:
            problems.append(
                {"rule": "budget_usd", "detail": f"spent {spent_usd:.6f} of {self.budget_usd}"}
            )
        return problems


def load_mandate(path: Path) -> Mandate:
    return Mandate.model_validate(yaml.safe_load(path.read_text()) or {})


def check_events(events: list[dict[str, Any]], mandate: Mandate) -> list[dict[str, Any]]:
    """Replay every event against the mandate. Returns violations with event indexes."""
    violations: list[dict[str, Any]] = []
    spent = 0.0
    requests = 0

    def add(idx: int, rule: str, detail: str) -> None:
        violations.append({"event_index": idx, "rule": rule, "detail": detail})

    for ev in events:
        idx, typ, data = ev["index"], ev["type"], ev.get("data", {})
        if typ == "violation_attempt":
            for p in data.get("problems", []):
                add(idx, p.get("rule", "?"), "blocked before sending: " + p.get("detail", ""))
            continue
        if typ == "sandbox_exec":
            if not mandate.tool_allowed("otari_code_execution"):
                add(idx, "allowed_tools", "code execution not allowed")
            continue
        if typ not in CALL_EVENTS:
            continue
        req = data.get("request", {})
        requests += 1
        model = req.get("model", "")
        if not mandate.model_allowed(model):
            add(idx, "allowed_models", f"model {model} not allowed")
        for t in req.get("tools", []):
            if not mandate.tool_allowed(t):
                add(idx, "allowed_tools", f"tool {t} not allowed")
        if mandate.max_requests and requests > mandate.max_requests:
            add(idx, "max_requests", f"request {requests} > {mandate.max_requests}")
        before = spent
        spent += float(data.get("usage", {}).get("cost_usd") or 0.0)
        if mandate.budget_usd and spent > mandate.budget_usd >= before:
            add(idx, "budget_usd", f"spend {spent:.6f} > budget {mandate.budget_usd}")
        code = (data.get("error") or {}).get("code")
        if typ == "llm_error" and code in ENFORCED_ERROR_CODES:
            add(idx, code, f"Otari refused: HTTP {data.get('status')} {code}")
    return violations
