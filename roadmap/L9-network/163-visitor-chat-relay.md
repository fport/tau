# 163 · Visitors talk to web sub-taus through the universe

Status: done
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/universe, cloud/shared
Blocked by: 156, 158, 159, 160

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §5. The universe's network identity (`UNIVERSE_IDENTITY` secret; card at `/.well-known/tau.json`; inbox `POST /net/inbox` with the spine's checks), a `Relay` Durable Object for visitor threads (24 h TTL, ≤ 50 messages per thread), `POST /api/chat/<target>` and `GET /api/chat/<target>/<thread>?after=<n>` (long poll ≤ 25 s), the `tau_visitor` cookie, 10 messages/min per IP (rate-limit binding), 2 000 chars. Hosted targets go to `HOST` (`POST /api/visit/...`); hub-run targets get a sealed `visit` envelope and the reply `message` lands in the inbox and the thread.

## Acceptance criteria

- [x] vitest with a fake `HOST` and a fake hub spine: both paths, caps, TTL, bad targets, a non-web sub-tau refused
- [x] End to end locally: `sub.html` → universe → kit spine → hub on the fake model → reply on the page

## Blocked by

- [156](156-visit-envelopes-and-web-sub-taus.md), [158](158-shared-net-typescript.md), [159](159-tau-host-core.md), [160](160-universe-handles-and-pages-api.md)

## Comments

- 2026-09-30: filed with ADR 0013.
- 2026-09-30: done. The contract is §5 of `docs/reference/tau-universe.md`.
  - Identity: the secret `UNIVERSE_IDENTITY` (tau-net's `TAU_NET_IDENTITY` form, parsed with `cloud/shared/net`'s `Identity`). `GET /.well-known/tau.json` is the card (address = the universe host, name `tau universe`, software `tau-universe/<version>`), `404 no_card` without it. `pnpm run identity` writes a fresh one to `.universe-identity` (0600, gitignored) or with `--dev` to `.dev.vars`, prints only the public keys and tells the owner to run `npx wrangler secret put UNIVERSE_IDENTITY < .universe-identity`; `pnpm run configure --check-identity` lists the Worker's secret names. `configure` also reports whether `.dev.vars` has one and takes `--limit-namespaces N`.
  - Inbox `POST /net/inbox`: the spine's checks and codes in the spine's order (`503 not_configured` without the identity, 415, 413, 400 shape, `wrong_recipient`, `stale`, `INBOX_IP_LIMIT` and `INBOX_SENDER_LIMIT`), then, before any card fetch, only a `message` whose `reply_to` is a visit of the thread `thread` that went to `from` (else `400 bad_request` with a detail), then the sender's card (`502`), the signature (`403`), the box opened with the identity and its `sub` equal to the visited sub-tau (`400`), duplicates (`200 duplicate`); accepted answers get `202 {"status": "delivered", "id"}`.
  - `Relay`: one SQLite Durable Object per thread (named by the thread id): `thread`, `messages` (≤ 50) and `visits` (pending until 60 s hosted / 120 s hub-run, the answer's id). Tables only once a thread begins (probing ids stores nothing); an alarm deletes everything 24 h after the thread began, and reads treat an expired thread as gone.
  - Chat API: `POST /api/chat/<slug | @handle/name>` `{text, thread?}` → `200 {thread, id, n}` (+ `tau_visitor` cookie: 24 random bytes, `Path=/api/chat`, 1 year, `HttpOnly`, `SameSite=Lax`, `Secure` on https). Errors: `404 not_found`, `415`, `403 bad_origin` (the page's `Origin` is required), `429 rate_limited` (`CHAT_IP_LIMIT`, 10/min per IP, IPv6 by /64), `413`, `400 bad_request`, `403 not_web`, `503 unavailable` (hosted without `HOST`, hub-run without the identity), `409 thread_full`, `409 busy` (one pending message per thread). `GET /api/chat/<target>/<thread>?after=<n>&wait=<s>` → `{messages: [{n, from: "visitor"|"sub", text, ts}], pending, state}` with `state` `open | resting | full | unavailable`; `resting` is tau-host's `daily_cap` or `budget`.
  - Polling: the Worker holds the GET (up to 25 s, only while a message is pending) and reads the Relay every 2 s; the Durable Object is never held open. `wait=0` returns at once.
  - Hosted delivery (in `waitUntil`): `POST https://<universe>/api/visit/<handle>/<name>` through `HOST` with `{visitor, thread?, text}`, where `visitor` is the SHA-256 of the cookie (43 b64u characters, also what the Relay stores) and `thread` tau-host's own id (absent on the first message; `unknown_thread` restarts it once); no `Origin`, cookie or client IP go along; 28 s timeout. Hub-run delivery: a `visit` from the universe host (`id` = the visit, `thread` = the visitor thread, `hops` 0) sealed to the card's box key, posted to the tau's inbox; anything but `202`/`duplicate` makes the thread `unavailable`.
  - Tests: `test/chat.test.ts` (47): card, inbox refusals (unknown `reply_to`, wrong sender, forged signature, other sub-tau, second answer, limits before any fetch), hub-run flow with a fake spine and answers built with `cloud/shared/net`, the waiting poll, busy, late answers, hosted flow with a fake `HOST` (resting, `unknown_thread`, `no_reply`, errors, `thread_full` at 50), bad targets, `not_web`, origin, text limits, per-IP limit, thread ownership, TTL alarm, no storage for probed ids, and no visitor text in any log line.
  - End to end: universe `wrangler dev` with `pnpm run identity --dev`, a kit spine from `tau net spine init` under `wrangler dev` on :8787, a hub home on the fake provider with `tau sub new coach --public --web`, `tau net publish` and `tau net universe join`. `curl` played the page (`sub.html`'s chat is 161's): `POST /api/chat/coach` → the spine queued the visit → `tau net poll --once` (1 handled, 1 replied) → the waiting `GET ...?after=1&wait=25` returned the fake model's answer; a second message continued the thread (the hub's log shows both visits and answers in one thread), a third while pending was `409 busy`. Neither Worker's log held the visitor text.
