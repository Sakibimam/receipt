import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from receipt.viewer import render
from tests.helpers import make_receipt


def test_viewer_stamps_from_verifier_and_escapes(tmp_path: Path, key: Ed25519PrivateKey) -> None:
    good = make_receipt(key)
    bad = make_receipt(key, models=("mock/a", "mock/<script>"))
    forged = make_receipt(key)
    forged["verdict"] = "VERIFIED"
    forged["totals"]["cost_usd"] = 0
    paths = []
    for name, r in (("a", good), ("b", bad), ("c", forged)):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(r))
        paths.append(p)
    page = render(paths)
    assert "<script" not in page and "&lt;script&gt;" in page
    assert 'class="slip verified"' in page
    assert 'class="slip failed"' in page
    assert 'class="slip tampered"' in page
    assert 'href="#r1-e1"' in page
