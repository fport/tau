# tau — Architecture decisions

> Source: the grill session of 2026-09-28. When a decision changes, update this file and move the old decision under "Changes".

tau is a personal "smart body" that automates life: an agent platform you talk to from Telegram, the terminal and by voice, and that touches the physical world through a robot arm, a necklace camera, home sensors and, later, a drone.

## Principles

1. **The brain thinks in the cloud, reflexes run locally.** Posture alerts, house rules and the emergency stop never depend on an LLM or on Cloudflare.
2. **The same code on every machine.** The only difference is the role: `TAU_ROLE=hub|node`. Only one hub is active at a time.
3. **Settings are data, not code.** The D1 `settings` table reaches the hub by hot reload; no deploy needed.
4. **Everything that touches the physical world or tau's own code needs approval** (tier 2).
5. **No hardware, no code.** A device that is not on hand only gets a reserved place in the mesh.

## Decisions

| Area | Decision | Note |
|---|---|---|
| Core | **Strands Agents** from scratch (Python 3.12+, `uv` workspace) | DevDuck is reference only |
| Packaging | **This repo is the centre.** Every package under `packages/*` is an independent PyPI distribution: `tau-<name>`, import `tau_<name>` (flat, no namespace). Extension through entry points (`tau.tools`, later `tau.nodes`, `tau.channels`) | `tau`, `tau-hub` and `tau-agent` are taken on PyPI. A package that needs its own release cadence moves to its own repo and tau consumes it from PyPI |
| Topology | **MacBook = hub** for now; when the RPi5 arrives the hub moves there | While the hub is offline tau does not think; the relay queues |
| State | **Cloudflare**: D1, R2, Vectorize, AI Search — all behind the `tau-cloud` Worker | The hub never calls the D1 REST API directly |
| External channel ingress | Telegram webhook → Worker → **Durable Object** ← the hub's outbound WebSocket | `chat_id` allowlist; hub offline → queue + a "tau is offline" reply |
| Mesh | **Control = MCP** (streamable HTTP over Tailscale) · **Data = Zenoh** (events, telemetry, discovery through liveliness) | No multicast on Tailscale → nodes `connect` explicitly to `zenohd` |
| Microcontrollers | **ESPHome** (free firmware) → MQTT → `zenohd` MQTT plugin → `tau/…` keyspace | No Home Assistant; if ever needed it is added later through MCP |
| Models | **LiteLLM Proxy** (Docker, image pinned by digest) + Postgres; roles `brain` / `fast` / `local` | `brain` = Bedrock Sonnet (fallback Anthropic), `fast` = Bedrock Haiku, `local` = Ollama on the Mac |
| Cost protection | Hard budget per virtual key + AWS Budgets alarm + Strands max tool iterations | Bedrock Knowledge Bases (OpenSearch Serverless) is not used |
| Safety | **Tier 0** read, free · **Tier 1** digital write, free + log · **Tier 2** physical action + tools tau wrote → Telegram inline approval | New tools land in `tools/_pending/`; registered routines are exempt from approval |
| Remote | macOS **OpenSSH** (key-only, `AllowUsers` restricted to tailnet + localhost) + **tmux + mosh** + Termius; wrangler with `CLOUDFLARE_API_TOKEN` | A `caffeinate -s` LaunchAgent keeps the Mac awake on AC until TauBar takes over. Claude Code `Notification` hook → tau → Telegram "waiting for you" |
| TauBar | **Tauri v2 + React/TS**, tray-only; `PreventSystemSleep` through `keepawake`; a narrow sudoers rule for `pmset disablesleep` | Sleep modes: Normal / **Stay awake on AC (default)** / Even with the lid closed. The Python mac-node runs as a sidecar and inherits the TCC permission |
| Knowledge base | `kb/` markdown → R2 → **AI Search** (managed) | Periodic indexing |
| Memory | `memory` → D1 row + Workers AI embedding → **Vectorize** (own pipeline, immediate upsert) | A **Self-RAG** loop inside the agent: retrieve → grade → re-query if needed |
| Session recording | Strands `SessionManager` → Worker → D1; resume with `/resume`, replay in the TUI | **Everything is kept.** Raw telemetry/media in R2 (NDJSON/Parquet), private bucket, short signed URLs. Retention lives in `settings` |
| AgentCore | **Lab only** (`deploy/agentcore/`) | `build_agent(profile)` carries no hub-specific assumption |
| Ambient | **Off by default**, the user turns it on; profiles `home` / `travel` / `sport` | Triggers: Telegram `/ambient`, TauBar, later the necklace. The startup message and routines run independently of ambient |
| Self-replication | Installing on a new machine (SSH, tier 2) · sub-agents/copies · persistence/self-heal | Start with one agent; past ~25 tools switch to agents-as-tools (`home`, `robot`, `dev`, `research`) |
| Channels | M1: Telegram text + **TUI** (Textual) · M2: Telegram voice (Workers AI Whisper) + **tau MCP server** · M4: **Hey tau** (openWakeWord + MLX Whisper, fully local) | The wake word must have 3–4 syllables |
| Persona | **Jarvis-style**, Turkish by default, mirrors the user's language; `persona.md` + `user.md` + dynamic context (time, profile, nodes, budget) | Brevity rule: at most 1–2 sentences in notifications and voice; approval requests carry no jokes |
| UI language | Per-installation setting `[ui] language = "en" \| "tr"` in `tau.toml` (default `en`), overridden by `TAU_LANG`, `tau --lang`, and `/lang` for one session. Every piece of UI chrome (slash commands, labels, pane titles, key hints, notices, approval dialog, CLI help) comes from one message table shared by the terminal and the TUI | The chrome is English by default; the persona is Turkish by default and language-adaptive; everything the model reads (prompt headings, context labels, gate texts, tool descriptions) is fixed English. Errors raised before Config exists are plain English |
| Components | Every pluggable part is an entry point in a `tau.*` group: `tau.tools`, `tau.commands`, `tau.providers`, `tau.sessions`, `tau.context`, `tau.hub_services`. `tau.toml` `[components]` disables tools and picks context sources and hub services; `tau components` lists everything with distribution, version and load errors, `tau doctor` checks the installation, `tau init` writes the first config | The tier gate is pinned last with `HookOrder.SDK_LAST`, so no plugin hook can rewrite a call after it was approved. Plugin tools that are not in the `ToolCatalog` fail closed: refused, never run |
| Secrets | Local `.env` (gitignored) · `wrangler secret` in the cloud · Keychain for TauBar | Provisioning moves secrets over SSH |
| Domain | `getporti.<tld>` → nameservers to Cloudflare | Disable DNSSEC at the registrar first; verify MX/SPF/DKIM/DMARC by hand |
| Necklace | **XIAO ESP32S3 Sense** (WiFi camera, pose on the Mac/RPi5) + **Nicla Vision** (on-device ML: rep counting with the IMU, fall detection) | Pose estimation is not done on the Nicla |
| SO-101 | **strands-robots**, MuJoCo sim first, `mode="real"` is an explicit opt-in | Trigger: TauBar `screenIsUnlocked` → `tau/desk/presence` → routine |

