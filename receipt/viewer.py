"""Static HTML viewer: each receipt is drawn as a till slip with a verifier stamp.

The stamp comes from re-verifying the file, never from the receipt's own `verdict`.
One self-contained page: inline CSS, no JavaScript, no network.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from receipt.verify import Report, verify_receipt

INTEGRITY = ("schema", "signature", "hash chain", "root hash", "event count", "mandate hash")


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def stamp_for(report: Report) -> tuple[str, str]:
    broken = [c for c in report.checks if not c.ok and c.name != "within mandate"]
    if broken:
        return "tampered", "Tampered"
    if not report.ok:
        return "failed", "Failed"
    return "verified", "Verified"


def money(x: Any) -> str:
    try:
        return f"${float(x):.6f}"
    except (TypeError, ValueError):
        return "—"


def event_line(ev: dict[str, Any], slip: str, flagged: dict[int, list[str]]) -> str:
    d = ev.get("data", {})
    req = d.get("request", {})
    idx = ev.get("index")
    typ = ev.get("type", "")
    what = req.get("model") or req.get("tool") or typ
    role = req.get("role") or req.get("label") or ""
    cost = d.get("usage", {}).get("cost_usd")
    status = d.get("status")
    if typ == "violation_attempt":
        note, amount = "blocked before sending", "—"
    elif typ == "sandbox_exec":
        note, amount = "ran verifier in Otari sandbox", "—"
    elif typ == "llm_error":
        code = (d.get("error") or {}).get("code") or "error"
        note, amount = f"refused: {status} {code}", money(cost) if cost else "—"
    else:
        tokens = d.get("usage", {}).get("total_tokens", 0)
        note, amount = f"{tokens} tokens", money(cost)
    headers = d.get("headers", {})
    if str(headers.get("Otari-Fallback", "")).lower() == "true":
        note += f" · fell back to {headers.get('Otari-Model')}"
    rid = headers.get("Otari-Request-ID", "")
    cls = "line flagged" if idx in flagged else "line"
    reasons = "".join(f'<span class="why">{esc(r)}</span>' for r in flagged.get(idx, []))
    return (
        f'<li class="{cls}" id="{slip}-e{idx}">'
        f'<span class="idx">{esc(idx)}</span>'
        f'<span class="what"><b>{esc(what)}</b>'
        f"{f' <i>{esc(role)}</i>' if role else ''}"
        f"<small>{esc(note)}{f' · req {esc(rid[:8])}' if rid else ''}</small>{reasons}</span>"
        f'<span class="amt">{esc(amount)}</span></li>'
    )


def slip_html(path: Path, receipt: dict[str, Any], slip: str) -> str:
    report = verify_receipt(receipt)
    kind, label = stamp_for(report)
    flagged: dict[int, list[str]] = {}
    for v in report.violations:
        flagged.setdefault(v["event_index"], []).append(f"{v['rule']}: {v['detail']}")
    for c in report.checks:
        if not c.ok and c.name != "within mandate":
            for i in c.events:
                flagged.setdefault(i, []).append(f"{c.name}: {c.detail}")

    events = receipt.get("events", [])
    totals = receipt.get("totals", {})
    mandate = receipt.get("mandate", {})
    lines = "\n".join(event_line(e, slip, flagged) for e in events)
    by_model = "".join(
        f"<tr><td>{esc(m)}</td><td>{esc(t.get('requests'))}</td>"
        f"<td>{esc(t.get('total_tokens'))}</td><td>{money(t.get('cost_usd'))}</td></tr>"
        for m, t in totals.get("by_model", {}).items()
    )
    sources = sorted(
        {s.get("url") for tc in receipt.get("tool_calls", []) for s in tc.get("sources", [])}
        - {None}
    )
    src_html = (
        "".join(f'<li><a href="{esc(u)}">{esc(u)}</a></li>' for u in sources)
        if sources
        else "<li>No web sources were returned in this session.</li>"
    )
    checks = "".join(
        f'<li class="{"ok" if c.ok else "bad"}"><span>{"✓" if c.ok else "✗"}</span>'
        f"{esc(c.name)}{f' <small>{esc(c.detail)}</small>' if c.detail else ''}</li>"
        for c in report.checks
    )
    violations = "".join(
        f'<li><a href="#{slip}-e{v["event_index"]}">Line {esc(v["event_index"])}</a> '
        f"{esc(v['rule'])}: {esc(v['detail'])}</li>"
        for v in report.violations
    )
    spent = float(totals.get("cost_usd") or 0)
    budget = float(mandate.get("budget_usd") or 0)
    pct = min(spent / budget * 100, 100) if budget else 0
    over = budget and spent > budget
    sig = receipt.get("signature", "")
    return f"""
