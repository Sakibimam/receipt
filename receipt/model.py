"""receipt.json schema and the pure derivation of totals/tool calls/fallbacks from events."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from receipt.mandate import CALL_EVENTS, Mandate, check_events

RECEIPT_VERSION = "receipt/1.0"
COST_PLACES = 8
SANDBOX_KEY = "otari_code_execution"


class ModelTotals(BaseModel):
    requests: int = 0
    errors: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class Totals(BaseModel):
    requests: int = 0
    cost_usd: float = 0.0
    total_tokens: int = 0
    by_model: dict[str, ModelTotals] = Field(default_factory=dict)


class ToolCall(BaseModel):
    event_index: int
    id: str | None = None
    type: str | None = None
    status: str | None = None
    query: str | None = None
    url: str | None = None
    exit_code: int | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)


class Fallback(BaseModel):
    event_index: int
    requested_model: str
    served_model: str | None = None
    attempt_count: str | None = None


class Violation(BaseModel):
    event_index: int
    rule: str
    detail: str


class Receipt(BaseModel):
    version: str = RECEIPT_VERSION
    session_id: str
    agent: str
    gateway: str
    started_at: str
    ended_at: str
    mandate: dict[str, Any]
    mandate_hash: str
    events_root_hash: str
    event_count: int
    totals: Totals
    tool_calls: list[ToolCall]
    fallbacks: list[Fallback]
    violations: list[Violation]
    verdict: Literal["VERIFIED", "FAILED"]
    events: list[dict[str, Any]]
    signer_public_key: str
    signature: str = ""


def derive(events: list[dict[str, Any]], mandate: Mandate) -> dict[str, Any]:
    """Everything in a receipt that is computed from events. Verifier recomputes this."""
    totals = Totals()
    tool_calls: list[ToolCall] = []
    fallbacks: list[Fallback] = []
    for ev in events:
        idx, typ, data = ev["index"], ev["type"], ev.get("data", {})
        if typ == "sandbox_exec" and data.get("tool_call"):
            tool_calls.append(ToolCall(event_index=idx, **data["tool_call"]))
        if typ == "sandbox_exec" and "usage" in data:
            st = totals.by_model.setdefault(SANDBOX_KEY, ModelTotals())
            st.requests += 1
            st.errors += 0 if data.get("status") == 200 else 1
            cost = float(data["usage"].get("cost_usd") or 0.0)
            st.cost_usd = round(st.cost_usd + cost, COST_PLACES)
        if typ not in CALL_EVENTS:
            continue
        model = data.get("request", {}).get("model", "?")
        mt = totals.by_model.setdefault(model, ModelTotals())
        usage = data.get("usage", {})
        mt.requests += 1
        mt.errors += 1 if typ == "llm_error" else 0
        mt.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        mt.completion_tokens += int(usage.get("completion_tokens") or 0)
        mt.total_tokens += int(usage.get("total_tokens") or 0)
        mt.cost_usd = round(mt.cost_usd + float(usage.get("cost_usd") or 0.0), COST_PLACES)
        for tc in data.get("tool_calls", []):
            tool_calls.append(ToolCall(event_index=idx, **tc_fields(tc)))
        headers = data.get("headers", {})
        if str(headers.get("Otari-Fallback", "")).lower() == "true":
            fallbacks.append(
                Fallback(
                    event_index=idx,
                    requested_model=model,
                    served_model=headers.get("Otari-Model"),
                    attempt_count=headers.get("Otari-Attempt-Count"),
                )
            )
    totals.requests = sum(m.requests for m in totals.by_model.values())
    totals.total_tokens = sum(m.total_tokens for m in totals.by_model.values())
    totals.cost_usd = round(sum(m.cost_usd for m in totals.by_model.values()), COST_PLACES)
    violations = [Violation(**v) for v in check_events(events, mandate)]
    return {
        "totals": totals.model_dump(),
        "tool_calls": [t.model_dump() for t in tool_calls],
        "fallbacks": [f.model_dump() for f in fallbacks],
        "violations": [v.model_dump() for v in violations],
        "verdict": "FAILED" if violations else "VERIFIED",
    }


def tc_fields(tc: dict[str, Any]) -> dict[str, Any]:
    keys = ToolCall.model_fields.keys() - {"event_index"}
    return {k: tc[k] for k in keys if k in tc}
