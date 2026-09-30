# L2 · Models

**Goal:** All model calls go through role-based routing (brain / fast / local) with hard budgets per role, enforced by tau itself; providers are called directly, no Docker ([ADR 0011](../../docs/adr/0011-budgets-in-tau-no-litellm.md), which replaced the LiteLLM proxy of 010–012).

**Done when:** Code only ever asks for a role, every role that costs money has a hard spend cap tau enforces, and the spend is visible.

| # | Issue | Type | Blocked by |
|---|---|---|---|
| 010 | [LiteLLM proxy with `brain` and `fast` roles](010-litellm-proxy-roles.md) | AFK | 003, 004 |
| 011 | [Hard budgets per role with graceful degradation](011-hard-budgets.md) | AFK | 005, 010 |
| 012 | [`local` role via Ollama with automatic fallback](012-local-role-ollama.md) | AFK | 010 |
| 067 | [Opt-in model failover through Strands `ModelRouter`](067-model-router-failover.md) | AFK | 010, 011 |
| 131 | [Prompt caching through the proxy](131-prompt-caching-through-the-proxy.md) (wontfix) | AFK | 010 |
| 132 | [Budgets, spend and failover inside tau; OpenAI and Gemini providers; no LiteLLM](132-budgets-in-tau-no-litellm.md) | AFK | 010, 011, 012 |

Live status: `python3 roadmap/board.py`
