# Models and budgets

tau's code never names a model. It asks for a **role** (`brain`, `fast`, `local`), and `tau.toml` says which provider and model id serve it. tau calls the provider directly with your own key from `.env`, or a local model through Ollama; there is nothing to run next to it. It also keeps the costs itself: every answer's token usage is priced and written to a small ledger on the hub, and a role with a **budget** stops at its cap for the day, week or month.

The decision is [ADR 0011](../adr/0011-budgets-in-tau-no-litellm.md). This guide is the user's side: pick a provider, understand the three roles, set the caps, see the spend, and know what happens when a budget runs out or a model cannot be reached.

```text
brain, fast ──► Anthropic, OpenAI or Gemini API    (your key from .env)
local       ──► Ollama, this machine or the Mac over the tailnet
                  └─ not reachable ──► fast answers instead   (failover)

every answer ──► priced (prices.toml) ──► TAU_DATA_DIR/spend.sqlite3
before a call: budget spent? ──► degrade_to answers, or tau says when it resets
```

## Providers and their keys

| Provider | Credentials (in `.env`) | Notes |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | A key that is not scoped to a workspace also needs `ANTHROPIC_WORKSPACE_ID` (Console → Settings → Workspaces); without it the API answers 400. `params.base_url` sets another API base URL. Honours the role's `cache` table. |
| `openai` | `OPENAI_API_KEY` | `params.base_url` points it at any OpenAI-compatible API. The role's `max_tokens` is sent as `max_completion_tokens`, which current OpenAI models expect. |
| `gemini` | `GEMINI_API_KEY`, or `GOOGLE_API_KEY` | Google Gemini through Strands' `GeminiModel` (the `google-genai` SDK). `max_tokens` is sent as `max_output_tokens`. |
| `ollama` | none | A local model. The server is the role's `params.base_url`, else `TAU_OLLAMA_URL`, else `http://127.0.0.1:11434` (without `/v1`; tau appends it). It fails fast: a 3-second connect timeout and no retries. Free. |
| `bedrock` | `AWS_REGION` + `AWS_PROFILE`, or `AWS_REGION` + `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`, or `AWS_REGION` + `AWS_BEARER_TOKEN_BEDROCK` | Optional. Model ids use the Converse form with the `global.` prefix. A `region` in the role drops `AWS_REGION`. Honours `cache`. |
| `fake` | none | The scripted model of the tests: answers `Okay.` or the role's `params.replies`. Free. |

`params.api_key_env` names another variable for the key of `anthropic`, `openai` or `gemini`, for example two OpenAI-compatible providers side by side:

```toml
[models.roles.fast]
provider = "openai"
model_id = "my-model"
params = { base_url = "https://llm.example.com/v1", api_key_env = "EXAMPLE_LLM_KEY" }
```

