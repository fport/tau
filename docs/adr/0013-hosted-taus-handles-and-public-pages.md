# ADR 0013 · Hosted taus, handles and public pages

Date: 2026-09-30 · Status: accepted · Builds on [ADR 0006](0006-private-first-topology.md), [ADR 0007](0007-cloud-mode-and-tau-network.md), [ADR 0010](0010-public-site-and-tau-universe.md), [ADR 0011](0011-budgets-in-tau-no-litellm.md) and [ADR 0012](0012-sub-taus.md).

## Context

Today a tau starts with a clone, `uv sync` and `tau init`, and it reaches other taus only after its owner deploys a spine Worker. That is right for the owner who wants everything on their own machine. Most people who see the universe want less: sign in, bring a provider key, and talk to their tau in the browser. The tiny project shows the shape people expect:

- sign in with GitHub;
- a person page at `/@handle` that lists the person's small agents;
- a page per public agent at `/<name>`, where anyone can talk to it.

The owner asked for three ways to run a tau, each needing only the owner's own provider key:

1. **local**, on their machine;
2. **hosted**, on `tau.getporti.com` after a GitHub sign-in;
3. **their own deployment** of the same hosted system in their own Cloudflare account.

The owner also asked for public sub-taus with pages like tiny's, for a site that opens on the universe, for a sharper look, and for generated characters for taus and sub-taus.

Constraints from the earlier ADRs:

- Local mode stays the private default (ADR 0006).
- The tier gate stays the only way a tier-2 action happens.
- Network turns never see the owner's profile, get no tools and refuse approvals (ADR 0007).
- The universe stays opt-in and shows only counts (ADR 0010).
- tau calls providers directly and enforces its own budgets, with no LiteLLM (ADR 0011).

## Decision

### 1. Three ways to run a tau

| Way | Where the brain runs | Who can read the data | What it can do |
|---|---|---|---|
| **Local** (default) | the Python hub on the owner's machine | the owner | everything: tools, nodes, voice, robot, sub-taus, the network through the owner's spine |
| **Hosted** | tau-host on `tau.getporti.com`, in the operator's Cloudflare account | the owner **and the operator**; provider keys are encrypted at rest | chat in the browser, sub-taus, public pages, the network, the universe; no device tools |
| **Own host** | the same tau-host, deployed by the owner into their own Cloudflare account | the owner | the same as hosted |

Every way needs only the owner's provider key (Anthropic, OpenAI or Gemini). `tau init` asks for it (§7). Hosted and own-host taus take it in the browser at onboarding.

Cloud mode (ADR 0007: the Python hub in a Container) stays the advanced fourth way. It does not change.

The sign-up page says plainly who can read what. Hosted is a convenience, and privacy means local or your own host.

### 2. tau-host: a Worker that hosts taus

`cloud/host` (Worker `tau-host`, TypeScript, bun) runs one or many taus. It has no hub and no container.

- **Accounts.**
  - GitHub OAuth web flow, with `state` and PKCE. The account's **handle** is the lower-cased GitHub login.
  - `SIGNUP` is `open` (multi-tenant, like `tau.getporti.com`) or a comma list of GitHub logins (an own host: the owner alone).
  - A session is a random 32-byte token in the cookie `tau_session` (`HttpOnly; Secure; SameSite=Lax; Path=/`, 30 days). The server stores only its SHA-256 hash.
  - State-changing requests also require `Origin` to equal the host.
  - `DEV_LOGIN=1` allows a password-less login for tests and `wrangler dev`, and only for requests to `localhost` or `127.0.0.1`.
- **Durable Objects** (SQLite-backed, Free plan):
  - `Accounts` (one instance): GitHub id ↔ handle, and sessions.
  - `Tau` (one per handle), which holds everything of that tau:
    - settings: provider, model ids per role, budget and UI language;
    - the persona, the owner's profile (the `user.md` of a hosted tau), sessions and messages;
    - sub-taus, pending approvals and spend;
    - the network identity, contacts and inbox (§4).
