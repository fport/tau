# tau — Domain glossary

Use these terms exactly in code, issues, tests and docs. If a concept you need is missing, add it here instead of inventing a synonym.

## System

- **tau** — the whole system. Lower case, also at the start of a sentence in prose.
- **Hub** — the one machine currently running the agent, the relay connection, schedulers and `zenohd` (`TAU_ROLE=hub`). Today the MacBook, later the RPi5. There is never more than one active hub. *Avoid: server, master.*
- **Node** — any other process that joins the mesh and offers capabilities (`TAU_ROLE=node`), e.g. the Mac node or the robot node. *Avoid: agent (reserved for the LLM agent), client.*
- **Device** — physical hardware (SO-101, XIAO, ESP32, Nicla). A device reaches tau through a node or the MQTT bridge; it is not itself a node.
- **Capability** — a tool a node exposes over MCP, namespaced by node (`mac.screenshot`, `arm.play`).
- **Mesh** — Zenoh network of the hub and nodes. **Control plane** = MCP (calling capabilities). **Data plane** = Zenoh (events, telemetry, liveliness).
- **Relay** — *retired by ADR 0006*: no server sits between an external channel and the hub; Telegram is polled directly.
- **Config** — static bootstrap configuration from `tau.toml` and `.env` (roles, ports, paths, credentials). Read once at start-up; editable in place from a channel through `tau_core.settings` (the TUI's settings screen, `/settings` in the terminal), never synced anywhere. Distinct from **Settings**, which are runtime data on the hub.
- **Web UI** — the hub's browser interface (first: the TUI served through `textual-serve`), reached only through the **Tunnel** or the tailnet.
- **Tunnel** — the outbound Cloudflare Tunnel from the hub that makes `tau.<domain>` reachable without an inbound port; **Access** is the Cloudflare identity policy in front of it. *Avoid: reverse proxy, port forward.*
- **Backup** — the client-side encrypted copy of `TAU_DATA_DIR` in a private R2 bucket; the key never leaves the hub and the owner's password manager.
- **Deployment mode** — where the hub runs and where its life data lives ([ADR 0007](docs/adr/0007-cloud-mode-and-tau-network.md)). **Local** (default): the hub runs on the owner's machine and life data stays under `TAU_DATA_DIR` (ADR 0006). **Cloud** (opt-in): the same hub runs as a Cloudflare Container managed by the owner's spine, and life data lives in the owner's own Cloudflare account (D1, KV). *Avoid: hosted, SaaS.*
- **Spine** — a tau's own Cloudflare Worker (`cloud/spine`, `tau-spine`): its address, card and mailbox; in cloud mode also the host of the brain container and its store. In local mode it only stores and forwards sealed envelopes. *Avoid: relay (retired), server, backend.*
- **Component** — a pluggable part of tau registered through a `tau.*` entry-point group (`tau.tools`, `tau.commands`, `tau.providers`, `tau.sessions`, `tau.context`, `tau.hub_services`) or a registry, enabled or disabled through `[components]` in `tau.toml`, and listed by `tau components`. *Avoid: plugin (use it only for a third-party distribution that provides components).*

## Talking to tau

- **Channel** — a way to converse with tau: Telegram, TUI, TauBar, voice ("Hey tau"), MCP server.
- **Session** — one recorded conversation: messages, tool calls, approvals. Resumed with `/resume`. Kept forever.
- **Persona** — tau's character, from `persona/persona.md` (Jarvis-style, Turkish by default, mirrors the user's language) and `persona/user.md` (facts about the user). Combined with the **dynamic context** (time, profile, live nodes, budget) into the system prompt each turn. Everything the model reads around it (headings, labels, gate texts) is English.
- **Slash command** — a `/name [argument]` line typed into a channel and handled by the channel, never sent to the model: `/help`, `/tools`, `/sessions`, `/resume`, `/new`, `/session`, `/compact`, `/clear`, `/status`, `/model`, `/lang`, `/settings`, `/quit`. Canonical names are English; Turkish aliases are accepted but never shown. Spec in `tau_core.commands`.
- **Compaction** — `/compact`: summarizing the current session with the agent's own model and continuing in a *new* session whose history starts with that summary (the **seed**). The old session is kept untouched and the two point at each other in their metadata (`compacted_from`, `compacted_to`). Never a rewrite of an existing session. *Avoid: truncate, prune.*
- **UI language** — the language of the UI chrome (slash-command hints, labels, pane titles, key hints, notices, approval dialog, CLI help): `en` (default) or `tr`, set by `[ui] language` in `tau.toml`, `TAU_LANG`, `tau --lang` or `/lang` for one run. Looked up through `tau_core.i18n` (`t(key, language)`). Distinct from the persona's language. *Avoid: locale.*
- **Status report** — the message the hub sends to Telegram when it starts or restarts.
- **TauBar** — the macOS tray app (Tauri): runs and supervises the hub ("Run the hub"), sleep modes, launch at login; later status, approvals, voice.