Keys go into `<TAU_HOME>/.env` (keep it at mode `0600`), never into `tau.toml`; the names are in `.env.example`. `/settings set NAME` in `tau chat` and the TUI's **Credentials** section write them for you with a hidden prompt. A missing key stops `tau chat` with the variable's name; `tau doctor` reports it without starting anything. The [environment reference](../reference/environment.md#model-credentials) lists every variable.

## Set up with `tau init`

`tau init` picks the first provider whose key it finds in the environment or `<home>/.env`: Anthropic, then OpenAI, then Gemini, then Bedrock, else the credential-free `fake`. `--provider anthropic|openai|gemini|bedrock|fake` picks one yourself.

```sh
tau init
```

```text
Provider: anthropic. ANTHROPIC_API_KEY was found in the environment or ~/.tau/.env. tau.toml caps brain and fast with budgets tau enforces itself (`tau spend` shows them), and local uses Ollama on this machine, falling back to fast when it is not running.
```

It writes the shipped `tau.toml` and rewrites only the `provider` and `model_id` of `brain` and `fast`, with the ids of a table shipped with tau-core (`templates/models.toml`):

| Provider | `brain` | `fast` |
|---|---|---|
| `anthropic` | `claude-sonnet-5` | `claude-haiku-4-5` |
| `openai` | `gpt-6.1-sol` | `gpt-6-luna` |
| `gemini` | `gemini-3.5-flash` | `gemini-3.1-flash-lite` |
| `bedrock` | `global.anthropic.claude-sonnet-5` | `global.anthropic.claude-haiku-4-5` |
| `fake` | `fake-brain` | `fake-fast` |

The budget tables stay (tau enforces them for every provider), and `local` stays on Ollama. To mix providers, say `brain` on Anthropic and `fast` on Gemini, edit the role tables by hand, use `/settings model fast gemini gemini-3.1-flash-lite` in `tau chat`, or use the **Model roles** section of the TUI's settings screen. After adding a key to an existing root, `tau init --force` rewrites `tau.toml` for it; `--force` also rewrites `persona/persona.md`, so edit the roles by hand if you changed that file.

## The roles

| Role | Shipped model | Used for | Budget | When it cannot answer |
|---|---|---|---|---|
| `brain` | Anthropic `claude-sonnet-5`, `max_tokens = 4096` | conversation and planning; `tau chat` and `tau tui` start on it | $15 per month | spent: `fast` answers until the 1st |
| `fast` | Anthropic `claude-haiku-4-5`, `max_tokens = 1024` | triage and summaries; `/model fast` | $1 per day | spent: tau says when it resets |
| `local` | Ollama `qwen3.5:9b`, `max_tokens = 1024` | on-device answers that never leave your machines | none (free) | not reachable: `fast` answers |

The shipped tables (the whole file is in the [tau.toml reference](../reference/tau-toml.md#the-shipped-file)):

```toml
[models.roles.brain]
provider = "anthropic"                    # anthropic | openai | gemini | ollama | bedrock | fake
model_id = "claude-sonnet-5"
max_tokens = 4096

[models.roles.brain.budget]               # a hard cap tau enforces itself
usd = 15                                  # dollars per period
period = "month"                          # day | week | month; resets at midnight, on Monday, on the 1st
degrade_to = "fast"                       # once spent, this role answers until the reset; omit to stop and say so

[models.roles.fast]
provider = "anthropic"
model_id = "claude-haiku-4-5"
max_tokens = 1024

[models.roles.fast.budget]
usd = 1
period = "day"

[models.roles.local]
provider = "ollama"                       # Ollama on this machine; TAU_OLLAMA_URL points at another (the Mac over the tailnet)
model_id = "qwen3.5:9b"                   # answers well in Turkish; `ollama pull qwen3.5:9b`
max_tokens = 1024
params = { reasoning_effort = "none" }    # answer at once instead of reasoning first
failover = "fast"                         # answers while Ollama is not reachable (a sleeping or absent Mac)
```

Three settings let another role stand in, and they are not the same thing:

| Setting | When | Checked |
|---|---|---|
| `budget.degrade_to = "<role>"` | the role's budget is spent for this period | before every call |
| `failover = "<role>"` | the role's model cannot be reached | at every call |
| `fallback = { provider, model_id, … }` | the role's provider has no credentials | once, when the agent is built |

`degrade_to` and `failover` must name another role defined in the file, and following them from role to role must not come back to where it started (`brain` degrades to `fast`, `fast` fails over to `brain` is refused). A stand-in is an ordinary role: its own budget and failover apply, and its spend counts under its own name.

## Budgets

A budget is a table under the role in `tau.toml` (an inline `budget = { usd = 1, period = "day" }` works too):

| Key | Meaning |
|---|---|
| `usd` | Dollars per period, a positive number. |
| `period` | `day`, `week` or `month`: calendar periods in Europe/Istanbul. A day resets at midnight, a week on Monday at 00:00, a month on the 1st at 00:00. |
| `degrade_to` | Optional. Another role that answers once this budget is spent, until the reset. Omit it and tau ends the turn and says when the budget resets. |

How tau keeps it:

- **Before every call** of a budgeted role, tau adds up what the role spent since the period started. At or over the cap, the call never reaches the provider: `degrade_to` answers, or the turn ends with one sentence.
- **After every answer**, tau prices the token usage the provider reported and writes one row to the ledger. The check is before the call, so the last answer before the cap can take the spend a few cents over it.
- **One ledger per hub.** `TAU_DATA_DIR/spend.sqlite3` is shared by every process that uses the same data directory: the hub with its Telegram channel, `tau chat`, `tau tui`. A budget counts every call, whichever channel made it. It holds the time, role, provider, model id, token counts and dollars of each call, never any text, and is created with mode `0600`.
- **Every provider.** Budgets work the same on `anthropic`, `openai`, `gemini` and `bedrock`; `ollama` and `fake` calls cost $0.
- **Only roles with a `budget` or a `failover` are metered.** A role with neither is called without the ledger; `tau spend` shows it as `no budget (its calls are not counted)`. To count a role's spend without really limiting it, give it a high cap.

**Change a cap:** edit the number in `tau.toml` and restart what runs tau. A running hub, `tau chat` or `tau tui` read the file when they start, so restart the hub (`tau hub stop`, then start it again, or untick and tick **Run the hub** in TauBar) and reopen the terminal channels. `tau spend` and `tau doctor` read the file each time, so they show the new cap at once. The spend itself is never reset by a change: a new cap applies to what the role already spent this period.

## When a budget is spent

tau turns a spent budget into one sentence in the UI language (Turkish with `[ui] language = "tr"`), never a stack trace. The terminal, the TUI and Telegram show the same text.

With `degrade_to`, the stand-in role answers and the reply ends with a notice:

```text
The brain budget is spent until 01.10.2026 00:00; fast answered instead.
```

Without `degrade_to`, the turn ends before any call is made:

```text
The brain budget is spent ($15.00 of $15.00) and resets at 01.10.2026 00:00. To raise the cap, change it in tau.toml.
```

When the stand-in is spent too:

```text
The brain budget is spent until 01.10.2026 00:00, and fast, which stands in for it, is spent too until 01.10.2026 00:00.
```

Times are Europe/Istanbul. The hub log (`<TAU_DATA_DIR>/logs/tau.log`) records every degraded call as a warning, for example `role brain: budget spent ($15.02 of $15.00, resets 2026-10-01T00:00:00+03:00); fast answers instead`.

## Failover and the local role

`failover = "<role>"` hands a call to another role when the model cannot be reached **before anything streamed**:

- the connection is refused (Ollama is not running): at once;
- nothing answers (a sleeping Mac, a laptop away from home): after the 3-second connect timeout of the `ollama` provider;
- the provider answers with a 5xx error.

Throttling (429) is never failed over; Strands retries it. Nor is an error after the reply started (the stand-in would repeat half an answer) or any other refusal, such as a model Ollama does not have. The reply then ends with:

```text
local is not reachable right now; fast answered instead.
```

and the hub log has a warning such as `role local: ollama qwen3.5:9b is not reachable (…); fast answers instead`. The shipped `local` role on a Mac that is asleep or away is answered by `fast` within about 3 to 6 seconds. Any role can have a failover: pointing `brain`'s `failover` at a role on another provider keeps tau answering through an outage of `brain`'s provider, within that role's budget.

### Set up Ollama

1. Install [Ollama](https://ollama.com) on the Mac and pull the model:

    ```sh
    ollama pull qwen3.5:9b
    ```

2. `qwen3.5:9b` is the recommended local model: it answers well in Turkish. `params = { reasoning_effort = "none" }` asks it to answer at once instead of reasoning first, so a short reply takes about two seconds. Any other model you pulled works too: put its Ollama name in `model_id`.
3. **Hub on the Mac:** nothing to set; tau reaches Ollama on `127.0.0.1:11434`.
4. **Hub elsewhere** (a [Raspberry Pi](raspberry-pi.md)): set the Mac's address in the hub's `.env`,

    ```sh
    TAU_OLLAMA_URL=http://my-mac.tailXXXXXX.ts.net:11434
    ```

    and let Ollama on the Mac listen on its tailnet address only, never on every interface: the tailnet is the only network that should reach it ([ADR 0006](../adr/0006-private-first-topology.md)). For the Ollama app that is `launchctl setenv OLLAMA_HOST 100.x.y.z:11434` and a restart of the app; for `ollama serve` in a terminal, `OLLAMA_HOST=100.x.y.z:11434 ollama serve`.

Ollama calls are free, and a prompt to `local` never leaves your machines. While the Mac is away, `local`'s questions go to `fast` and count against `fast`'s budget.

## Prices

tau prices an answer with a table of US dollars per million tokens, keyed by model id. tau-core ships one (`templates/prices.toml`, from the providers' pricing pages on 2026-09-30):

| Model id | Input | Output | Cache read | Cache write |
|---|---|---|---|---|
| `claude-sonnet-5`, `claude-sonnet-5-5`, `global.anthropic.claude-sonnet-5` | 2.00 | 10.00 | 0.20 | 2.50 |
| `claude-haiku-4-5`, `claude-haiku-4-5-20251001`, `global.anthropic.claude-haiku-4-5` | 1.00 | 5.00 | 0.10 | 1.25 |
| `claude-opus-5-5` | 4.00 | 20.00 | 0.20 | 5.00 |
| `gpt-6.1-sol` | 2.00 | 10.00 | 0.10 | – |
| `gpt-6-sol` | 2.00 | 10.00 | 0.20 | – |
| `gpt-6-luna` | 0.10 | 0.50 | 0.01 | – |
| `gemini-3.5-flash` | 1.50 | 9.00 | 0.15 | – |
| `gemini-3.1-flash-lite` | 0.25 | 1.50 | 0.025 | – |
| `gemini-2.5-pro` | 1.25 | 10.00 | 0.125 | – |

A dash is a price the table leaves out; the input price stands in for it. `tau.toml` extends or overrides it per model id:

```toml
[models.prices."my-model"]
input = 0.5            # $ per million input tokens (required)
output = 1.5           # $ per million output tokens (required)
cache_read = 0.05      # optional; defaults to input
cache_write = 0.625    # optional; defaults to input
```

- A price in `tau.toml` wins over the shipped one for the same id. Values are dollars, 0 or more; an unknown key is an error.
- A model in neither table is **unpriced**: its calls go into the ledger without a cost and count as $0, so a budget on it would never be reached. `tau doctor` warns about every budgeted role on an unpriced model, and `tau spend` counts its unpriced calls.
- Anthropic and Bedrock report cached tokens apart from the input tokens; OpenAI and Gemini include them in the input. tau takes that into account, so a cached token is priced once, at its cache price.
- Long-context surcharges (above 200k tokens) are not modelled. The ledger is tau's estimate; the provider's bill is the truth.

## See the spend

**`tau spend`** prints every role against its budget, read from the ledger (`--json` for scripts):

```text
  brain    anthropic $0.42 of $15.00 this month, resets 01.10.2026 00:00
  fast     anthropic $0.03 of $1.00 today, resets 01.10.2026 00:00
  local    ollama    $0.00 this month, no budget
```

A spent role is marked `· SPENT` (with `, fast answers instead` when it degrades), and a role with calls on an unpriced model `· N calls without a price for <model id>`. The [CLI reference](../reference/cli.md#tau-spend) has the JSON.

**`/status`** in the terminal, the TUI or Telegram ends with the same numbers, read from the ledger on the spot:

```text
Budget: brain $0.42 of $15.00 this month (resets 01.10.2026 00:00); fast $0.03 of $1.00 today (resets 01.10.2026 00:00)
```

**The model** sees that line as `- Budget: …` under `## Now` in its system prompt, so it can tell you how much is left (the `budget` context source; one local query per role before a call, no network). Without any budget in `tau.toml` the line reads `- Budget: unknown`.

**`tau doctor`** prints it as its `budget` line:

```text
ok   budget: brain $0.00 of $15.00 this month (resets 01.10.2026 00:00); fast $0.00 of $1.00 today (resets 01.10.2026 00:00)
```

**The hub** serves it on its control API (loopback only), and `GET /status` carries the same object under `spend`:

```sh
curl -s 127.0.0.1:7877/spend
```

```json
{
  "roles": {
    "brain": {
      "provider": "anthropic",
      "model_id": "claude-sonnet-5",
      "spent_usd": 0.42,
      "cap_usd": 15.0,
      "period": "month",
      "since": "2026-09-01T00:00:00+03:00",
      "reset_at": "2026-10-01T00:00:00+03:00",
      "exhausted": false,
      "degrade_to": "fast",
      "unpriced_calls": 0,
      "metered": true
    }
  }
}
```

Every role of `tau.toml` has an entry; a role without a budget has `"cap_usd": null` and is reported for the current month.

## The provider's own limit

Set a monthly spend limit in your provider's console as well (the Anthropic Console's workspace limits, or the billing limits of OpenAI or Google). It is the last line of defence: tau cannot see calls made with the same key outside tau, a role without a budget is not counted, and the price table can lag behind a price change.

## Troubleshooting

| You see | Do |
|---|---|
| `fail role brain: provider 'anthropic' is missing ANTHROPIC_API_KEY (names are in .env.example)` | Add the key to `<TAU_HOME>/.env` (or `/settings set ANTHROPIC_API_KEY`), then restart tau. |
| `warn role brain: has a budget, but model 'my-model' has no price, so its calls count as $0; add [models.prices."my-model"] to tau.toml` | Add the price table shown above. |
| `local is not reachable right now; fast answered instead.` on every `local` turn | Ollama is not running or not where tau looks. `curl http://127.0.0.1:11434/api/tags` on the Mac (or the `TAU_OLLAMA_URL` address from the hub) should list the model; start Ollama, check `TAU_OLLAMA_URL` and that Ollama listens on the tailnet address. |
| A model error on `local` that mentions a missing model | `ollama pull qwen3.5:9b`, or the name in `model_id`. A model Ollama does not have is not failed over. |
| A 400 from Anthropic about a key that is not scoped to a workspace | Set `ANTHROPIC_WORKSPACE_ID`. |
| A new cap in `tau.toml` shows in `tau spend` but tau still stops at the old one | Restart the hub and reopen `tau chat` / `tau tui`; they read `tau.toml` when they start. |
| `tau.toml: [models.roles.brain] 'budget' needs 'period', one of day, week, month.` | `period = "1mo"` or `"1d"` from an older file: write `"month"` or `"day"`. |
| `tau.toml: [models.roles.brain] stand-ins loop: brain → fast → brain (budget.degrade_to and failover together).` | Remove one of the two stand-ins so the chain ends. |
| `warn .env: names in .env that .env.example does not list: …` | A variable you no longer use: delete it from `.env`, or add its name to `.env.example` if you still need it. |
| The provider's console shows more than `tau spend` | Calls outside tau with the same key, a role without a budget, or a price that changed. Check the console limit. |
