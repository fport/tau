# 067 · Opt-in model failover through Strands `ModelRouter`

Status: done
Type: AFK
Layer: L2 · Models
Packages: tau-core
Blocked by: 010, 011

## What to build

Strands ships a provisional `ModelRouter` that picks a model per call and can fail over to another model on provider errors. tau resolves one `Model` per role today; when the LiteLLM proxy (010) already handles `brain` → Bedrock with Anthropic fallback, a second failover layer in the hub is redundant, but for direct-provider mode (no proxy) and for `local` → `fast` degradation (011, 012) an in-process router could replace hand-written fallback code.

Evaluate the `ModelRouter` API as shipped in the pinned strands-agents version, decide whether tau adopts it behind an opt-in `[models.roles.<role>] failover = [...]` setting, and if so implement it so that budgets (011) still see every call and the role abstraction (code asks for `brain`/`fast`/`local`, never a model id) is preserved. If the API is still provisional or conflicts with the proxy, record the decision in an ADR and close.

## Acceptance criteria

- [x] Decision recorded (ADR or comment): adopt behind opt-in config, or defer with the reason
- ~~If adopted: `failover` per role is config only, off by default, tested with `FakeModel`s that raise; budgets and spend reporting count the fallback calls~~ not adopted
- [x] No model id in code; the proxy path (010) is unchanged when `failover` is unset

## Blocked by

- [010 · LiteLLM proxy with `brain` and `fast` roles](010-litellm-proxy-roles.md)
- [011 · Hard budgets per role with graceful degradation](011-hard-budgets.md)

## Comments

- 2026-09-29: filed as a follow-up of the Strands-correctness pass (064); `ModelRouter` is provisional in strands-agents 1.57.1, so it was kept out of that wave.
- 2026-09-30: deferred, recorded as decision 7 of [ADR 0009](../../docs/adr/0009-anthropic-only-models-behind-the-proxy.md).
  - Why not adopt it: `ModelRouter` is still marked provisional in strands-agents 1.57.1, and it has three problems:
    - `agent.model` stays the first candidate, so `/status`, compaction and the SDK's proactive compression reason about the wrong model.
    - A candidate that fails mid-stream leaves duplicate text in the channels.
    - It advances on any failure the retry strategy declines.
  - Why nothing needs it now:
    - The proxy already does `brain`/`local` → `fast`.
    - A spent budget degrades in `ProxyModel` before anything streams (011).
  - Revisit when the API is final and threads the chosen model through the agent, or when direct mode needs failover.
