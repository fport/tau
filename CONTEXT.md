# tau — Domain glossary

Use these terms exactly in code, issues, tests and docs. If a concept you need is missing, add it here instead of inventing a synonym.

## System

- **tau** — the whole system. Lower case, also at the start of a sentence in prose.
- **Hub** — the one machine currently running the agent, the relay connection, schedulers and `zenohd` (`TAU_ROLE=hub`). Today the MacBook, later the RPi5. There is never more than one active hub. *Avoid: server, master.*
- **Node** — any other process that joins the mesh and offers capabilities (`TAU_ROLE=node`), e.g. the Mac node or the robot node. *Avoid: agent (reserved for the LLM agent), client.*
- **Device** — physical hardware (SO-101, XIAO, ESP32, Nicla). A device reaches tau through a node or the MQTT bridge; it is not itself a node.
- **Capability** — a tool a node exposes over MCP, namespaced by node (`mac.screenshot`, `arm.play`).
- **Mesh** — Zenoh network of the hub and nodes. **Control plane** = MCP (calling capabilities). **Data plane** = Zenoh (events, telemetry, liveliness).
- **Relay** — *retired by ADR 0006*: no server sits between an external channel and the hub; Telegram is polled directly. The universe's `Relay` Durable Object (one visitor thread, ADR 0013 §5) is a different thing: it relays anonymous **visitors** to a web sub-tau, never the owner's own channels.
- **Config** — static bootstrap configuration from `tau.toml` and `.env` (roles, ports, paths, credentials). Read once at start-up; editable in place from a channel through `tau_core.settings` (the TUI's settings screen, `/settings` in the terminal), never synced anywhere. Distinct from **Settings**, which are runtime data on the hub.
- **Web UI** — the hub's browser interface (first: the TUI served through `textual-serve`), reached only through the **Tunnel** or the tailnet.
- **Tunnel** — the outbound Cloudflare Tunnel from the hub that makes `tau.<domain>` reachable without an inbound port; **Access** is the Cloudflare identity policy in front of it. *Avoid: reverse proxy, port forward.*
- **Backup** — the client-side encrypted copy of `TAU_DATA_DIR` in a private R2 bucket; the key never leaves the hub and the owner's password manager.
- **Deployment mode** — where the hub runs and where its life data lives ([ADR 0007](docs/adr/0007-cloud-mode-and-tau-network.md)). **Local** (default): the hub runs on the owner's machine and life data stays under `TAU_DATA_DIR` (ADR 0006). **Cloud** (opt-in): the same hub runs as a Cloudflare Container managed by the owner's spine, and life data lives in the owner's own Cloudflare account (D1, KV). A **hosted tau** has no hub, so it is not a deployment mode: it is one of the three ways to run a tau (ADR 0013), next to local and **own host**, with cloud mode as the advanced fourth. *Avoid: SaaS; "hosted" for cloud mode.*
- **Spine** — a tau's own Cloudflare Worker (`cloud/spine`, `tau-spine`): its address, card and mailbox; in cloud mode also the host of the brain container and its store. In local mode it only stores and forwards sealed envelopes. *Avoid: relay (retired), server, backend.*
- **Control API** — the hub's loopback HTTP API on `127.0.0.1:<control_port>`. Only `GET /health` and `GET /status` are open; every other **control route** (`/spend`, `/guard/*`, any route a hub service adds) is protected: the request is signed with the hub's control token (`TAU_DATA_DIR/hub/control.token`, never sent) and the answer carries a proof ([ADR 0008](docs/adr/0008-owner-guard.md)). Clients use `tau_core.hub.HubClient`. *Avoid: API key, auth header (the token never travels).*
- **Component** — a pluggable part of tau registered through a `tau.*` entry-point group (`tau.tools`, `tau.commands`, `tau.providers`, `tau.sessions`, `tau.context`, `tau.hub_services`) or a registry, enabled or disabled through `[components]` in `tau.toml`, and listed by `tau components`. *Avoid: plugin (use it only for a third-party distribution that provides components).*
- **Setup feature** — one entry of `tau setup`'s catalog (`tau_core/templates/features.toml`, [ADR 0014](docs/adr/0014-one-installer-and-onboarding.md)): something the owner picks in the wizard or the app (the TUI, sub-taus, Telegram, the owner guard, the network, start at login, …), with its package, platforms, macOS permissions and setup steps, which are `tau` subcommands. A feature may install a package that brings several **Components**, or none. *Avoid: plugin, module.*

## Talking to tau

- **Channel** — a way to converse with tau: Telegram, TUI, TauBar, voice ("Hey tau"), MCP server. tau Desktop and web tabs run the TUI, so they are the `tui` channel.
- **Session** — one recorded conversation: messages, tool calls, approvals. Resumed with `/resume`. Kept forever.
- **Persona** — tau's character, from `persona/persona.md` (Jarvis-style, Turkish by default, mirrors the user's language) and `persona/user.md` (facts about the user). Combined with the **dynamic context** (time, profile, live nodes, budget) into the system prompt each turn. Everything the model reads around it (headings, labels, gate texts) is English.
- **Slash command** — a `/name [argument]` line typed into a channel and handled by the channel, never sent to the model: `/help`, `/tools`, `/sessions`, `/resume`, `/new`, `/session`, `/compact`, `/clear`, `/status`, `/model`, `/lang`, `/settings`, `/guard`, `/quit`. Canonical names are English; Turkish aliases are accepted but never shown. Spec in `tau_core.commands`.
- **Compaction** — `/compact`: summarizing the current session with the agent's own model and continuing in a *new* session whose history starts with that summary (the **seed**). The old session is kept untouched and the two point at each other in their metadata (`compacted_from`, `compacted_to`). Never a rewrite of an existing session. *Avoid: truncate, prune.*
- **UI language** — the language of the UI chrome (slash-command hints, labels, pane titles, key hints, notices, approval dialog, CLI help): `en` (default) or `tr`, set by `[ui] language` in `tau.toml`, `TAU_LANG`, `tau --lang` or `/lang` for one run. Looked up through `tau_core.i18n` (`t(key, language)`). Distinct from the persona's language. *Avoid: locale.*
- **Status report** — the message the hub sends to Telegram when it starts or restarts.
- **TauBar** — the macOS tray app (Tauri): runs and supervises the hub ("Run the hub"), sleep modes, launch at login, the guard line and "Lock now"; holds the camera and microphone permission for the hub it runs; later approvals, voice.
- **tau Desktop** — the desktop app (`apps/tau-desktop`, Tauri + xterm.js): every window runs the real `tau tui` in a PTY. It holds no camera or microphone permission and opens no network listener. *Avoid: desktop client, GUI.*

