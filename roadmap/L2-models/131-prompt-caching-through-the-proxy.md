# 131 · Prompt caching through the proxy

Status: needs-triage
Type: AFK
Layer: L2 · Models
Packages: tau-core, infra/litellm
Blocked by: 010

## What to build

With the direct `anthropic` provider, a role's `cache` table puts a cache point after the persona and `## User` block. The dynamic `## Now` block, which changes every minute, stays outside it (`PersonaLoader.build_system_content`). Behind the LiteLLM proxy (010, ADR 0009) this is lost: Strands' `OpenAIModel` drops `cachePoint` blocks, so every call pays the full input price for the persona.

Find the way that keeps the split, for example:

- LiteLLM's `cache_control_injection_points` on the system message, if the persona and `## Now` can reach the proxy as separate content parts;
- a `ProxyModel` override that turns the cache point into an Anthropic `cache_control` marker on the stable part;
- the proxy's Anthropic-format `/v1/messages` route with `AnthropicModel`.

Measure it with the `cache_read_input_tokens` the proxy reports. Caching the whole system prompt is worse than nothing: it would write the cache again every minute at 1.25× the price.

## Acceptance criteria

- [ ] A second turn within five minutes reads the persona from Anthropic's cache through the proxy (reported cache-read tokens > 0)
- [ ] The minute-by-minute `## Now` block is never inside the cached prefix
- [ ] Budgets and spend reporting (011) still count the cached calls correctly
- [ ] Off by default or on only where it saves money; the role's `cache` table in tau.toml decides, as in direct mode

## Blocked by

- [010 · LiteLLM proxy with `brain` and `fast` roles](010-litellm-proxy-roles.md)

## Comments

- 2026-09-30: filed while closing 010; ADR 0009 lists it as a consequence of going through the proxy.
