# 191 · The public site on Next.js (vinext), in the same Worker

Status: done
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

- [x] Every route of tau-universe.md §2 answers as before in both languages, with the `?lang=` switch, the start page's language and the 404s.
- [x] tau-host's paths are forwarded untouched: streamed bodies, tau-host's own headers, no page CSP.
- [x] Pages carry `script-src 'self' 'nonce-…'`, every inline script has the nonce, and no third-party script loads.
- [x] The pages look and behave as before (screenshots at 360 to 2560 px, both languages, the universe's states, reduced motion).
- [x] `bun run typecheck`, `bun run build` and `bun run test` pass; CI follows.
- [x] The reference, the README, CLAUDE.md and the docs describe the new build.

## Comments

- 2026-10-01: filed with ADR 0016 at the owner's request ("convert it to Next.js").
- 2026-10-01: done. As built:
  - **Stack.** vinext 1.0 (Next.js 16 API on Vite 8), React 19, `@cloudflare/vite-plugin`; `wrangler.jsonc` and `bun run configure` unchanged in use. The Worker is about 300 KB gzip; the browser gets about 140 KB gzip of React and vinext runtime per page.
  - **Server in front.** `src/index.ts` became `src/server.ts` with `createUniverse(render)`; `worker/index.ts` renders with vinext and a per-page nonce (`pageSecurityPolicy`, `newNonce` in src/pages.ts), and drops the page policy under `vite dev` only. tau-host's paths stay the first thing `fetch` does, returned untouched. `/download/*` (roadmap 190) is wired after the API. `/soon` and `/tr/soon` joined `PAGES`. Looked-up pages render from internal routes (`/page/person`, `/page/sub`, `/page/missing`); `page` is reserved. On a local host, `?fixture=1` skips the lookup so the person and sub-tau pages can be seen with fixtures.
  - **Pages.** `app/(en)/` and `app/(tr)/tr/` root layouts; the page bodies were converted from the old HTML mechanically (header and footer to `site/chrome.tsx`, scripts to `site/page-script.tsx`), so the markup, ids and words are unchanged; `body` classes moved to a wrapper `div.page`.
  - **Build and scripts.** `scripts/build.mjs` is now `scripts/theme.mjs` (theme and fonts only); esbuild and `scripts/dev-site.mjs` are gone; `bun run dev|preview` on 127.0.0.1:8790. The root `.gitignore` ignores the docs build only at the root (`/site/`), since `cloud/universe/site/` is source now.
  - **Tests.** Two vitest projects: `server` (test/worker.ts with a stand-in renderer) and `site` (the built Worker, tau-host stubbed). 339 tests. Checked by hand in headless Chrome in production and development builds: every page in both languages, the universe's interactions, fixtures for person and sub-tau pages, no console or hydration errors.