- **Keys.**
  - Provider keys and network private keys are sealed with AES-256-GCM, under a key derived by HKDF-SHA256 from the Worker secret `VAULT_KEY` (32 bytes, b64u) with `info = "tau-host/1 vault|<handle>"`.
  - A provider key never goes back to the browser; the app shows the provider and the last four characters.
  - A new key is checked with one small request before it is stored.
- **The brain.**
  - A TypeScript agent loop with tool use calls the providers' HTTP APIs directly with `fetch`: the Anthropic Messages, OpenAI Chat Completions and Gemini `generateContent` APIs. There is no provider SDK and no router library.
  - Roles are `brain` and `fast`.
  - Model ids and prices are data, generated from tau-core's `templates/models.toml` and `templates/prices.toml` into `cloud/host/src/generated/`. A CI check fails when the generated files are stale.
  - The default persona is generated the same way from tau-core's `templates/persona.md`.
- **Tiers.** Tools are tiered as in the hub.
  - `ask_sub` is tier 0.
  - `create_sub` and `net_send` are tier 2.
  - A tier-2 call pauses the turn and shows an approval card in the owner's app. The turn resumes on approve, and the call is refused on deny or after 10 minutes. Nothing auto-approves, tests included; tests use fake approvers.
- **Budgets** (ADR 0011).
  - A monthly budget in USD per tau, 5 by default, counted from the providers' reported usage times the price data.
  - A turn that would start over budget is refused with a clear message.
  - Visitor turns (§5) count against the same budget and against the sub-tau's daily cap.
- **The owner's app** at `/app`:
  - chat with the tau and switch sessions;
  - sub-taus: create one from a description (the `brain` drafts it) or from a template, then edit it, chat with it, and set its flags;
  - approvals, contacts and the universe toggle;
  - settings: key, models, budget, persona, profile and language;
  - export everything as JSON, and delete the account.
- **Own pages.** tau-host serves `/`, `/app`, and a visitor chat page at `/@<handle>/<name>` for its own public web sub-taus. On `tau.getporti.com` these are reached through the universe (§6).
- **Limits.** tau-host runs on the Workers Free plan for a handful of taus. Duration-heavy use, where many long turns keep Durable Objects awake, needs Workers Paid. Configuration and deployment are documented, and `SIGNUP` can close sign-ups at any time.

### 3. Handle-based addresses

The address grammar of protocol v1 widens, and the envelope version stays 1:

- An **address** is `host[:port]` as before, **or** `host[:port]/@handle`.
- A **handle** matches `^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$`, the GitHub login rules in lower case.
- The card is at `<scheme>://<address>/.well-known/tau.json`, and the inbox is at `<scheme>://<address>/net/inbox`. The same rule as before, applied to the longer address.
- A sub-tau is `<address>/<name>`. Sub-tau names never start with `@`, and the names `net`, `app`, `api`, `auth`, `claim` and `hub` are reserved.
- Hosted taus have addresses like `tau.getporti.com/@alice`.
- Hubs, spines and the universe that predate this ADR reject such addresses as `bad_request`. Talking to hosted taus needs the upgraded tau-net, spine and universe. A hub keeps using its plain `host` address.

### 4. Hosted taus on the network

A hosted tau is a full network node:

- It has its own Ed25519 and X25519 keys, generated in its `Tau` object and sealed with the vault.
- tau-host serves its card and inbox with the same checks and limits as a spine (§4 of the protocol reference).
- A delivered envelope is opened in the `Tau` object, which runs the network turn directly, with no mailbox polling: its persona and public note, no profile, no tools, no approvals, and the same hop and hourly limits.
- Contact requests and `net_send` wait for the owner in the app.
- A hosted tau joins and reports to the universe with the same signed requests as a hub.

The protocol's TypeScript half lives in `cloud/shared/net/`, shared by tau-host and the universe:

- b64u encoding and address parsing;
- Ed25519 envelopes;
- the X25519, HKDF-SHA256 and ChaCha20-Poly1305 seal, with `@noble/ciphers` because WebCrypto has no ChaCha20.

