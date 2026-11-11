"""Command line interface: `receipt keygen`, `receipt verify`, `receipt mock-run`."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from receipt.sign import DEFAULT_KEY_PATH, generate_key, load_or_create_key
from receipt.verify import verify_receipt

app = typer.Typer(help="Signed, verifiable receipts for AI agent sessions.", no_args_is_help=True)


@app.command()
def keygen(
    path: Path = typer.Option(DEFAULT_KEY_PATH, help="Where to write the private key."),
    force: bool = typer.Option(False, help="Overwrite an existing key."),
) -> None:
    """Create an Ed25519 signing key (kept outside the repo)."""
    try:
        pub = generate_key(path, overwrite=force)
    except FileExistsError as exc:
        typer.echo(f"{exc} (use --force to replace)")
        raise typer.Exit(1) from exc
    typer.echo(f"key written to {path}\npublic key: {pub}")


@app.command()
def verify(
    file: Path,
    as_json: bool = typer.Option(False, "--json", help="Print the report as JSON."),
    key: str | None = typer.Option(None, help="Require this signer public key (hex)."),
    witness: bool = typer.Option(
        False, help="Also reconcile every call with Otari's usage ledger (needs OTARI_API_KEY)."
    ),
) -> None:
    """Verify a receipt. Exit code 0 = PASS, 1 = FAIL."""
    report = verify_receipt(json.loads(file.read_text()), expected_key=key, witness=witness)
    typer.echo(json.dumps(report.to_dict(), indent=2) if as_json else report.render())
    raise typer.Exit(0 if report.ok else 1)


@app.command("mock-run")
def mock_run(out: Path = typer.Option(Path("runs/mock/receipt.json"))) -> None:
    """Record a tiny session against the MockGateway (no Otari) and sign it."""
    from receipt.mock import MockGateway
    from receipt.session import Session

    gw = MockGateway()
    session = Session(agent="mock-agent")
    for model in ("mock/researcher", "mock/summarizer"):
        resp = gw.chat(model, [{"role": "user", "content": "hello"}])
        session.record("llm_call", {"model": model, "response": resp})
    receipt = session.finalize(load_or_create_key())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2))
    typer.echo(f"wrote {out} (MOCK gateway, not Otari)")


@app.command()
def models(contains: str = typer.Option("", help="Filter model ids by substring.")) -> None:
    """List the Otari model catalog (GET /models)."""
    import os

    import httpx
    from dotenv import load_dotenv

    load_dotenv()
    base = os.environ.get("OTARI_BASE_URL", "https://api.otari.ai/api/v1")
    key = os.environ.get("OTARI_API_KEY", "")
    if not key:
        typer.echo("OTARI_API_KEY not set")
        raise typer.Exit(1)
    r = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    r.raise_for_status()
    for m in r.json().get("data", []):
        mid = m.get("id", "")
        if contains.lower() in mid.lower():
            typer.echo(mid)


@app.command()
def ping(
    model: str = typer.Option(..., help="Open-weight model id on Otari."),
    evidence: Path = typer.Option(Path("evidence/p1_first_call.json")),
) -> None:
    """One live, non-streaming call to Otari; saves redacted evidence."""
    from receipt.chain import now_iso
    from receipt.client import OtariClient
    from receipt.session import Session

    session = Session(agent="ping")
    client = OtariClient(session)
    if client.mock:
        typer.echo("OTARI_API_KEY not set; refusing to write live evidence from the mock")
        raise typer.Exit(1)
    res = client.chat(
        model,
        [{"role": "user", "content": "Reply with one short sentence: what is a receipt?"}],
        role="ping",
        max_tokens=200,
    )
    record = {
        "captured_at": now_iso(),
        "live": True,
        "endpoint": f"{client.base_url}/chat/completions",
        "request_model": model,
        "status": res.status,
        "response_model": res.model,
        "headers": res.headers,
        "usage": res.usage,
        "error": res.error,
        "content_preview": res.content[:300],
        "note": "Redacted: only Otari-* headers kept; no auth headers or keys.",
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(record, indent=2))
    typer.echo(json.dumps(record, indent=2))
    raise typer.Exit(0 if res.ok else 1)


def _run_one(name: str, out_dir: Path, rogue: bool, mock: bool, mandate_path: Path) -> dict:
    from receipt.agent import Models, run
    from receipt.client import OtariClient
    from receipt.mandate import load_mandate
    from receipt.session import Session

    mandate = load_mandate(mandate_path)
    agent = "research-agent (rogue)" if rogue else "research-agent"
    session = Session(agent=agent, mandate=mandate)
    client = OtariClient(session, force_mock=mock)
    session.gateway = client.gateway
    result = run(session, client, Models.from_env(), rogue=rogue)
    receipt = session.finalize(load_or_create_key())
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "receipt.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False))
    label = "MOCK gateway (not Otari)" if result["mock"] else "live Otari"
    brief = [f"# Run {name} — {agent}", "", f"_{label}_", "", result["brief"] or "(no brief)"]
    sources = [f"- {u}" for u in result["sources"]] or ["(none returned)"]
    brief += ["", "## Sources", *sources]
    brief += ["", "## Otari sandbox verifier output", "```", result["sandbox"].strip(), "```"]
    (out_dir / "brief.md").write_text("\n".join(brief) + "\n")
    return receipt


@app.command()
def demo(
    out: Path = typer.Option(Path("runs"), help="Output directory."),
    mock: bool = typer.Option(False, help="Use the MockGateway instead of Otari."),
    mandate: Path = typer.Option(Path("mandate.yaml")),
    only: str = typer.Option("ab", help="Which runs: a, b or ab."),
) -> None:
    """Run A (compliant) and B (rogue) under the same mandate and sign both receipts."""
    for name, rogue in (("a", False), ("b", True)):
        if name not in only:
            continue
        typer.echo(f"== run {name.upper()} ({'rogue' if rogue else 'compliant'})")
        receipt = _run_one(name, out / name, rogue, mock, mandate)
        report = verify_receipt(receipt)
        t = receipt["totals"]
        typer.echo(
            f"   {receipt['verdict']}: {t['requests']} requests, ${t['cost_usd']:.6f}, "
            f"{len(receipt['violations'])} violation(s) -> {out / name / 'receipt.json'}"
        )
        typer.echo("   " + report.render().replace("\n", "\n   "))


@app.command()
def tamper(
    file: Path,
    out: Path | None = typer.Option(None, help="Defaults to <file>.tampered.json"),
) -> None:
    """Copy a receipt and change one number (the first call's cost) to show rejection."""
    receipt = json.loads(file.read_text())
    target = None
    for ev in receipt["events"]:
        if ev["type"] == "llm_call":
            target = ev
            break
    if target is None:
        typer.echo("no llm_call event to tamper with")
        raise typer.Exit(1)
    before = target["data"]["usage"]["cost_usd"]
    target["data"]["usage"]["cost_usd"] = 0.0
    dest = out or file.with_suffix(".tampered.json")
    dest.write_text(json.dumps(receipt, indent=2, ensure_ascii=False))
    typer.echo(f"event {target['index']}: cost_usd {before} -> 0.0, written to {dest}")
    report = verify_receipt(receipt)
    typer.echo(report.render())


@app.command()
def mcp(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8765),
    stdio: bool = typer.Option(False, help="Use stdio instead of streamable HTTP."),
) -> None:
    """Serve receipt_verify and receipt_summarize over MCP (streamable HTTP at /mcp)."""
    from receipt.mcp_server import main

    main(host=host, port=port, transport="stdio" if stdio else "streamable-http")


if __name__ == "__main__":
    app()
