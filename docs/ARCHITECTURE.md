# tau — Architecture decisions

> Source: the grill session of 2026-09-28. When a decision changes, update this file and move the old decision under "Changes".

tau is a personal "smart body" that automates life: an agent platform you talk to from Telegram, the terminal and by voice, and that touches the physical world through a robot arm, a necklace camera, home sensors and, later, a drone.

## Principles

1. **The brain thinks in the cloud, reflexes run locally.** Posture alerts, house rules and the emergency stop never depend on an LLM or on any cloud service.
2. **The same code on every machine.** The only difference is the role: `TAU_ROLE=hub|node`. Only one hub is active at a time.
3. **Settings are data, not code.** A settings file on the hub, hot-reloaded; no deploy, no cloud copy.
4. **Everything that touches the physical world or tau's own code needs approval** (tier 2).
5. **No hardware, no code.** A device that is not on hand only gets a reserved place in the mesh.
6. **Private first.** In local mode (the default) life data stays on the hub; the only public surface is one hostname behind identity; no intermediary can approve an action; every inbound text is untrusted ([ADR 0006](adr/0006-private-first-topology.md)). Cloud mode is the owner's explicit choice to run the same hub in their own Cloudflare account ([ADR 0007](adr/0007-cloud-mode-and-tau-network.md)).
7. **Taus talk as peers.** Every tau that joins the network has its own spine Worker and address; envelopes are signed and sealed end to end, only accepted contacts reach the model, and nothing a peer sends can approve an action.

## Decisions

