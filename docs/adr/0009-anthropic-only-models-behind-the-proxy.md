# ADR 0009 · Anthropic-only models behind the LiteLLM proxy

Date: 2026-09-30 · Status: superseded in part by [ADR 0011](0011-budgets-in-tau-no-litellm.md) (decisions 1–6; 7 and 8 stand) · Supersedes the 2026-09-28 "Models" and "Cost protection" decisions in `docs/ARCHITECTURE.md` (Bedrock as the primary provider, AWS Budgets alarms) and closes roadmap 067.

## Context

The 2026-09-28 plan was:

- `brain`: Claude Sonnet on Amazon Bedrock, with the Anthropic API as its fallback.
- `fast`: Claude Haiku on Bedrock.
- `local`: Ollama on the Mac.
- All three behind a LiteLLM proxy with hard budgets per role, plus AWS Budgets alarms.

The AWS half of issue 003 (IAM user, Bedrock model access, Budgets alarms) was never done. Only an Anthropic API key exists, and every live run so far went through the direct `anthropic` provider as Bedrock's fallback. On 2026-09-30 the owner decided to drop Bedrock instead of setting up AWS.

Hard budgets are still wanted: the owner is careful about surprise bills. Spend should also be visible inside tau (in the dynamic context, `/status` and the hub API), not only in a provider console.

## Decision

1. **Anthropic is the only cloud provider in tau's own setup.**
   - `brain` is Claude Sonnet 5.
   - `fast` is Claude Haiku 4.5.
   - `local` is Ollama on the Mac, recommended model `qwen3.5:9b` (answers well in Turkish; thinking is switched off).

   Model ids are data. In proxy mode they live in `infra/litellm/config.yaml`; in direct mode, in `tau.toml` and `templates/models.toml`.

2. **Every role goes through the LiteLLM proxy by default** (`infra/litellm`, docker compose).
   - Pinning: the LiteLLM image is pinned by tag and digest (v1.103.1), and so is Postgres (17.11-alpine), which keeps the spend. Both images are multi-arch, so the same file runs on the RPi5 hub.
   - Exposure: the proxy publishes only `127.0.0.1:4000`, and the database publishes nothing.
   - Cost map: the proxy uses the one bundled with the pinned image (`LITELLM_LOCAL_MODEL_COST_MAP`). A remote map could change what a budget means.
   - Privacy: prompts and replies never reach its spend log (`turn_off_message_logging`, `store_prompts_in_spend_logs: false`).
   - How tau talks to it: the `proxy` provider, which is Strands' `OpenAIModel` pointed at the proxy. It never uses `LiteLLMModel`, because that imports the `litellm` package. `litellm` stays out of every `pyproject.toml` and `uv.lock` (the PyPI releases were compromised in March 2026). The only new dependency is the `strands-agents[openai]` extra.

   Each role is one model group, and each group has one virtual key (`TAU_PROXY_KEY_<GROUP>`).

3. **The proxy's fallbacks are degradations, not provider redundancy.** Without Bedrock there is no second provider for Sonnet.
   - `brain` → `fast` when Anthropic refuses the Sonnet call (overloaded, 5xx).
   - `local` → `fast` when Ollama is unreachable. The local deployment has no retries and a 20 s stream timeout, so a sleeping Mac costs one short wait, not minutes.

   tau reads the proxy's `x-litellm-attempted-fallbacks` header and logs every fallback on the hub.

4. **A hard budget per role, defined in `tau.toml`.**
   - Definition: `[models.roles.<role>.budget]` sets `usd`, a `period` (LiteLLM `budget_duration`, resets in UTC) and an optional `degrade_to` role.
   - Enforcement: `tau proxy keys` writes the cap to the role's key, and the proxy enforces it. A cap changes with a config edit and one command, never with a code change.
   - A spent key is not a fallback case. The proxy refuses it before routing, with `429 budget_exceeded`, so tau decides what happens:
     - With `degrade_to`, that role answers and the channel says so.
     - Without it, the turn ends with one sentence in the UI language that names the reset time.
   - `ProxyModel` catches the refusal before Strands can retry the 429 as throttling.

5. **Spend comes from the proxy, per role.**
   - Source: the proxy's spend for the key's current period (for a daily cap, that is today's spend). tau reads it with the role's own key (`GET /key/info`, no master key). Every proxied answer also carries it in a header.
   - Where it shows:
     - under `## Now` as `- Budget: …` (the label was `Budget today`)
     - in `/status`
     - in the hub's `GET /spend` and `/status`
     - in `tau proxy spend`
   - `tau doctor` warns when a key's cap drifts from `tau.toml`.

6. **Direct mode stays, without budgets.**
   - Providers: `anthropic`, `bedrock` (optional, for other installations), `ollama` and `fake` all work without Docker.
   - `tau init` picks `proxy` only when a proxy key is present. Otherwise it writes direct providers and drops the budget tables, because nothing would enforce them.
   - Proxy mode never falls back to direct mode. A missing key or a stopped proxy is a clear error, never a silent bypass of the budget.

7. **No in-process failover router for now (roadmap 067).** Strands' `ModelRouter` (strands-agents 1.57.1) is not adopted, for these reasons:
   - Its API is marked provisional.
   - `agent.model` stays the first candidate. So `/status`, compaction and the SDK's proactive compression reason about a model that is not the one running.
   - A candidate that fails mid-stream leaves its partial output in front of the replacement's full reply, which would show as duplicate text in the TUI and on Telegram.
   - It advances on any failure the retry strategy declines, unless a custom strategy is written.
   - `structured_output` bypasses it.
   - Nothing needs it today. The proxy already does `brain`/`local` → `fast`. The budget case is a few lines in `ProxyModel`, which acts before anything has streamed.

   Revisit when `ModelRouter` is final and threads the selected model through the agent, or when direct mode needs failover.

8. **Last line of defence: a monthly spend limit on the Anthropic workspace** in the Console. It replaces the AWS Budgets alarms and caps everything, including calls that bypass tau.

## Consequences

- Issue 003 loses its AWS criteria. The Anthropic key and a Console spend limit remain.
- Two long-running containers join the hub:
  - On the Mac, Docker Desktop must start at login; `restart: unless-stopped` brings the containers back.
  - On the RPi5, the docker service does the same.
- Cloud mode ([ADR 0007](0007-cloud-mode-and-tau-network.md)) runs the hub in a container without the proxy, so it uses direct mode and has no proxy budgets.
- `PLANNED_PROVIDERS` is empty. The mechanism stays for the next provider a later issue builds.
- Prompt caching does not pass through the proxy yet: `OpenAIModel` drops Strands' cache points. This is a follow-up (roadmap 131).
- The `local` role's budget only bounds what its `fast` fallback may spend; Ollama itself costs nothing.

## Why not

- **Keep Bedrock as the primary provider.** It needs an AWS account, an IAM identity and model access that the owner decided against. The only gain would be provider redundancy for the same models.
- **Only the Console spend limit.** It is one monthly cap for the whole workspace: no per-role or daily caps, no degrade, and no spend inside tau.
- **Count cost in tau itself.** tau would need its own price table, and every process (`tau chat`, the hub, the TUI) would keep its own counter. The proxy sees every call once and already knows the prices of the pinned image.
- **`LiteLLMModel` or the litellm SDK in-process.** That is exactly the supply-chain exposure the container isolates.
- **`ModelRouter` now.** See decision 7.