Test vectors generated by tau-net keep the TypeScript and Python halves byte-compatible.

### 5. Public sub-taus with a web page, and visitors

A sub-tau definition gets three optional fields:

- **`web`**: false by default; meaningful only with `public = true`. The sub-tau gets a chat page for anonymous visitors.
- **`web_daily`**: 50 by default, 1–1000. At most this many visitor turns per UTC day, counted by the tau that runs the sub-tau.
- **`starters`**: up to 4 suggested first messages, each 1–80 characters.

Universe reports carry `web` and `starters` with each public sub-tau.

Visitors talk to a web sub-tau through the universe page:

- **Hosted sub-taus.** The universe forwards the visitor's message to tau-host over a service binding. tau-host runs the sub-tau's network turn: its persona and public note, no profile, no tools, no approvals. It answers within the daily cap.
- **Hub-run sub-taus** (local mode or cloud mode):
  - The universe has its own network identity: the secret `UNIVERSE_IDENTITY`, a card at `https://<universe>/.well-known/tau.json` with the universe host as its address, and an inbox at `POST /net/inbox`.
  - It sends the hub a new envelope kind, **`visit`**: sealed content `{text, sub}`, with `thread` set to the visitor's conversation.
  - The hub accepts a `visit` only when all of these hold:
    - it comes from the universe the hub joined, with the key pinned at first contact;
    - it names a sub-tau with `public = true` and `web = true`;
    - the sub-tau is within `web_daily`.
  - The hub answers with a `message` (`reply_to`, same `thread` and `sub`) to the universe.
  - `visit` creates no contact and no universe link, and a hub that predates it drops it as an unknown kind.
- **What visitors get.**
  - The page's API is `POST /api/chat/<target>` to send and `GET /api/chat/<target>/<thread>?after=<n>` to poll. A visitor is an anonymous random cookie, `tau_visitor`.
  - Limits: 10 messages per minute per IP, 2 000 characters per message, and threads kept 24 hours.
  - The page says that visitor chats are not end-to-end private: the universe sees them in order to relay them.
  - Visitor turns cost the owner's key. That is why `web` is a separate flag with a daily cap.

### 6. Handles, person pages and sub-tau pages on the universe

- **Handles.**
  - A tau in the universe may have a handle, which is always a GitHub login proven by a sign-in.
  - A hosted tau on the universe's own host has its handle from its address.
  - Any other tau, whether local, own-host or cloud mode, **claims** one:
    1. `tau net universe claim` prints `https://<universe>/claim#<signed claim>`.
    2. The owner opens the link and signs in with GitHub.
    3. The universe checks both the tau's signature and the GitHub session, then binds the handle to the tau's address.
  - A claim is a new signed request kind (`claim`, valid for 1 hour). One handle maps to one address. A new claim by the same GitHub account moves the handle, and a claim by another account is refused.
  - On `tau.getporti.com` the universe asks tau-host who is signed in over the service binding (`GET /api/host/whoami`). A universe without a host binding cannot bind handles.
- **Pages** (each also under `/tr/`):
  - **`/@<handle>`, a person page.** It shows the handle, `github.com/<handle>`, "building since", counts (public sub-taus, visible links, messages), their tau and public sub-taus as cards with their characters, and the taus they are linked with.
  - **`/<slug>`, a sub-tau page.** It shows the sub-tau's character, name, about line and owner ("by @handle"). When `web = true` it adds the starter chips, a chat box, and an "online" note for hub-run sub-taus.
  - **`/@<handle>/<name>`** is always the sub-tau's page.
