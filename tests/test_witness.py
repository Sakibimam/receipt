from receipt.witness import compare


def test_compare_matches_and_mismatches() -> None:
    usage = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3, "cost_usd": 0.000017}
    ok = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3, "cost_usd": "0.000017"}
    assert compare(usage, ok) == []
    lie = {**ok, "cost_usd": "0.000500", "total_tokens": 300}
    assert len(compare(usage, lie)) == 2


def test_refused_unbilled_call_without_ledger_row_matches(monkeypatch) -> None:
    """Regression: a 403-refused sandbox call has no ledger row and was flagged missing."""
    import receipt.witness as w

    monkeypatch.setattr(w, "ledger_lookup", lambda *a, **k: None)
    events = [
        {
            "index": 0,
            "type": "sandbox_exec",
            "data": {
                "status": 403,
                "usage": {"cost_usd": 0.0},
                "headers": {"Otari-Request-ID": "r"},
            },
        },
        {
            "index": 1,
            "type": "llm_call",
            "data": {
                "status": 200,
                "usage": {"cost_usd": 0.01},
                "headers": {"Otari-Request-ID": "q"},
            },
        },
    ]
    rows = w.witness_events(events, api_key="k", base_url="http://x")
    assert [r["status"] for r in rows] == ["matched", "missing"]
