# tau universe protocol (v1) and the spine kit

This page is the contract between three parts, which are built and tested separately:

- the universe Worker (`cloud/universe`, TypeScript), which serves the public site at `tau.<domain>`;
- the universe client in `tau-net` (`tau net universe`, the `net` hub service);
- the spine kit in `tau-net` (`tau net spine init|deploy`).

The decision is [ADR 0010](../adr/0010-public-site-and-tau-universe.md). Addresses, base64url, cards and the scheme rule are those of the [tau network protocol](tau-network.md) §1–§2.

## 1. Signed requests

A tau talks to a universe with signed requests. The wire body is the same shape as an envelope:

```json
{"payload": "<b64u of the payload bytes>", "sig": "<b64u Ed25519 signature>"}
```

- **Signature**: Ed25519 over `b"tau-universe/1\n" + payload_bytes`, with the tau's signing key (the `sign_key` of its card). The domain prefix differs from envelopes (`tau-net/1`), so no signature is valid in both places.
- **Payload**: UTF-8 JSON, at most 64 KiB, with these common fields:

| Field | Type | Meaning |
|---|---|---|
| `v` | int | always `1` |
| `kind` | str | `join`, `report`, `leave` or `claim` |
| `universe` | str | the universe's host (e.g. `tau.getporti.com`), so a request cannot be replayed to another universe |
| `address` | str | the tau's address, a host or `host/@handle` ([protocol](tau-network.md) §1) |
| `ts` | int | Unix seconds |

The fields that depend on `kind`:

