# 168 · A claim button in tau-host's app for taus on an own host

Status: needs-triage
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/host
Blocked by: 162

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §6. A tau on an own host, such as `tau.example.com/@alice`, that joins the universe on `tau.getporti.com` is listed by its address only. A hub-run tau gets its handle with `tau net universe claim`. tau-host's app needs the same thing: a button on the Network page that signs a `claim` with the tau's identity and opens `https://<universe>/claim#<signed claim>`.

## Acceptance criteria

- [ ] The Network page offers "claim your handle" while the universe lists the tau without one; the signed link matches `docs/reference/tau-universe.md` §1
- [ ] The own-host guide (EN + TR) describes it

## Comments

- 2026-09-30: filed; the own-host guide says the button is not built yet.
