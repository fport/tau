# ADR 0015 · The web app: one agentic chat for the hub and tau-host

Date: 2026-10-01 · Status: accepted · Builds on [ADR 0005](0005-components-and-entry-point-groups.md), [ADR 0006](0006-private-first-topology.md), [ADR 0008](0008-owner-guard.md), [ADR 0012](0012-sub-taus.md), [ADR 0013](0013-hosted-taus-handles-and-public-pages.md) and [ADR 0014](0014-one-installer-and-onboarding.md). Amends ADR 0006 (consequences: the web UI's first slice), ADR 0008 decision 6 (two more in-hub opt-outs) and ADR 0012 (generated interfaces are no longer out of scope).

## Context

The owner wants a chat that feels like Claude Desktop, for a signed-in owner, whether the tau is hosted or runs on the owner's own hub. It should have:

- tools and sub-taus with their own tools;
- interfaces the model renders inside the chat, like the scoreboard a tiny draws;
- scheduled tasks;
- settings for physical routines ("lamps on at 07:00").

Today there are two brains and neither has these:

- **The hub** runs Strands (`build_agent`, tiers, the file session store), but it has **no turn API**.
  - `tau tui` and `tau chat` build their own agent in their own process.
  - Only Telegram and network turns run inside the hub.
  - The control API is loopback-only, signed, refuses any `Origin` and does not stream.
- **tau-host** runs its own TypeScript loop in the `Tau` Durable Object.
  - It has five fixed tools, NDJSON streaming, and pause-and-resume approvals.
  - Its app is plain DOM code.

There is also no rendered UI (152), no scheduler (037 needs Zenoh, 047 is a queue sketch) and no device (only `demo_physical_action`).

Constraints:

- Private first: no inbound port, and no server between a channel and the hub that could approve (ADR 0006).
- Tier 2 always goes through approval.
- Guarded channels stay guarded (ADR 0008).
- Hosted taus have no device tools (ADR 0013).
- No hardware, no code.

The owner decided on 2026-10-01:

- hosted taus keep the TypeScript loop;
- 074's `textual-serve` slice is dropped for a real web app;
- there is no smart lamp yet, so the first device is simulated.

## Decision

### 1. One app, two homes, one protocol

- **The app.** One React + Vite + TypeScript app in `apps/web` (bun) is the owner's chat.
  - It is served by the hub (the `tau-web` package, §2) and by tau-host at `/app` (§7).
  - It talks to a `Backend` interface with two implementations, `hub` and `host`.
  - `GET /api/capabilities` tells it which pages exist, so a hosted tau shows no devices or routines.
- **The turn protocol** (`docs/reference/turn-protocol.md`) is the contract between the app and either backend.
  - **Events.** Every event is one JSON line `{v: 1, seq, type, …}`. The types are:
    - `turn` (turn id, session id), `text`, `reasoning`;
    - `tool_use` (id, tool, tier, input), `tool_progress`, `tool_result` (id, status, summary);
    - `approval` (request id, tool, tier, input, reason, expiry) and `approval_decided`;
    - `widget` (§3), `throttled`, `notice`, `guard`, `end` (stop reason), `error`.
  - **History.** It also defines the history shape the app renders when a session is opened again. That shape is user text, assistant text, tool use and result pairs, and widgets.
  - **Code.** tau-core serializes its turn events to this protocol through its public API. The TypeScript types live in `cloud/shared/turn`.
- **Transport** is NDJSON over a streaming `fetch`, as tau-host already does.
  - A turn runs in its backend, independent of the tab. A tab that reconnects re-attaches with `after=<seq>`, and a turn can be cancelled.
  - Approvals are answered with their own `POST`.
- **The look** is pure black with fire only on what is active: the streaming reply, the focused composer, the current page, a pending approval. The palette is the one issue 166 sets for TauBar. Fonts are self-hosted.
- **UI chrome** comes from the app's message table (`en`, `tr`). The language comes from the backend: `[ui] language` on the hub, the account setting on tau-host.

### 2. `tau-web`: the hub serves the app and runs the turns

`packages/tau-web` (import `tau_web`) is one `tau.hub_services` component, `web`. It replaces 074's `textual-serve` plan.

- **Bind.** It listens on `127.0.0.1:<port>` (`[component.web] port`, default 7878), or on the hub's tailnet address, never on `0.0.0.0`. The ways in stay Tailscale Serve and the Tunnel + Access (023, 076).
- **Turns run inside the hub.**
  - The service builds a `TauAgent` per open session with `channel="web"`, the in-hub guard (`guard=DISCOVER`) and a `WebApprover`.
  - The Strands agent, its tools, tiers, hooks, budgets and session store are exactly the ones `tau tui` uses.
  - A session is open in at most one process at a time: the file store takes an advisory lock, and `/resume` of a locked session says where it is open.
- **Paired devices, for everything.** Every route but the pairing page needs a paired browser.
  - `tau web device add <name>` prints a one-time pairing link. The code is in the URL fragment, valid for 10 minutes and single use.
  - The hub stores only the device key's hash under `TAU_DATA_DIR/web/devices.json`.
  - The browser keeps the key in an `HttpOnly; SameSite=Strict` cookie, which is also `Secure` everywhere but plain `http://127.0.0.1`.
  - `tau web device list|remove` manage devices.
  - This is stricter than ADR 0006 §5, which asked for the key only for approvals. The app shows sessions and the model reads `user.md`, so a stolen Access session alone must not read them either.
- **Browser attacks.**
  - The `Host` header must be loopback, the tailnet name or the configured `hub.tau.<domain>`, which stops DNS rebinding.
  - Every non-`GET` request must carry the app's own `Origin`, which stops other sites posting to `127.0.0.1`.
  - With `[component.web] access_aud` set, the `Cf-Access-Jwt-Assertion` is verified too.
- **The guard applies unchanged.** `web` is a guarded, trusted channel. The label is set in tau-web's code and there is no flag, so decision 6 of ADR 0008 holds. The device id is the channel's `client_id`, so 117's per-client grants let the phone in while the owner is away from the Mac. Until then, the web app is locked like any remote TUI.
- **`WebApprover`.**
  - It emits an `approval` event and waits for `POST /api/approvals/<id>` from a paired device.
  - An approval without an answer is rejected after the gate's timeout.
  - Nothing is ever approved automatically.
  - The guard's step-up after an approval runs as it does for the TUI.

### 3. Rendered UI: `render_ui` and widgets

- **The tool.** `render_ui(title, html)` is a tier-0 tool that tau-web adds to the agents it builds. It is not in `tau.tools`, because only channels that can show a widget offer it.
  - The model writes one self-contained HTML document of at most 256 KB.
  - The tool answers the model with "rendered".
  - The HTML is kept in the session as the tool's input, so a reopened session draws the widget again.
- **The frame.** The app shows the widget in an `<iframe sandbox="allow-scripts" srcdoc>`.
  - There is no `allow-same-origin`, so the frame has an opaque origin, no cookies and no storage of the app.
  - There are no forms, popups or top navigation, and `allow=""` grants no camera or microphone.
  - The app puts a Content-Security-Policy `<meta>` first in the document: `default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'`.
  - A widget can reach nothing: not the network, not the hub, not the app.
  - The app's theme tokens are injected as CSS variables, so widgets can match the look.
- **The parent listens to one message:** `{type: "tau.widget.size", height}`, a number, which sizes the frame.
- **Later.** Widgets that talk back (a button that asks tau something) are later work (187). A widget's message would go into the composer for the owner to send; it would never become a tool call by itself.
- **Native cards.** Approvals, tool calls, routines, tasks and devices are cards the app draws from typed events and data. They are never model-written HTML.

### 4. Two kinds of schedule

Both live in a new package, `packages/tau-routines` (import `tau_routines`, hub service `routines`). Their state is under `TAU_DATA_DIR/routines/`, written atomically with mode `0600`. Times follow the hub's local time zone.

- **A routine** is a trigger plus one tool call with fixed arguments, and no LLM. This is the reflex engine of Principle 1.
  - **Triggers.** v1 has clock triggers: daily at `HH:MM`, on chosen weekdays, once at a time, or every N minutes (at least 5). Event triggers from the mesh stay with 037.
  - **Missed firings.** A firing missed while the hub was off runs only within a grace period (default 10 minutes). Otherwise it is recorded as missed.
  - **Running.** The engine calls the tool through a `TierGate` with the routine's exemption. That exemption is keyed by routine id, tool and a hash of the canonical arguments. A `RefusingApprover` refuses anything else.
  - **Guard.** Routines keep working without the internet, the cloud, or the owner at the Mac. They are exempt from the guard, as `docs/ARCHITECTURE.md` already says.
- **A scheduled task** is a trigger plus a prompt, run as a headless agent turn.
  - **The turn.** It runs with `channel="schedule"`, a model role, a tool allowlist (like a sub-tau's, empty by default) and a per-run cost cap (default $0.10) on top of the role's budget.
  - **Sessions.** Every run opens a new session with `task_id` in its metadata. The result goes to the app's inbox, and to Telegram when the task asks for it.
  - **Tier 2.** Inside a scheduled task, tier 2 is refused with a notice to use a routine instead. Waiting for the owner's approval there is later work (188).
- **Registration is one tier-2 approval, on every path.**
  - This covers the settings form in the app, the `add_routine` and `schedule_task` tools, and `tau routine add`.
  - The approval shows the full definition: trigger, tool and arguments, or prompt, role, allowlist and cap.
  - Editing anything but the name re-approves. Pausing and deleting are free.
- **Guard opt-out (amends ADR 0008 decision 6).** The routine engine and scheduled turns are two more in-hub callers that pass a literal `guard=None`, and the repo rule's allowlist gains exactly their two files.
  - They are identified by their registration, which was approved on a trusted, guarded channel.
  - They are bounded by it too: a routine can run only its fixed call, and a scheduled task can run only its allowlisted tools, at tier 0 or 1.
  - A schedule that ran only while the owner sat at the Mac would be useless at 07:00.

### 5. Devices: a simulated lamp first

No smart lamp is on hand, so the first device is simulated.

- **The package.** `packages/tau-sim` offers `lamp_list` (tier 0) and `lamp_set(name, on)` (tier 2) through `tau.tools`.
  - The lamps are named in `[sim] lamps`.
  - Their state is in `TAU_DATA_DIR/sim/lamps.json`.
  - Every UI marks them as simulated.
- **Device sources.** tau-core's public API gains a small `DeviceSource` protocol (`devices()`, `subscribe(callback)`). The sim service implements it, and tau-web lists every hub service that does. The mesh (032, 033) implements it later.
- **A real lamp** arrives as an MCP node with the same tool names (069 decides its tiers). Routines keep working unchanged.

### 6. Tools and sub-taus in the app

- **The toolbox** lists the catalog: each tool's name, tier, description, package and whether it is enabled.
- **Sub-taus** are listed and edited in the app: persona, about, role, tool allowlist, public and web.
  - Edits write `persona/subs/<name>.md` through tau-sub's public API.
  - Allowlisting a tier-2 tool does not pre-approve it: every call still asks.
- **Tools tau writes** (034) show their full source in the app's approval card.

### 7. tau-host runs the same app

- **The UI.** tau-host serves the web app at `/app` with the `host` backend. It replaces `cloud/host/client/app.ts`, and the onboarding, sub-tau, network, approval and settings views move over.
- **The brain** stays the TypeScript loop in the `Tau` Durable Object (owner's decision). It speaks the turn protocol, adds `render_ui`, and gets roomier limits: more steps and output tokens, bounded by the monthly budget.
- **Scheduled tasks** run on the Durable Object's alarm, which already multiplexes approval expiry and the universe report. Hosted taus get no routines and no devices (ADR 0013).
- **Out of scope.** The hosted network code (`cloud/host/src/net*`, `cloud/shared/net`) does not change here.

## Consequences

- **Issues:**
  - 177: the turn protocol;
  - 178: `tau-web`;
  - 179: the web app's chat;
  - 180: `render_ui`;
  - 181: routines on a clock;
  - 182: scheduled tasks;
  - 183: the simulated lamp;
  - 184: the app's control pages;
  - 185: tau-host on the web app;
  - 186: hosted scheduled tasks;
  - 187: widgets that talk back, needs-triage;
  - 188: tier-2 steps in scheduled tasks, needs-triage.
- **Changes to earlier issues:**
  - 074 and 152 are replaced by 178–180.
  - 023 and 080 are now blocked by 178 and 179 instead of 074.
  - 037 keeps the event triggers and builds on 181's engine.
  - 047 builds on 182.
- **Docs.** The docs pages that promise `textual-serve` change with 179: Private deployment, the guard guide, the voice guide, the tiers reference and the threat model, each with its Turkish twin.
- **The Mac app.** The Mac app of ADR 0014 can later open the hub's web app in a window next to, or instead of, the TUI. That is its owner's call, and no issue is filed here.
- **Hub state.** The hub gains a second long-lived agent host besides Telegram, so a session lock in the file store becomes necessary (178).
- **Remote use.** Remote use of the web app while the owner is away depends on 117.

## Why not

- **Strands in tau-host.** Running the Python hub for hosted taus means Containers and Workers Paid (cloud mode), and the owner declined that for hosted taus. The shared protocol keeps the app indifferent to which loop answers.
- **tau-host as a relay to the hub.** A server between the owner's browser and the hub would be the intermediary ADR 0006 forbids. It could read turns, and it could forge approvals. The hub serves its own app instead.
- **`textual-serve` first (074).** A terminal in a tab cannot render widgets, device cards or a phone-friendly composer. It would have been thrown away.
- **Model-written HTML in the app's own DOM, or a JSON component schema only.** HTML in the DOM would give the model's output the app's origin and cookies. A schema cannot draw the free-form interfaces the owner asked for. The sandboxed frame plus native cards covers both.
- **Scheduled tasks under the guard.** They would never run while the owner sleeps. Approving the registration once, with a narrow allowlist and no tier 2, keeps the trust decision at a moment when the owner is present.
