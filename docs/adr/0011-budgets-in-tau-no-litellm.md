# ADR 0011 · Budgets in tau, providers called directly, no LiteLLM

Date: 2026-09-30 · Status: accepted · Supersedes decisions 1–6 of [ADR 0009](0009-anthropic-only-models-behind-the-proxy.md) (Anthropic-only, the LiteLLM proxy, budgets on proxy keys). Decisions 7 (no Strands `ModelRouter` yet) and 8 (a spend limit in the provider's console) stand.

## Context

ADR 0009, accepted earlier the same day, put every model role behind a LiteLLM proxy in Docker. The proxy did three things:

- enforced a hard budget per role;
- counted the spend;
- fell back from `local` to `fast` while Ollama was away.

It worked on the owner's Mac. But tau is meant to be installed by other people from PyPI (L8, [ADR 0007](0007-cloud-mode-and-tau-network.md)). A user who has to install Docker, run a compose stack with Postgres and manage virtual keys before the first answer will not get far.

Those users bring either a local model (Ollama) or their own key for Anthropic, OpenAI or Google Gemini. For them, the proxy adds no provider tau cannot call itself. It only adds the three features above, and tau can provide all three in-process.

ADR 0009 rejected counting cost in tau for two reasons: each process would need its own price table, and each would keep its own counter. Neither holds anymore:

- the prices become a data file shipped with tau-core;
- every process on the hub writes to one SQLite ledger under `TAU_DATA_DIR`.

## Decision

1. **No LiteLLM, no Docker for models.** `infra/litellm`, the `proxy` provider and `tau proxy` are removed. `litellm` stays out of every Python dependency (the PyPI compromise of March 2026).

2. **Providers are called directly.**
   - `anthropic`, `openai` and `gemini` are cloud providers. `openai` also covers OpenAI-compatible APIs through `params.base_url`; `gemini` uses Strands' `GeminiModel` (`google-genai`).
   - `ollama` is the local model. It fails fast: a 3 s connect timeout and no retries.
   - `bedrock` stays optional, and `fake` remains for tests.

   `tau init` picks the first provider whose key it finds, in this order: Anthropic, OpenAI, Gemini, Bedrock, else `fake`. It writes that provider's model ids (`templates/models.toml`) for `brain` and `fast`, and keeps `local` on Ollama.

3. **tau enforces the budgets.**
   - Definition: a role's `[models.roles.<role>.budget]` sets `usd` per calendar `period` (`day`, `week` or `month`, in Europe/Istanbul) and an optional `degrade_to`.
   - Metering: a role with a budget (or a `failover`) is wrapped in `tau_core.budget.RoleModel`. Every answer's token usage is priced (`templates/prices.toml`, overridable per model in `[models.prices]`) and recorded in `TAU_DATA_DIR/spend.sqlite3`. The ledger holds time, role, model, tokens and dollars, never text.
   - Enforcement: before a call, a role whose period spend reached its cap does one of two things:
     - with `degrade_to`, hands the call to that role, and the channel says so;
     - without it, ends the turn with one sentence in the UI language that names the reset time.

4. **Failover is a role setting.** `failover = "<role>"` answers when the role's model cannot be reached before anything has streamed: connection refused or timed out, or a 5xx.
   - Throttling is left to Strands' retry.
   - The channel says which role answered, and the hub log records it.
   - The shipped `local` role fails over to `fast`.
   - `degrade_to` and `failover` must name other roles and must not form a loop together.

5. **Spend is read from the ledger.** The same numbers appear:
   - under `## Now` (`- Budget: …`);
   - in `/status`;
   - in the hub's `GET /spend` and `/status` `spend` key;
   - in `tau spend` and in the `budget` line of `tau doctor`.

   `tau doctor` also warns about a budgeted role whose model has no price, because such a budget could never be reached.

## Consequences

- Installing tau needs Python and a key (or Ollama), nothing else. The same code runs on the Mac, the RPi5 and in the cloud-mode container. The container enforces the same budgets, but its ledger lives in the container's data directory. Until that directory survives a restart (roadmap 096), a container's budgets count only since it last started.
- The budget is only as good as the price table. The table ships with tau-core and is dated. A new model needs a `[models.prices]` entry until a release adds it; `tau doctor` points this out.
- tau cannot see calls made with the same key outside tau. The provider's console limit (ADR 0009, decision 8) stays the last line of defence.
- The per-key isolation of the proxy is gone: each role uses the provider's key directly. The key never leaves `.env` on the hub.
- Prompt caching works again for the direct Anthropic provider (the role's `cache` table). Roadmap 131 (caching through the proxy) is dropped.
- Only roles with a budget or a failover are metered. `tau spend` says so for the others.

## Why not

- **Keep the proxy as an optional mode.** That would mean two budget implementations, two sets of docs and two failure modes, while almost every user takes the simple path. The owner chose one path.
- **Run LiteLLM without Docker.** `pip install litellm` is exactly the supply-chain exposure the container was isolating, and its budgets need Postgres anyway.
- **Rely on provider consoles alone.** They offer one monthly cap per account or workspace, with no per-role or daily caps, no degrade and no spend inside tau.
