# 132 · Budgets, spend and failover inside tau; OpenAI and Gemini providers; no LiteLLM

Status: done
Type: AFK
Layer: L2 · Models
Packages: tau-core, tau-tui
Blocked by: 010, 011, 012

## What to build

Users who install tau from PyPI bring a key (Anthropic, OpenAI, Gemini) or a local Ollama, and must not need Docker. Remove the LiteLLM proxy of 010–012 and do its three jobs inside tau:

- a hard budget per role (day, week or month) with `degrade_to`;
- spend reporting;
- failover from an unreachable model (Ollama on a sleeping Mac) to another role.

Add `openai` and `gemini` as direct providers next to `anthropic` and `ollama`. The decision is [ADR 0011](../../docs/adr/0011-budgets-in-tau-no-litellm.md).

## Acceptance criteria

- [x] No `infra/litellm`, no `proxy` provider, no `tau proxy`; nothing named litellm in any `pyproject.toml` or `uv.lock`
- [x] `anthropic`, `openai`, `gemini` and `ollama` are direct providers; `tau init` picks the first key it finds (Anthropic, OpenAI, Gemini, Bedrock, else fake)
- [x] Every answer of a budgeted role is priced and recorded under `TAU_DATA_DIR`; a spent role degrades or says when it resets, in the UI language, never with a stack trace
- [x] `failover` hands an unreachable model's call to another role within seconds, and the channel and the log say so
- [x] Spend per role shows in the dynamic context, `/status`, `GET /spend`, `tau spend` and `tau doctor`
- [x] Tests offline; a live run on the hub Mac with Anthropic and Ollama

## Blocked by

- [010 · LiteLLM proxy with `brain` and `fast` roles](010-litellm-proxy-roles.md)
- [011 · Hard budgets per role with graceful degradation](011-hard-budgets.md)
- [012 · `local` role via Ollama with automatic fallback](012-local-role-ollama.md)

## Comments

- 2026-09-30: done. The owner asked why users should need LiteLLM at all, since each brings a key or a local model; ADR 0011 records the answer.
  - New modules:
    - `tau_core.prices` (`templates/prices.toml`, overridden by `[models.prices."<id>"]`);
    - `tau_core.spend` (the SQLite ledger `spend.sqlite3`, calendar periods in Europe/Istanbul, the report, the `budget` context source, the `spend` hub service, `tau spend`);
    - `tau_core.budget.RoleModel` (budget check before the call, spend recorded from the answer's usage, `degrade_to`, `failover` on connection errors, timeouts and 5xx).
  - Only roles with a budget or a failover are wrapped, so tests and plain roles see their provider's model unchanged.
  - Cost: Anthropic and Bedrock count cached tokens apart from the input; OpenAI and Gemini include them. `prices.cost` handles both.
  - Ollama gets a 3 s connect timeout and no retries.
  - `local` uses `params = { reasoning_effort = "none" }`, which makes `qwen3.5:9b` answer in about 1.4 s through Ollama's OpenAI endpoint.
  - Verified live on the hub Mac:
    - `brain` answered through Anthropic directly and its cost reached the ledger and `tau spend`.
    - `local` answered through Ollama.
    - With Ollama unreachable, `fast` answered: about 4 s on a refused connection and about 6 s on a host that never answers. The notice said "local is not reachable right now; fast answered instead."
    - A $0.000001 daily cap refused the second call in Turkish. With `degrade_to = "fast"`, fast answered with its notice.
  - OpenAI and Gemini are covered by offline tests only: no key was at hand. Their model ids and prices were taken from the providers' pricing pages on 2026-09-30.
