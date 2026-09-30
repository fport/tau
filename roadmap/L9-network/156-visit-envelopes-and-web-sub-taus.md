# 156 · `visit` envelopes and web sub-taus on the hub

Status: done
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

- [x] tau-sub fields round-trip through `new`/`edit`/`show`; validation errors are clear
- [x] tau-net handles `visit` per the rules above; tests cover: accepted, wrong sender, private sub, `web = false`, over the daily cap, unknown universe key change (refused and logged)
- [x] Spine vitest: `visit` accepted by the inbox; kit regenerated
- [x] `docs/reference/tau-network.md` (§3 kinds, §6 hub behaviour) and `tau-universe.md` (report `subs` fields) updated

## Blocked by

None.

## Comments

- 2026-09-30: filed with ADR 0013.
- 2026-09-30: done. As built:
  - tau-sub: `web` (bool), `web_daily` (int 1–1000, default 50), `starters` (≤ 4, each collapsed to one line, 1–80 characters, duplicates dropped). `render` writes them only when set (old files render as before). `tau sub new --web --web-daily N --starter TEXT` (`--web` needs `--public`; checked before drafting); `show` prints them and says when `web` is set without `public`. `PublicSub` carries `web`, `web_daily`, `starters`; tau-net reads them with `tau_net.subs.page_settings`, so an older tau-sub means "no page".
  - Reports: each `subs` item is `{"name", "about", "web", "starters"}` from a hub. `make_payload` adds `web`/`starters` only when the item has them (byte-compatible with `cloud/shared/net`); a universe treats missing ones as `false`/`[]`.
  - `visit`: sealed `{"text": str (≤ 8000), "sub": str (required)}`. Hub order: `from == [component.net] universe` (else `not the joined universe`, nothing fetched), profile `universe_join` (else `not in the universe`), signature with the pinned keys (first visit: fetched card, then pinned; a mismatch is `key changed`, a warning), `to`, duplicate, box, public sub-tau with `web` (`no public sub-tau /x`, `no web page for /x`), `auto_reply` on, `max_hops`, then `web_daily` counted per UTC day before the turn (`/x is over web_daily (n visitor turns today)`).
  - The turn: the sub-tau's persona, public note and role, `tools=[]`, auto-reject, `private_context`, a fresh agent on a `MemorySessionStore` (no visitor sees another's conversation); frame `VISIT_FRAME` (first line `[tau network] A message for you, /{sub}, a specialist of your owner's tau, from an anonymous`); history = the log entries of that universe, thread and sub.
  - Reply: `message` to the universe, `reply_to` = visit id, same `thread`, `hops` = visit hops + 1, content `{"text", "sub"}`, deterministic id; logged with `own_sub`, never counted. No contact is created.
  - Store: new document `universe` (`universe.json` / `net.universe`): `{"pins": {host: {"sign_key", "box_key", "pinned_at"}}, "visits": {"day", "subs": {name: n}}}`. `tau net universe leave` forgets the pin (the way to trust a rotated universe key: leave, join, next visit pins). `universe status` shows today's visitor turns of web sub-taus.
  - `FakeUniverse(identity=...)` has a card, `POST /net/inbox` and `visit(to, text, sub, thread=...)`; `answers()` opens what came back.
