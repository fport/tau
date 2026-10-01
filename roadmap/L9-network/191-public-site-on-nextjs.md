# 191 · The public site on Next.js (vinext), in the same Worker

Status: in-progress
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/universe, docs
Blocked by: 176

## What to build

[ADR 0016](../../docs/adr/0016-public-site-on-nextjs.md). Move `cloud/universe`'s pages from plain HTML and esbuild scripts to a Next.js App Router on vinext, keeping the Worker, its Durable Objects, its cron, its API and tau-host's forwarding as they are.

- `worker/index.ts`: the entry; the server (`src/server.ts`, `createUniverse(render)`) decides every route first, vinext renders the pages with a per-request CSP nonce.
- `app/(en)/` and `app/(tr)/tr/` root layouts; every page of the site in both languages (landing, how it works, universe, download, soon, claim, person, sub-tau, 404); one header and one footer component.
- The canvas engine and the page scripts load from client components after hydration.
- Tests: the server with a stand-in renderer, and the pages against the built Worker.
- `bun run dev|build|deploy` through Vite; the docs, README and CLAUDE.md commands follow.

## Acceptance criteria

- [ ] Every route of tau-universe.md §2 answers as before in both languages, with the `?lang=` switch, the start page's language and the 404s.
- [ ] tau-host's paths are forwarded untouched: streamed bodies, tau-host's own headers, no page CSP.
- [ ] Pages carry `script-src 'self' 'nonce-…'`, every inline script has the nonce, and no third-party script loads.
- [ ] The pages look and behave as before (screenshots at 360 to 2560 px, both languages, the universe's states, reduced motion).
- [ ] `bun run typecheck`, `bun run build` and `bun run test` pass; CI follows.
- [ ] The reference, the README, CLAUDE.md and the docs describe the new build.

## Comments

- 2026-10-01: filed with ADR 0016 at the owner's request ("convert it to Next.js").
