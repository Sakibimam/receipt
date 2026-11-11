# Feedback on Otari

Answers to the three written questions. Every point comes from a friction log we kept while building, and the live findings have redacted evidence in `evidence/`.

## 1. When were you tempted to skip Otari and call a provider directly?

- **When the docs ran out.** otari.ai/docs and docs.otari.ai are thin index pages. The facts we needed (response headers, the `otari_tool_calls` shape, how budgets and `user` work) were only in the GitHub `docs/*.md` files. For a few minutes the OpenAI docs looked like the quicker path.
- **When nothing would turn on from code.** On a new workspace, web search and web fetch report `available: false, reason: workspace_disabled`. Budgets, routing policies and MCP registration all need a master key or a dashboard session (an API key gets `401 Invalid master key`). An agent can't set up its own guardrails, so every feature beyond chat waited on a human in a dashboard. When dashboard changes didn't show up for our key, we didn't find an API-key endpoint that shows which workspace the key belongs to.
- **When inline MCP was refused.** `mcp_servers` with a URL, as shown in `docs/mcp.md`, returned `400 "This workspace does not let a request name MCP servers by URL…"` with `code: null`. The docs don't mention the workspace setting.

- **When routing didn't fall back.** Our fallback policy returned `429 upstream_rate_limited` ("Model busy") three times with no fallback headers, then fell back properly on the next call (`Otari-Fallback: true`, attempt 2). We added our own retries, and the receipt shows every attempt.

We didn't skip Otari. The headers, the per-request ledger and code execution were worth too much.

## 2. What did we build ourselves that Otari should do?

- **A session-level, signed record.** Otari sees every request but gives nothing back that covers a whole session. We built the hash chain, canonical JSON, Ed25519 signing and the verifier. If Otari signed each response (or a session digest) with a gateway key, Receipt's strongest check would need no API key at all.
- **A pre-flight mandate check.** We block disallowed models, blocked tools, request caps and spend past a budget on the client before anything is sent, then record the attempt. Otari only enforces once a request arrives. A "dry run" or allow-list per key would let gateways refuse earlier and say why.
- **Citation provenance.** With web search disabled, `gpt-oss-120b` invented convincing sources ("Code Llama 2", "CodeMistral-7B"). We check that every URL a writer cites came back in an `otari_web_search` result earlier in the session. Otari already holds the search results, so it could attest to them.
- **Ledger reconciliation.** `GET /api/v1/usage/requests/{id}` works with a normal API key, which is great. We still had to write the reconcile loop, handle cost as a six-decimal string, and decide what to do with an undocumented numeric `usage.estimated_cost`, which turned out to be the unrounded cost.
- **Reasons for failed tool calls.** Under a tight key budget every web search came back `status: failed` with no error, while the chat call itself succeeded. We could only guess it was the budget.
- **Timeouts as facts.** A 3000-token non-streaming completion took longer than a 120 s client timeout with no progress signal. We record timeouts as events rather than losing them.

## 3. Would we keep using Otari, and why?

Yes, for this kind of product. By the end, web search, a routing policy with a real fallback, a key budget refusing with `Otari-Budget-Scope`, code execution and MCP through the gateway had all worked live in one signed session. Three things stood out and made Receipt more than a signed log:
1. One OpenAI-compatible endpoint across open-weight models from different providers (`openai/gpt-oss-120b`, `alibaba/qwen3-235b-a22b-instruct-2507`), with the real model and provider in headers.
2. A per-request ledger an API key can read, so a third party can catch a receipt owner who forges numbers and re-signs.
3. Code execution in a sandbox the agent doesn't control, which we used to recompute the hash chain and spend independently.

What would make it a clear yes for production: let an API key turn on features (or at least see why they are off), warn when `Otari-End-User-Budget` names a budget that doesn't exist (today that returns 200 and silently enforces nothing), give every error a machine-readable `code`, and sign responses.
