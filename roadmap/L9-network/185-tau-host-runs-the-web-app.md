# 185 · tau-host runs the web app: the turn protocol, `render_ui` and roomier turns

Status: ready-for-agent
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/host, apps/web, cloud/shared
Blocked by: 179, 180

## What to build

A signed-in owner of a hosted or own-host tau gets the same app as a hub owner ([ADR 0015](../../docs/adr/0015-web-app-agentic-chat.md) §7). The brain stays the TypeScript loop in the `Tau` Durable Object (the owner's decision, 2026-10-01).

**The app.**

- `apps/web` gains the `host` backend over `/api/host/…`, with the GitHub session cookie and the `Origin` rule already in place.
- tau-host's build (`scripts/build.mjs`) takes the web app's bundle for `/app` and keeps `visit.js` for visitor pages. `cloud/host/client/app.ts` is retired.
- **The views move over:** onboarding (provider key), sub-taus (list, new with draft or template, detail), network and contacts, approvals, and settings (provider, models, budget, language, profile). They move with the same routes and behaviour.
- **What hosted taus lack** is reported by `capabilities`: no devices, routines, toolbox editing or guard.

**The Durable Object.**

- `Tau.chat()` streams the turn protocol of 177, validated by `cloud/shared/turn`. It adds `seq`, re-attach with `after=` from the stored messages and a cancel through the existing `AbortSignal`.
- The loop's limits rise from 8 steps and 2048 output tokens to settings with defaults of 24 steps and 8192 tokens. They are bounded by the monthly budget, which is checked before every model call and not only at the start.
- `render_ui` joins the tools at tier 0 with the same contract and size cap as 180. Its HTML is stored in `messages`.
- Approvals keep their pause, card, resume and 600 s expiry flow, now as `approval` and `approval_decided` events.

**Not touched.** `cloud/host/src/net*` and `cloud/shared/net`, the network code (162), stay as they are. Changes there go through that work's owner.

## Acceptance criteria

- [ ] `/app` on a local tau-host (`bun run dev`, dev sign-in, fake provider) is the web app; every view listed above works as before (vitest plus the existing tests, updated)
- [ ] A hosted turn streams protocol events that pass `cloud/shared/turn` validation; a reconnect with `after=` resumes it
- [ ] A long tool loop runs past 8 steps within the new limits and stops at the budget with a notice
- [ ] `render_ui` works on a hosted tau exactly as on the hub (same frame, same tests)
- [ ] The network tests of `cloud/host` pass unchanged

## Blocked by

- [179 · The web app](../L4-interface/179-web-app-chat.md)
- [180 · `render_ui`](../L4-interface/180-render-ui-widgets.md)

## Comments

- 2026-10-01: filed with ADR 0015.
