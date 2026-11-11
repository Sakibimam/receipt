from receipt.witness import compare


def test_compare_matches_and_mismatches() -> None:
    usage = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3, "cost_usd": 0.000017}
    ok = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3, "cost_usd": "0.000017"}
    assert compare(usage, ok) == []
    lie = {**ok, "cost_usd": "0.000500", "total_tokens": 300}
    assert len(compare(usage, lie)) == 2
