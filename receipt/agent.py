"""Demo agent: researcher (web search) -> summarizer -> verifier inside Otari's sandbox.

Run A follows the mandate. Run B is a rogue agent: same task, same mandate, but it
tries a disallowed model, a blocked tool, and keeps spending past the budget.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Any

from receipt.chain import canonical
from receipt.client import CallResult, OtariClient, execute_code
from receipt.session import Session

TASK = (
    "Research the current state of open-weight coding models and write a 150-word brief "
    "with sources."
)
RESEARCH_TOOLS = [{"type": "otari_web_search", "max_uses": 3}]


@dataclass
class Models:
    researcher: str
    summarizer: str
    disallowed: str

    @classmethod
    def from_env(cls) -> Models:
        return cls(
            researcher=os.environ.get("RECEIPT_MODEL_RESEARCHER") or "openai/gpt-oss-120b",
            summarizer=os.environ.get("RECEIPT_MODEL_SUMMARIZER")
            or "alibaba/qwen3-235b-a22b-instruct-2507",
            disallowed=os.environ.get("RECEIPT_MODEL_DISALLOWED") or "anthropic/claude-fable-5",
        )


def research(client: OtariClient, model: str) -> CallResult:
    msgs = [
        {
            "role": "system",
            "content": "You are a researcher. Use web search. List 5 concrete findings, each "
            "with its source URL.",
        },
        {"role": "user", "content": TASK},
    ]
    res = client.chat(model, msgs, role="researcher", tools=RESEARCH_TOOLS, max_tokens=1500)
    if not res.ok and (res.error or {}).get("code") == "web_access_disabled":
        # Workspace has web search off: the refusal is already chained; continue without it.
        res = client.chat(model, msgs, role="researcher", max_tokens=1500)
    return res


def summarize(client: OtariClient, model: str, notes: str, sources: list[str]) -> CallResult:
    if sources:
        src = "\n".join(f"- {u}" for u in sources)
        rule = "then a Sources list. Cite ONLY these exact URLs, no others."
    else:
        src = "(none: live web search was unavailable)"
        rule = (
            "Write no URLs and no citations at all. End with the line: "
            "'Sources: none (live web search unavailable for this run).'"
        )
    msgs = [
        {
            "role": "system",
            "content": f"You write tight technical briefs. About 150 words, {rule}",
        },
        {"role": "user", "content": f"Task: {TASK}\n\nResearch notes:\n{notes}\n\nSources:\n{src}"},
    ]
    return client.chat(model, msgs, role="summarizer", max_tokens=600)


SANDBOX_CHECK = """
import base64, hashlib, json
d = json.loads(base64.b64decode("{payload}"))
def canon(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
prev, bad = "0" * 64, []
for i, e in enumerate(d["events"]):
    body = {{k: v for k, v in e.items() if k not in ("prev_hash", "hash")}}
    h = hashlib.sha256((prev + canon(body)).encode()).hexdigest()
    if e["index"] != i or e["prev_hash"] != prev or e["hash"] != h:
        bad.append(i)
    prev = e["hash"]
calls = [e for e in d["events"] if e["type"] in ("llm_call", "llm_error")]
cost = round(sum(float(e["data"].get("usage", {{}}).get("cost_usd") or 0) for e in d["events"]), 8)
budget = d["budget_usd"]
print(json.dumps({{
    "verifier": "receipt-sandbox/1", "chain_ok": not bad, "bad_events": bad,
    "events_checked": len(d["events"]), "head": prev, "requests": len(calls),
    "cost_usd": cost, "budget_usd": budget, "within_budget": cost <= budget,
}}, sort_keys=True))
"""


def sandbox_verify(client: OtariClient) -> CallResult:
    """Ship the chain so far to Otari's code sandbox; it recomputes hashes and spend."""
    s = client.session
    mandate = s.effective_mandate()
    payload = {"events": s.chain.events, "budget_usd": mandate.budget_usd}
    b64 = base64.b64encode(canonical(payload).encode()).decode()
    return execute_code(client, SANDBOX_CHECK.format(payload=b64), label="sandbox_verify")


def sources_from(res: CallResult) -> list[str]:
    urls: list[str] = []
    for tc in res.tool_calls:
        for src in tc.get("sources", []):
            if src.get("url") and src["url"] not in urls:
                urls.append(src["url"])
    return urls


def run(session: Session, client: OtariClient, models: Models, rogue: bool) -> dict[str, Any]:
    notes = research(client, models.researcher)
    sources = sources_from(notes)
    if rogue:
        # Rogue agent "wants a better model" and an unvetted fetch tool.
        client.chat(models.disallowed, [{"role": "user", "content": TASK}], role="rogue-upgrade")
        client.chat(
            models.researcher,
            [{"role": "user", "content": "Fetch https://example.com and summarise it."}],
            role="rogue-fetch",
            tools=[{"type": "otari_web_fetch"}],
        )
    brief = summarize(client, models.summarizer, notes.content, sources)
    if rogue:
        # Keep "polishing" with long rewrites until the mandate stops it.
        text = brief.content
        for i in range(12):
            r = client.chat(
                models.summarizer,
                [
                    {
                        "role": "user",
                        "content": "Rewrite this brief as an exhaustive 1500-word report with "
                        f"every detail you know (pass {i + 1}):\n\n{text}",
                    }
                ],
                role="rogue-polish",
                max_tokens=2000,
            )
            if r.blocked:
                break
            text = r.content or text
    check = sandbox_verify(client)
    return {
        "brief": brief.content,
        "sources": sources,
        "sandbox": check.content,
        "mock": client.mock,
    }
