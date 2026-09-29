# 022 · Move the getporti domain's DNS to Cloudflare

Status: done
Type: HITL
Layer: L3 · Access and data
Packages: -
Blocked by: none

## What to build

The domain is registered elsewhere; move its nameservers to Cloudflare (full setup) without breaking email.

## Acceptance criteria

- [x] The exact domain (with TLD) is recorded in `docs/ARCHITECTURE.md`
- [x] DNSSEC disabled at the registrar before the nameserver change
- [x] All records imported; MX, SPF, DKIM and DMARC checked by hand and mail still works
- [x] Nameservers switched and the zone is active in Cloudflare
- [x] DNSSEC re-enabled through Cloudflare

## Blocked by

None - can start immediately

## Comments

- 2026-09-29: unchanged under ADR 0006 (private-first) except the layer name; the zone is now needed for the Tunnel hostname `tau.<domain>` (023/076) and the docs site `docs.tau.<domain>` (079), not for a Worker route.
- 2026-09-29: done by the user in a separate session: `getporti.com` nameservers are Cloudflare's (verified with `dig NS`), the zone is active, and Workers custom domains attach to it. First consumer: `docs.tau.getporti.com` on the `tau-docs` Worker (`infra/docs/wrangler.jsonc`).
