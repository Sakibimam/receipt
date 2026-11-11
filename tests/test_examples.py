"""The committed example receipts must keep giving the verdicts the README promises."""

import json
from pathlib import Path

from receipt.verify import verify_receipt

EX = Path("examples")


def load(name: str) -> dict:
    return json.loads((EX / name).read_text())


def test_run_a_verifies() -> None:
    r = load("run_a.receipt.json")
    assert r["gateway"] == "otari" and verify_receipt(r).ok


def test_run_b_fails_on_mandate_only() -> None:
    rep = verify_receipt(load("run_b.receipt.json"))
    assert not rep.ok
    assert [c.name for c in rep.checks if not c.ok] == ["within mandate"]
    assert rep.failing_events == [1, 2, 14, 15]


def test_tampered_fails_integrity() -> None:
    rep = verify_receipt(load("run_a.tampered.json"))
    bad = {c.name for c in rep.checks if not c.ok}
    assert {"signature", "hash chain", "recomputed totals"} <= bad


def test_auditor_receipt_records_otari_mcp_calls() -> None:
    r = load("auditor.receipt.json")
    assert verify_receipt(r).ok
    calls = r["events"][0]["data"]["tool_calls"]
    assert [c["type"] for c in calls] == ["mcp", "mcp"]


def test_run_b_has_live_fallback_and_otari_budget_refusal() -> None:
    r = load("run_b.receipt.json")
    assert r["fallbacks"] and r["fallbacks"][0]["served_model"].lower().startswith("qwen")
    assert any(v["rule"] == "budget_exceeded" for v in r["violations"])
