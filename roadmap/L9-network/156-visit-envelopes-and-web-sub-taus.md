# 156 · `visit` envelopes and web sub-taus on the hub

Status: ready-for-agent
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-net, tau-sub, cloud/spine
Blocked by: –

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §5, hub side.

- **tau-sub:** optional front-matter fields `web` (bool, default false, only meaningful with `public = true`), `web_daily` (int 1–1000, default 50), `starters` (list of ≤ 4 strings, 1–80 chars). `tau sub new/edit/show` know them; `tau.subs` discovery exposes them.
- **Reports:** each public sub-tau in a universe report carries `web` and `starters` (reference §1 and §3 of `tau-universe.md`).
- **Kind `visit`:** sealed content `{"text": str, "sub": str}`, `thread` = the visitor thread id. The spine knows the kind (so its inbox accepts it). The hub accepts a `visit` only from the universe it joined (`[component.net] universe`, key pinned at first contact in the network store), only for a sub-tau with `public` and `web`, within `web_daily` per UTC day (counted in the network store). It runs that sub-tau's network turn with a frame saying the text comes from an anonymous visitor of the sub-tau's public page, and replies with a `message` to the universe (`reply_to`, same `thread`, same `sub`). No contact is created, nothing counts toward universe links. Everything else is dropped and logged like a stranger.

## Acceptance criteria

- [ ] tau-sub fields round-trip through `new`/`edit`/`show`; validation errors are clear
- [ ] tau-net handles `visit` per the rules above; tests cover: accepted, wrong sender, private sub, `web = false`, over the daily cap, unknown universe key change (refused and logged)
- [ ] Spine vitest: `visit` accepted by the inbox; kit regenerated
- [ ] `docs/reference/tau-network.md` (§3 kinds, §6 hub behaviour) and `tau-universe.md` (report `subs` fields) updated

## Blocked by

None.

## Comments

- 2026-09-30: filed with ADR 0013.
