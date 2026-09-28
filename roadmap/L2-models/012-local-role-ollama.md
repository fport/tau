# 012 · `local` role via Ollama with automatic fallback

Status: ready-for-agent
Type: AFK
Layer: L2 · Models
Packages: infra/litellm, tau-core
Blocked by: 010

## What to build

The `local` role routes to Ollama on the Mac over the tailnet. If Ollama is unreachable (Mac asleep or away), the call falls back to `fast` and the fallback is logged.

## Acceptance criteria

- [ ] `local` answers through Ollama when reachable
- [ ] With Ollama stopped, the same call succeeds through `fast` and the fallback is logged
- [ ] The model name is configurable; a recommended model for Turkish is documented

## Blocked by

- [010 · LiteLLM proxy with `brain` and `fast` roles](010-litellm-proxy-roles.md)

## Comments