| Area | Decision | Note |
|---|---|---|
| Core | **Strands Agents** from scratch (Python 3.12+, `uv` workspace) | DevDuck is reference only |
| Packaging | **This repo is the centre.** Every package under `packages/*` is an independent PyPI distribution: `tau-<name>`, import `tau_<name>` (flat, no namespace). Extension through entry points (`tau.tools`, later `tau.nodes`, `tau.channels`) | `tau`, `tau-hub` and `tau-agent` are taken on PyPI. A package that needs its own release cadence moves to its own repo and tau consumes it from PyPI |
| Topology | **MacBook = hub** for now; when the RPi5 arrives the hub moves there | While the hub is offline tau does not think; Telegram keeps updates for about a day |
| State | Local mode: **on the hub** (`TAU_DATA_DIR`: files + SQLite): sessions, settings, memory, knowledge base, routines. Cloudflare **R2** holds only client-side encrypted backups (`age`) | In local mode D1, Vectorize and AI Search hold no personal data and the spine only holds sealed envelopes in transit ([ADR 0006](adr/0006-private-first-topology.md)); cloud mode keeps the same data in the owner's own D1/KV ([ADR 0007](adr/0007-cloud-mode-and-tau-network.md)) |
| Deployment modes | **Local** (default): the hub on the owner's machine · **Cloud** (opt-in): the same Python hub as a **Cloudflare Container** behind the owner's spine Worker; sessions and state in D1 (`[sessions] backend = "spine"`), persona and `tau.toml` in KV (`tau cloud push`) | Same code in both. Cloud mode needs Workers Paid and Docker for the image; the spine's cron keeps the container awake for the Telegram poller ([ADR 0007](adr/0007-cloud-mode-and-tau-network.md)) |
| tau network | **Federated**: address = the host of a tau's spine; card at `/.well-known/tau.json` (Ed25519 signing key, X25519 box key); envelopes signed and sealed end to end, posted hub → the peer's spine → the peer's hub by long poll. `tau-net` package, `cloud/spine` Worker | Contacts need the owner's acceptance and are key-pinned; network turns run with `persona.md` + the public note `persona/net.md`, no tools, no approvals, bounded auto-replies; `net_send` is tier 2. Protocol: `docs/reference/tau-network.md` |
| Universe | `tau.<domain>` is the public site with an **opt-in directory of taus**: signed `join`/`report`/`leave` (Ed25519, prefix `tau-universe/1`), links drawn only when both taus report each other, counts only, never contents; unlisted contacts are never reported. The spine ships inside `tau-net` (`tau net spine init|deploy`), so no repository is needed to join | Anyone can run a universe (`[component.net] universe`); taus leave with `tau net universe leave` or drop out after 30 days without a report ([ADR 0010](adr/0010-public-site-and-tau-universe.md)). Protocol: `docs/reference/tau-universe.md` |
| Sub-taus | Named specialists of one tau (`/coach`, `/landing`): a persona, an about line, a model role, a tool allowlist (empty by default, tiers unchanged) and their own sessions, defined in `persona/subs/<name>.md` (gitignored). `tau sub new --describe` drafts one with the brain; the main tau delegates with `ask_sub` (tier 0) and creates with `create_sub` (tier 2). Public ones answer contacts as `<address>/<name>` and circle their tau in the universe | Package `tau-sub`; they share the hub, identity, spine and address ([ADR 0012](adr/0012-sub-taus.md)) |
| Docs and site languages | English source + Turkish twins for the docs site (mkdocs-static-i18n, `*.tr.md`), the public site and the README | ADRs, issues, reference pages, code and commits stay English; UI chrome keeps `[ui] language` |
| Public surface | One private hostname `hub.tau.<domain>` → **Cloudflare Tunnel** (outbound from the hub) → the hub's web UI/API, behind a **Cloudflare Access** policy (owner identity, optional device rule). **Tailscale Serve** when there is no domain | No inbound port on the hub, ever. Unauthenticated traffic never reaches the tunnel |
| Telegram | The hub polls `getUpdates` directly (outbound); no webhook, no Worker | `chat_id` allowlist on the hub; approvals through inline buttons are accepted because nothing sits between Telegram and the hub |
| Mesh | **Control = MCP** (streamable HTTP over Tailscale) · **Data = Zenoh** (events, telemetry, discovery through liveliness) | No multicast on Tailscale → nodes `connect` explicitly to `zenohd` |
| Microcontrollers | **ESPHome** (free firmware) → MQTT → `zenohd` MQTT plugin → `tau/…` keyspace | No Home Assistant; if ever needed it is added later through MCP |
| Models | **Providers called directly**: `anthropic`, `openai`, `gemini` (the user's own key), `ollama` (local), optional `bedrock`; roles `brain` / `fast` / `local` | Default: `brain` = Claude Sonnet 5, `fast` = Claude Haiku 4.5, `local` = Ollama on the Mac (`qwen3.5:9b`) with `failover` to `fast`. No LiteLLM, no Docker ([ADR 0011](adr/0011-budgets-in-tau-no-litellm.md)) |
| Cost protection | Hard budget per role (`[models.roles.<role>.budget]`: `usd` per day/week/month) **enforced by tau**: every answer priced (`prices.toml`) and recorded in a SQLite ledger under `TAU_DATA_DIR`; a spent role answers with its `degrade_to` or says when it resets + the provider console's monthly limit + Strands max tool iterations | Spend per role under `## Now`, in `/status`, `GET /spend` (a protected control route) and `tau spend`; the ledger holds tokens and dollars, never text |
| Safety | **Tier 0** read, free · **Tier 1** digital write, free + log · **Tier 2** physical action + tools tau wrote → approval on a trusted channel (TUI, TauBar, the web app from a paired device, direct Telegram); on a guarded channel the **owner guard** also checks the lock before tier 1 and 2 and asks for a face **step-up** after a tier-2 approval | New tools land in `tools/_pending/`; registered routines are exempt from approval and from the guard, and scheduled tasks from the guard (both approved once at registration; tasks never run tier 2, [ADR 0015](adr/0015-web-app-agentic-chat.md)); every inbound text is untrusted, shell/file tools are tier 2 or sandboxed, fetch tools are allowlisted; the guard only narrows, never approves ([ADR 0008](adr/0008-owner-guard.md)) |
| Owner guard | **Door mode**: `tau tui`, `tau chat` and tau Desktop stay locked until the owner's face is verified at the Mac (built-in camera, YuNet + SFace, a random head-turn challenge); reflex locks on idle, screen lock, sleep and max age; a passive presence recheck after idle; a step-up after every tier-2 approval. One guard in the hub (`tau-guard`, hub service `guard`), each check in a short-lived worker subprocess; channels reach it through `tau_core.guard.HubGuard` over protected `/guard/*` routes | macOS only, local mode only. Telegram and network turns are identified channels and opt out in code (`guard=None`, a repo rule allows only those two); the template is AES-GCM encrypted with its key in the Keychain, never leaves the hub and is excluded from backups. A 2D webcam check is a presence factor: it does not stop a deepfake or anyone with a shell ([ADR 0008](adr/0008-owner-guard.md)) |
| Remote | macOS **OpenSSH** (key-only, `AllowUsers` restricted to tailnet + localhost) + **tmux + mosh** + Termius; wrangler with `CLOUDFLARE_API_TOKEN` | TauBar keeps the Mac awake; without it a `caffeinate -s` LaunchAgent does (on AC only), and `setup.sh` removes that agent once TauBar is installed. Claude Code `Notification` hook → tau → Telegram "waiting for you" |
| TauBar | **Tauri v2 + React/TS**, tray-only; `PreventSystemSleep` through `keepawake`; a narrow sudoers rule for `pmset disablesleep`; launch at login through `SMAppService.mainApp` (a login item, not a LaunchAgent); **runs and supervises the hub** on macOS ("Run the hub": `tau hub run` as its child); holds the camera and microphone permission for that hub (usage descriptions, entitlements, a stable signing identity); guard line and "Lock now" | Restart after an unclean exit with backoff, none after `tau hub stop`, stop on quit, never a second hub (hub lock + launchd check); the launchd agent is the alternative. Sleep modes: Normal / **Stay awake on AC (default)** / Even with the lid closed; quitting restores normal sleep. The Python mac-node runs as a sidecar and inherits the TCC permission |
| Knowledge base | `kb/` markdown indexed **locally** (SQLite vectors + a local embedding model), `kb_search` tool | Backed up encrypted with the rest of the data dir |
| Memory | Strands `MemoryManager` with a **local** tau `MemoryStore` (SQLite + local embeddings); extraction on the `fast` role | A **Self-RAG** loop inside the agent: retrieve → grade → re-query if needed |
| Session recording | The file session store on the hub (ADR 0003) is the record; resume with `/resume`, replay in the TUI, `/compact` opens a summarized new session | **Everything is kept.** Encrypted backups to R2; raw telemetry/media stay local (NDJSON/Parquet) and are backed up the same way. Retention lives in settings |
| AgentCore | **Lab only** (`deploy/agentcore/`) | `build_agent(profile)` carries no hub-specific assumption |
| Ambient | **Off by default**, the user turns it on; profiles `home` / `travel` / `sport` | Triggers: Telegram `/ambient`, TauBar, later the necklace. The startup message and routines run independently of ambient |
| Self-replication | Installing on a new machine (SSH, tier 2) · sub-agents/copies · persistence/self-heal | Start with one agent; past ~25 tools switch to agents-as-tools (`home`, `robot`, `dev`, `research`) |
| Desktop app | **tau Desktop** (`apps/tau-desktop`): Tauri v2 + React/TS + xterm.js; every window runs the real `tau tui` in a PTY (`portable-pty`), so the TUI's lock screen and every feature work unchanged | No camera or microphone permission (the guard runs in the hub), every webview permission request denied, no network listener; the Python is always the checkout's own `.venv` ([ADR 0008](adr/0008-owner-guard.md)) |
| Web app | **One React app** (`apps/web`) is the owner's chat, served by the hub's `tau-web` service (`127.0.0.1:7878` or the tailnet, behind Tailscale Serve or Tunnel + Access) and by tau-host at `/app`. It speaks one **turn protocol** (NDJSON events, history blocks) to both backends: on the hub the Strands agent runs inside the hub on the `web` channel; on tau-host the TypeScript loop. It has streaming chat, tool and approval cards, **widgets** from the tier-0 `render_ui` tool in a sandboxed frame, and pages for routines, scheduled tasks, devices, the toolbox and sub-taus ([ADR 0015](adr/0015-web-app-agentic-chat.md)) | Every hub route but pairing needs a **paired device**; `web` is guarded and trusted. Widgets reach neither the network, the hub nor the app. tau-host is never a relay to a hub |
| Channels | M1: **TUI** (Textual) + `tau ask` (one shot, for scripts and iOS Shortcuts over Tailscale) · M2: Telegram text (direct polling) + **web app** (the owner's chat, served by the hub's `tau-web` behind Access or on the tailnet, [ADR 0015](adr/0015-web-app-agentic-chat.md)) · M3: **tau-voice** (separate package: push-to-talk, local STT/TTS) + **tau MCP server** · M4: **Hey tau** (wake word on top of tau-voice) | The wake word must have 3–4 syllables; voice from the phone uses the web UI microphone and is transcribed on the hub |
| Persona | **Jarvis-style**, Turkish by default, mirrors the user's language; `persona.md` + `user.md` + dynamic context (time, profile, nodes, budget) | Brevity rule: at most 1–2 sentences in notifications and voice; approval requests carry no jokes |
| UI language | Per-installation setting `[ui] language` = `en` or `tr` in `tau.toml` (default `en`), overridden by `TAU_LANG`, `tau --lang`, and `/lang` for one session. Every piece of UI chrome (slash commands, labels, pane titles, key hints, notices, approval dialog, CLI help) comes from one message table shared by the terminal and the TUI | The chrome is English by default; the persona is Turkish by default and language-adaptive; everything the model reads (prompt headings, context labels, gate texts, tool descriptions) is fixed English. Errors raised before Config exists are plain English |
| Components | Every pluggable part is an entry point in a `tau.*` group: `tau.tools`, `tau.commands`, `tau.providers`, `tau.sessions`, `tau.context`, `tau.hub_services`. `tau.toml` `[components]` disables tools and picks context sources and hub services; `tau components` lists everything with distribution, version and load errors, `tau doctor` checks the installation, `tau init` writes the first config | The tier gate is pinned last with `HookOrder.SDK_LAST`, so no plugin hook can rewrite a call after it was approved. Plugin tools that are not in the `ToolCatalog` fail closed: refused, never run. Control API routes are protected by default (signed with the hub's control token, answers carry a proof; only `/health` and `/status` are open), and `build_agent(guard=DISCOVER)` puts any channel that does not opt out under the owner guard; `tau-guard` plugs in as the hub service and command `guard`, with no `tau.guard` group ([ADR 0008](adr/0008-owner-guard.md)) |
| Secrets | Local `.env` (gitignored) · Keychain for TauBar and the guard's template key · the backup key in the owner's password manager · the hub's control token in `TAU_DATA_DIR/hub/control.token` (fresh at every start, `0600`) | Provisioning moves secrets over SSH; nothing personal is needed to install or read the docs |
| Domain | `getporti.<tld>` → nameservers to Cloudflare (needed for Tunnel and Access hostnames) | Disable DNSSEC at the registrar first; verify MX/SPF/DKIM/DMARC by hand |
| Distribution | PyPI packages (`tau-core`, `tau-tui`, `tau-voice`, `tau-web`, …); `uv tool install tau-core --with tau-tui`, then `tau init` and `tau doctor`; docs site with step-by-step guides (MkDocs Material) | Infrastructure steps get `tau setup <thing>` helpers where a script is safe |
| Necklace | **XIAO ESP32S3 Sense** (WiFi camera, pose on the Mac/RPi5) + **Nicla Vision** (on-device ML: rep counting with the IMU, fall detection) | Pose estimation is not done on the Nicla |
| SO-101 | **strands-robots**, MuJoCo sim first, `mode="real"` is an explicit opt-in | Trigger: TauBar `screenIsUnlocked` → `tau/desk/presence` → routine |

### Subdomain scheme

- `tau.getporti.<tld>` → the public site: what tau is, and `/universe`, the opt-in map of taus (`cloud/universe`, [ADR 0010](adr/0010-public-site-and-tau-universe.md))
- `<name>.tau.getporti.<tld>` → a tau's spine and network address (the owner's: `furkan.tau.getporti.<tld>`)
- `hub.tau.getporti.<tld>` → the hub's web UI and API through Cloudflare Tunnel, behind Cloudflare Access
- `docs.tau.getporti.<tld>` → the docs site (static)
- `<project>.getporti.<tld>` → projects built with Claude Code and deployed with `wrangler`
- Until the domain is moved: Tailscale Serve on the tailnet

## Roadmap (layer order)

Each layer sits on the previous one and the next starts once the current one is useful on its own. Issues live under [`roadmap/`](https://github.com/fport/tau/blob/main/roadmap/README.md), one folder per layer; `python3 roadmap/board.py` shows the state.

| # | Layer | Scope |
|---|---|---|
| **0** | **Remote access** | Tailscale + OpenSSH hardening + tmux/mosh + Termius + stay awake on AC → `infra/remote/` |
| **1** | **Agent** | Strands core (`build_agent`), persona, tier system, TUI, launchd service. Model straight from the provider for now; the role abstraction exists from day one. Follow-ups: 062 (English UI and language setting), 063 (premium TUI), 064 (Strands correctness pass), 065 (component builder), 066 (English docs) |
| **2** | **Models** | `brain`/`fast`/`local` roles on the user's provider (Anthropic, OpenAI, Gemini) and Ollama, hard budgets per role with degrade and failover inside tau, spend reporting ([ADR 0011](adr/0011-budgets-in-tau-no-litellm.md)); in-process failover through Strands `ModelRouter` deferred ([ADR 0009](adr/0009-anthropic-only-models-behind-the-proxy.md)) |
| **3** | **Access and data** | Domain NS → Cloudflare, Tunnel + Access in front of the hub's web UI (Tailscale Serve alternative), Telegram by direct polling + **startup status report**, local settings/memory/KB, encrypted R2 backups, `tau ask` |
| **4** | **Interface** | TauBar (takes over the sleep modes), the web app (turn protocol, `tau-web`, chat, widgets, control pages; [ADR 0015](adr/0015-web-app-agentic-chat.md)), tau-voice (push-to-talk, local STT/TTS), voice from the phone through the web app, tau MCP server, Claude Code hook, Hey tau |
| **5** | **Mesh** | `zenohd` + MCP node discovery, hot-reloaded `tools/` + `_pending`, ESPHome/MQTT, clock routines (`tau-routines`) and a simulated lamp (`tau-sim`), then event routines |
| **6** | **Robot** | SO-101 (sim → real → a wave when you sit down at the desk), necklace (XIAO → Nicla) |
| **7** | **Lab** | AgentCore, autonomous task queue |
| **8** | **Distribution** | PyPI release path (trusted publishing on tags, `uv tool install tau-core --with tau-tui` verified from the wheels), docs site (MkDocs Material, strict build in CI, Cloudflare Pages at `docs.tau.<domain>`) |
| **9** | **Cloud mode and the tau network** | The spine Worker (local dev + deploy), `tau-net` (signed, sealed envelopes between taus; contacts; network turns), `tau-cloud` (the hub in a Cloudflare Container with a D1/KV store); follow-ups: Telegram webhook in cloud mode, Vectorize memory, e-mail routing, voice through a Durable Object ([ADR 0007](adr/0007-cloud-mode-and-tau-network.md)) |
| **10** | **Guard** | The owner guard ([ADR 0008](adr/0008-owner-guard.md)): seams in tau-core (`HubGuard`, admission, stop reason `locked`, tier-2 step-up, protected control routes), the `tau-guard` service (state machine, reflex locks, worker, audit log), face verification (YuNet + SFace, head-turn challenge, encrypted template, `tau guard`), guarded channels (TUI lock screen, terminal lock prompt, `/guard`, Telegram lock), TauBar's camera permission and "Lock now", tau Desktop; follow-ups: Touch ID, remote unlock through Telegram, voice under the guard, the guard on the RPi5 hub |
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
│   ├── tau-net/              # tau network: identity, envelopes, contacts, `net` hub service, `tau net`
│   ├── tau-cloud/            # cloud mode: `spine` session backend, `tau cloud push|pull|status|run`
│   ├── tau-sub/              # sub-taus: `tau sub`, `ask_sub`, `create_sub`
│   ├── tau-guard/            # owner guard: `guard` hub service, face worker, `tau guard`
│   ├── tau-web/              # `web` hub service: serves the web app, runs its turns, paired devices, `render_ui`
│   ├── tau-routines/         # `routines` hub service: clock routines (no LLM) and scheduled tasks, `tau routine|task`
│   ├── tau-sim/              # simulated devices (the lamp) until real ones arrive
│   ├── tau-voice/            # hub service + channel: microphone, local STT/TTS
│   ├── tau-mesh/             # Zenoh + MCP discovery
│   ├── tau-robot/            # strands-robots / SO-101 node
│   └── tau-vision/           # workout coach (pose)
├── nodes/mac/                # macOS node (TauBar sidecar)
├── apps/taubar/              # Tauri v2 + React/TS
├── apps/web/                 # the web app (React + Vite): chat, widgets, control pages; bundled into tau-web and tau-host
├── apps/tau-desktop/         # Tauri v2 + React/TS + xterm.js: `tau tui` in a PTY
├── cloud/spine/              # tau-spine Worker (TS): card, mailbox, hub doorbell and long poll; cloud mode: brain container + D1/KV store
├── cloud/universe/           # tau-universe Worker (TS): the public site at tau.<domain> and the opt-in directory of taus
├── persona/                  # persona.md, user.example.md (user.md gitignored)
├── tools/                    # hot-reloaded tools
│   └── _pending/             # tools tau wrote, waiting for approval
├── infra/
│   ├── tunnel/               # cloudflared config, Access policy notes
│   ├── backup/               # encrypted R2 backup and restore scripts
│   ├── zenoh/                # zenohd + MQTT plugin config
│   ├── services/             # launchd plist, systemd unit
│   └── remote/               # sshd_config, tmux, mosh
├── firmware/                 # ESPHome YAML, XIAO, Nicla (when the hardware arrives)
└── deploy/agentcore/
```

## Open items

Each one is tracked as a `ready-for-human` issue.

1. **SO-101 motion generation:** keyframe scripts / leader teleop + policy / live LLM guidance → [038](https://github.com/fport/tau/blob/main/roadmap/L6-robot/038-decide-so101-motion-method.md)
2. **Domain:** the full name (TLD) and the NS move → [022](https://github.com/fport/tau/blob/main/roadmap/L3-cloud/022-move-dns-to-cloudflare.md)
3. **Necklace workout alerts:** alert channel, exercises, mistakes → [042](https://github.com/fport/tau/blob/main/roadmap/L6-robot/042-decide-workout-alert-channel.md)
4. **Hey tau:** the wake phrase → [030](https://github.com/fport/tau/blob/main/roadmap/L4-interface/030-pick-wake-phrase.md)
5. **Drone:** model choice, SHGM rules → [050](https://github.com/fport/tau/blob/main/roadmap/backlog/050-drone-model-and-rules.md)
6. **Shopping list (TR):** RPi5, XIAO, Nicla, ESP32 + LD2410 + sensors → [049](https://github.com/fport/tau/blob/main/roadmap/backlog/049-hardware-shopping-list.md)

## Changes

Decisions that were replaced, with the date, so the history stays readable.

- **2026-10-01 — The web app ([ADR 0015](adr/0015-web-app-agentic-chat.md)).** Before: the web UI was to be the TUI in a browser tab through `textual-serve` (074). Generated interfaces were out of scope (152), routines waited for Zenoh (037), and the hub had no turn API. Now: one React web app is the owner's chat for both the hub and tau-host, over one turn protocol. The hub's `tau-web` service runs the Strands agent inside the hub for paired devices. The model can render widgets in a sandboxed frame. `tau-routines` adds clock routines without an LLM and scheduled agent tasks, each approved once at registration. A simulated lamp is the first device. Hosted taus keep their TypeScript loop and get the same app.

- **2026-09-30 — The owner guard ([ADR 0008](adr/0008-owner-guard.md)).** Before: anyone at the owner's unlocked Mac who opened the TUI could read every session and approve a tier-2 action with one key, and the control API on `127.0.0.1` checked only the `Host` header, so any local process could call any route. Now: `tau tui`, `tau chat` and the new tau Desktop app are guarded channels that stay locked until the owner's face is verified at the Mac, lock again by reflex (idle, screen lock, sleep, max age, `/guard lock`, Telegram) and ask for a face step-up after every tier-2 approval; Telegram and network turns opt out in code as identified channels; every control route except `/health` and `/status` needs a signed request and answers with a proof (`GET /spend` included); TauBar holds the camera permission. Reason: the owner wants tau to work only for them, and the approval alone did not tell who pressed the key.

- **2026-09-30 — Budgets in tau, no LiteLLM ([ADR 0011](adr/0011-budgets-in-tau-no-litellm.md)).** Before (ADR 0009, the same morning): every role behind a LiteLLM proxy in Docker with Postgres, budgets on the proxy's virtual keys, Anthropic as the only cloud provider. Now: providers are called directly (Anthropic, OpenAI, Gemini, Ollama, optional Bedrock); tau prices every answer, keeps the spend in a SQLite ledger on the hub and enforces per-role budgets (day/week/month) with `degrade_to`, plus a per-role `failover` for an unreachable model. Reason: users who install tau from PyPI bring a key or Ollama and should not need Docker.

- **2026-09-30 — The public site and the tau universe ([ADR 0010](adr/0010-public-site-and-tau-universe.md)).** Before: `tau.<domain>` was reserved for the hub's web UI behind Tunnel + Access. Now: `tau.<domain>` is the public site with the opt-in universe directory; the owner's tau lives at `<name>.tau.<domain>`; the web UI moves to `hub.tau.<domain>` with the same Tunnel + Access rules. The spine ships inside `tau-net` so that anyone can join the network without the repository.

- **2026-09-30 — Anthropic-only models behind the proxy ([ADR 0009](adr/0009-anthropic-only-models-behind-the-proxy.md)).** Before: `brain` = Bedrock Sonnet with Anthropic as its fallback, `fast` = Bedrock Haiku, and AWS Budgets alarms next to the proxy budgets. Now: Anthropic is the only cloud provider (`brain` Sonnet 5, `fast` Haiku 4.5), every role goes through the LiteLLM proxy with a hard budget from `tau.toml` (`degrade_to` a cheaper role or a notice with the reset time), and a monthly spend limit on the Anthropic workspace is the last line of defence. Bedrock remains an optional direct provider. Reason: the AWS account was never set up, and the owner chose not to add it (003).

- **2026-09-30 — Cloud mode and the tau network ([ADR 0007](adr/0007-cloud-mode-and-tau-network.md)).** Before: life data only on the hub, and the `tau-cloud` Worker reduced to an optional offline notice. Now: two deployment modes with the same code. Local (default) keeps ADR 0006; cloud runs the hub as a Cloudflare Container in the owner's own account with D1/KV storage. Every tau can also have a spine Worker (`cloud/spine`) that gives it an address on a federated network of taus: signed, end-to-end sealed envelopes; contacts accepted by the owner; narrow network turns. Reason: others should be able to run tau without a machine at home, and taus should be able to talk to each other.

- **2026-09-30 — Who runs the hub on macOS (issue 084).** Before: a launchd user agent (`com.tau.hub`, `RunAtLoad` + `KeepAlive = {SuccessfulExit: false}`), installed by `tau hub install`. Now: TauBar's "Run the hub" switch starts and supervises `tau hub run` with the same contract (restart after a crash, not after `tau hub stop`), and TauBar itself starts at login as an `SMAppService` login item; the launchd agent stays as the alternative. Reason: on the hub Mac (macOS 26.3.1) launchd pended every automatic start of user agents, so the agent neither started at login nor came back after a kill (057, 052).

- **2026-09-29 — Private-first topology ([ADR 0006](adr/0006-private-first-topology.md)).** Before: state in Cloudflare (D1, R2, Vectorize, AI Search) behind the `tau-cloud` Worker; Telegram through webhook → Worker → Durable Object → hub; `api.tau.<domain>` as a public API. Now: life data on the hub with client-side encrypted R2 backups; one public hostname through Cloudflare Tunnel behind Cloudflare Access (Tailscale Serve without a domain); Telegram polled directly by the hub; approvals only from trusted channels; voice as a separate package; installable from PyPI with a docs site.

- **2026-09-29 — Repo language.** Before: `docs/ARCHITECTURE.md` and `infra/remote/` were Turkish, and tau's user-facing output was Turkish by rule. Now: everything in the repo is English, including this file, `infra/remote/` and the script messages. Turkish remains only for talking to the user in the Claude Code session and for the body of `persona/persona.md`; the UI chrome follows the `[ui] language` setting (issue 066).
- **2026-09-29 — Slash commands.** Before: Turkish command names (`/devam`, `/oturumlar`, `/yardım`, `/çık`, `/ayar`, `/ambient seyahat`). Now: canonical English names (`/resume`, `/sessions`, `/help`, `/quit`, `/settings`, `/ambient travel`) with the Turkish names kept as aliases that are accepted forever but never shown in hints (issue 062).
- **2026-09-29 — Profile names.** Before: `ev` / `seyahat` / `spor`. Now: `home` / `travel` / `sport`, with `home` as the default. Renamed now because profile keys will later live in D1 as data (issue 062).
- **2026-09-29 — Persona language.** Before: "Jarvis-style, Turkish". Now: Turkish by default and mirroring the language the user writes in; code, commands, file names and technical terms are left as they are.