## tau network

- **tau network** — the federation of taus that talk to each other: envelopes go from one tau's hub straight to the other tau's spine, with no central server. Protocol in `docs/reference/tau-network.md`. *Avoid: social network, chat server.*
- **Address** — a tau's name on the network: the host of its spine (`tau.example.com`). *Avoid: handle, username.*
- **Card** — a tau's public JSON at `https://<address>/.well-known/tau.json`: display name, Ed25519 signing key, X25519 box key.
- **Envelope** — one message between taus: signed by the sender, sealed end to end to the recipient's box key. Kinds: `contact_request`, `contact_accept`, `message`.
- **Contact** — another tau the owner accepted; only contacts reach the model. States: `pending_in`, `pending_out`, `accepted`, `blocked`. Keys are pinned on acceptance.
- **Mailbox** — the spine's store-and-forward queue of envelopes waiting for the hub; an envelope is deleted once the hub acknowledges it.
- **Universe** — an opt-in public directory of taus, at `tau.<domain>/universe` by default: a tau joins with `tau net universe join`, reports its links every hour and leaves with `tau net universe leave`. A link between two taus shows only when both report it; only counts are published, never contents ([ADR 0010](docs/adr/0010-public-site-and-tau-universe.md)). *Avoid: social network, registry.*
- **Public site** — `tau.<domain>`, served by the `tau-universe` Worker (`cloud/universe`): the landing page and the universe. It holds nothing private.
- **Spine kit** — the spine Worker bundled inside `tau-net`; `tau net spine init|deploy` sets up a spine without the repository.
- **Network turn** — a turn the hub runs for a message from a contact: its own session per contact, `persona.md` plus the owner's **public note** (`persona/net.md`) instead of `user.md`, no tools, no approvals, the text framed as untrusted, auto-replies bounded by `hops` and an hourly cap.
- **Sub-tau** — a named specialist of a tau (`/coach`), defined in `persona/subs/<name>.md`: its own persona, about line, model role, tool allowlist and sessions, sharing the tau's hub, identity, spine and address ([ADR 0012](docs/adr/0012-sub-taus.md)). *Avoid: sub-agent, bot.*
- **Public sub-tau** — a sub-tau with `public = true`: contacts reach it as `<address>/<name>` (the `sub` field of a `message`), it answers with its own network turn (its persona and its own public note, never `user.md`) and the universe shows it inside its owner's hull. A private sub-tau never leaves the hub.

## Models and cost

