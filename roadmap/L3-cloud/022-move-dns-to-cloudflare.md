# 022 · Move the getporti domain's DNS to Cloudflare

Status: ready-for-human
Type: HITL
Layer: L3 · Cloud
Packages: -
Blocked by: none

## What to build

The domain is registered elsewhere; move its nameservers to Cloudflare (full setup) without breaking email.

## Acceptance criteria

- [ ] The exact domain (with TLD) is recorded in `docs/ARCHITECTURE.md`
- [ ] DNSSEC disabled at the registrar before the nameserver change
- [ ] All records imported; MX, SPF, DKIM and DMARC checked by hand and mail still works
- [ ] Nameservers switched and the zone is active in Cloudflare
- [ ] DNSSEC re-enabled through Cloudflare

## Blocked by

None - can start immediately

## Comments
