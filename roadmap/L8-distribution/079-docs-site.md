# 079 · Docs site: MkDocs Material built strictly in CI and deployed to Cloudflare Pages at `docs.tau.<domain>`

Status: ready-for-human
Type: HITL
Layer: L8 · Distribution
Packages: docs, .github
Blocked by: none

## What to build

The docs site of ADR 0006 §8: step-by-step guides that need nothing personal to read or follow. The 2026-09-29 docs wave scaffolds it: `mkdocs.yml` (Material, brand stylesheet, the nav for getting started and the guides), the `docs` dependency group, `mkdocs build --strict` in `ci.yml`, and `.github/workflows/docs.yml` (strict build on every push to `main` that touches the docs, deploy to the Cloudflare Pages project `tau-docs` when the secrets exist, build-only otherwise). This issue makes it live and keeps it honest.

Human steps first:

1. In Cloudflare (the account from 013), create the Pages project `tau-docs` as a direct-upload project (not Git-connected, so the build stays in our CI).
2. Create an API token with Pages edit permission (or add that permission to the token from 013) and store `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` as repository secrets.
3. After 022: add the custom domain `docs.tau.<domain>` to the Pages project (Cloudflare adds the DNS record).
4. Then set this issue to `ready-for-agent`.

Agent work after that:

- Run `docs.yml` with deploy on, confirm the `pages.dev` URL and, after step 3, `https://docs.tau.<domain>`; make `site_url` and the README's docs link match.
- Content gate before the first deploy: every page in the nav exists and says something (a stub is written or removed from the nav), `mkdocs build --strict` passes, the ADRs and the architecture page are reachable from the nav, and a search for the private patterns of `.env.example` (tailnet names, `100.x`, key fingerprints, account ids) over `docs/` finds only example values.
- Previews: pull requests that touch the docs get a preview deployment (a non-`main` branch on the same Pages project) with the URL in the job summary.

## Acceptance criteria

- [ ] (user) The `tau-docs` Pages project exists; `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` are repository secrets; after 022 the custom domain is attached
- [ ] `mkdocs build --strict` runs in CI on every push and pull request and fails on a broken link or a missing page
- [ ] A push to `main` deploys the site; a docs pull request gets a preview URL
- [ ] `https://docs.tau.<domain>` serves the site over HTTPS (the `pages.dev` URL until 022 is done)
- [ ] The nav has no placeholder pages; the ADRs and the architecture page are reachable; the README links to the live site; no personal value anywhere in `docs/`

## Blocked by

None - the human steps come first; the custom domain waits for 022 but the `pages.dev` deploy does not.

## Comments

- 2026-09-29: opened for ADR 0006 (private-first), §8 ("step-by-step guides on the docs site"). The scaffold (`mkdocs.yml`, `docs.yml`, the strict build in CI) comes from the docs wave of the same day; this issue tracks the human setup, the first deploy and the content gate.
