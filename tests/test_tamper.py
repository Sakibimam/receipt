from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from receipt.verify import verify_receipt
from tests.helpers import make_receipt


def test_header_field_edit_breaks_signature(key: Ed25519PrivateKey) -> None:
    r = make_receipt(key)
    r["agent"] = "someone-else"
    assert not verify_receipt(r).ok


def test_content_is_committed_by_hash(key: Ed25519PrivateKey) -> None:
    r = make_receipt(key)
    data = r["events"][0]["data"]
    assert len(data["request"]["messages_sha256"]) == 64
    assert len(data["content_sha256"]) == 64
