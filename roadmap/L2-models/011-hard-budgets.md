# 011 · Hard budgets per role with graceful degradation

Status: ready-for-agent
Type: AFK
Layer: L2 · Models
Packages: tau-core, infra/litellm
Blocked by: 005, 010

## What to build

Each role key gets a hard spend cap (e.g. `fast` $1/day, `brain` $15/month). When a cap is hit, tau falls back to a cheaper role where allowed, otherwise tells the user in Jarvis tone that the budget is exhausted and when it resets. Today's spend per role appears in the dynamic context and in the hub control API.

## Acceptance criteria

- [ ] Exceeding a cap blocks further calls on that key (verified with a tiny test cap)
- [ ] The user gets a clear message in the UI language, never a stack trace
- [ ] Spend per role is visible in the dynamic context and via the control API
- [ ] Cap values change without code changes

## Blocked by

- [005 · Live persona files and dynamic context in the system prompt](../L1-agent/005-live-persona-dynamic-context.md)
- [010 · LiteLLM proxy with `brain` and `fast` roles](010-litellm-proxy-roles.md)

## Comments
