# ADR 0016 · The public site on Next.js (vinext), in the same Worker

Date: 2026-10-01 · Status: accepted · Amends [ADR 0010](0010-public-site-and-tau-universe.md) (how `tau.<domain>` is built) and the security headers of [tau-universe.md](../reference/tau-universe.md) §2.

## Context

The public site (`cloud/universe`) was plain HTML pages in `public/` with small TypeScript scripts bundled by esbuild, served by the `tau-universe` Worker. The Worker is mostly a backend: the opt-in directory (a Durable Object), the visitor relay (one Durable Object per thread), the universe's own card and inbox, the hourly prune, and the forwarding of tau-host's paths.

The owner wants the site to grow, and wants it to be a Next.js project so it has room to. The plain pages also had a cost: every page carried its own copy of the header and footer (18 copies across the two languages), and every page script built its DOM by hand.

The constraints stay:
- One Worker on the owner's account, the Free plan included, with the Durable Objects, the cron, the rate limits and the `HOST` service binding as they are.
- The routes, the language rules and the 404s of tau-universe.md §2, and tau-host's paths forwarded untouched (streamed bodies, tau-host's own headers).
- No third-party script or font, and a CSP that keeps scripts to the site's own.
- bun for installing and running everything (Node only where a tool needs it).

## Decision

1. **Next.js App Router on vinext.**
   - The site is built with [vinext](https://github.com/cloudflare/vinext), Cloudflare's reimplementation of the Next.js API on Vite, and its Workers integration (`@cloudflare/vite-plugin`). That is Cloudflare's default for Next.js on Workers.
   - Pages are React Server Components under `app/`. `next/*` imports resolve to vinext.
2. **The same Worker, with the server in front.**
   - `worker/index.ts` is the Worker's entry. It exports the Durable Object classes and the cron handler as before.
   - For each request it runs the existing server first (`createUniverse` in `src/server.ts`): tau-host's paths, the API, `/net/inbox`, the card, the `?lang=` switch, the start page's language, the handle and slug lookups, the 404s.
   - Only then does it ask vinext to render a page. tau-host's paths never reach vinext or the page headers.
   - A person, sub-tau or short page is looked up first, then rendered from an internal route (`/page/person/<handle>`, `/page/sub/<handle>/<name>`, `/page/slug/<slug>`, under `/tr/` in Turkish).
   - Next.js reads a folder named `@x` as a parallel route, so `/@handle` cannot be an `app/` folder. The internal routes are not reachable from outside (`page` is a reserved name).
3. **Two languages, two root layouts.**
   - `app/(en)/` renders `<html lang="en">` and `app/(tr)/tr/` renders `<html lang="tr">`.
   - Each page's words live in an English component and its Turkish twin under `site/`. The header and footer are one component each, set by language.
   - The script strings stay in `client/messages.ts`.
4. **The canvas and the page behaviours stay imperative.**
   - The universe engine (`client/painter.ts`, `cosmos.ts`), the star field and the page scripts keep their DOM code.
   - Small client components load them after hydration, so React renders the markup and never reconciles what the scripts draw.
5. **CSP with a nonce.**
   - React streams its payload in inline scripts, so `script-src 'self'` alone would break hydration.
   - For each page the Worker makes a random nonce and sends `script-src 'self' 'nonce-…'` and `style-src 'self' 'nonce-…'`. vinext puts the nonce on every script and style it emits.
   - The rest of the policy is unchanged. The API and other responses keep the nonce-free policy.
6. **Tests in two runs.**
   - The server's tests (API, directory, relay, routes, language rules, 404s, headers, forwarding) run the server with a stand-in renderer (`test/worker.ts`).
   - The page tests run the built Worker (`bun run build` first), so they check what ships: the words, the nonces, the routes.

## Consequences

- The site needs `react`, `react-dom`, `vinext`, `vite` and `@cloudflare/vite-plugin`.
- About 140 KB (gzip) of React and vinext runtime comes to the browser on every page. The Worker stays near 300 KB (gzip), far under the Free plan's limit.
- Pages render per request, because each needs its own nonce. They are small, and the Worker answers them in a few milliseconds.
- `bun run dev` is `vite dev` with the Durable Objects in workerd. `bun run build` and `bun run deploy` go through Vite and Wrangler.
- `bun run configure`, the secrets and `wrangler.jsonc` stay as they were.
- New pages and components are React. Server components can read the Durable Objects directly through `cloudflare:workers` when a page wants server-rendered data. Today's pages keep reading the API from the browser, as before.

## Why not

- **OpenNext.** It runs the real Next.js build and has the longest record on Workers, but its Worker is several times larger and close to the Free plan's limit. Cloudflare's guidance for new Next.js projects is vinext.
- **Two Workers** (a Next.js front and the API behind it). One more deployment and one more service binding, for no gain: the server already decides every route.
- **Keeping the plain pages with a templating step.** It solves the duplicated header, but not what the owner asked for: a framework to build on.
- **Dropping the nonce** (`'unsafe-inline'`). The nonce costs nothing per page and keeps injected scripts out.
