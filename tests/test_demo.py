import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from receipt.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import receipt.sign as sign

    monkeypatch.setattr(sign, "DEFAULT_KEY_PATH", tmp_path / "k.key")


def test_mock_demo_a_verifies_b_fails_tamper_rejected(tmp_path: Path) -> None:
    res = runner.invoke(app, ["demo", "--mock", "--out", str(tmp_path)])
    assert res.exit_code == 0, res.output
    a = json.loads((tmp_path / "a" / "receipt.json").read_text())
    b = json.loads((tmp_path / "b" / "receipt.json").read_text())
    assert a["verdict"] == "VERIFIED" and b["verdict"] == "FAILED"
    rules = {v["rule"] for v in b["violations"]}
    assert {"allowed_models", "allowed_tools"} <= rules
    assert any(e["type"] == "sandbox_exec" for e in a["events"])
    sandbox = next(e for e in a["events"] if e["type"] == "sandbox_exec")
    assert json.loads(sandbox["data"]["stdout"])["chain_ok"] is True

    assert runner.invoke(app, ["verify", str(tmp_path / "a" / "receipt.json")]).exit_code == 0
    assert runner.invoke(app, ["verify", str(tmp_path / "b" / "receipt.json")]).exit_code == 1
    runner.invoke(app, ["tamper", str(tmp_path / "a" / "receipt.json")])
    tampered = tmp_path / "a" / "receipt.tampered.json"
    assert runner.invoke(app, ["verify", str(tampered)]).exit_code == 1