<article class="slip {kind}" aria-labelledby="{slip}-title">
  <div class="stamp" role="img" aria-label="Verifier result: {label}">{label}</div>
  <header>
    <h2 id="{slip}-title">{esc(receipt.get("agent", "agent"))}</h2>
    <p>{esc(path.as_posix())}</p>
    <dl>
      <dt>Session</dt><dd>{esc(receipt.get("session_id"))}</dd>
      <dt>Gateway</dt><dd>{esc(receipt.get("gateway"))}</dd>
      <dt>Started</dt><dd>{esc(receipt.get("started_at"))}</dd>
      <dt>Mandate</dt><dd>{esc(mandate.get("name"))} ({
        esc(receipt.get("mandate_hash", "")[:12])
    })</dd>
    </dl>
  </header>
  <ol class="lines">{lines}</ol>
  <div class="total">
    <span>Total, {esc(totals.get("requests", 0))} requests</span><strong>{money(spent)}</strong>
  </div>
  <div class="budget{" over" if over else ""}">
    <div class="bar"><i style="width:{pct:.1f}%"></i></div>
    <span>{money(spent)} of {money(budget)} budget</span>
  </div>
  <table class="models"><thead><tr><th>Model</th><th>Req</th><th>Tokens</th><th>Cost</th>
  </tr></thead><tbody>{by_model}</tbody></table>
  {
        f'<section class="violations"><h3>Outside the mandate</h3><ul>{violations}</ul></section>'
        if violations
        else ""
    }
  <section><h3>Sources</h3><ul class="sources">{src_html}</ul></section>
  <section><h3>What the verifier checked</h3><ul class="checks">{checks}</ul></section>
  <footer>
    <p>Signed by {esc(receipt.get("signer_public_key", "")[:16])}…</p>
    <p>Chain head {esc(receipt.get("events_root_hash", "")[:24])}…</p>
    <p class="sig">{esc(sig[:44])}…</p>
  </footer>
