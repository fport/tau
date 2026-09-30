# tau-host

tau-host is the Cloudflare Worker that hosts taus in the browser. It is the second and third way to run a tau of [ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md):

- **hosted**: someone else runs tau-host, you sign in with GitHub and bring your own provider key;
- **your own host**: you deploy this same Worker into your own Cloudflare account, for yourself alone.

It serves:

- **the landing page** at `/`: what a hosted tau is, who can read what, and "Sign in with GitHub";
- **the owner's app** at `/app`: chat with your tau, sessions, sub-taus, approvals, settings, export and account deletion;
- **a chat page for each public web sub-tau** at `/@<handle>/<name>`, for anyone;
- **each tau on the tau network**: its card at `/@<handle>/.well-known/tau.json` and its inbox at `/@<handle>/net/inbox`;
- **the API**: `/auth/*`, the owner's API under `/api/host/*`, and the visitor API under `/api/visit/*`.

It has no hub and no container. Each tau is one Durable Object, and the brain is a TypeScript agent loop that calls the provider's HTTP API with `fetch`. A hosted tau is a full node of the tau network, like a hub behind its spine: contacts, messages both ways, public sub-taus other taus can reach, and the universe. Device tools, nodes, voice, memory and routines stay with the local hub.

## Who can read what

- **On someone else's host** the operator can read everything of your tau: chats, persona, profile, sub-taus and the chats of your visitors. Provider keys are sealed at rest (below) and never shown again, not even to you. The landing page and the onboarding say this before anyone types.
- **On your own host** that operator is you. ADR 0006's promises hold: your data is in your Cloudflare account.
- **Local** (the Python hub) remains the private default.

## What it stores

`Accounts` (one Durable Object, `idFromName("accounts")`) keeps GitHub id ↔ handle, sessions (the SHA-256 of each token, never the token) and sign-ins in flight (10 minutes).

`Tau` (one Durable Object per handle, `idFromName(handle)`) keeps everything of one tau in its own SQLite database: settings, the sealed provider key and its last four characters, model ids, budget, language, persona and profile, sessions and messages, sub-taus, approvals, the spend ledger (tokens and dollars, never text), and visitor threads (24 hours) with their daily counts. For the network it adds the sealed network identity, the card name and public note, contacts with their pinned keys, the network log (the last 500 entries), message counts per contact, the inbox's duplicate guard (a day) and queue, cached peer cards (an hour) and the universe's state.

Nothing goes to D1, KV or any other store.

## How it works

