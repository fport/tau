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
| `kind` | str | `join`, `report` or `leave` |
| `universe` | str | the universe's host (e.g. `tau.getporti.com`), so a request cannot be replayed to another universe |
| `address` | str | the tau's address |
| `ts` | int | Unix seconds |

The fields that depend on `kind`:

| `kind` | Extra fields |
|---|---|
| `join` | `owner` (str, 0–60 characters: the owner's display name, may be empty), `about` (str, 0–200 characters) |
| `report` | `links`: a list of at most 500 `{"peer": address, "messages": int ≥ 0}` items; `messages` is the number of `message` envelopes exchanged with that peer, both directions, as counted by the reporter |
| `leave` | nothing |

`owner` and `about` are plain text: the universe strips control characters and the page escapes them.

## 2. Universe endpoints

The universe's own host is the `UNIVERSE` variable when it is set, otherwise the request host.

| Method and path | Response |
|---|---|
| `GET /` | the landing page (static) |
| `GET /universe` | the universe page (static; its script reads `/api/universe`) |
| `GET /api/universe` | `200` the public snapshot (below); `Cache-Control: public, max-age=60`; `Access-Control-Allow-Origin: *` |
| `GET /api/taus/<address>` | `200` one tau with its visible links, or `404 {"error": "not_found"}` |
| `POST /api/join` | a signed `join` |
| `POST /api/report` | a signed `report` |
| `POST /api/leave` | a signed `leave` |

`POST` checks, in this order:

| Check | Failure |
|---|---|
| body ≤ 65 536 bytes | `413 {"error": "too_large"}` |
| well-formed wire body and payload, `v == 1`, known `kind`, valid `address`, field types and lengths of §1 | `400 {"error": "bad_request", "detail": "..."}` |
| `universe` equals the universe's host | `400 {"error": "wrong_universe"}` |
| `abs(now - ts) ≤ 300` and `ts` greater than the last accepted `ts` of this address | `400 {"error": "stale"}` |
| the path matches the payload's `kind` | `400 {"error": "bad_request"}` |
| the card at the address can be fetched (https; http only for `localhost`/`127.0.0.1` with `ALLOW_INSECURE_PEERS=1`; 5 s; ≤ 8 KiB; `address` matches) | `502 {"error": "card_unavailable"}` |
| the signature verifies with the card's `sign_key` | `403 {"error": "bad_signature"}` |
| `report` or `leave` for a joined address | `404 {"error": "not_joined"}` |
| at most 30 accepted requests per address per hour | `429 {"error": "rate_limited"}` |

Effects:

- **`join`** creates or updates the tau: address, card name, `sign_key`, `owner`, `about`, `joined_at` (first join) and `last_seen = ts`. It answers `200 {"ok": true, "url": "https://<universe>/universe#<address>"}`.
- **`report`** replaces the tau's reported links with the new list, refreshes the card name and `last_seen`, and answers `200 {"ok": true, "visible_links": int}`. Peers that are not joined are ignored.
- **`leave`** deletes the tau and its reported links, and answers `200 {"ok": true}`.

The public snapshot:

```json
{
  "universe": "tau.getporti.com",
  "generated_at": 1790000000,
  "stats": {"taus": 2, "online": 1, "messages": 14},
  "taus": [
    {"address": "furkan.tau.example.com", "name": "Furkan's tau", "owner": "Furkan", "about": "...",
     "joined_at": 1790000000, "last_seen": 1790000000, "online": true}
  ],
  "links": [{"a": "alice.example.com", "b": "bob.example.com", "messages": 14}]
}
```

- **Taus** are ordered by `joined_at`.
- **`online`** means `last_seen` is within the last 2 hours; hubs report every hour.
- **A link** between `a` and `b` (with `a < b`) is visible only when `a` reports `b` and `b` reports `a`, and both are joined. Its `messages` is the smaller of the two reported counts.
- **`stats.messages`** is the sum over visible links.

A cron job runs every hour. It deletes taus whose `last_seen` is older than 30 days, together with their links, and prunes rate-limit rows older than one hour.

Pages send `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: strict-origin-when-cross-origin`.

## 3. Hub behaviour (`tau-net`)

`tau.toml`:

```toml
[component.net]
universe = "tau.getporti.com"   # the universe host; "" switches the universe off entirely
universe_join = false           # set by `tau net universe join` / `leave`
universe_owner = ""             # your display name in the universe (optional)
universe_about = ""             # one line about your tau (optional)
universe_links = true           # report mutual links (with counts) to listed contacts
universe_report_minutes = 60
```

The CLI:

- **`tau net universe join [--owner NAME] [--about TEXT] [--no-links]`** sets `universe_join = true` (and the given fields) in `tau.toml` through `tau_core.settings`, sends a `join` and then a `report`, and prints the tau's universe URL.
- **`tau net universe leave`** sends a `leave` and sets `universe_join = false`.
- **`tau net universe status`** shows the setting, whether the universe lists this tau, and its visible links.

The `net` hub service reports while `universe_join` is true:

- once at start, then every `universe_report_minutes`;
- a failure is a warning in `/status` (`net.universe`), never a crash.

A report works like this:

- It reads `GET /api/universe` first and lists only accepted contacts that appear in it. Unlisted contacts are never sent.
- With `universe_links = false`, `links` is empty.
- The counts come from the `counts` document of the network store: `{peer: {"in": n, "out": n}}`. It goes up by one for every `message` envelope handled from a contact or sent to one; the file backend stores it as `counts.json`, the spine backend as `net.counts`.

## 4. The spine kit (`tau net spine`)

`tau-net` ships the spine as a kit: the bundled Worker (`worker.js`, built from `cloud/spine` with `wrangler deploy --dry-run --outdir`), the D1 migrations and a Wrangler configuration template. `cloud/spine`'s `pnpm run kit` regenerates the kit, and a check keeps it in sync with the source.

- **`tau net spine init DIR [--address HOST]`** writes a Wrangler project into `DIR`, and refuses a non-empty `DIR`:
  - `wrangler.jsonc` in local mode, with the Worker name `tau-spine`, `main = "worker.js"`, no build step, the KV, D1, Durable Object and cron settings of `cloud/spine`, and `ADDRESS` plus a custom-domain route when `--address` is a host that is not `*.workers.dev`;
  - `worker.js`, `migrations/`;
  - a `package.json` with Wrangler pinned as a dev dependency;
  - `.gitignore` and a `README.md`.
- **`tau net spine deploy DIR`** takes these steps, and never prints the token:
  1. checks that `npx` exists and that `wrangler whoami` shows a login; otherwise it prints `npx wrangler login` and stops;
  2. runs `npm install`, then `npx wrangler deploy`, then `npx wrangler d1 migrations apply DB --remote`;
  3. generates `TAU_SPINE_TOKEN` in the hub's `.env` when it is missing, and feeds it to `npx wrangler secret put HUB_TOKEN` through stdin;
  4. writes `TAU_SPINE_URL` into the hub's `.env`: `https://<address>` from `--address`, or the `workers.dev` URL printed by the deploy.

  Afterwards `tau net init` and `tau net publish` finish the setup.
