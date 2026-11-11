import copy

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from receipt.mock import MockGateway
from receipt.session import Session
from receipt.sign import public_key_hex
from receipt.verify import verify_receipt


def make_receipt(key: Ed25519PrivateKey) -> dict:
    gw = MockGateway()
    s = Session(agent="test")
    for m in ("mock/a", "mock/b", "mock/c"):
        resp = gw.chat(m, [{"role": "user", "content": "hi"}])
        s.record("llm_call", {"model": m, "response": resp})
    return s.finalize(key)


def test_valid_receipt_passes(key: Ed25519PrivateKey) -> None:
    r = make_receipt(key)
    assert verify_receipt(r).ok
    assert verify_receipt(r, expected_key=public_key_hex(key)).ok


def test_edited_event_fails(key: Ed25519PrivateKey) -> None:
    r = copy.deepcopy(make_receipt(key))
    r["events"][1]["data"]["response"]["usage"]["cost_usd"] = 0
    rep = verify_receipt(r)
    assert not rep.ok and 1 in rep.failing_events


def test_resigned_with_other_key_fails_expected_key(key: Ed25519PrivateKey) -> None:
    r = make_receipt(key)
    other = Ed25519PrivateKey.generate()
    assert not verify_receipt(r, expected_key=public_key_hex(other)).ok


def test_header_field_edit_breaks_signature(key: Ed25519PrivateKey) -> None:
    r = make_receipt(key)
    r["agent"] = "someone-else"
    assert not verify_receipt(r).ok