</article>"""


CSS = """
:root{
  --counter:#d6dde3; --counter-ink:#33414d; --paper:#fbfbf6; --ink:#1d2731;
  --faint:#6b7782; --rule:#c9cdd0; --ok:#17795a; --bad:#b3261e; --warn:#9a5b00;
  --flag:#fbe9e7;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --counter:#1b232b; --counter-ink:#b9c4cd; --paper:#eeeee6; --ink:#1d2731;
    --faint:#5d6973; --rule:#c4c7c7; --flag:#f6dcd8;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--counter);color:var(--counter-ink);
  font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
.page{max-width:1240px;margin:0 auto;padding:40px 16px 64px}
.intro{max-width:62ch;margin:0 0 36px}
.intro h1{font-size:clamp(28px,4vw,40px);line-height:1.15;margin:0 0 12px;color:var(--counter-ink);
  font-weight:700;letter-spacing:-.01em}
.intro p{margin:0 0 8px}
.counter{display:flex;gap:28px;align-items:flex-start;flex-wrap:wrap}
.slip{position:relative;flex:1 1 340px;max-width:400px;background:var(--paper);color:var(--ink);
  font:13.5px/1.45 ui-monospace,"SF Mono",Menlo,Consolas,monospace;padding:28px 22px 30px;
  box-shadow:0 1px 0 rgba(0,0,0,.08),0 14px 30px -18px rgba(20,30,40,.55)}
.slip::before,.slip::after{content:"";position:absolute;left:0;right:0;height:10px;
  background:linear-gradient(-45deg,transparent 7px,var(--paper) 0) 0 0/14px 10px repeat-x,
             linear-gradient(45deg,transparent 7px,var(--paper) 0) 0 0/14px 10px repeat-x}
.slip::before{top:-9px;transform:scaleY(-1)}
.slip::after{bottom:-9px}
.slip header{text-align:center;border-bottom:1px dashed var(--rule);padding-bottom:14px;margin-bottom:10px}
.slip h2{font-size:17px;margin:0 0 2px}
.slip header p{margin:0 0 10px;color:var(--faint);font-size:12px;word-break:break-all}
.slip dl{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;margin:0;text-align:left;font-size:12px}
.slip dt{color:var(--faint)} .slip dd{margin:0;word-break:break-all}
.lines{list-style:none;margin:0;padding:0}
.line{display:grid;grid-template-columns:2ch 1fr auto;gap:10px;padding:7px 4px;
  border-bottom:1px dotted var(--rule);scroll-margin-top:24px}
.line .idx{color:var(--faint)}
.line b{font-weight:600;word-break:break-all}
.line i{font-style:normal;color:var(--faint)}
.line small{display:block;color:var(--faint);font-size:11.5px}
.line .amt{text-align:right;white-space:nowrap}
.line.flagged{background:var(--flag);box-shadow:inset 3px 0 0 var(--bad)}
.line .why{display:block;color:var(--bad);font-size:11.5px;margin-top:2px}
.line:target{outline:2px solid var(--bad);outline-offset:-2px}
.total{display:flex;justify-content:space-between;align-items:baseline;border-top:2px solid var(--ink);
  border-bottom:2px solid var(--ink);margin:14px 0 10px;padding:8px 0;font-size:14px}
.total strong{font-size:20px}
.budget{margin:0 0 14px;font-size:12px;color:var(--faint)}
.budget .bar{height:6px;background:#e4e6e3;margin-bottom:4px}
.budget .bar i{display:block;height:100%;background:var(--ok)}
.budget.over .bar i{background:var(--bad)} .budget.over span{color:var(--bad)}
.models{width:100%;border-collapse:collapse;font-size:12px;margin-bottom:6px}
.models th{text-align:left;font-weight:600;color:var(--faint);border-bottom:1px solid var(--rule);padding:4px 0}
.models td{padding:4px 0;vertical-align:top;word-break:break-all}
.models td+td,.models th+th{text-align:right;padding-left:8px;word-break:normal}
.slip section{border-top:1px dashed var(--rule);margin-top:12px;padding-top:10px}
.slip h3{font-size:13px;margin:0 0 6px}
.slip ul{margin:0;padding:0;list-style:none}
.sources li{margin:2px 0;word-break:break-all;font-size:12px}
.sources a{color:var(--ink)}
.violations{color:var(--bad)} .violations a{color:var(--bad);font-weight:600}
.violations li{margin:3px 0;font-size:12px}
.checks li{display:flex;gap:8px;font-size:12px;margin:2px 0}
.checks li small{color:var(--faint)}
.checks .ok span{color:var(--ok)} .checks .bad{color:var(--bad)}
.slip footer{margin-top:14px;border-top:1px dashed var(--rule);padding-top:10px;text-align:center;
  font-size:11px;color:var(--faint)}
.slip footer p{margin:2px 0;word-break:break-all}
.stamp{position:absolute;top:110px;right:14px;transform:rotate(-11deg);font:800 26px/1
  -apple-system,"Helvetica Neue",Arial,sans-serif;letter-spacing:.08em;text-transform:uppercase;
  padding:8px 14px;border:4px double currentColor;border-radius:6px;opacity:.86;
  mix-blend-mode:multiply;pointer-events:none;animation:press .5s cubic-bezier(.2,1.6,.4,1) .2s both}
.verified .stamp{color:var(--ok)} .failed .stamp{color:var(--bad)}
.tampered .stamp{color:var(--warn);transform:rotate(8deg)}
@keyframes press{from{opacity:0;transform:scale(1.6) rotate(-11deg)}}
@media (prefers-reduced-motion:reduce){.stamp{animation:none}}
@media (max-width:480px){.slip{max-width:none}.stamp{font-size:20px;top:96px}}
a:focus-visible{outline:2px solid currentColor;outline-offset:2px}
.how{max-width:62ch;margin:48px 0 0;font-size:14px}
.how h2{font-size:18px;margin:0 0 8px}
.how code{font:13px ui-monospace,Menlo,monospace;background:rgba(255,255,255,.35);padding:1px 4px}
@media print{body{background:#fff}.slip{box-shadow:none;border:1px solid #ccc}.stamp{animation:none}}
"""


def render(paths: list[Path]) -> str:
    import json

    slips = []
    for i, p in enumerate(paths):
        slips.append(slip_html(p, json.loads(p.read_text()), f"r{i}"))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Receipt report</title>
<style>{CSS}</style></head>
<body><main class="page">
<div class="intro">
  <h1>What each agent did, what it spent, and whether it kept to its mandate</h1>
  <p>Every slip below was re-verified when this page was made: the Ed25519 signature, the hash
  chain, the totals recomputed from each call, and every line checked against the mandate.
  The stamp is the verifier's result, not the agent's claim.</p>
</div>
<div class="counter">{"".join(slips)}</div>
<section class="how">
  <h2>Check it yourself</h2>
  <p>Run <code>receipt verify receipt.json --witness</code> to repeat these checks and also
  reconcile every call with Otari's own usage ledger. Change any number in the file and the
  stamp turns to Tampered.</p>
</section>
</main></body></html>
"""


def write_report(paths: list[Path], out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(paths))
    return out
