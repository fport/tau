# 099 · E-mail routing: `*@<domain>` to the tau it names

Status: needs-triage
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/spine, tau-net
Blocked by: 092

## What to build

Cloudflare Email Routing delivers mail for the owner's domain to the spine's `email()` handler:

- Mail to the apex goes to a forward address.
- Mail to `tau@<domain>` reaches the owner's tau as untrusted text.

In local mode the spine must not keep mail in clear. It seals the mail to the hub's box key and queues it in the mailbox like an envelope. Decide in triage whether tau may answer mail at all, and at which tier.

## Acceptance criteria

- [ ] A mail to the tau's address arrives at the hub as a sealed mailbox entry and shows up in the owner's channel
- [ ] Senders not on an allowlist are dropped or held for the owner, never answered automatically
- [ ] No mail body is stored unsealed by the spine in local mode

## Blocked by

- [092 · Spine Worker](092-spine-worker.md)

## Comments

- 2026-09-30: filed with ADR 0007.
