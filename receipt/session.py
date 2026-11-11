"""A recording session: owns the event chain and produces the signed receipt."""

from __future__ import annotations

import uuid
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from receipt.chain import Chain, canonical, now_iso, root_hash
from receipt.mandate import CALL_EVENTS, Mandate
from receipt.model import RECEIPT_VERSION, Receipt, derive
from receipt.sign import public_key_hex, sign


def signing_payload(receipt: dict[str, Any]) -> str:
    return canonical({k: v for k, v in receipt.items() if k != "signature"})


class Session:
    def __init__(
        self,
        agent: str,
        mandate: Mandate | None = None,
        gateway: str = "mock",
        session_id: str | None = None,
    ) -> None:
        self.agent = agent
        # No mandate = a record without limits: allow whatever the session used.
        self.mandate = mandate
        self.gateway = gateway
        self.session_id = session_id or f"ses_{uuid.uuid4().hex[:16]}"
        self.started_at = now_iso()
        self.chain = Chain()

    def record(self, type_: str, data: dict[str, Any]) -> dict[str, Any]:
        return self.chain.append(type_, data)

    def spent_usd(self) -> float:
        return sum(
            float(e["data"].get("usage", {}).get("cost_usd") or 0.0)
            for e in self.chain.events
            if e["type"] in CALL_EVENTS
        )

    def requests(self) -> int:
        return sum(1 for e in self.chain.events if e["type"] in CALL_EVENTS)

    def effective_mandate(self) -> Mandate:
        if self.mandate is not None:
            return self.mandate
        return unrestricted_mandate(self.chain.events)

    def finalize(self, key: Ed25519PrivateKey) -> dict[str, Any]:
        events = self.chain.events
        mandate = self.effective_mandate()
        receipt = Receipt(
            version=RECEIPT_VERSION,
            session_id=self.session_id,
            agent=self.agent,
            gateway=self.gateway,
            started_at=self.started_at,
            ended_at=now_iso(),
            mandate=mandate.model_dump(),
            mandate_hash=mandate.digest(),
            events_root_hash=root_hash(events),
            event_count=len(events),
            events=events,
            signer_public_key=public_key_hex(key),
            **derive(events, mandate),
        ).model_dump()
        receipt["signature"] = sign(key, signing_payload(receipt))
        return receipt


def unrestricted_mandate(events: list[dict[str, Any]]) -> Mandate:
    models = sorted({e["data"].get("request", {}).get("model", "") for e in events})
    tools = sorted(
        {t for e in events for t in e["data"].get("request", {}).get("tools", [])}
        | {"otari_code_execution"}
    )
    return Mandate(name="unrestricted", allowed_models=models, allowed_tools=tools)
