# 167 · One GitHub account with a hosted tau and a hub-run tau: who holds the handle

Status: needs-triage
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/universe, cloud/host, tau-net
Blocked by: 165

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §6 maps one handle to one address. An owner who signs in on `tau.getporti.com` gets a hosted tau at `tau.getporti.com/@<login>`, which takes the handle from its address. The same owner's local tau then cannot claim `/@<login>`: the universe refuses it as `handle_taken`, or the claim moves the handle away from the hosted tau. The owner hit this on the first live try.

Options to decide:

- **One person, several taus.** `/@<login>` becomes the person's page and lists every tau the GitHub account proved: the hosted one and hub-run ones. A claim adds an address instead of moving the handle.
- **One tau per person.** The owner picks which tau holds the handle, and the other appears under its address only.

## Acceptance criteria

- [ ] A decision recorded (an ADR 0013 amendment)
- [ ] The owner's local tau and hosted tau both show on `/@<login>`, or the chosen rule is enforced with a clear message on the claim page

## Comments

- 2026-09-30: filed after the go-live of hosted taus.
