from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from receipt.client import OtariClient
from receipt.mandate import Mandate, load_mandate
from receipt.session import Session
from receipt.verify import verify_receipt
from tests.helpers import MANDATE


def test_repo_mandate_loads() -> None:
    m = load_mandate(Path("mandate.yaml"))
    assert m.allowed_models and m.budget_usd > 0
    assert m.digest() == load_mandate(Path("mandate.yaml")).digest()


def test_disallowed_model_blocked_and_signed(key: Ed25519PrivateKey) -> None:
    s = Session(agent="t", mandate=MANDATE)
    c = OtariClient(s, force_mock=True)
    r = c.chat("mock/forbidden", [{"role": "user", "content": "x"}])
    assert r.blocked and not r.ok
    assert s.chain.events[-1]["type"] == "violation_attempt"
    assert s.requests() == 0  # nothing was sent
    receipt = s.finalize(key)
    rep = verify_receipt(receipt)
    assert receipt["verdict"] == "FAILED" and rep.failing_events == [0]
    assert rep.violations[0]["rule"] == "allowed_models"


def test_blocked_tool(key: Ed25519PrivateKey) -> None:
    m = Mandate(**{**MANDATE.model_dump(), "blocked_tools": ["otari_web_fetch"]})
    s = Session(agent="t", mandate=m)
    r = OtariClient(s, force_mock=True).chat(
        "mock/a", [{"role": "user", "content": "x"}], tools=[{"type": "otari_web_fetch"}]
    )
    assert r.blocked


def test_max_requests_blocks_next_call() -> None:
    m = Mandate(**{**MANDATE.model_dump(), "max_requests": 1})
    s = Session(agent="t", mandate=m)
    c = OtariClient(s, force_mock=True)
    assert c.chat("mock/a", [{"role": "user", "content": "x"}]).ok
    assert c.chat("mock/a", [{"role": "user", "content": "x"}]).blocked


def test_mandate_maps_end_user_to_metadata() -> None:
    m = Mandate(**{**MANDATE.model_dump(), "end_user": "u1", "end_user_budget": "b1"})
    s = Session(agent="t", mandate=m)
    OtariClient(s, force_mock=True).chat("mock/a", [{"role": "user", "content": "x"}])
    req = s.chain.events[0]["data"]["request"]
    assert req["metadata"] == {"end_user": "u1"} and req["end_user_budget"] == "b1"


def test_otari_budget_refusal_is_violation(key: Ed25519PrivateKey) -> None:
    s = Session(agent="t", mandate=MANDATE)
    s.record(
        "llm_error",
        {
            "request": {"model": "mock/a", "tools": []},
            "status": 403,
            "usage": {},
            "error": {"code": "budget_exceeded", "detail": "x"},
        },
    )
    rep = verify_receipt(s.finalize(key))
    assert any(v["rule"] == "budget_exceeded" for v in rep.violations)
