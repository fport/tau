# 164 · Docs, README and site: three ways to start

Status: done
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: docs, README, cloud/universe
Blocked by: 154, 159, 161

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §1. A "Start" page on the docs site (EN + TR) with the three ways side by side (local, hosted, own host) and what each can read and do; a guide "Deploy your own host" (GitHub OAuth App, secrets, `SIGNUP`, deploy); "Public sub-taus with a web page" (web, starters, daily cap, costs); the README and `README.tr.md` open with the three ways; `how-it-works` gets the three ways and visitor chats; CONTEXT.md terms (hosted tau, tau-host, handle, claim, web sub-tau, visit, character).

## Acceptance criteria

- [x] mkdocs strict build; every new page has its `.tr.md` twin; example values only

## Blocked by

- [154](154-init-asks-for-the-key.md), [159](159-tau-host-core.md), [161](161-site-hard-theme-characters-pages.md)

## Comments

- 2026-09-30: filed with ADR 0013.
- 2026-09-30: done. As built:
  - **Docs site** (EN + TR twins): `docs/getting-started/three-ways.md` ("Three ways to start", first under Getting started): local, hosted and own host side by side (where it runs, what it needs, who can read it, what it can and cannot do, the address, the cost), who can read what, the first steps of each (`tau init` now asks for the provider and the key), cloud mode as the advanced fourth way, and a "Planned" box naming 162 (hosted taus on the network and in the universe) and 165 (go-live on `tau.getporti.com`). `docs/guides/own-host.md` ("Deploy your own host"): prerequisites (bun 1.3, Node 24), host name (custom domain or `workers.dev`), the GitHub OAuth App (homepage and callback `https://tau.example.com/auth/callback`), `bun run configure --route --client-id --signup`, deploy, the secrets (`GITHUB_CLIENT_SECRET` at Wrangler's hidden prompt; `VAULT_KEY` generated into a `0600` file and handed to `bunx wrangler secret put` on stdin, never on a command line), sign-in and onboarding, the universe (planned box), Free-plan limits and when Workers Paid is needed, who may sign in, update, export, delete, troubleshooting. `docs/guides/public-sub-taus.md` ("Public sub-taus with a web page"): what visitors and the sub-tau see, slugs (first come), handles and `tau net universe claim`, the local steps (`--public --web --web-daily --starter`, the front matter, redeploying the spine for `visit`), the hosted app's Visibility settings, costs, privacy and turning it off. Nav labels translated in `mkdocs.yml`; `docs/index.md` and `docs/guides/tau-network.md` (+ tr) link the new pages.
  - **README.md / README.tr.md** open with a short table of the three ways, then the local way and the network; step 2 describes the new `tau init`; public sub-taus, web pages and handles move to "works"; `cloud/host` and `cloud/shared` are on the map.
  - **Site** `how-it-works` (EN + TR): chapters `#visitors` ("A page anyone can talk to") and `#ways` ("Three ways to run it", opening "Before you start", with a diagram), two more real risks (someone else's host, visitor chats), and a link to the docs' start page; existing classes only. `test/pages.test.ts` lists the two new section ids.
  - **CONTEXT.md**: tau-host, hosted tau, own host, operator, handle, claim, slug, web sub-tau, visit, visitor, universe identity, character; Address may be `host/@handle`; "hosted" is no longer an avoided term; the retired Relay entry points at the universe's `Relay` object. **CLAUDE.md**: `cloud/host` dev and test commands.
  - Checked: `uv run --group docs mkdocs build --strict`, `bun run test` in `cloud/universe` (291 tests), both explainer chapters in headless Chrome at desktop and phone widths in both languages without horizontal scroll.
  - Found: `bun run configure --signup` refuses an empty value, so closing sign-ups means editing `"SIGNUP": ""` in `wrangler.jsonc` (the guide says so; `cloud/host/README.md` suggests `configure --force --signup ...`).
