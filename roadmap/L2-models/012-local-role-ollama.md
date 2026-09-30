# 012 · `local` role via Ollama with automatic fallback

Status: done
Type: AFK
Layer: L2 · Models
Packages: infra/litellm, tau-core
Blocked by: 010

## What to build

The `local` role routes to Ollama on the Mac over the tailnet. If Ollama is unreachable (Mac asleep or away), the call falls back to `fast` and the fallback is logged.

## Acceptance criteria

- [x] `local` answers through Ollama when reachable
- [x] With Ollama stopped, the same call succeeds through `fast` and the fallback is logged
- [x] The model name is configurable; a recommended model for Turkish is documented

## Blocked by

- [010 · LiteLLM proxy with `brain` and `fast` roles](010-litellm-proxy-roles.md)

## Comments
- 2026-09-30: done (commits b21cb34, dbfb9ca).
  - Proxy side: the `local` model group is `ollama_chat/<model>` from `TAU_LOCAL_MODEL` (default `qwen3.5:9b`, recommended for Turkish; `think: false` makes it answer in about 2 s instead of reasoning first). It reaches the Docker host by default, or `TAU_OLLAMA_URL` (the Mac's tailnet address once the hub moves). No retries, a 20 s stream timeout, and a router fallback `local → fast`. tau logs the proxy's fallback from the `x-litellm-attempted-fallbacks` header.
  - Direct side: `provider = "ollama"` exists too (Ollama's OpenAI-compatible endpoint, no fallback), so `PLANNED_PROVIDERS` is empty.
  - Verified live:
    - `local` answered in Turkish through Ollama.
    - With Ollama unreachable, `fast` answered after about 1.7 s on connection refused and after about 21 s on a host that never answers. The response said `attempted-fallbacks: 1`.
    - The Ollama app refused a scripted quit, so "stopped" was reproduced by pointing the proxy at a closed port, which is the same connection refusal a stopped Ollama gives. Worth one manual check: quit Ollama from its menu and ask something on `local`.

- 2026-09-30 (later): superseded by 132 ([ADR 0011](../../docs/adr/0011-budgets-in-tau-no-litellm.md)). The owner dropped the LiteLLM proxy so users need no Docker; `infra/litellm`, the `proxy` provider and `tau proxy` are gone, and budgets, spend and failover now live in tau-core.
