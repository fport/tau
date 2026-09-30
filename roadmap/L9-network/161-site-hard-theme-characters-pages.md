# 161 · The site opens on the universe: hard theme, characters, person and sub-tau pages

Status: in-progress
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/universe (public, client), cloud/shared, docs
Blocked by: –

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §8, §5 (pages) and §6 (pages).

- **Theme:** near-black, faint grid and code texture, one neon red accent from the tau triangle, chrome-white type, thin lines, square corners, HUD rings. Replace the soft look everywhere on the site; the docs site (`mkdocs.yml` palette + `docs/stylesheets/`) follows the palette.
- **Landing `/` and `/tr/`:** the live universe graph full screen as the hero; above the fold only the tagline and the three ways (hosted: "Sign in with GitHub" → `/auth/login`; local: `tau init`; own host: docs link). Text sections below the fold stay short.
- **Characters:** `cloud/shared/character.ts`, a pure function `character(seed, opts) → SVG string`: triangle-body creatures (body shape variants, neon palette colour, eyes, ≤ 1 accessory such as beret, glasses, visor, antenna, horns), deterministic per seed, idle animation via CSS classes that respect `prefers-reduced-motion`. Used for taus and sub-taus in the graph, cards and pages. A gallery page for development only (not shipped) or a vitest snapshot.
- **Pages (static shells + client TS reading the 160 APIs):** `person.html` (`/@handle`: header with handle, GitHub link, "building since", counts, cards for the tau and its public sub-taus with characters, linked taus), `sub.html` (`/<slug>`, `/@handle/<name>`: large character, name, about, "by @handle", starter chips, chat box when `web`, "online" note for hub-run sub-taus, a line saying visitor chats pass through the universe), `claim.html` (reads the fragment, shows what will be bound, "Sign in with GitHub", then `POST /api/claim`). All with `tr` twins. The chat box speaks the 163 API (`POST /api/chat/<target>`, `GET /api/chat/<target>/<thread>?after=`); build it against that contract with a dev fixture.
- Keep the CSP (`script-src 'self'`), no external fonts or scripts, phone widths without horizontal scroll.

## Acceptance criteria

- [ ] Screenshots (desktop + phone, en + tr) of `/`, `/universe`, `/@handle`, `/<slug>`, `/claim` from `pnpm dev` with dev fixtures, checked by the orchestrator
- [x] Characters deterministic (vitest), distinct across a sample of seeds, accessible (`role="img"`, `aria-label`)
- [x] `how-it-works` pages restyled; mkdocs strict build passes with the new palette

## Blocked by

None (APIs per ADR 0013; merge after or alongside 160).

## Comments

- 2026-09-30: filed with ADR 0013.
- 2026-09-30: built; the screenshot check is the orchestrator's. As built:
  - **Theme.** `cloud/shared/theme.css`: tokens `--bg #07080a`, `--bg-2 #0d0f13`, `--bg-3 #13161c`, `--line #1f232b`, `--line-2 #2e3440`, `--text #e8ecf1`, `--muted #8a93a3`, `--faint #5d6574`, `--accent #ff2e3e`, `--accent-hot #ff6b75`, `--accent-glow rgba(255,46,62,.45)`, `--accent-soft`, `--accent-line`, `--on-accent`, `--code`, `--grid`, `--chrome` (gradient), `--font-sans` (Jost 100–900, bundled) and `--font-mono` (system), `--radius: 0`; primitives `.button(-primary)`, `.chip`, `.kicker`, `.pip(-off, -live)`, `.panel`, `.corners`, `.grid-bg`, `.code-bg` (data: SVG glyph columns), `.chrome`, `.hud-ring/-ticks/-arc/-frag/-spin(-back)`, and the characters' motion (`.ch-anim`, `.ch-p0…7`, float, blink, wiggle, bob), all off under `prefers-reduced-motion`. The universe build copies it to `public/static/theme.css` with the fonts next to it (relative `fonts/` URLs). The universe's build output moved from `/app/` to `/static/` (`/app` is tau-host's).
  - **Characters.** `cloud/shared/character.ts`: `character(seed, {size = 96, animated = true, label})` returns an `<svg role="img" aria-label>` string (`label: ""` makes it `aria-hidden`); `traits(seed)` and `describe(traits)` are exported too. FNV-1a + xorshift32, draws in a frozen order: 12 neon colours, 7 bodies (sharp, rounded, tall, squat, notched, lean, cut; each sharp or soft), 8 eye kinds, 7 mouths, 13 accessories + none, marks, cheeks, feet, glow, a motion phase. A lit and a shaded facet split along the ridge (no clip paths or ids: many creatures share a page), presentation attributes only (the CSP allows no inline style). Seeds: a tau's address; a sub-tau's `<address>/<name>`. `cloud/universe/test/character.test.ts` pins three seeds' traits, checks 200 seeds give 200 different SVGs using every colour, body, eye kind and accessory, well-formedness without a DOM, the CSP rules and the accessible name. `node scripts/gallery.mjs` writes a self-ignoring `.gallery/index.html` of 40 creatures.
  - **Landing.** The graph fills the hero behind a HUD ring and the code texture; the hero's text (tagline and the three ways: `/auth/login`, docs `getting-started/install/`, docs `guides/own-host/` — that page is 164's) keeps to the left on desktops, the bottom on tablets and under the graph on phones; the graph fits the free part of the box (`fit()` with insets). Clicking a tau opens its person page (or `/universe#address`). Below the fold: what tau is, who can read what (local, own host, hosted), the universe. `/universe`, `how-it-works` and the 404 pages carry the theme; nodes, roster cards and the detail card show characters, handles and page links.
  - **Pages.** `person.html`, `sub.html`, `claim.html` and their `tr/` twins, with `client/person.ts`, `sub.ts` (visitor chat: `POST /api/chat/<target>`, long poll `GET …/<thread>?after=`, thread kept in sessionStorage, replies as text, enter/shift+enter, 2 000 characters, errors by code, "offline — messages wait" for hub-run sub-taus) and `claim.ts` (decodes the fragment, keeps it in sessionStorage over the GitHub round trip, `POST /api/claim`, 160's error codes). They read 160's as-built shapes (person: the tau's fields at the top level, `links`; subs: `path`/`url`, `hosted`, `owner`). Header on every page: coin + `tau / breadcrumb`, nav, "Sign in" (GitHub mark) → `/auth/login`, the language switch (on these pages the script points it at the same URL in the other language).
  - **Fixtures.** On localhost only, `?fixture=1` switches the pages to `client/fixtures.ts` (loaded on demand) for the tab's session; `?fixture=0` ends it. `node scripts/dev-site.mjs` (127.0.0.1:8795) serves `public/` with the Worker's page routes for looking at the site without the Worker.
  - **Docs.** `docs/stylesheets/brand.css` uses the same tokens; the brand page documents the site theme and the red coin (`sync-brand.mjs` derives `tau-coin-red.svg`).