### Subdomain scheme

- `tau.getporti.<tld>` → dashboard
- `api.tau.getporti.<tld>` → relay, Telegram webhook, memory API (Cloudflare Access)
- `<project>.getporti.<tld>` → projects built with Claude Code and deployed with `wrangler`
- `*.workers.dev` until the domain is moved

## Roadmap (layer order)

Each layer sits on the previous one and the next starts once the current one is useful on its own. Issues live under [`roadmap/`](../roadmap/README.md), one folder per layer; `python3 roadmap/board.py` shows the state.

| # | Layer | Scope |
|---|---|---|
| **0** | **Remote access** | Tailscale + OpenSSH hardening + tmux/mosh + Termius + stay awake on AC → `infra/remote/` |
| **1** | **Agent** | Strands core (`build_agent`), persona, tier system, TUI, launchd service. Model straight from the provider for now; the role abstraction exists from day one. Follow-ups: 062 (English UI and language setting), 063 (premium TUI), 064 (Strands correctness pass), 065 (component builder), 066 (English docs) |
| **2** | **Models** | LiteLLM proxy, `brain`/`fast`/`local` roles, budgets, AWS Budgets |
| **3** | **Cloud** | Domain NS → Cloudflare, `tau-cloud` Worker, Telegram relay (DO) + **startup status report**, D1/R2/Vectorize/AI Search, session recording |
| **4** | **Interface** | TauBar (takes over the sleep modes), Telegram voice, tau MCP server, Claude Code hook, Hey tau |
| **5** | **Mesh** | `zenohd` + MCP node discovery, hot-reloaded `tools/` + `_pending`, ESPHome/MQTT |
| **6** | **Robot** | SO-101 (sim → real → a wave when you sit down at the desk), necklace (XIAO → Nicla) |
| **7** | **Lab** | AgentCore, autonomous task queue |
| — | **When the RPi5 arrives** | Hub migration through self-replication (independent of the layers) |
| — | **Later** | Drone |