- **Role** — `brain` (conversation, planning), `fast` (triage, summaries), `local` (Ollama on the Mac). Code asks for a role, never for a concrete model id.
- **Budget** — a hard spend cap on a role per calendar period (`usd` per `day`, `week` or `month`, Europe/Istanbul), set in `tau.toml` and enforced by tau itself (ADR 0011). Distinct from the per-turn token limit `max_total_tokens`.
- **Spend** — what a role spent in its current budget period: every answer's token usage priced (`prices.toml`, `[models.prices]`) and recorded in the **ledger** (`TAU_DATA_DIR/spend.sqlite3`; tokens and dollars, never text). Shown under `## Now`, in `/status`, by `GET /spend` and by `tau spend`.
- **Degrade** — a spent role handing its calls to its `budget.degrade_to` role until the reset; the channel says so. *Avoid: fallback (a spent budget is never a fallback).*
- **Failover** — an unreachable role (`failover = "<role>"`: connection refused or timed out, 5xx; not throttling) handing the call to another role, e.g. `local` (Ollama on a sleeping Mac) → `fast`; the channel says so.
- **Fallback** — a role's `fallback` table: another provider used only when the primary has no credentials.

## Safety

- **Tier** — a tool's permission level. **Tier 0**: read, runs freely. **Tier 1**: digital write, runs and is logged. **Tier 2**: physical action, activating self-written code, or speaking for the owner to another tau (`net_send`), needs approval.
- **Approval** — an explicit user decision on a tier-2 call, through whichever channel the call came from (terminal prompt, Telegram buttons, TauBar). Never from the tau network: a network turn refuses every approval, and sending to another tau (`net_send`) is itself tier 2.
- **Pending tool** — a tool tau wrote itself, waiting in `tools/_pending/` for approval.
- **Sim mode / real mode** — robot execution targets. Sim is the default; real mode needs explicit config and approval.

## Behavior

- **Event** — something that happened, published on Zenoh as `tau/<area>/<name>` (e.g. `tau/desk/presence`). Summaries of events are stored locally on the hub.
- **Agent event** — a record of what the agent did in a session (tool call, approval, turn limit, error, notice); distinct from a mesh **Event** on Zenoh.
- **Turn event** — what a channel receives while one user turn streams: `TextDelta`, `ReasoningDelta`, `ToolUseStarted`, `ToolProgress`, `ToolFinished`, `Throttled`, `Notice`, `TurnEnd`. Rendered by the terminal and the TUI; not stored (agent events are).
- **Stop reason** — why a turn ended, carried by `TurnEnd`: `end_turn`, `limit_turns`, `limit_total_tokens`, `max_tokens`, `cancelled`, `interrupt`, `error`, `busy`.
- **Repair turn** — when the history ends on an unfinished turn (a failed, cancelled or limited turn, or a crash-restored session), the next turn sends an assistant notice before the user's prompt so the history keeps alternating. Only the SDK appends to history; tau never does by hand.
- **Telemetry** — high-frequency raw data (sensor streams, joint states). Never stored with the sessions; batched to local files and backed up encrypted with the rest of the data dir.
- **Routine** — a user-registered rule: event pattern → action, with optional conditions (time window, cooldown). Registering a tier-2 routine needs one approval; its firings do not.
- **Reflex engine** — runs routines locally without an LLM or the cloud.
- **Ambient mode** — tau thinking proactively about events. Off by default; the user turns it on per **profile**.
- **Profile** — a named bundle of settings (`home`, `travel`, `sport`; `home` is the default): which events to watch, where to notify, the ambient budget.
- **Settings** — runtime configuration stored as data on the hub (a file under `TAU_DATA_DIR`) and hot-reloaded; never synced to a third party. Planned in issue 019. Until then `/settings` (and the TUI's **settings screen**, F10) edits the bootstrap **Config** (`tau.toml`, `.env`): model roles, credentials, UI language, profile, agent options. The **setup screen** is what `tau tui` shows when there is no `tau.toml` yet; it runs the same code as `tau init`.

## Knowledge

- **KB (knowledge base)** — long-form markdown documents under `kb/`, indexed locally on the hub (SQLite vectors + a local embedding model).
- **Memory** — short facts extracted from conversations; a local SQLite row plus a local embedding, searchable immediately.
- **Self-RAG loop** — the agent decides whether to retrieve, retrieves from memory/KB, grades relevance, and re-queries once if needed.