## tau network

- **tau network** — the federation of taus that talk to each other: envelopes go from one tau's hub straight to the other tau's spine, with no central server. Protocol in `docs/reference/tau-network.md`. *Avoid: social network, chat server.*
- **Address** — a tau's name on the network: the host of its spine (`tau.example.com`), or `host/@handle` for a tau on a tau-host (`tau.getporti.com/@alice`, ADR 0013 §3). The card is at `<scheme>://<address>/.well-known/tau.json` and the inbox at `<scheme>://<address>/net/inbox`; a sub-tau is `<address>/<name>`. Distinct from the **handle**, which names a person on the universe. *Avoid: username.*
- **Card** — a tau's public JSON at `https://<address>/.well-known/tau.json`: display name, Ed25519 signing key, X25519 box key.
- **Envelope** — one message between taus: signed by the sender, sealed end to end to the recipient's box key. Kinds: `contact_request`, `contact_accept`, `message`, and `visit` (from the universe only).
- **Contact** — another tau the owner accepted; only contacts reach the model. States: `pending_in`, `pending_out`, `accepted`, `blocked`. Keys are pinned on acceptance.
- **Mailbox** — the spine's store-and-forward queue of envelopes waiting for the hub; an envelope is deleted once the hub acknowledges it.
- **Universe** — an opt-in public directory of taus, at `tau.<domain>/universe` by default: a tau joins with `tau net universe join`, reports its links every hour and leaves with `tau net universe leave`. A link between two taus shows only when both report it; only counts are published, never contents ([ADR 0010](docs/adr/0010-public-site-and-tau-universe.md)). *Avoid: social network, registry.*
- **Public site** — `tau.<domain>`, served by the `tau-universe` Worker (`cloud/universe`): the landing page, how it works, the universe, person pages (`/@<handle>`), sub-tau pages (`/<slug>`, `/@<handle>/<name>`) and `/claim`, each also under `/tr/`. With a tau-host behind it (the `HOST` service binding) it forwards `/app`, `/auth/*`, `/api/host/*` and hosted taus' cards and inboxes to it. It holds no life data; visitor chats pass through it (see **Visitor**).
- **Spine kit** — the spine Worker bundled inside `tau-net`; `tau net spine init|deploy` sets up a spine without the repository.
- **Network turn** — a turn the hub runs for a message from a contact: its own session per contact, `persona.md` plus the owner's **public note** (`persona/net.md`) instead of `user.md`, no tools, no approvals, the text framed as untrusted, auto-replies bounded by `hops` and an hourly cap.
- **Sub-tau** — a named specialist of a tau (`/coach`), defined in `persona/subs/<name>.md`: its own persona, about line, model role, tool allowlist and sessions, sharing the tau's hub, identity, spine and address ([ADR 0012](docs/adr/0012-sub-taus.md)). *Avoid: sub-agent, bot.*
- **Public sub-tau** — a sub-tau with `public = true`: contacts reach it as `<address>/<name>` (the `sub` field of a `message`), it answers with its own network turn (its persona and its own public note, never `user.md`) and the universe shows it inside its owner's hull. A private sub-tau never leaves the hub.
- **Web sub-tau** — a public sub-tau with `web = true`: it gets a chat page on the universe for anonymous **visitors**, answers at most `web_daily` visitor turns per UTC day (default 50, 1–1000, counted by the tau that runs it) and shows up to four `starters`, suggested first messages ([ADR 0013](docs/adr/0013-hosted-taus-handles-and-public-pages.md) §5). *Avoid: bot, chatbot.*
- **Visit** — the envelope kind the universe sends to a hub for a visitor's message to a hub-run web sub-tau: sealed `{text, sub}`, `thread` set to the visitor's conversation, signed with the **universe identity**. The hub accepts it only from the universe it joined (keys pinned at the first visit), for a `public` + `web` sub-tau within `web_daily`, and answers with a `message` to the universe. It creates no contact and no universe link.
- **Visitor** — an anonymous person talking to a web sub-tau on its page: a random cookie (`tau_visitor`), no key and no card. Their conversation, a **thread**, is kept by the universe for 24 hours (at most 50 messages) and relayed in plain text, so visitor chats are not end-to-end private. Visitor turns cost the owner's key and budget. *Avoid: guest, user.*
- **Universe identity** — the universe's own network identity (the Worker secret `UNIVERSE_IDENTITY`), with a card at `https://<universe>/.well-known/tau.json` and an inbox at `/net/inbox`: it signs and seals visits and takes the hubs' answers. Hubs pin its keys at the first visit.
- **Handle** — a person's name on the universe, always a GitHub login in lower case proven by a GitHub sign-in (`@alice`; `^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$`). A hosted tau has its handle from its address; any other tau gets one by a **claim**. One handle maps to one address. *Avoid: username, nick.*
- **Claim** — binding a handle to a tau's address: `tau net universe claim` prints `https://<universe>/claim#<signed claim>` (valid for one hour); the owner opens it and signs in with GitHub, and the universe checks both the tau's signature and the GitHub session. A new claim by the same GitHub account moves the handle; one by another account is refused.
- **Slug** — a sub-tau's short page `/<name>` on the universe, global and first come: the first report that lists a public sub-tau with a free, unreserved name takes it for that tau until the tau leaves or expires. Without one, a sub-tau's page is `/@<handle>/<name>`. *Avoid: vanity URL, alias.*
- **Character** — the small creature that stands for a tau or a sub-tau on the site and in tau-host: built on the tau triangle, generated deterministically from the address (and the name, for a sub-tau) by one pure function, `cloud/shared/character.ts`. *Avoid: avatar (nobody uploads one).*