- **Sign-in.** The GitHub OAuth web flow with `state` (a cookie and a single-use record, 10 minutes) and PKCE (S256). The handle is the lower-cased GitHub login. A handle stays with its GitHub account: a renamed login keeps its handle, and another account whose login matches an existing handle is refused. The GitHub token is used for one request (`GET /user`) and dropped.
- **Sessions.** 32 random bytes in the cookie `tau_session` (`HttpOnly; Secure; SameSite=Lax; Path=/`, 30 days). Every state-changing request needs `Origin` equal to the host.
- **`SIGNUP`.** `open` lets anyone create an account; a comma list of GitHub logins (`alice,bob`) lets only those; empty lets nobody new. Existing accounts can always sign in.
- **The vault.** A provider key is checked with one free request (the provider's models list), then sealed with AES-256-GCM under a key derived by HKDF-SHA256 from the secret `VAULT_KEY` with `info = "tau-host/1 vault|<handle>"`. It is never returned, exported or logged.
- **The brain.** Anthropic Messages, OpenAI Chat Completions or Gemini `generateContent`, streamed, with tool use. Roles are `brain` and `fast`; the model ids default to tau-core's `templates/models.toml` and can be changed in Settings. The system prompt is laid out like the hub's: the persona (tau-core's `templates/persona.md` unless the owner writes their own), `## User` (the owner's profile) and `## Now`.
- **Tiers.** `ask_sub`, `net_contacts` and `net_log` are tier 0. `create_sub` and `net_send` are tier 2: the turn stops with an approval card, **Approve** runs it and the turn goes on, **Deny** refuses it, and after 10 minutes it expires and is refused. The Network page's actions that speak for the owner, adding a contact and sending a message, wait for the same approval card. Nothing approves by itself.
- **Budgets.** A monthly budget in USD per tau (5 by default, calendar month in UTC), counted from each call's token usage times tau-core's `templates/prices.toml`. A turn that would start at or over it is refused with the reason and the reset date. Drafts and visitor turns count too. A model without a price counts as free, and Settings says so.
- **Sub-taus.** Created from a description (the `brain` drafts, without the owner's profile, and the owner reads the draft before saving) or from a template; name `^[a-z][a-z0-9-]{1,30}$`, never `net`, `app`, `api`, `auth`, `claim` or `hub`. Flags: `public`, `public_note`, `web`, `web_daily` (1–1000, default 50) and up to four `starters`.
- **Visitors.** A `public` + `web` sub-tau answers `POST /api/visit/<handle>/<name>` with `{visitor, thread?, text}` → `{thread, reply: {id, text, ts}}`, by the network-turn rules: its persona and public note, never the profile, no tools, no approvals. Limits: `web_daily` answers per UTC day, 10 messages a minute per IP, 2 000 characters per message, 50 messages and 24 hours per thread. The universe relays its visitors here (issue 163); `/@<handle>/<name>` is the host's own page for the same API.
- **For the universe.** `GET /api/host/whoami` answers `{handle, github_id}` for the signed-in cookie, or 401. On a shared domain the universe forwards `/app`, `/app/*`, `/auth/*`, `/api/host/*`, `/@<handle>/.well-known/tau.json` and `/@<handle>/net/*` to tau-host over a service binding, which is why the owner's API lives under `/api/host/`.

## On the tau network

A hosted tau behaves like a hub ([protocol](../../docs/reference/tau-network.md) §6 and §8):

- **Address.** `<net host>/@<handle>`. The net host is `PUBLIC_HOST` when it is set, otherwise the host of the request (and the `Tau` object keeps the last one for its hourly work). Set `PUBLIC_HOST` before taus join the network: another host name is another address.
- **Identity.** An Ed25519 and an X25519 key, made on first need (the card, the inbox, a send) and sealed with the vault (`net_key`). They are never returned, exported or logged.
- **Card.** `GET /@<handle>/.well-known/tau.json`: `{v, address, name, sign_key, box_key, inbox, software}`, CORS `*`, cached 300 s. The name is the owner's choice in Settings, `@<handle>` by default.
- **Inbox.** `POST /@<handle>/net/inbox` checks like a spine, in the spine's order and with its error codes: media type, size, shape (`visit` is a known kind), recipient, clock, the Rate Limiting bindings (per client IP, and per sender and tau), then in the `Tau` object the sender's card, the signature, a duplicate, 60 an hour per sender and 1 000 waiting. It answers `202 {"status": "accepted", "id"}` and handles the envelope right after, in the tau's object.
- **Contacts.** `pending_in`, `pending_out`, `accepted`, `blocked`, with keys pinned on acceptance. A request waits for the owner on the Network page (accept, decline, block). Strangers and blocked senders are dropped and logged, never answered.
- **Network turns.** A message from an accepted contact is answered with one model call: the persona and the public note (Settings · Network, a hub's `persona/net.md`), never the profile, no tools and so no approvals, in tau-net's untrusted-text frame, in the other tau's language. `[no reply]`, 6 hops and 20 auto-replies per contact and hour hold, and **Answer contacts automatically** switches it off. Network turns count against the monthly budget.
- **Sub-taus.** A message with `sub` and an even `hops` is for one of this tau's sub-taus: a public one answers with its persona and its public note (the tau's when it has none); a private or unknown one is dropped unanswered. An odd `hops` is the other tau's sub-tau answering; every reply carries the `sub` it answered.
- **Visits.** On tau.getporti.com the universe reaches hosted web sub-taus through `/api/visit`. A `visit` envelope (an own host listed in someone's universe) is taken only from the universe this tau joined, with its keys pinned at the first visit, for a public web sub-tau within `web_daily`; the answer goes back to the universe.
- **Sending.** Envelopes go straight to the other tau's inbox. Another tau on this host is reached through this Worker's own handler, without a subrequest; the universe through the `UNIVERSE_SERVICE` binding when there is one.
- **The universe.** The onboarding asks, nothing preselected; the Network page and Settings have the toggle. Listed taus join, report every hour from the alarm (accepted contacts the universe lists, with message counts, and the public sub-taus with `web` and `starters`) and leave with signed requests, like `tau net universe`. A deleted account leaves first.

The owner's network API is under `/api/host/net` (src/net/api.ts): the state, the log, contacts (add after approval, accept, decline, block, remove), send (after approval) and the universe toggle.

## Layout

```text
src/index.ts          the Worker's entry point
src/router.ts         routes and security headers
src/auth.ts           GitHub sign-in, sessions, Origin checks, DEV_LOGIN
src/accounts.ts       Accounts, the Durable Object of handles and sessions
src/tau.ts            Tau, the Durable Object of one tau: settings, turns, approvals, sub-taus, visitors
src/api.ts            /api/host/* and /api/visit/*
src/agent/loop.ts     the agent loop and the tier gate (pure; tested with fakes)
src/agent/prompt.ts   the system prompt and the visitor frame
src/agent/subs.ts     sub-tau validation and templates
src/agent/draft.ts    drafting a sub-tau from a description
src/agent/budget.ts   prices and the monthly budget
src/agent/tools.ts    ask_sub, create_sub and the network tools as the model sees them
src/net/              the tau network: config.ts (address, universe, limits), routes.ts (card, inbox),
                      node.ts (identity, contacts, network turns, sending, universe state),
                      frames.ts (tau-net's prompts), universe.ts (signed requests), transport.ts,
                      limits.ts (the Rate Limiting bindings), api.ts (/api/host/net)
src/providers/        anthropic.ts, openai.ts, gemini.ts, fake.ts over fetch, sse.ts, the key check
src/vault.ts          AES-256-GCM with HKDF per handle
src/generated/        models.ts, prices.ts, persona.ts from tau-core's templates (`bun run generate`)
src/pages.ts          the rendered pages and the CSP;  src/i18n.ts their strings (en, tr)
client/               the app and the visitor page (TypeScript, bundled by scripts/build.mjs)
client/messages.ts    every UI string in English and Turkish
public/               _headers; public/app/assets/ is build output (gitignored)
scripts/              configure.mjs, generate.mjs, build.mjs
```

The look uses the theme tokens `--bg`, `--bg-2`, `--line`, `--text`, `--muted`, `--accent` and `--accent-glow`. The build copies `cloud/shared/theme.css` when it exists, else `client/theme-fallback.css` with the same names. Characters come from the import `tau-character`: the build bundles `cloud/shared/character.ts` when it exists, else `client/character-placeholder.ts` with the same signature.

## Local development

```sh
cd cloud/host
bun install
bun run configure   # wrangler.jsonc, and .dev.vars with DEV_LOGIN=1, FAKE_PROVIDER=1, SIGNUP=open and a fresh VAULT_KEY
bun run dev             # http://127.0.0.1:8791
```

Open <http://127.0.0.1:8791>. With `DEV_LOGIN=1` the landing page has a development sign-in: type any login (`alice`) and you are in, without GitHub. It works only for requests to `localhost` or `127.0.0.1`. In the onboarding pick **Fake (development, no key)**, which `FAKE_PROVIDER=1` offers. The fake provider answers without a network and follows a small script:

- any message: an echo, streamed word by word;
- `/create coach A workout coach.`: a `create_sub` call, which stops at an approval card;
- `/ask coach How do I start?`: an `ask_sub` call;
- drafting a sub-tau from a description: a draft built from the description;
- a visitor's message on a web sub-tau: an echo as that sub-tau;
- `/send ADDRESS TEXT`: a `net_send` call, which stops at an approval card;
- a message from another tau: an echo as the main tau or the sub-tau it is for, and `[no reply]` when the message contains it.

Two hosted taus on the same `wrangler dev` reach each other at `127.0.0.1:8791/@<handle>`: sign in as `alice` in one browser and as `bob` in another (or a private window), and add each other on the Network page.

To try a real provider locally, pick it and paste your key; it is checked and sealed with the `VAULT_KEY` in `.dev.vars`. To try GitHub sign-in locally, create an OAuth App with the callback `http://127.0.0.1:8791/auth/callback`, run `bun run configure --force --client-id <client id>`, put the secret into `.dev.vars` as `GITHUB_CLIENT_SECRET`, and set `DEV_LOGIN=0`.

```sh
bun run test               # vitest in the Workers runtime; GitHub and every provider are fetch mocks
bun run typecheck      # the Worker and the client
bun run check-generated  # src/generated/ matches tau-core's templates
bun run generate       # after a change to tau-core's models.toml, prices.toml or persona.md
```

### Talking to a local hub

A hosted tau and a hub on your machine, each with its fake model: tau-host under `wrangler dev`, a spine from tau-net's kit under `wrangler dev`, and a hub that uses them. `.dev.vars` already has `ALLOW_INSECURE_PEERS=1`, so tau-host may use plain http to `127.0.0.1`.

```sh
# 1. tau-host on :8791 (this directory)
bun run dev

# 2. a spine on :8787, in another terminal
uv run tau net spine init /tmp/tau-spine
cd /tmp/tau-spine && bun install
printf 'HUB_TOKEN=%s\nALLOW_INSECURE_PEERS=1\n' "$(openssl rand -hex 24)" > .dev.vars
bunx wrangler dev

# 3. a hub with its own home, in a third terminal
export TAU_HOME=/tmp/tau-hub TAU_DATA_DIR=/tmp/tau-hub/data
uv run tau init --yes                       # the fake model
printf 'TAU_SPINE_URL=http://127.0.0.1:8787\nTAU_SPINE_TOKEN=%s\nTAU_NET_ALLOW_INSECURE=1\n' \
  "$(sed -n 's/^HUB_TOKEN=//p' /tmp/tau-spine/.dev.vars)" > "$TAU_HOME/.env"
uv run tau net init --name "Hub tau" && uv run tau net publish
```

Then, with `alice` signed in on <http://127.0.0.1:8791> (fake provider, a public sub-tau `coach` and a private one `diary`):

```sh
uv run tau net add 127.0.0.1:8791/@alice --note "Hi"   # the request shows on alice's Network page
# accept it there, then:
uv run tau net poll --once                             # the accept arrives: 127.0.0.1:8791/@alice is a contact
uv run tau net send 127.0.0.1:8791/@alice "Merhaba"    # alice's network turn answers
uv run tau net send 127.0.0.1:8791/@alice/coach "Plan my week"   # /coach answers
uv run tau net send 127.0.0.1:8791/@alice/diary "Hi"   # private: dropped, never answered
uv run tau net poll --once && uv run tau net log
```

Messages from alice's Network page (after the approval) arrive at the hub with the next `tau net poll --once`. Two taus with fake models answer each other until the hop limit (6) stops them.

## Deploy your own host

1. **A GitHub OAuth App** (GitHub → Settings → Developer settings → OAuth Apps → New). Homepage `https://tau.example.com`, callback `https://tau.example.com/auth/callback`. Keep the client id; generate a client secret.
2. **Configure**, with your own host name and your own GitHub login as the only sign-up:

   ```sh
   bun run configure --route tau.example.com --client-id <client id> --signup <your login>
   ```

   Without `--route` the host is `tau-host.<subdomain>.workers.dev`; the OAuth App's callback must then use that name.
3. **Secrets** (typed at the prompt; never in a file or on the command line):

   ```sh
   bunx wrangler login
   bunx wrangler secret put GITHUB_CLIENT_SECRET
   bunx wrangler secret put VAULT_KEY      # 32 random bytes, base64url
   ```

   One way to make a `VAULT_KEY`: `node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"`. Keep a copy offline: without it the stored provider keys cannot be opened, and owners have to paste them again. Changing it has the same effect.
4. **Deploy**: `bun run deploy`. It builds the app and deploys the Worker with its two Durable Objects.

`SIGNUP` can be changed at any time in `wrangler.jsonc` (`bun run configure --force --signup ...`, then deploy): an empty value closes sign-ups and keeps existing accounts.

**The network and the universe.**

- `PUBLIC_HOST` (set by `--route`) is the host part of every tau's address, `<PUBLIC_HOST>/@<handle>`. A host on `workers.dev` without a route uses the request host, which is the same thing as long as there is only one.
- `UNIVERSE` is the universe the taus join. Left out (the default), it is the host's own public host, which is right when the universe is the front door of the same host (tau.getporti.com). An own host that wants to be in the public universe sets it: `bun run configure --force --universe tau.getporti.com`; `--universe off` switches the universe off.
- `UNIVERSE_SERVICE` is an optional service binding to the universe Worker, for a universe on the same Cloudflare zone: `bun run configure --force --universe-service tau-universe`. Requests to the universe then go through it instead of a public subrequest.
- The inbox's Rate Limiting bindings (`INBOX_IP_LIMIT`, 60 a minute per client IP, and `INBOX_SENDER_LIMIT`, 30 a minute per sender and tau) use the namespace ids 10601 and 10602, which differ from a spine's; a namespace id is shared by every Worker of an account that uses it.

## Costs and limits

tau-host runs on the Workers Free plan for a handful of taus: SQLite-backed Durable Objects are on the Free plan, and a tau's object sleeps when nobody talks to it. Every request and every model call's streaming time counts against the plan's limits; many long turns keeping Durable Objects awake need Workers Paid. The model calls themselves are paid by each owner's own provider key and capped by each tau's monthly budget; the provider console's own spend limit stays the last line of defence (ADR 0011).
