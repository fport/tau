# 140 · Public site at `tau.<domain>` with the tau universe page

Status: in-progress
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/universe
Blocked by: none

## What to build

The `tau-universe` Worker (`cloud/universe`) of ADR 0010. It implements §1–§2 of `docs/reference/tau-universe.md`:

- **The landing page at `/`:** what tau is, how it works and what stays private, with CTAs to the docs and the universe. It uses the brand assets of `docs/brand`.
- **The universe page at `/universe`:** a force-directed map of the opted-in taus.
  - Taus are grouped into hulls by owner, and mutual links are dashed lines.
  - Search, a detail card and a list fallback are included.
  - It is honest when empty and respects reduced motion.
- **The directory API:** signed `join`, `report` and `leave`, `GET /api/universe` and `GET /api/taus/<address>`, the mutual-link rule, rate limits and an hourly cron.

Tracked example config and gitignored `wrangler.jsonc` as in `cloud/spine`; the custom domain comes from `pnpm run configure --route tau.example.com`.

## Acceptance criteria

- [ ] Every POST check row and effect of the reference is covered by a vitest test in workerd; security headers on the pages
- [ ] `pnpm dev` serves both pages; a local join + report of two taus shows one mutual link on `/universe`
- [ ] No third-party script; the graph code is bundled; CSP `script-src 'self'`
- [ ] README covers local dev, joining from a local tau, deploy with a custom domain, privacy

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: opened with ADR 0010.