## Hosted taus

- **tau-host** — the Cloudflare Worker that hosts taus in the browser (`cloud/host`, [ADR 0013](docs/adr/0013-hosted-taus-handles-and-public-pages.md) §2): GitHub sign-in, one SQLite-backed Durable Object per tau (settings, persona, profile, sessions, sub-taus, approvals, spend), a TypeScript agent loop that calls the provider directly, the owner's app at `/app` and a chat page per web sub-tau at `/@<handle>/<name>`. No hub, no container, no device tools, nodes, memory or routines. `SIGNUP` (`open` or a list of GitHub logins) decides who may create an account; provider keys are sealed with `VAULT_KEY`. *Avoid: SaaS, cloud mode (that is the Python hub in a Container).*
- **Hosted tau** — a tau that lives on a tau-host run by someone else, such as `tau.getporti.com`, with the address `host/@handle`. The owner brings their own provider key; the host's **operator** can read the tau (chats, persona, profile, sub-taus, visitor chats), and the site says so. Hosted is a convenience; privacy means local or own host.
- **Own host** — tau-host deployed by the owner into their own Cloudflare account, usually with `SIGNUP` set to their own login: the same app as hosted, and only the owner can read it.
- **Operator** — whoever runs a tau-host or a universe: holds its Cloudflare account and secrets and can read what it stores in the clear. On an own host, the owner.

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

