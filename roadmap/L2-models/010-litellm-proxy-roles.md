# 010 · LiteLLM proxy with `brain` and `fast` roles

Status: ready-for-agent
Type: AFK
Layer: L2 · Models
Packages: infra/litellm, tau-core
Blocked by: 003, 004

## What to build

LiteLLM Proxy runs on the hub with docker compose (image pinned by digest, Postgres for spend tracking). `brain` → Bedrock Sonnet with Anthropic as fallback; `fast` → Bedrock Haiku. tau talks to the proxy through an OpenAI-compatible client. Switching between direct-provider mode (#004) and proxy mode is config only.

## Acceptance criteria

- [ ] `docker compose up` starts proxy and Postgres; the image is referenced by digest, not tag
- [ ] `tau chat` works through the proxy for both roles; fallback verified by disabling the primary
- [ ] Each role has its own virtual key
- [ ] No `litellm` Python package appears in any `pyproject.toml` or `uv.lock`
- [ ] Runs on arm64 (future RPi5 hub)
- [ ] `infra/litellm/README.md` covers start, stop and key rotation

## Blocked by

- [003 · Provision model credentials with cost guards](../L1-agent/003-provision-model-credentials.md)
- [004 · Tracer bullet: `tau chat` answers in the Jarvis persona](../L1-agent/004-tau-chat-tracer-bullet.md)

## Notes

LiteLLM 1.82.7 and 1.82.8 on PyPI were compromised in March 2026 — this is why the proxy runs isolated in a pinned container.

## Comments

- 2026-09-29: the proxy must be reached with `strands.models.openai.OpenAIModel(client_args={"base_url": ...})` (plus the per-role virtual key as `api_key`), never with `strands.models.litellm.LiteLLMModel`: that class imports the `litellm` package, which is exactly the dependency the container isolates us from. The `strands-agents[openai]` extra is the only addition allowed.