## Proposed repo layout

```
tau/
├── CLAUDE.md                 # agent instructions
├── CONTEXT.md                # glossary
├── roadmap/                  # file-based issue tracker + board.py
├── docs/                     # ARCHITECTURE.md, agents/, adr/
├── pyproject.toml            # uv workspace root
├── packages/                 # each an independent PyPI distribution: tau-<name> / import tau_<name>
│   ├── tau-core/             # build_agent, persona, tiers, roles, session store, `tau` CLI, `tau hub`
│   ├── tau-tui/              # Textual
│   ├── tau-mesh/             # Zenoh + MCP discovery
│   ├── tau-robot/            # strands-robots / SO-101 node
│   └── tau-vision/           # workout coach (pose)
├── nodes/mac/                # macOS node (TauBar sidecar)
├── apps/taubar/              # Tauri v2 + React/TS
├── cloud/tau-cloud/          # Worker (TS): relay DO, D1, R2, Vectorize, AI Search, Whisper
├── persona/                  # persona.md, user.example.md (user.md gitignored)
├── tools/                    # hot-reloaded tools
│   └── _pending/             # tools tau wrote, waiting for approval
├── infra/
│   ├── litellm/              # docker-compose + config.yaml
│   ├── zenoh/                # zenohd + MQTT plugin config
│   ├── services/             # launchd plist, systemd unit
│   └── remote/               # sshd_config, tmux, mosh
├── firmware/                 # ESPHome YAML, XIAO, Nicla (when the hardware arrives)
└── deploy/agentcore/
```

## Open items

Each one is tracked as a `ready-for-human` issue.

1. **SO-101 motion generation:** keyframe scripts / leader teleop + policy / live LLM guidance → [038](../roadmap/L6-robot/038-decide-so101-motion-method.md)
2. **Domain:** the full name (TLD) and the NS move → [022](../roadmap/L3-cloud/022-move-dns-to-cloudflare.md)
3. **Necklace workout alerts:** alert channel, exercises, mistakes → [042](../roadmap/L6-robot/042-decide-workout-alert-channel.md)
4. **Hey tau:** the wake phrase → [030](../roadmap/L4-interface/030-pick-wake-phrase.md)
5. **Drone:** model choice, SHGM rules → [050](../roadmap/backlog/050-drone-model-and-rules.md)
6. **Shopping list (TR):** RPi5, XIAO, Nicla, ESP32 + LD2410 + sensors → [049](../roadmap/backlog/049-hardware-shopping-list.md)

## Changes

Decisions that were replaced, with the date, so the history stays readable.

- **2026-09-29 — Repo language.** Before: `docs/ARCHITECTURE.md` and `infra/remote/` were Turkish, and tau's user-facing output was Turkish by rule. Now: everything in the repo is English, including this file, `infra/remote/` and the script messages. Turkish remains only for talking to the user in the Claude Code session and for the body of `persona/persona.md`; the UI chrome follows the `[ui] language` setting (issue 066).
- **2026-09-29 — Slash commands.** Before: Turkish command names (`/devam`, `/oturumlar`, `/yardım`, `/çık`, `/ayar`, `/ambient seyahat`). Now: canonical English names (`/resume`, `/sessions`, `/help`, `/quit`, `/settings`, `/ambient travel`) with the Turkish names kept as aliases that are accepted forever but never shown in hints (issue 062).
- **2026-09-29 — Profile names.** Before: `ev` / `seyahat` / `spor`. Now: `home` / `travel` / `sport`, with `home` as the default. Renamed now because profile keys will later live in D1 as data (issue 062).
- **2026-09-29 — Persona language.** Before: "Jarvis-style, Turkish". Now: Turkish by default and mirroring the language the user writes in; code, commands, file names and technical terms are left as they are.
