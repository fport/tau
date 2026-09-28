# L2 · Models

**Goal:** All model calls go through role-based routing (brain / fast / local) behind a LiteLLM proxy with hard budgets.

**Done when:** No code path calls a provider directly, every role has a hard spend cap, and today's spend is visible.

| # | Issue | Type | Blocked by |
|---|---|---|---|
| 010 | [LiteLLM proxy with `brain` and `fast` roles](010-litellm-proxy-roles.md) | AFK | 003, 004 |
| 011 | [Hard budgets per role with graceful degradation](011-hard-budgets.md) | AFK | 005, 010 |
| 012 | [`local` role via Ollama with automatic fallback](012-local-role-ollama.md) | AFK | 010 |

Live status: `python3 roadmap/board.py`
