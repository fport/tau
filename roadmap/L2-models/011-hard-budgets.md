# 011 · Hard budgets per role with graceful degradation

Status: done
Type: AFK
Layer: L2 · Models
Packages: tau-core, infra/litellm
Blocked by: 005, 010

## What to build

Each role key gets a hard spend cap (e.g. `fast` $1/day, `brain` $15/month). When a cap is hit, tau falls back to a cheaper role where allowed, otherwise tells the user in Jarvis tone that the budget is exhausted and when it resets. Today's spend per role appears in the dynamic context and in the hub control API.

## Acceptance criteria

- [x] Exceeding a cap blocks further calls on that key (verified with a tiny test cap)
- [x] The user gets a clear message in the UI language, never a stack trace
- [x] Spend per role is visible in the dynamic context and via the control API
- [x] Cap values change without code changes

## Blocked by

- [005 · Live persona files and dynamic context in the system prompt](../L1-agent/005-live-persona-dynamic-context.md)
- [010 · LiteLLM proxy with `brain` and `fast` roles](010-litellm-proxy-roles.md)

## Comments
- 2026-09-30: done (commit b21cb34, [ADR 0009](../../docs/adr/0009-anthropic-only-models-behind-the-proxy.md)).
  - Budgets: `[models.roles.<role>.budget]` holds `usd`, `period` (LiteLLM `budget_duration`, resets in UTC) and an optional `degrade_to`. The config rejects a degrade to the role itself, to an unknown role, or in a loop. `tau proxy keys` writes the cap to the role's key; `tau doctor` warns when a key's cap drifts from `tau.toml` or a role has no budget.
  - Defaults: brain $15 per 1mo (degrades to fast), fast $1 per 1d, local $0.50 per 1d.
  - Spent budget:
    - `ProxyModel` recognises the proxy's `429 budget_exceeded` before Strands would retry it as throttling.
    - With `degrade_to`, it streams the call from that role and the channel shows "The brain budget is spent until …; fast answered instead."
    - Otherwise it raises `BudgetExhausted`, which every channel shows as one sentence in the UI language with the reset time in Europe/Istanbul. `tau_core.models.ModelNotice` is the base class; the agent unwraps `EventLoopException`.
  - Spend:
    - `tau_core.spend.SpendTracker` reads each proxy role's key with the key itself (`GET /key/info`, no master key), caches it for 60 s, never blocks a model call, and takes updates from the `x-litellm-key-spend` header.
    - It shows under `## Now` as `- Budget: …` (renamed from `Budget today`; the value is the current period's spend, which for a daily cap is today's), as a `Budget:` line in `/status`, and in the hub's `GET /spend` and `/status` `spend` key (`spend` hub service).
    - `tau proxy spend` prints it too.
  - Verified live:
    - A throwaway key capped at $0.000001 was refused on its next call, with the Turkish and the English notice.
    - With `degrade_to = "fast"`, fast answered and the notice said so. With fast spent too, the combined notice appeared.
    - Changing `usd` in `tau.toml` and running `tau proxy keys` updated the key; `tau doctor` had flagged the drift first.
    - `GET /spend` on a hub on a spare port listed all three roles.

- 2026-09-30 (later): superseded by 132 ([ADR 0011](../../docs/adr/0011-budgets-in-tau-no-litellm.md)). The owner dropped the LiteLLM proxy so users need no Docker; `infra/litellm`, the `proxy` provider and `tau proxy` are gone, and budgets, spend and failover now live in tau-core.
