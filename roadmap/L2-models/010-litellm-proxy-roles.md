# 010 · LiteLLM proxy with `brain` and `fast` roles

Status: done
Type: AFK
Layer: L2 · Models
Packages: infra/litellm, tau-core
Blocked by: 003, 004

## What to build

LiteLLM Proxy runs on the hub with docker compose (image pinned by digest, Postgres for spend tracking). `brain` → Anthropic Sonnet, falling back to `fast`; `fast` → Anthropic Haiku (Bedrock was dropped on 2026-09-30, [ADR 0009](../../docs/adr/0009-anthropic-only-models-behind-the-proxy.md)). tau talks to the proxy through an OpenAI-compatible client. Switching between direct-provider mode (#004) and proxy mode is config only.

## Acceptance criteria

- [x] `docker compose up` starts proxy and Postgres; the image is referenced by digest, not tag
- [x] `tau chat` works through the proxy for both roles; fallback verified by disabling the primary
- [x] Each role has its own virtual key
- [x] No `litellm` Python package appears in any `pyproject.toml` or `uv.lock`
- [x] Runs on arm64 (future RPi5 hub)
- [x] `infra/litellm/README.md` covers start, stop and key rotation

## Blocked by

- [003 · Provision model credentials with cost guards](../L1-agent/003-provision-model-credentials.md)
- [004 · Tracer bullet: `tau chat` answers in the Jarvis persona](../L1-agent/004-tau-chat-tracer-bullet.md)

## Notes

LiteLLM 1.82.7 and 1.82.8 on PyPI were compromised in March 2026 — this is why the proxy runs isolated in a pinned container.

## Comments

- 2026-09-29: the proxy must be reached with `strands.models.openai.OpenAIModel(client_args={"base_url": ...})` (plus the per-role virtual key as `api_key`), never with `strands.models.litellm.LiteLLMModel`: that class imports the `litellm` package, which is exactly the dependency the container isolates us from. The `strands-agents[openai]` extra is the only addition allowed.
- 2026-09-30: done (commits b21cb34, dbfb9ca). Started with only 003's Anthropic half in place: the owner dropped Bedrock rather than set up AWS ([ADR 0009](../../docs/adr/0009-anthropic-only-models-behind-the-proxy.md)), so `brain` falls back to `fast` inside the proxy instead of to a second provider.
  - `infra/litellm`: `ghcr.io/berriai/litellm:v1.103.1` and `postgres:17.11-alpine`, both pinned by digest and multi-arch. The proxy publishes 127.0.0.1:4000 only and the database no port. The proxy uses the cost map bundled with the image and never stores prompts. `proxy.sh init|up|restart|down|status|logs`.
  - tau side: `provider = "proxy"` is `ProxyModel`, a subclass of Strands' `OpenAIModel`. `model_id` is the model group, and the key comes from `TAU_PROXY_KEY_<GROUP>`. `tau proxy keys` creates one key per role (alias `tau-<role>`); `tau proxy rotate` replaces one and keeps the period's spend, since LiteLLM's `/key/regenerate` is enterprise-only.
  - `tau.toml` and the shipped template now put brain, fast and local on the proxy. `tau init` writes direct providers when no proxy key is present.
  - Verified live on the Mac (arm64):
    - `tau chat` answered on `brain` and on `fast` through the proxy.
    - With brain's model set to a non-existent id, `fast` answered and the hub logged `the proxy fell back from model group brain to fast`.
    - `uv.lock` gained only `openai`, `tqdm` and `aws-bedrock-token-generator` (the `strands-agents[openai]` extra); no `litellm`.
  - Next issues should know:
    - LiteLLM answers a spent key with `429 budget_exceeded`, which Strands would retry as throttling; `ProxyModel` catches it first.
    - The response headers `x-litellm-attempted-fallbacks` and `x-litellm-key-spend` are read on every call.
    - Prompt caching does not pass the proxy yet (131).

- 2026-09-30 (later): superseded by 132 ([ADR 0011](../../docs/adr/0011-budgets-in-tau-no-litellm.md)). The owner dropped the LiteLLM proxy so users need no Docker; `infra/litellm`, the `proxy` provider and `tau proxy` are gone, and budgets, spend and failover now live in tau-core.
