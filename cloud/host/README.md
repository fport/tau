# tau-host

tau-host is the Cloudflare Worker that hosts taus in the browser. It is the second and third way to run a tau of [ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md):

- **hosted**: someone else runs tau-host, you sign in with GitHub and bring your own provider key;
- **your own host**: you deploy this same Worker into your own Cloudflare account, for yourself alone.

It serves:

- **the landing page** at `/`: what a hosted tau is, who can read what, and "Sign in with GitHub";
- **the owner's app** at `/app`: chat with your tau, sessions, sub-taus, approvals, settings, export and account deletion;
- **a chat page for each public web sub-tau** at `/@<handle>/<name>`, for anyone;
- **the API**: `/auth/*`, the owner's API under `/api/host/*`, and the visitor API under `/api/visit/*`.

It has no hub and no container. Each tau is one Durable Object, and the brain is a TypeScript agent loop that calls the provider's HTTP API with `fetch`. Device tools, nodes, voice, memory and routines stay with the local hub. Hosted taus on the tau network (cards, inboxes, contacts, `net_send`, the universe) come with issue 162.

## Who can read what

- **On someone else's host** the operator can read everything of your tau: chats, persona, profile, sub-taus and the chats of your visitors. Provider keys are sealed at rest (below) and never shown again, not even to you. The landing page and the onboarding say this before anyone types.
- **On your own host** that operator is you. ADR 0006's promises hold: your data is in your Cloudflare account.
- **Local** (the Python hub) remains the private default.

## What it stores

`Accounts` (one Durable Object, `idFromName("accounts")`) keeps GitHub id ↔ handle, sessions (the SHA-256 of each token, never the token) and sign-ins in flight (10 minutes).

`Tau` (one Durable Object per handle, `idFromName(handle)`) keeps everything of one tau in its own SQLite database: settings, the sealed provider key and its last four characters, model ids, budget, language, persona and profile, sessions and messages, sub-taus, approvals, the spend ledger (tokens and dollars, never text), and visitor threads (24 hours) with their daily counts.

Nothing goes to D1, KV or any other store.

## How it works