- **Slugs.** Short slugs are global and go to the first claimant. The first report that lists a public sub-tau whose name is free claims `/<name>` for that tau. Otherwise the sub-tau lives only at `/@<handle>/<name>`, or at its address for a tau without a handle. Every page and route name of the site is reserved. A slug is released when its tau leaves or expires.
- **Directory.** The directory keeps each tau's handle and each sub-tau's `web`, `starters` and first-seen date (schema v3). Snapshots and `/api/taus/<address>` carry them. New endpoints are `GET /api/people/<handle>`, `GET /api/subs/<slug>` and `POST /api/claim`.
- **Routing on `tau.getporti.com`.** The universe Worker stays the front door. It forwards these paths to tau-host through the service binding `HOST`:
  - `/app`, `/app/*`, `/auth/*` and `/api/host/*`;
  - `/@<handle>/.well-known/tau.json` and `/@<handle>/net/*`;
  - the universe's own calls to tau-host's visitor API.

  Everything else is the universe's.

### 7. Local: "just bring your key"

- `tau init` without credentials in the environment asks for the provider (`anthropic`, `openai` or `gemini`) and then the key, with hidden input.
- It checks the key with one small request, unless `--no-check` is given, and writes it to `<home>/.env`, which is created with mode `0600`.
- `--yes` keeps the old behaviour: ask nothing and fall back to `fake`.

### 8. Look and characters

- The public site opens on the universe itself, a full-screen live graph, with the three ways to start as its only text above the fold.
- The theme is hard, not soft: near-black with a faint grid and code texture, one neon red accent drawn from the tau triangle, chrome-white type, thin lines, square corners and HUD rings.
- Every tau and sub-tau gets a **character**, generated deterministically from its address, or its address and name. It is a small creature built on the tau triangle: a triangle body shape, a colour from a fixed neon palette, eyes, and at most one accessory, with an idle animation that respects `prefers-reduced-motion`.
- The generator is one pure function (`cloud/shared/character.ts`, a seed in and SVG out) used by the site and by tau-host.
- The docs site follows the same palette.

## Consequences

- **New code:**
  - `cloud/host` (tau-host);
  - `cloud/shared/` (the protocol's TypeScript half and the character generator, imported by relative path and bundled by wrangler);
  - a directory at schema v3 with a relay object for visitor threads;
  - tau-net: `host/@handle` addresses, the `visit` kind and `tau net universe claim`;
  - tau-sub: the `web`, `web_daily` and `starters` fields;
  - tau-core: the key prompt in `tau init`.
- **Upgrades:** the spine and the spine kit accept `host/@handle` addresses and the `visit` kind. The kit has to be regenerated, and existing spines redeployed, to reach hosted taus.
- **Operator duties on `tau.getporti.com`:**
  - a GitHub OAuth App with the callback `https://tau.getporti.com/auth/callback`;
  - the secrets `GITHUB_CLIENT_SECRET`, `VAULT_KEY` and `UNIVERSE_IDENTITY`;
  - the service binding from `tau-universe` to `tau-host`.
- **Duplication:** hosted taus reimplement the tau turn in TypeScript: persona, profile, sub-taus and the network rules. It stays aligned with tau-core through generated data files (persona, models, prices) and the shared protocol vectors, not by sharing code. Device tools, nodes, memory and routines stay hub-only.
- **Privacy:** ADR 0006's promises hold for local mode and for an own host. On `tau.getporti.com`, hosted taus and visitor chats are readable by the operator, and the site says so where people sign up and where visitors type.

## Why not

- **Hosted taus as Python hubs in Containers:** a container per person costs money even when idle, needs Workers Paid for everyone and is slow to start. The owner rejected it for this purpose. A Durable Object per tau is cheap, sleeps for free and scales with the number of people.
- **An AI SDK or router library for providers:** three small `fetch` clients are easy to audit and match ADR 0011. A dependency tree that sits between tau and its keys is the risk that ADR removed.
- **Handles picked freely on join:** they would let anyone squat a GitHub name. Proving the handle with a GitHub sign-in keeps `/@name` honest.
- **A subdomain per hosted tau (`alice.tau.getporti.com`):** second-level wildcard certificates need Advanced Certificate Manager, and one Custom Domain per person needs an API token that can edit Workers. Path addresses need neither and match the page URLs.
- **Visitors messaging hubs directly:** a visitor has no key and no card. The universe relays under its own identity, so the hub keeps accepting only signed envelopes from a key it pinned.
