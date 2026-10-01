# 179 · The web app: chat, sessions, tool cards and approvals, served by tau-web

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: apps/web, tau-web, docs
Blocked by: 178

## What to build

The owner's chat in the browser, like a desktop assistant ([ADR 0015](../../docs/adr/0015-web-app-agentic-chat.md) §1).

**Stack.**

- `apps/web`: React 19, Vite and TypeScript, with bun and vitest, matching `apps/tau-desktop`.
- `bun run build` writes the bundle into `packages/tau-web/src/tau_web/static/`. The bundle is gitignored and built in CI before `uv build --package tau-web`.
- `bun run dev` proxies `/api` to a running hub.

**The `Backend` interface.**

- `hub` is implemented here; `host` comes in 185.
- It covers `capabilities`, `sessions`, `history`, `startTurn`, `attach`, `cancel` and `decide`.

**Layout.**

- A left rail: Chat, Sessions, Inbox, then the pages that `capabilities` enables (184). Settings goes at the bottom.
- The chat takes the centre, with the composer at the bottom. At phone width the rail collapses into a menu.

**Chat.**

- **Streaming and replies.** Text streams in. Markdown is rendered without raw HTML. Code blocks get a copy button.
- **Tool cards.** Each shows the tool, its tier, its input, a live status and the result summary.
- **The approval card.** It shows the tool, tier, input and reason, with Approve and Reject buttons and a countdown. A decided card turns quiet.
- **Other states.** Reasoning can be collapsed. Throttled and notice lines are shown. Cancel sits in the composer while a turn runs.
- **Reconnects.** A dropped connection re-attaches with `after=`, and the stream never shows the same text twice.

**Sessions.** A list from every channel, with a channel badge and title. Opening a session renders `history_blocks`, and a new session starts with one click. A session locked by another process opens read-only, with a notice.

**Lock screen.** When a turn ends with `locked`, the composer keeps the text and shows the guard's state. It also shows the step-up progress from `guard` events ("look at the Mac and turn left"). Once 117 lands it offers "Ask on Telegram"; until then it says where to unlock.

**Pairing page.** It posts the fragment code and then goes to the chat.

**Look.**

- Pure black (`#050505`, `#0B0B0B`, `#1C1C1C`, from 166). The fire gradient only on what is active: the streaming reply's edge, the focused composer, the current rail item and a pending approval.
- Self-hosted Chakra Petch, IBM Plex Sans and JetBrains Mono.
- Motion stops under `prefers-reduced-motion`.

**Language.** The UI chrome comes from `apps/web/src/messages.ts` (`en`, `tr`), with the language from `capabilities`. There are no Turkish strings outside the `tr` column.

**Docs.** The pages that promise `textual-serve` now describe the web app, each with its Turkish twin in the same change: Private deployment, the guard guide, the voice guide, the tiers reference and the threat model. A new guide, "The web app", covers pairing a device, Tailscale Serve and the lock.

## Acceptance criteria

- [ ] On a hub with tau-web, `http://127.0.0.1:7878` after pairing shows the chat; a message streams a reply from the hub's agent with a tool card for each call
- [ ] A tier-2 call shows the approval card; Approve runs the tool, Reject refuses it, the countdown expires it (vitest with a fake backend, and one end-to-end test against a hub running `FakeModel`)
- [ ] Sessions from the TUI, Telegram and the web are listed and render from their history; a new session and a resumed one both work
- [ ] Killing the connection mid-turn and reconnecting shows the full reply once
- [ ] A locked hub shows the lock screen and keeps the prompt; the step-up progress appears during an approval
- [ ] The layout works at 360 px wide with no horizontal scroll; every string exists in `en` and `tr`
- [ ] The docs pages above and their `.tr.md` twins no longer mention `textual-serve`; `mkdocs build --strict` passes

## Blocked by

- [178 · tau-web](178-tau-web-hub-service.md)

## Comments

- 2026-10-01: filed with ADR 0015. The native cards for routines, tasks and devices are 184, and widgets are 180.