- **Sign-in.** The GitHub OAuth web flow with `state` (a cookie and a single-use record, 10 minutes) and PKCE (S256). The handle is the lower-cased GitHub login. A handle stays with its GitHub account: a renamed login keeps its handle, and another account whose login matches an existing handle is refused. The GitHub token is used for one request (`GET /user`) and dropped.
- **Sessions.** 32 random bytes in the cookie `tau_session` (`HttpOnly; Secure; SameSite=Lax; Path=/`, 30 days). Every state-changing request needs `Origin` equal to the host.
- **`SIGNUP`.** `open` lets anyone create an account; a comma list of GitHub logins (`alice,bob`) lets only those; empty lets nobody new. Existing accounts can always sign in.
- **The vault.** A provider key is checked with one free request (the provider's models list), then sealed with AES-256-GCM under a key derived by HKDF-SHA256 from the secret `VAULT_KEY` with `info = "tau-host/1 vault|<handle>"`. It is never returned, exported or logged.
- **The brain.** Anthropic Messages, OpenAI Chat Completions or Gemini `generateContent`, streamed, with tool use. Roles are `brain` and `fast`; the model ids default to tau-core's `templates/models.toml` and can be changed in Settings. The system prompt is laid out like the hub's: the persona (tau-core's `templates/persona.md` unless the owner writes their own), `## User` (the owner's profile) and `## Now`.
- **Tiers.** `ask_sub` is tier 0. `create_sub` is tier 2: the turn stops with an approval card, **Approve** runs it and the turn goes on, **Deny** refuses it, and after 10 minutes it expires and is refused. Nothing approves by itself.
- **Budgets.** A monthly budget in USD per tau (5 by default, calendar month in UTC), counted from each call's token usage times tau-core's `templates/prices.toml`. A turn that would start at or over it is refused with the reason and the reset date. Drafts and visitor turns count too. A model without a price counts as free, and Settings says so.
- **Sub-taus.** Created from a description (the `brain` drafts, without the owner's profile, and the owner reads the draft before saving) or from a template; name `^[a-z][a-z0-9-]{1,30}$`, never `net`, `app`, `api`, `auth`, `claim` or `hub`. Flags: `public`, `public_note`, `web`, `web_daily` (1–1000, default 50) and up to four `starters`.
- **Visitors.** A `public` + `web` sub-tau answers `POST /api/visit/<handle>/<name>` with `{visitor, thread?, text}` → `{thread, reply: {id, text, ts}}`, by the network-turn rules: its persona and public note, never the profile, no tools, no approvals. Limits: `web_daily` answers per UTC day, 10 messages a minute per IP, 2 000 characters per message, 50 messages and 24 hours per thread. The universe relays its visitors here (issue 163); `/@<handle>/<name>` is the host's own page for the same API.
- **For the universe.** `GET /api/host/whoami` answers `{handle, github_id}` for the signed-in cookie, or 401. On a shared domain the universe forwards `/app`, `/app/*`, `/auth/*` and `/api/host/*` to tau-host over a service binding, which is why the owner's API lives under `/api/host/`.

## Layout

```text
src/index.ts          routes and security headers
src/auth.ts           GitHub sign-in, sessions, Origin checks, DEV_LOGIN
src/accounts.ts       Accounts, the Durable Object of handles and sessions
src/tau.ts            Tau, the Durable Object of one tau: settings, turns, approvals, sub-taus, visitors
src/api.ts            /api/host/* and /api/visit/*
src/agent/loop.ts     the agent loop and the tier gate (pure; tested with fakes)
src/agent/prompt.ts   the system prompt and the visitor frame
src/agent/subs.ts     sub-tau validation and templates
src/agent/draft.ts    drafting a sub-tau from a description
src/agent/budget.ts   prices and the monthly budget
src/agent/tools.ts    ask_sub and create_sub as the model sees them
src/providers/        anthropic.ts, openai.ts, gemini.ts, fake.ts over fetch, sse.ts, the key check
src/vault.ts          AES-256-GCM with HKDF per handle
src/generated/        models.ts, prices.ts, persona.ts from tau-core's templates (`pnpm run generate`)
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
pnpm install
pnpm run configure   # wrangler.jsonc, and .dev.vars with DEV_LOGIN=1, FAKE_PROVIDER=1, SIGNUP=open and a fresh VAULT_KEY
pnpm dev             # http://127.0.0.1:8791
```

Open <http://127.0.0.1:8791>. With `DEV_LOGIN=1` the landing page has a development sign-in: type any login (`alice`) and you are in, without GitHub. It works only for requests to `localhost` or `127.0.0.1`. In the onboarding pick **Fake (development, no key)**, which `FAKE_PROVIDER=1` offers. The fake provider answers without a network and follows a small script:

- any message: an echo, streamed word by word;
- `/create coach A workout coach.`: a `create_sub` call, which stops at an approval card;
- `/ask coach How do I start?`: an `ask_sub` call;
- drafting a sub-tau from a description: a draft built from the description;
- a visitor's message on a web sub-tau: an echo as that sub-tau.

To try a real provider locally, pick it and paste your key; it is checked and sealed with the `VAULT_KEY` in `.dev.vars`. To try GitHub sign-in locally, create an OAuth App with the callback `http://127.0.0.1:8791/auth/callback`, run `pnpm run configure --force --client-id <client id>`, put the secret into `.dev.vars` as `GITHUB_CLIENT_SECRET`, and set `DEV_LOGIN=0`.

```sh
pnpm test               # vitest in the Workers runtime; GitHub and every provider are fetch mocks
pnpm run typecheck      # the Worker and the client
pnpm run check-generated  # src/generated/ matches tau-core's templates
pnpm run generate       # after a change to tau-core's models.toml, prices.toml or persona.md
```

## Deploy your own host

1. **A GitHub OAuth App** (GitHub → Settings → Developer settings → OAuth Apps → New). Homepage `https://tau.example.com`, callback `https://tau.example.com/auth/callback`. Keep the client id; generate a client secret.
2. **Configure**, with your own host name and your own GitHub login as the only sign-up:

   ```sh
   pnpm run configure --route tau.example.com --client-id <client id> --signup <your login>
   ```

   Without `--route` the host is `tau-host.<subdomain>.workers.dev`; the OAuth App's callback must then use that name.
3. **Secrets** (typed at the prompt; never in a file or on the command line):

   ```sh
   npx wrangler login
   npx wrangler secret put GITHUB_CLIENT_SECRET
   npx wrangler secret put VAULT_KEY      # 32 random bytes, base64url
   ```

   One way to make a `VAULT_KEY`: `node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"`. Keep a copy offline: without it the stored provider keys cannot be opened, and owners have to paste them again. Changing it has the same effect.
4. **Deploy**: `pnpm run deploy`. It builds the app and deploys the Worker with its two Durable Objects.

`SIGNUP` can be changed at any time in `wrangler.jsonc` (`pnpm run configure --force --signup ...`, then deploy): an empty value closes sign-ups and keeps existing accounts.

## Costs and limits

tau-host runs on the Workers Free plan for a handful of taus: SQLite-backed Durable Objects are on the Free plan, and a tau's object sleeps when nobody talks to it. Every request and every model call's streaming time counts against the plan's limits; many long turns keeping Durable Objects awake need Workers Paid. The model calls themselves are paid by each owner's own provider key and capped by each tau's monthly budget; the provider console's own spend limit stays the last line of defence (ADR 0011).
