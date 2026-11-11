"""A recording session: owns the event chain and produces the signed receipt."""

from __future__ import annotations

import uuid
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from receipt.chain import Chain, canonical, now_iso, root_hash
from receipt.sign import public_key_hex, sign

RECEIPT_VERSION = "receipt/0.1"


def signing_payload(receipt: dict[str, Any]) -> str:
    return canonical({k: v for k, v in receipt.items() if k != "signature"})


class Session:
    def __init__(self, agent: str, session_id: str | None = None) -> None:
        self.agent = agent
        self.session_id = session_id or f"ses_{uuid.uuid4().hex[:16]}"
        self.started_at = now_iso()
        self.chain = Chain()

    def record(self, type_: str, data: dict[str, Any]) -> dict[str, Any]:
        return self.chain.append(type_, data)

    def finalize(self, key: Ed25519PrivateKey) -> dict[str, Any]:
        events = self.chain.events
        receipt: dict[str, Any] = {
            "version": RECEIPT_VERSION,
            "session_id": self.session_id,
            "agent": self.agent,
            "started_at": self.started_at,
            "ended_at": now_iso(),
            "event_count": len(events),
            "events_root_hash": root_hash(events),
            "events": events,
            "signer_public_key": public_key_hex(key),
        }
        receipt["signature"] = sign(key, signing_payload(receipt))
        return receipt
