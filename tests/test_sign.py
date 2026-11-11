from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from receipt.sign import generate_key, load_key, public_key_hex, sign, verify_signature


def test_sign_roundtrip(key: Ed25519PrivateKey) -> None:
    sig = sign(key, "hello")
    assert verify_signature(public_key_hex(key), "hello", sig)
    assert not verify_signature(public_key_hex(key), "hellO", sig)


def test_wrong_key_rejected(key: Ed25519PrivateKey) -> None:
    other = Ed25519PrivateKey.generate()
    assert not verify_signature(public_key_hex(other), "hello", sign(key, "hello"))


def test_garbage_inputs_do_not_raise() -> None:
    assert not verify_signature("zz", "x", "!!")


def test_keygen_file_mode(tmp_path: Path) -> None:
    p = tmp_path / "k" / "signing.key"
    pub = generate_key(p)
    assert (p.stat().st_mode & 0o777) == 0o600
    assert public_key_hex(load_key(p)) == pub
