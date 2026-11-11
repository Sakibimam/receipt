from __future__ import annotations

from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from receipt.client import OtariClient
from receipt.mandate import Mandate
from receipt.session import Session

MANDATE = Mandate(
    name="test",
    allowed_models=["mock/a", "mock/b"],
    allowed_tools=["otari_code_execution"],
    budget_usd=1.0,
    max_requests=10,
)


def make_receipt(
    key: Ed25519PrivateKey,
    mandate: Mandate = MANDATE,
    models: tuple[str, ...] = ("mock/a", "mock/b"),
) -> dict[str, Any]:
    s = Session(agent="test", mandate=mandate)
    c = OtariClient(s, force_mock=True)
    for m in models:
        c.chat(m, [{"role": "user", "content": "hello there"}])
    return s.finalize(key)
