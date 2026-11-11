import copy
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from receipt.chain import canonical
from receipt.mandate import Mandate
from receipt.session import signing_payload
from receipt.sign import public_key_hex, sign
from receipt.verify import verify_receipt
from tests.helpers import MANDATE, make_receipt


def failed(rep, name: str) -> bool:
    return any(c.name == name and not c.ok for c in rep.checks)


def resign(r: dict, key: Ed25519PrivateKey) -> dict:
    r["signature"] = sign(key, signing_payload(r))
    return r


def test_valid_receipt_passes(key: Ed25519PrivateKey) -> None:
    r = make_receipt(key)
    rep = verify_receipt(r, expected_key=public_key_hex(key))
    assert rep.ok, rep.render()
    assert r["verdict"] == "VERIFIED"
    assert r["totals"]["requests"] == 2
    assert set(r["totals"]["by_model"]) == {"mock/a", "mock/b"}


def test_receipt_survives_json_roundtrip(key: Ed25519PrivateKey) -> None:
    r = json.loads(json.dumps(make_receipt(key), indent=2))
    assert verify_receipt(r).ok


def test_edited_total_cost_fails(key: Ed25519PrivateKey) -> None:
    r = make_receipt(key)
    r["totals"]["cost_usd"] = 0.0
    rep = verify_receipt(r)
    assert failed(rep, "signature") and failed(rep, "recomputed totals")


def test_edited_total_fails_even_if_resigned(key: Ed25519PrivateKey) -> None:
    """A signer who lies in the summary is caught by recomputation."""
    r = make_receipt(key)
    r["totals"]["cost_usd"] = 0.0
    rep = verify_receipt(resign(r, key))
    assert not failed(rep, "signature") and failed(rep, "recomputed totals")


def test_edited_event_cost_fails(key: Ed25519PrivateKey) -> None:
    r = make_receipt(key)
    r["events"][1]["data"]["usage"]["cost_usd"] = 0.0
    rep = verify_receipt(r)
    assert failed(rep, "hash chain") and 1 in rep.failing_events


def test_removed_event_fails(key: Ed25519PrivateKey) -> None:
    r = make_receipt(key)
    del r["events"][0]
    rep = verify_receipt(r)
    assert failed(rep, "hash chain") and failed(rep, "event count")


def test_reordered_events_fail(key: Ed25519PrivateKey) -> None:
    r = make_receipt(key)
    r["events"].reverse()
    assert failed(verify_receipt(r), "hash chain")


def test_wrong_key_fails(key: Ed25519PrivateKey) -> None:
    r = make_receipt(key)
    other = Ed25519PrivateKey.generate()
    r["signer_public_key"] = public_key_hex(other)
    assert failed(verify_receipt(r), "signature")
    assert failed(
        verify_receipt(make_receipt(key), expected_key=public_key_hex(other)), "signer key"
    )


def test_loosened_mandate_fails(key: Ed25519PrivateKey) -> None:
    r = make_receipt(key)
    r["mandate"]["budget_usd"] = 999
    assert failed(verify_receipt(resign(r, key)), "mandate hash")


def test_out_of_mandate_model_fails_with_index(key: Ed25519PrivateKey) -> None:
    r = make_receipt(key, models=("mock/a", "mock/rogue"))
    rep = verify_receipt(r)
    assert r["verdict"] == "FAILED"
    assert failed(rep, "within mandate") and rep.failing_events == [1]


def test_budget_crossing_flags_one_event(key: Ed25519PrivateKey) -> None:
    tight = Mandate(**{**MANDATE.model_dump(), "budget_usd": 1e-9})
    r = make_receipt(key, mandate=tight)
    budget = [v for v in r["violations"] if v["rule"] == "budget_usd"]
    assert [v["event_index"] for v in budget] == [0]


def test_schema_garbage_fails_cleanly() -> None:
    assert not verify_receipt({"hello": "world"}).ok


def test_canonical_payload_excludes_signature(key: Ed25519PrivateKey) -> None:
    r = make_receipt(key)
    assert '"signature"' not in signing_payload(r)
    assert canonical(copy.deepcopy(r)) == canonical(r)
