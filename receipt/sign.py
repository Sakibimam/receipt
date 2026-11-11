"""Ed25519 signing for receipts. The private key never leaves ~/.receipt/."""

from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

DEFAULT_KEY_PATH = Path(
    os.environ.get("RECEIPT_KEY_PATH", Path.home() / ".receipt" / "signing.key")
)


def generate_key(path: Path = DEFAULT_KEY_PATH, overwrite: bool = False) -> str:
    """Create a new Ed25519 key at `path` (mode 600). Returns the public key hex."""
    if path.exists() and not overwrite:
        raise FileExistsError(f"key already exists at {path}")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    return public_key_hex(key)


def load_key(path: Path = DEFAULT_KEY_PATH) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(f"{path} is not an Ed25519 private key")
    return key


def load_or_create_key(path: Path = DEFAULT_KEY_PATH) -> Ed25519PrivateKey:
    if not path.exists():
        generate_key(path)
    return load_key(path)


def public_key_hex(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return raw.hex()


def sign(key: Ed25519PrivateKey, payload: str) -> str:
    return base64.b64encode(key.sign(payload.encode("utf-8"))).decode("ascii")


def verify_signature(public_hex: str, payload: str, signature_b64: str) -> bool:
    try:
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_hex))
        pub.verify(base64.b64decode(signature_b64), payload.encode("utf-8"))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