## Owner guard

Decided in [ADR 0008](docs/adr/0008-owner-guard.md); the user's side is `docs/guides/guard.md`.

- **Owner** — the one person tau works for: the person enrolled in the guard and the holder of the allowlisted Telegram chats. There is exactly one. *Avoid: user account, admin.*
- **Guard** (owner guard) — the check that the owner is at the Mac before a guarded channel works: the `guard` hub service of `tau-guard`, seen by channels through `tau_core.guard` (`HubGuard`). It only ever narrows: it refuses turns and turns approvals into rejections, never approves. States: `off`, `locked`, `verifying`, `unlocked`, `unavailable`. *Avoid: loop guard (that is `[agent] max_turns`), auth, login.*
- **Guarded channel** — a channel that needs the owner verified at the Mac: the TUI (local, over SSH, in tau Desktop, in a web tab), `tau chat`, `tau ask`, later voice, and any channel that does not opt out (`build_agent(guard=DISCOVER)` fails closed).
- **Identified channel** — an in-hub channel that knows the owner another way and passes `guard=None` in code: Telegram (chat-id allowlist) and network turns (contacts' keys, no tools). The only two; a repo rule enforces it. Distinct from **trusted** (ADR 0006), which is about who may answer a tier-2 approval.
- **Step-up** — the fresh identity check after the owner approves a tier-2 call on a guarded channel: head turns, or a passive match shortly after one. It never replaces the approval; a failure rejects the call.
- **Face template** — the owner's enrolled face: the renormalised mean of 10–20 SFace embeddings plus the head-turn calibration, AES-GCM encrypted in `TAU_DATA_DIR/guard/owner.face.v1.bin` with the key in the macOS Keychain. Biometric data; never leaves the hub, excluded from backups. *Avoid: face ID, photo (no image is ever stored).*
- **Presence recheck** — a passive face check of about a second, with no head turns, that admission asks for after a few minutes of idle time since the last face match or after `presence_recheck_minutes`; a non-matching face locks.
- **Lock trigger** — why the guard locked: `command`, `idle`, `screen_lock`, `sleep`, `max_age`, `hub_stop`, `telegram`, `step_up_failed`, `startup`. The idle, screen, sleep and max-age locks are reflexes: no LLM, no cloud.
- **Cooldown** — after three counted failures (`no_match`, `spoof`, `multiple_faces`) within 10 minutes, checks are refused for 30 s, doubling up to 15 minutes. Distinct from a routine's cooldown.

## Behavior

- **Event** — something that happened, published on Zenoh as `tau/<area>/<name>` (e.g. `tau/desk/presence`). Summaries of events are stored locally on the hub.
- **Agent event** — a record of what the agent did in a session (tool call, approval, turn limit, error, notice); distinct from a mesh **Event** on Zenoh.
- **Turn event** — what a channel receives while one user turn streams: `TextDelta`, `ReasoningDelta`, `ToolUseStarted`, `ToolProgress`, `ToolFinished`, `Throttled`, `Notice`, `TurnEnd`. Rendered by the terminal and the TUI; not stored (agent events are).
- **Stop reason** — why a turn ended, carried by `TurnEnd`: `end_turn`, `limit_turns`, `limit_total_tokens`, `max_tokens`, `cancelled`, `interrupt`, `error`, `busy`, `locked` (the owner guard refused the turn before any history, prompt or model work; nothing is appended and no repair turn follows).
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
