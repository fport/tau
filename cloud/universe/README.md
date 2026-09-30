# tau universe

The universe is the Cloudflare Worker behind tau's public site. It serves:

- **the landing page** at `/`: what tau is, how it works, what stays private, and links to the docs;
- **how it works** at `/how-it-works`: the whole picture for a newcomer, from the brain at home to taus talking to each other, sub-taus, the universe and what an attacker could get;
- **the universe page** at `/universe`: a live map of the taus whose owners chose to list them, and the ones that talk to each other;
- **the same three pages in Turkish** under `/tr/` (see [Two languages](#two-languages));
- **the directory API** at `/api/*`: taus join, report and leave with requests signed by their own key, and the page reads a public snapshot.

The contract, with every status code, JSON shape and limit, is [the tau universe reference](../../docs/reference/tau-universe.md) (§1–§2). The decision behind it is [ADR 0010](../../docs/adr/0010-public-site-and-tau-universe.md). Addresses, cards and the http/https rule come from [the tau network reference](../../docs/reference/tau-network.md).

The universe is independent of any tau's spine: it only reads public cards, and holds nothing private.

## What it stores, and what it shows

A tau appears only after its owner runs `tau net universe join`. Every join, report and leave is signed with the tau's Ed25519 key over `tau-universe/1\n` + the payload, and checked against the `sign_key` of the card at the tau's address. Nobody can list, change or remove a tau they do not control.

The directory keeps, per listed tau:

- its address, card name and `sign_key`;
- an optional owner display name (0–60 characters) and one line about it (0–200), with control characters stripped;
- when it joined and when it last reported;
- the links it reported last: peers that were listed at that moment, each with a message count.

It also keeps, per address, the `ts` of the last accepted request (the replay guard) and one row per accepted request of the last hour (the rate limit).

The public snapshot shows a link between two taus only when **both** report each other, with the smaller of the two counts. It never shows one-sided claims, unlisted contacts or anything a tau did not send. A tau that leaves is gone at once; its own reports go with it, and a link to it stops being mutual. A tau that stops reporting for 30 days is dropped by the hourly cron.

The operator of a universe can see one-sided claims between listed taus before they become mutual, and Cloudflare's request logs show which address sent a request. Hubs only ever report taus that are already listed.

## Layout

```text
src/index.ts       fetch router (API, the pages, 404) and the hourly cron
src/api.ts         /api/*: the POST checks in the reference's order, the snapshot, one tau
src/directory.ts   Directory, the Durable Object with its own SQLite: taus, reports, clocks, hits
src/snapshot.ts    the pure snapshot builder: the link rule, online, stats
src/card.ts        fetching a tau's card (https; http only for loopback in development)
src/protocol.ts    payload validation and text sanitising
src/pages.ts       the page list, the language choice, the 404 pages and the security headers
src/crypto.ts      base64url and Ed25519 (copied from cloud/spine; the context differs)
src/address.ts     addresses and the http/https rule (copied from cloud/spine)
src/http.ts        small HTTP helpers (a verbatim copy of cloud/spine's)
client/            the universe page's script (TypeScript, bundled with d3-force and d3-polygon)
client/messages.ts the script's strings in English and Turkish
public/            the English site: index.html, how-it-works.html, universe.html, 404.html,
                   styles/, _headers
public/tr/         the Turkish site: the same four files, translated
public/brand/      copies of docs/brand files (`pnpm run sync-brand`; a test keeps them exact)
public/app/        build output, gitignored: universe.js and the Jost web font
scripts/           configure.mjs, build.mjs, sync-brand.mjs, dev-taus.mjs
```

### Design notes

- **Storage: one SQLite Durable Object, no D1.** Many Cloudflare accounts on the Workers Free plan are at their D1 database limit; SQLite-backed Durable Objects are available on the Free plan and need no provisioning or ids. The single `Directory` instance (`idFromName("universe")`) owns every table and creates them on first use (a `schema_version` table tracks the version). The Worker does the request parsing, card fetch and signature check, then calls the object's RPC methods (`lastTs`, `join`, `report`, `leave`, `snapshot`, `tau`, `prune`). The replay, joined and rate-limit checks and the effect run in one synchronous transaction, so two copies of a request can never both pass.
- **No card cache.** A tau sends about one request an hour (its report), so a one-hour cache like the spine's would almost never hit. Without one, a new key or card name counts from the next request. The clock and replay checks run before the fetch, so a replayed request never triggers one.
- **Pages and headers.** `run_worker_first` sends `/api/*` and every page in both languages to the Worker, which adds the security headers of §2 (CSP `default-src 'self'` and friends, `nosniff`, `Referrer-Policy`). Every other file is served straight from the asset store with `public/_headers`. Unknown paths reach the Worker, which answers `public/404.html` (or `public/tr/404.html` under `/tr/`) with status 404. There is no inline script or style anywhere (a test checks it); the graph code and the explainer's diagrams (inline SVG styled from `site.css`) need none, and no third-party script or font is loaded.
- **The page.** It reads `/api/universe` once. Taus with the same owner share a hull, links are dashed and wider for more messages, online taus glow. `#<address>` pins a tau; the list under the graph is the keyboard path to every tau. Under `prefers-reduced-motion` the layout is computed up front and nothing moves.

## Two languages

The site is bilingual. English is the source; Turkish is a translation, written as natural Turkish rather than word for word.

| English | Turkish |
|---|---|
| `/` (`public/index.html`) | `/tr/` (`public/tr/index.html`) |
| `/how-it-works` (`public/how-it-works.html`) | `/tr/how-it-works` (`public/tr/how-it-works.html`) |
| `/universe` (`public/universe.html`) | `/tr/universe` (`public/tr/universe.html`) |
| unknown paths (`public/404.html`) | unknown paths under `/tr/` (`public/tr/404.html`) |

- **Switcher.** Every page carries an EN · TR switcher in its header. It links the same page in the other language with `?lang=en` or `?lang=tr`; the Worker stores that choice in a `lang` cookie (one year, `SameSite=Lax`, `HttpOnly`) and redirects to the URL without the parameter. That click is the only way the site sets a cookie.
- **Start page.** `/` redirects to `/tr/` when the cookie says `tr`, or when there is no cookie and the browser's `Accept-Language` prefers Turkish to English. A stored choice always wins, and no other page ever redirects.
- **Search engines.** Each page names both versions with `<link rel="alternate" hreflang>` (`en`, `tr`, and `x-default` for English), with absolute URLs on `tau.getporti.com`.
- **Links.** Turkish pages link other Turkish pages (`/tr/…`) and the Turkish docs (`https://docs.tau.getporti.com/tr/…`); English pages link the English docs.
- **The universe script.** `client/messages.ts` holds its strings, one table per language with the same keys; the script picks the table by `<html lang>` and formats numbers, dates and relative times with `Intl` in that language. Turkish puts no plural ending after a number and no message attaches a suffix to one.

### Adding a page

1. Write the English page as `public/<name>.html`, with the header (menu and switcher), the footer and the three `hreflang` links of the existing pages.
2. Write its Turkish twin as `public/tr/<name>.html`: `<html lang="tr">`, the Turkish menu, links under `/tr/`, docs links under `https://docs.tau.getporti.com/tr/`, and the same element ids as the English page.
3. Add both paths to `PAGES` in `src/pages.ts` and to `run_worker_first` in `wrangler.example.jsonc` (a test checks the two agree), then add the pair to `TWINS` in `test/pages.test.ts`.
4. Link the new page from the menu or the footer of every page, in both languages.
5. Run `pnpm test`: it checks both pages' status, headers, language, `hreflang` links, switcher, links and matching ids.

When the English text changes, change the Turkish page in the same commit, or put `<!-- tr: out of date -->` at the top of the Turkish file until it is translated.

## Local development

Requirements: Node 24 and pnpm 10. No Cloudflare account is needed.

```sh
cd cloud/universe
pnpm install
pnpm run configure    # writes wrangler.jsonc and .dev.vars (ALLOW_INSECURE_PEERS=1)
pnpm dev              # builds the page script, then http://127.0.0.1:8790
```

`wrangler dev` keeps the Durable Object's SQLite under `.wrangler/state`. Open http://127.0.0.1:8790/, http://127.0.0.1:8790/how-it-works and http://127.0.0.1:8790/universe, and the same under `/tr/`. `wrangler dev` reads the list of static files when it starts: restart it after adding a page.

To see the universe page with some taus on it, fill the local directory with a small cast of development taus. The script serves their cards on `http://127.0.0.1:18790` and up, signs a join and a report for each, and stops; `--leave` removes them again, `--count N` joins only the first N:

```sh
node scripts/dev-taus.mjs            # 7 taus, 5 mutual links (and one one-sided claim that stays hidden)
node scripts/dev-taus.mjs --leave
```

It refuses any universe that is not on `127.0.0.1` or `localhost`.

Other commands:

| Command | What it does |
|---|---|
| `pnpm test` | the Vitest suite in the Workers runtime: API, Directory, snapshot builder, pages in both languages, the language choice, the script's strings, brand copies |
| `pnpm typecheck` | `tsc --noEmit` for the Worker and for the page script |
| `pnpm run build` | bundles `client/universe.ts` into `public/app/universe.js` and copies the web font (`wrangler dev` and `wrangler deploy` run it too) |
| `pnpm run sync-brand` | copies the brand files from `docs/brand/` into `public/brand/`; `--check` only reports differences |
| `pnpm run types` | regenerates `worker-configuration.d.ts` (the `Env` type) from `wrangler.example.jsonc` |
| `curl http://127.0.0.1:8790/cdn-cgi/local/scheduled` | runs the cron once (`wrangler dev` does not run crons by itself) |

`pnpm run configure --route HOST` also sets `UNIVERSE` to `HOST`. Signed requests must name the universe's host, so for local development configure without `--route` (the universe is then the request host, `127.0.0.1:8790`), or run `pnpm exec wrangler dev --var UNIVERSE:`.

### Joining from a local tau

A hub running against a local spine can join the local universe. The universe fetches the tau's card from its spine, over http for a loopback address because `.dev.vars` sets `ALLOW_INSECURE_PEERS=1`.

1. Run a local spine with a published card (see [`cloud/spine/README.md`](../spine/README.md): `pnpm dev` there, then `tau net init` and `tau net publish` on the hub).
2. Point the hub at the local universe. In `tau.toml`:

   ```toml
   [component.net]
   universe = "127.0.0.1:8790"
   ```

   and in the hub's `.env`, `TAU_NET_ALLOW_INSECURE=1` (development only).
3. Join, then look:

   ```sh
   tau net universe join --owner "Your name" --about "One line about your tau"
   tau net universe status
   ```

   The tau is at http://127.0.0.1:8790/universe#127.0.0.1:8787. (The join answer's `url` always says `https://`, as in production.)

## Deploy

The universe runs on the Workers Free plan: one Worker, its static assets and one SQLite Durable Object. There is nothing to provision by hand and no secret.

```sh
cd cloud/universe
pnpm run configure --route tau.example.com   # or --force to replace an existing wrangler.jsonc
npx wrangler login                           # once
pnpm run deploy                              # builds the page script and deploys
```

- `--route` adds `"routes": [{ "pattern": "tau.example.com", "custom_domain": true }]` and sets `UNIVERSE` to the same host. The zone must be on your Cloudflare account; Wrangler creates the DNS record and the certificate.
- Without `--route`, the universe answers at `tau-universe.<your-subdomain>.workers.dev` and names itself by the request host.
- Hubs point at a universe with `[component.net] universe = "<host>"`; `tau.getporti.com` is the default.
- `wrangler.jsonc` is gitignored; keep it. Re-running `pnpm run configure --force` carries its routes and `UNIVERSE` over.

Check a deployment:

```sh
curl -sI https://tau.example.com/ | grep -i content-security-policy
curl -sI -H 'Accept-Language: tr' https://tau.example.com/ | grep -i location   # /tr/
curl -s https://tau.example.com/api/universe
```