| `kind` | Extra fields |
|---|---|
| `join` | `owner` (str, 0–60 characters: the owner's display name, may be empty), `about` (str, 0–200 characters). Clients always send both; a universe treats a missing one as `""` |
| `report` | `links`: a list of at most 500 `{"peer": address, "messages": int ≥ 0}` items; `messages` is the number of `message` envelopes exchanged with that peer, both directions, as counted by the reporter. Optional `subs`: a list of at most 20 `{"name": str, "about": str, "web": bool, "starters": [str]}` items, the tau's public sub-taus ([ADR 0012](../adr/0012-sub-taus.md), [ADR 0013](../adr/0013-hosted-taus-handles-and-public-pages.md) §5); `name` matches `^[a-z][a-z0-9-]{1,30}$`, `about` has 0–200 characters (a missing `about` is `""`), `web` says whether visitors can talk to it on its page (a missing `web` is `false`), `starters` are at most 4 suggested first messages of 1–80 characters (a missing `starters` is `[]`). A report without `subs` lists none |
| `leave` | nothing |
| `claim` | `nonce`: 16–64 base64url characters, `^[A-Za-z0-9_-]{16,64}$` (clients send 18 random bytes, 24 characters) |

`owner`, `about`, a sub-tau's `about` and its `starters` are plain text: the universe strips control characters and the page escapes them.

### Claims

A `claim` binds a handle, a GitHub login proven by a sign-in, to a tau's address ([ADR 0013](../adr/0013-hosted-taus-handles-and-public-pages.md) §6). The tau signs it, and the browser posts it:

- `tau net universe claim` builds the payload `{"v": 1, "kind": "claim", "universe", "address", "ts", "nonce"}` (in that order, compact JSON), signs it like any request, and prints `https://<universe>/claim#<b64u(wire JSON)>`: the fragment is the base64url of the compact wire body `{"payload": ..., "sig": ...}`, the same shape as a `join`. The hub sends nothing.
- The owner opens the link and signs in with GitHub there; the page posts the wire body to the universe (`POST /api/claim`, §2), which checks the tau's signature against the card at `address` and the GitHub session, then binds the handle.
- A claim is valid while `abs(now - ts) ≤ 3600` (the other kinds: 300 s). Like every request it also needs a `ts` greater than the last one the universe accepted from the address, so a report the hub sends after the link was made spoils the link: `tau net universe claim` makes a new one. Its `nonce` makes it single-use.
- Anyone who opens the link can bind their own GitHub login to that tau, so the link is shown only to the owner and never shared.
- `GET /api/taus/<address>` carries `handle` once one is bound, and `tau net universe status` shows it.

Test vector: signing seed `AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8` (bytes `0x00..0x1f`, `sign_key` `A6EHv_POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg`), nonce `AAECAwQFBgcICQoLDA0ODw` (bytes `0x00..0x0f`):

```text
payload JSON  {"v":1,"kind":"claim","universe":"universe.example","address":"alice.example","ts":1790000000,"nonce":"AAECAwQFBgcICQoLDA0ODw"}
payload       eyJ2IjoxLCJraW5kIjoiY2xhaW0iLCJ1bml2ZXJzZSI6InVuaXZlcnNlLmV4YW1wbGUiLCJhZGRyZXNzIjoiYWxpY2UuZXhhbXBsZSIsInRzIjoxNzkwMDAwMDAwLCJub25jZSI6IkFBRUNBd1FGQmdjSUNRb0xEQTBPRHcifQ
sig           xjRvteuZfBpQauW_R1YeTz39uUEoeJJ70tcSoijYj2VByWoajzkHXTc4MTEjyIU_w7R6M8nOug60xfykdQTlDg
link          https://universe.example/claim#eyJwYXlsb2FkIjoiZXlKMklqb3hMQ0pyYVc1a0lqb2lZMnhoYVcwaUxDSjFibWwyWlhKelpTSTZJblZ1YVhabGNuTmxMbVY0WVcxd2JHVWlMQ0poWkdSeVpYTnpJam9pWVd4cFkyVXVaWGhoYlhCc1pTSXNJblJ6SWpveE56a3dNREF3TURBd0xDSnViMjVqWlNJNklrRkJSVU5CZDFGR1FtZGpTVU5SYjB4RVFUQlBSSGNpZlEiLCJzaWciOiJ4alJ2dGV1WmZCcFFhdVdfUjFZZVR6Mzl1VUVvZUpKNzB0Y1NvaWpZajJWQnlXb2FqemtIWFRjNE1URWp5SVVfdzdSNk04bk91ZzYweGZ5a2RRVGxEZyJ9
```

The signature is Ed25519 over `b"tau-universe/1\n" + payload JSON`. `tau-net` tests these values (`packages/tau-net/tests/test_claim.py`); a universe that verifies them verifies a real claim.

## 2. Universe endpoints

The universe's own host is the `UNIVERSE` variable when it is set, otherwise the request host.

| Method and path | Response |
|---|---|
| `GET /` | the landing page (static); redirects to `/tr/` once when the `lang` cookie says `tr`, or when there is no cookie and `Accept-Language` prefers Turkish |
| `GET /how-it-works` | how tau works, for newcomers (static) |
| `GET /universe` | the universe page (static; its script reads `/api/universe`) |
| `GET /@<handle>` | a person page (the template `person.html`), or the 404 page when no listed tau has the handle ([ADR 0013](../adr/0013-hosted-taus-handles-and-public-pages.md) §6) |
| `GET /<slug>`, `GET /@<handle>/<name>` | a sub-tau page (the template `sub.html`), or the 404 page when there is no such sub-tau |
| `GET /claim` | the claim page (the template `claim.html`); its script reads the signed claim from the URL's `#` and posts it to `/api/claim` |
| `GET /tr/`, `/tr/how-it-works`, `/tr/universe`, `/tr/@<handle>`, `/tr/<slug>`, `/tr/@<handle>/<name>`, `/tr/claim` | the Turkish pages; `?lang=en\|tr` on any page stores the choice in the `lang` cookie and redirects to the clean URL |
| `GET /api/universe` | `200` the public snapshot (below); `Cache-Control: public, max-age=60`; `Access-Control-Allow-Origin: *` |
| `GET /api/taus/<address>` | `200` the tau's snapshot fields at the top level plus `links: [{"peer": address, "messages": int}]` (visible links only), or `404 {"error": "not_found"}` |
| `GET /api/people/<handle>` | `200` the person page's data (below), or `404 {"error": "not_found"}`; `Cache-Control: public, max-age=30`; CORS as above |
| `GET /api/subs/<slug>`, `GET /api/subs/@<handle>/<name>` | `200` the sub-tau page's data (below), or `404 {"error": "not_found"}`; cache and CORS as above |
| `POST /api/join` | a signed `join` |
| `POST /api/report` | a signed `report` |
| `POST /api/leave` | a signed `leave` |
| `POST /api/claim` | a signed `claim`, posted by the claim page with the owner's tau-host session cookie |

A handle in a path is matched without regard to case: `/@Alice` redirects (`301`) to `/@alice`, and `/api/people/Alice` answers Alice's page. The templates are served only through these routes, never at `/person` or `/sub`.

`POST` checks, in this order:

| Check | Failure |
|---|---|
| `claim` only: the universe has a `HOST` binding (below) | `501 {"error": "claims_unavailable"}` |
| `claim` only: `Origin` equals the universe's own origin | `403 {"error": "bad_origin"}` |
| body ≤ 65 536 bytes | `413 {"error": "too_large"}` |
| well-formed wire body and payload, `v == 1`, known `kind`, valid `address`, field types and lengths of §1 (`subs` included; a `claim` needs a `nonce` of 16–64 base64url characters) | `400 {"error": "bad_request", "detail": "..."}` |
| `universe` equals the universe's host | `400 {"error": "wrong_universe"}` |
| `abs(now - ts) ≤ 300` (`≤ 3600` for a `claim`) and `ts` greater than the last accepted `ts` of this address | `400 {"error": "stale"}` |
| the path matches the payload's `kind` | `400 {"error": "bad_request"}` |
| the card at the address can be fetched (https; http only for `localhost`/`127.0.0.1` with `ALLOW_INSECURE_PEERS=1`; 5 s; ≤ 8 KiB; `address` matches) | `502 {"error": "card_unavailable"}` |
| the signature verifies with the card's `sign_key` | `403 {"error": "bad_signature"}` |
| `claim` only: tau-host names the signed-in GitHub account (below) | `401 {"error": "not_signed_in"}`, or `502 {"error": "host_unavailable"}` for any other answer |
| `report`, `leave` or `claim` for a joined address | `404 {"error": "not_joined"}` |
| at most 30 accepted requests per address per hour | `429 {"error": "rate_limited"}` |
| `claim` only: the handle rules (below) | `409 {"error": "handle_taken"}` or `409 {"error": "handle_mismatch"}` |

The card of a `host/@handle` address is at `<scheme>://host/@handle/.well-known/tau.json`. When that host is the universe's own host, the tau lives in tau-host, and the universe fetches the card through the `HOST` binding; without the binding such a card is unavailable.

Effects:

- **`join`** creates or updates the tau: address, card name, `sign_key`, `owner`, `about`, `joined_at` (first join) and `last_seen = ts`. It answers `200 {"ok": true, "url": "https://<universe>/universe#<address>"}`.
- **`report`** replaces the tau's reported links with the new list (only peers joined at that moment are kept), replaces its public sub-taus with the report's `subs` (none when the report has no `subs`), refreshes the card name and `last_seen`, and answers `200 {"ok": true, "visible_links": int}`. Peers that are not joined are ignored. A sub-tau keeps its `first_seen` (the `ts` of the first report that listed it) while every report lists it; one that was absent starts again. A sub-tau named `net`, `app`, `api`, `auth`, `claim` or `hub` (reserved by ADR 0013 §3) is dropped.
- **`leave`** deletes the tau, its sub-taus, its handle, its slugs and its own reported links, and answers `200 {"ok": true}`. Other taus' reports stay; their links to it simply stop being mutual.
- **`claim`** binds the GitHub login signed in on tau-host, as the handle, to the tau, and answers `200 {"ok": true, "handle": "alice", "url": "https://<universe>/@alice", "moved_from": null}`.

**Handles.** A handle is a GitHub login in lower case (`^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$`). One handle maps to one address, and a tau has at most one handle.

- A tau hosted on the universe's own host (`<universe>/@<h>`) has the handle `h` from its first `join` or `report`, without a claim: tau-host proved it with a GitHub sign-in. It takes the handle from any other tau.
- Any other tau claims one. The universe stores the GitHub account id with the handle and never shows it.
  - A handle held by another tau under the **same** GitHub id moves to the claiming tau; `moved_from` names the tau it left.
  - A handle held under **another** GitHub id, or by a hosted tau on the universe's own host, is refused with `handle_taken`.
  - A hosted tau can claim only the handle of its own address (`handle_mismatch` otherwise).
  - A claim replaces the claiming tau's earlier handle.
- A claim is valid for an hour and, like every request, only while its `ts` is newer than the last request accepted from its address. An accepted claim moves that guard, so it is single use; a refused one does not, so after `401 not_signed_in` the owner signs in and posts the same claim again. A `report` the hub sends after the link was made also makes the link stale: the owner runs `tau net universe claim` again.
- A handle goes with its tau when the tau leaves or expires.

**Slugs.** A sub-tau's short page `/<name>` belongs to the first tau whose report lists a public sub-tau with that name while the name is free. The name keeps belonging to that tau until the tau leaves or expires, also while its reports stop listing the sub-tau (the page is then 404). Every other tau's sub-tau with that name lives only at `/@<handle>/<name>`, or has no page when its tau has no handle. The names the site uses are never slugs: every page and template (`universe`, `how-it-works`, `claim`, `person`, `sub`, …), every top-level name under `public/` (`brand`, `styles`, `app`, `fonts`, …), every path prefix of the Worker and of tau-host (`api`, `auth`, `net`, `hub`, `tr`) and a few kept for later (`docs`, `about`, `login`, `logout`, `settings`, `new`, `help`, `static`, `assets`). The list is `RESERVED_NAMES` in `cloud/universe/src/routes.ts`.

The public snapshot:

```json
{
  "universe": "tau.getporti.com",
  "generated_at": 1790000000,
  "stats": {"taus": 2, "online": 1, "messages": 14},
  "taus": [
    {"address": "alice.example.com", "name": "Alice's tau", "owner": "Alice", "about": "...",
     "joined_at": 1790000000, "last_seen": 1790000000, "online": true, "handle": "alice",
     "subs": [{"name": "coach", "about": "A patient running coach.", "web": true,
               "starters": ["Plan my week"], "first_seen": 1790000000, "slug": "coach"}]}
  ],
  "links": [{"a": "alice.example.com", "b": "bob.example.com", "messages": 14}]
}
```

- **Taus** are ordered by `joined_at`.
- **`handle`** is the tau's handle, or `null`.
- **`subs`** are a tau's public sub-taus from its last report, ordered by name; `[]` when it reported none. Each has `web` (visitors can talk to it on its page), `starters` (suggested first messages, at most 4), `first_seen`, and `slug`: its name when it holds the short page `/<name>`, otherwise `null`. `GET /api/taus/<address>` carries them too.
- **`online`** means `last_seen` is within the last 2 hours; hubs report every hour.
- **A link** between `a` and `b` (with `a < b`) is visible only when `a` reports `b` and `b` reports `a`, and both are joined. Its `messages` is the smaller of the two reported counts.
- **`stats.messages`** is the sum over visible links.

A person page, `GET /api/people/alice`:

```json
{
  "handle": "alice",
  "github": "https://github.com/alice",
  "building_since": 1790000000,
  "counts": {"subs": 1, "links": 1, "messages": 14},
  "address": "alice.example.com", "name": "Alice's tau", "owner": "Alice", "about": "...",
  "joined_at": 1790000000, "last_seen": 1790003600, "online": true, "hosted": false,
  "subs": [{"name": "coach", "about": "A patient running coach.", "web": true,
            "starters": ["Plan my week"], "first_seen": 1790000000, "slug": "coach",
            "path": "/coach", "url": "https://tau.getporti.com/coach"}],
  "links": [{"peer": "bob.example.com", "messages": 14, "name": "Bob's tau", "handle": "bob",
             "online": true}]
}
```

- **`building_since`** is the tau's `joined_at`. **`counts`** are its public sub-taus, its visible links and the messages over them.
- **`hosted`** means the tau lives in tau-host on the universe's own host.
- A sub-tau's **`path`** is `/<slug>` when it holds its short page, otherwise `/@<handle>/<name>`; **`url`** is the same on `https://<universe>`. Both are `null` for a sub-tau of a tau without a handle and without a slug.
- **`links`** are the visible links, each with the linked tau's name, handle (or `null`) and `online`.

A sub-tau page, `GET /api/subs/coach` or `GET /api/subs/@alice/coach`:

```json
{
  "name": "coach", "about": "A patient running coach.", "web": true, "starters": ["Plan my week"],
  "first_seen": 1790000000, "slug": "coach", "path": "/coach",
  "url": "https://tau.getporti.com/coach", "online": true, "hosted": false,
  "owner": {"handle": "alice", "name": "Alice's tau", "address": "alice.example.com"}
}
```

`online` and `hosted` are the owning tau's. `owner.handle` is `null` for a tau without a handle. A slug that no longer names a listed sub-tau, and a handle or name the directory does not have, are `404`.

**tau-host behind the universe.** A universe may have the optional service binding `HOST` to a tau-host Worker ([ADR 0013](../adr/0013-hosted-taus-handles-and-public-pages.md) §2, §6; `pnpm run configure --host-service tau-host`). With it:

- these paths go to tau-host unchanged (method, URL, headers with the cookies, body), and tau-host's answer comes back as it is, with tau-host's own headers: `/app`, `/app/*`, `/auth/*`, `/api/host/*`, `/@<handle>/.well-known/tau.json` and `/@<handle>/net/*`;
- a `claim` asks tau-host who is signed in: `GET https://<universe>/api/host/whoami` through the binding, with only the claim request's `Cookie` header. tau-host answers `200 {"handle": "<github login>", "github_id": <int>}` or `401`;
- a hosted tau's card is fetched through the binding.

Without the binding, those paths are `404` (the 404 page for a `GET` outside `/api/`, JSON otherwise), claims are `501`, and hosted taus on the universe's own host cannot join. Everything else works the same.

The directory lives in one SQLite-backed Durable Object (`Directory`, one instance by name). Schema version 2 added each tau's sub-taus (a JSON column of `taus`); version 3 added the handle with its GitHub id, each sub-tau's `web`, `starters` and `first_seen`, and the `slugs` table. An older database is upgraded in place on first use: every tau stays, its sub-taus get `web = false`, no starters and `first_seen` = its `last_seen`, and slugs go to taus in `joined_at` order. The Worker checks size, shape, universe, the clock window, the card and the signature, and for a claim the GitHub account. The Durable Object then runs the replay check, the joined check, the rate limit, the handle rules and the effect in one transaction. A card must carry a string `name`; the universe cleans it and cuts it to 80 characters, and uses the address when nothing is left. `universe` is compared without regard to case. In a report, a repeated peer keeps its last entry, and a link to the tau itself is ignored; a repeated sub-tau name keeps its last entry too, and starters are cleaned like `about` (a starter left empty is dropped). A mutual link with 0 messages is shown. `joined_at` is the `ts` of the first join.

A cron job runs every hour. It deletes taus whose `last_seen` is older than 30 days, together with their links, handles and slugs, and prunes rate-limit rows and replay clocks older than one hour.

Pages send `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: strict-origin-when-cross-origin`. The person, sub-tau and claim pages send them too; the paths forwarded to tau-host carry tau-host's own headers.

## 3. Hub behaviour (`tau-net`)

`tau.toml` holds only the non-personal knobs:

```toml
[component.net]
universe = "tau.getporti.com"   # the universe host; "" switches the universe off entirely
universe_links = true           # report mutual links (with counts) to listed contacts
universe_report_minutes = 60
```

Membership and the personal values are runtime data. They live in the `profile` document of the network store (`profile.json` in the file store, `net.profile` in the spine store), never in `tau.toml`, so a checked-in `tau.toml` stays free of personal data:

```json
{"name": "Alice's tau", "universe_join": true, "universe_owner": "Alice", "universe_about": "..."}
```

The card name comes from the profile first, then from `[component.net] name` in `tau.toml` (optional), and falls back to `tau`. `tau net init --name` writes it to the profile.

The CLI:

- **`tau net universe join [--owner NAME] [--about TEXT] [--no-links | --links]`** writes the profile, publishes the card first when it is missing or different, sends a `join` and then a `report`, and prints the tau's universe URL. `--no-links` and `--links` store a `universe_links` override in the profile; without one, `tau.toml` applies.
- **`tau net name NAME`** sets the card name in the profile.
- **`tau net universe leave`** sends a `leave` and sets `universe_join = false`.
- **`tau net universe status`** shows the setting, whether the universe lists this tau, its handle (the `handle` of `GET /api/taus/<address>`, when there is one), its visible links and its public sub-taus, with today's visitor turns of those with a web page.
- **`tau net universe claim`** prints the claim link of §1 for this tau, after publishing the card when it is missing or different, and says when the tau is not joined yet.

Clients keep `ts` strictly increasing per tau and retry a `stale` answer up to three times with the next `ts`, because the CLI and the hub can report in the same second. `universe_report_minutes` is limited to 5–1440.

The `net` hub service reports while the profile's `universe_join` is true:

- once at start, then every `universe_report_minutes`;
- a failure is a warning in `/status` (`net.universe`), never a crash;
- the profile is read again at every interval, so `join` and `leave` take effect without a hub restart;
- a `not_joined` answer while the profile says joined makes the hub join again, for example after the 30-day expiry.

A report works like this:

- It reads `GET /api/universe` first and lists only accepted contacts that appear in it. Unlisted contacts are never sent.
- With `universe_links = false`, `links` is empty.
- `subs` lists only the tau's **public** sub-taus (`public = true` in `persona/subs/<name>.md`), at most 20 by name, each `about` cut to 200 characters, with `web` and `starters` from the definition (`web = true`, `starters = [...]`, ADR 0013 §5); a hub without public sub-taus leaves `subs` out. Private sub-taus never leave the hub, and the list does not depend on `universe_links`.
- `tau net universe leave` also forgets the universe's keys the hub pinned at its first `visit` ([protocol](tau-network.md) §6.4, "Visits"): a tau that left takes no visits.
- The counts come from the `counts` document of the network store: `{peer: {"in": n, "out": n}}`. It goes up by one for every `message` envelope handled from a contact or sent to one; the file backend stores it as `counts.json`, the spine backend as `net.counts`.

## 4. The spine kit (`tau net spine`)

`tau-net` ships the spine as a kit in `tau_net/spine_kit/`. `cloud/spine`'s `pnpm run kit` regenerates it from the source, and a test plus a CI job fail when it is stale. The kit holds:

- the bundled Worker, `worker.js`, built from `cloud/spine` with `wrangler deploy --dry-run --outdir`;
- `wrangler.template.jsonc`, derived from `wrangler.example.jsonc`;
- `package.template.json`, with Wrangler pinned;
- `VERSION` and a `README.md`;
- `migrations/`, only when the local-mode config has a D1 binding. It has none since the mailbox moved into the `Mailbox` Durable Object.

- **`tau net spine init DIR [--address HOST]`** writes a Wrangler project into `DIR`, and refuses a non-empty `DIR`:
  - `wrangler.jsonc` in local mode, with the Worker name `tau-spine`, `main = "worker.js"`, no build step, the bindings, Durable Object migrations, vars and cron of `cloud/spine`'s local-mode config, and `ADDRESS` plus a custom-domain route when `--address` is a host that is not `*.workers.dev`;
  - `worker.js` (and `migrations/` when there is a D1 binding);
  - a `package.json` with Wrangler pinned as a dev dependency;
  - `.gitignore` and a `README.md`.
- **`tau net spine deploy DIR`** takes these steps, and never prints the token:
  1. checks that `npx` exists and that `npx --yes wrangler@<pinned> whoami --json` shows a login (its output, which holds the account's e-mail, is never printed); otherwise it prints `npx wrangler login` and stops;
  2. runs `npm install --no-audit --no-fund` and `npx wrangler deploy`, then `npx wrangler d1 migrations apply DB --remote` only when the project has a D1 binding;
  3. generates `TAU_SPINE_TOKEN` in the hub's `.env` when it is missing, and feeds it to `npx wrangler secret put HUB_TOKEN` through stdin. The token never appears in argv, and any echoed line containing it is masked;
  4. writes `TAU_SPINE_URL` into the hub's `.env`: `https://<address>` from `--address`, or the `workers.dev` URL printed by the deploy.

  Afterwards `tau net init` and `tau net publish` finish the setup.
