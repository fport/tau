# tau — Domain glossary

Use these terms exactly in code, issues, tests and docs. If a concept you need is missing, add it here instead of inventing a synonym.

## System

- **tau** — the whole system. Lower case, also at the start of a sentence in prose.
- **Hub** — the one machine currently running the agent, the relay connection, schedulers and `zenohd` (`TAU_ROLE=hub`). Today the MacBook, later the RPi5. There is never more than one active hub. *Avoid: server, master.*
- **Node** — any other process that joins the mesh and offers capabilities (`TAU_ROLE=node`), e.g. the Mac node or the robot node. *Avoid: agent (reserved for the LLM agent), client.*
- **Device** — physical hardware (SO-101, XIAO, ESP32, Nicla). A device reaches tau through a node or the MQTT bridge; it is not itself a node.
- **Capability** — a tool a node exposes over MCP, namespaced by node (`mac.screenshot`, `arm.play`).
- **Mesh** — Zenoh network of the hub and nodes. **Control plane** = MCP (calling capabilities). **Data plane** = Zenoh (events, telemetry, liveliness).
- **Relay** — the `tau-cloud` Worker plus its Durable Object. Receives external channel traffic and forwards it to the hub over the hub's outbound WebSocket. Queues messages while no hub is connected.
- **Config** — static bootstrap configuration from `tau.toml` and `.env` (roles, ports, paths). Distinct from **Settings**, which are runtime data in D1.
- **Component** — a pluggable part of tau registered through a `tau.*` entry-point group (`tau.tools`, `tau.commands`, `tau.providers`, `tau.sessions`, `tau.context`, `tau.hub_services`) or a registry, enabled or disabled through `[components]` in `tau.toml`, and listed by `tau components`. *Avoid: plugin (use it only for a third-party distribution that provides components).*

## Talking to tau

- **Channel** — a way to converse with tau: Telegram, TUI, TauBar, voice ("Hey tau"), MCP server.
- **Session** — one recorded conversation: messages, tool calls, approvals. Resumed with `/resume`. Kept forever.
- **Persona** — tau's character, from `persona/persona.md` (Jarvis-style, Turkish by default, mirrors the user's language) and `persona/user.md` (facts about the user). Combined with the **dynamic context** (time, profile, live nodes, budget) into the system prompt each turn. Everything the model reads around it (headings, labels, gate texts) is English.
- **Slash command** — a `/name [argument]` line typed into a channel and handled by the channel, never sent to the model: `/help`, `/tools`, `/sessions`, `/resume`, `/new`, `/session`, `/lang`, `/quit`. Canonical names are English; Turkish aliases are accepted but never shown. Spec in `tau_core.commands`.
- **UI language** — the language of the UI chrome (slash-command hints, labels, pane titles, key hints, notices, approval dialog, CLI help): `en` (default) or `tr`, set by `[ui] language` in `tau.toml`, `TAU_LANG`, `tau --lang` or `/lang` for one run. Looked up through `tau_core.i18n` (`t(key, language)`). Distinct from the persona's language. *Avoid: locale.*
- **Status report** — the message the hub sends to Telegram when it starts or restarts.
- **TauBar** — the macOS tray app (Tauri): sleep modes, status, approvals, voice.

## Models and cost

- **Role** — `brain` (conversation, planning), `fast` (triage, summaries), `local` (Ollama on the Mac). Code asks for a role, never for a concrete model id.
- **Proxy** — the LiteLLM proxy container that maps roles to providers and enforces budgets.
- **Budget** — hard spend cap on a role's virtual key (daily or monthly).

## Safety

- **Tier** — a tool's permission level. **Tier 0**: read, runs freely. **Tier 1**: digital write, runs and is logged. **Tier 2**: physical action or activating self-written code, needs approval.
- **Approval** — an explicit user decision on a tier-2 call, through whichever channel the call came from (terminal prompt, Telegram buttons, TauBar).
- **Pending tool** — a tool tau wrote itself, waiting in `tools/_pending/` for approval.
- **Sim mode / real mode** — robot execution targets. Sim is the default; real mode needs explicit config and approval.

## Behavior

- **Event** — something that happened, published on Zenoh as `tau/<area>/<name>` (e.g. `tau/desk/presence`). Summaries of events are stored in D1.
- **Agent event** — a record of what the agent did in a session (tool call, approval, turn limit, error, notice); distinct from a mesh **Event** on Zenoh.
- **Telemetry** — high-frequency raw data (sensor streams, joint states). Never stored in D1; batched to R2.
- **Routine** — a user-registered rule: event pattern → action, with optional conditions (time window, cooldown). Registering a tier-2 routine needs one approval; its firings do not.
- **Reflex engine** — runs routines locally without an LLM or the cloud.
- **Ambient mode** — tau thinking proactively about events. Off by default; the user turns it on per **profile**.
- **Profile** — a named bundle of settings (`home`, `travel`, `sport`; `home` is the default): which events to watch, where to notify, the ambient budget.
- **Settings** — runtime configuration stored as data in D1 and hot-reloaded by the hub (`/settings`).

## Knowledge

- **KB (knowledge base)** — long-form markdown documents, stored in R2 and indexed by AI Search.
- **Memory** — short facts extracted from conversations; D1 row plus a Vectorize embedding, searchable immediately.
- **Self-RAG loop** — the agent decides whether to retrieve, retrieves from memory/KB, grades relevance, and re-queries once if needed.
