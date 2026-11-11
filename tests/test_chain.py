from receipt.chain import GENESIS_HASH, Chain, canonical, verify_chain


def test_canonical_is_sorted_and_compact() -> None:
    assert canonical({"b": 1, "a": [1, 2]}) == '{"a":[1,2],"b":1}'


def test_chain_links_and_verifies() -> None:
    c = Chain()
    e0 = c.append("a", {"x": 1})
    e1 = c.append("b", {"y": 2})
    assert e0["prev_hash"] == GENESIS_HASH
    assert e1["prev_hash"] == e0["hash"]
    assert verify_chain(c.events) == []


def test_edit_reorder_remove_detected() -> None:
    c = Chain()
    for i in range(4):
        c.append("t", {"i": i})
    edited = [dict(e) for e in c.events]
    edited[2] = {**edited[2], "data": {"i": 99}}
    assert 2 in verify_chain(edited)

    reordered = [c.events[0], c.events[2], c.events[1], c.events[3]]
    assert verify_chain(reordered)

    removed = c.events[:1] + c.events[2:]
    assert verify_chain(removed)
