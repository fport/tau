# 161 · The site opens on the universe: hard theme, characters, person and sub-tau pages

Status: ready-for-agent
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
- [ ] Characters deterministic (vitest), distinct across a sample of seeds, accessible (`role="img"`, `aria-label`)
- [ ] `how-it-works` pages restyled; mkdocs strict build passes with the new palette

## Blocked by

None (APIs per ADR 0013; merge after or alongside 160).

## Comments

- 2026-09-30: filed with ADR 0013.
