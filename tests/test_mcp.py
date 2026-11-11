import json

import anyio
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp import Client

from receipt.mcp_server import server
from tests.helpers import make_receipt


def _call(tool: str, args: dict) -> dict:
    async def go() -> dict:
        async with Client(server) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert {"receipt_verify", "receipt_summarize"} <= names
            res = await client.call_tool(tool, args)
            assert not res.is_error, res
            if res.structured_content:
                sc = res.structured_content
                return sc.get("result", sc)
            return json.loads(res.content[0].text)

    return anyio.run(go)


def test_mcp_verify_pass_and_tamper(key: Ed25519PrivateKey) -> None:
    r = make_receipt(key)
    assert _call("receipt_verify", {"receipt_json": json.dumps(r)})["verdict"] == "PASS"
    r["totals"]["cost_usd"] = 0
    assert _call("receipt_verify", {"receipt_json": json.dumps(r)})["verdict"] == "FAIL"


def test_mcp_summarize_reports_violation(key: Ed25519PrivateKey) -> None:
    r = make_receipt(key, models=("mock/a", "mock/rogue"))
    out = _call("receipt_summarize", {"receipt_json": json.dumps(r)})
    assert out["verdict"] == "FAIL" and out["failing_events"] == [1]
    assert "allowed_models" in out["summary"]


def test_mcp_bad_json() -> None:
    assert _call("receipt_verify", {"receipt_json": "nope"})["verdict"] == "FAIL"


def test_mcp_check_by_session_id(tmp_path, monkeypatch, key: Ed25519PrivateKey) -> None:
    r = make_receipt(key)
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "receipt.json").write_text(json.dumps(r))
    monkeypatch.setenv("RECEIPT_DIR", str(tmp_path))
    out = _call("receipt_check", {"session_id": r["session_id"]})
    assert out["verdict"] == "PASS"
    assert _call("receipt_check", {"session_id": "ses_nope"})["verdict"] == "UNKNOWN"
