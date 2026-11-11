"""Second witness: reconcile every recorded call with Otari's own usage ledger.

The client could lie about cost. Otari can't be edited by the client. For each
`llm_call` that carries an Otari-Request-ID we fetch GET /usage/requests/{id}
and compare cost and token counts with what the receipt claims.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
from dotenv import load_dotenv

from receipt.client import DEFAULT_BASE_URL


def ledger_lookup(
    request_id: str, api_key: str, base_url: str, retries: int = 3
) -> dict[str, Any] | None:
    url = f"{base_url}/usage/requests/{request_id}"
    for attempt in range(retries):
        r = httpx.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code != 404:
            return {"error": r.status_code}
        time.sleep(1.5 * (attempt + 1))  # ledger rows land asynchronously
    return None


def witness_events(
    events: list[dict[str, Any]],
    api_key: str | None = None,
    base_url: str | None = None,
) -> list[dict[str, Any]]:
    """Return one result row per live call: matched / mismatch / missing."""
    load_dotenv()
    api_key = api_key or os.environ.get("OTARI_API_KEY", "")
    base_url = base_url or os.environ.get("OTARI_BASE_URL") or DEFAULT_BASE_URL
    rows: list[dict[str, Any]] = []
    for ev in events:
        data = ev.get("data", {})
        priced_sandbox = ev["type"] == "sandbox_exec" and "usage" in data
        if (ev["type"] != "llm_call" and not priced_sandbox) or data.get("mock"):
            continue
        rid = data.get("headers", {}).get("Otari-Request-ID")
        if not rid:
            continue
        found = ledger_lookup(rid, api_key, base_url) if api_key else {"error": "no key"}
        usage = data.get("usage", {})
        row: dict[str, Any] = {"event_index": ev["index"], "request_id": rid}
        if not found or "error" in found:
            row.update(status="missing", ledger=found)
        else:
            diffs = compare(usage, found)
            row.update(status="mismatch" if diffs else "matched", diffs=diffs)
            row["ledger"] = {k: found.get(k) for k in ("cost_usd", "total_tokens", "status")}
        rows.append(row)
    return rows


def compare(usage: dict[str, Any], ledger: dict[str, Any]) -> list[str]:
    diffs: list[str] = []
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if ledger.get(k) is not None and int(ledger[k]) != int(usage.get(k) or 0):
            diffs.append(f"{k}: receipt {usage.get(k)} vs otari {ledger[k]}")
    if ledger.get("cost_usd") is not None:
        if abs(float(ledger["cost_usd"]) - float(usage.get("cost_usd") or 0)) > 1e-6:
            diffs.append(f"cost_usd: receipt {usage.get('cost_usd')} vs otari {ledger['cost_usd']}")
    return diffs
