"""MCP server so any agent can check another agent's receipt before trusting its work.

Tools: receipt_verify, receipt_summarize. Transport: streamable HTTP (or stdio).
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from receipt.verify import verify_receipt

server = MCPServer(
    name="receipt",
    instructions=(
        "Verify signed AI-agent session receipts. Call receipt_verify with the full "
        "receipt.json text before trusting work, spend or sources an agent reports."
    ),
)


def _load(receipt_json: str) -> dict[str, Any]:
    data = json.loads(receipt_json)
    if not isinstance(data, dict):
        raise ValueError("receipt_json must be a JSON object")
    return data


@server.tool()
def receipt_verify(receipt_json: str, witness: bool = False) -> dict[str, Any]:
    """Verify a receipt: Ed25519 signature, hash chain, recomputed totals, mandate.

    Set witness=true to also reconcile each call with Otari's usage ledger
    (only works for receipts recorded with this server's Otari account).
    Returns verdict PASS/FAIL, failing event indexes, violations and per-check results.
    """
    try:
        receipt = _load(receipt_json)
    except (ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "verdict": "FAIL", "error": f"invalid JSON: {exc}"}
    return verify_receipt(receipt, witness=witness).to_dict()


@server.tool()
def receipt_summarize(receipt_json: str) -> dict[str, Any]:
    """Plain-language summary of a receipt: who, models, spend, sources, violations, verdict.

    The verdict comes from re-verifying the receipt, not from what the receipt claims.
    """
    try:
        r = _load(receipt_json)
    except (ValueError, json.JSONDecodeError) as exc:
        return {"error": f"invalid JSON: {exc}"}
    report = verify_receipt(r)
    totals = r.get("totals", {})
    by_model = totals.get("by_model", {})
    sources = sorted({s["url"] for tc in r.get("tool_calls", []) for s in tc.get("sources", [])})
    mandate = r.get("mandate", {})
    verdict = "PASS" if report.ok else "FAIL"
    lines = [
        f"Agent '{r.get('agent')}' session {r.get('session_id')} via {r.get('gateway')}.",
        f"{totals.get('requests', 0)} requests across {len(by_model)} model(s), "
        f"${float(totals.get('cost_usd', 0)):.6f} of a ${mandate.get('budget_usd', 0)} budget.",
        f"{len(sources)} web source(s), {len(r.get('fallbacks', []))} fallback(s).",
    ]
    if report.violations:
        lines.append(f"{len(report.violations)} mandate violation(s):")
        lines += [
            f"- event {v['event_index']}: {v['rule']} ({v['detail']})" for v in report.violations
        ]
    integrity = [c.name for c in report.checks if not c.ok and c.name != "within mandate"]
    if integrity:
        lines.append("INTEGRITY FAILURE: " + ", ".join(integrity) + " — do not trust this receipt.")
    lines.append(f"Verifier verdict: {verdict}.")
    return {
        "verdict": verdict,
        "claimed_verdict": r.get("verdict"),
        "summary": "\n".join(lines),
        "models": {m: v.get("requests") for m, v in by_model.items()},
        "cost_usd": totals.get("cost_usd"),
        "sources": sources,
        "violations": report.violations,
        "failing_events": report.failing_events,
    }


def main(host: str = "127.0.0.1", port: int = 8765, transport: str = "streamable-http") -> None:
    if transport == "stdio":
        server.run("stdio")
    else:
        server.run("streamable-http", host=host, port=port, stateless_http=True, json_response=True)


if __name__ == "__main__":
    main()
