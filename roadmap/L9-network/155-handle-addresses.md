# 155 · Handle-based addresses (`host/@handle`) in tau-net and the spine

Status: ready-for-agent
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-net, cloud/spine
Blocked by: –

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §3. The address grammar widens to `host[:port]` **or** `host[:port]/@handle` (handle `^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$`). Card and inbox URLs are `<scheme>://<address>/.well-known/tau.json` and `<scheme>://<address>/net/inbox`. Sub-tau targets `<address>/<name>` must parse unambiguously with both forms (names never start with `@`; reserved sub names `net`, `app`, `api`, `auth`, `claim`, `hub` are refused by tau-sub). The spine accepts such addresses in `from` (it fetches the sender's card at the longer URL); a spine's own address stays a plain host. Regenerate the spine kit.

## Acceptance criteria

- [ ] tau-net: address parsing/validation, card fetch, send, contacts and `tau net send/add` work with `tau.example.com/@alice` and `tau.example.com/@alice/coach`
- [ ] cloud/spine: `address.ts` and the inbox checks accept path senders; vitest covers both forms and bad ones (`/@`, `/@Upper`, `/@a/b/c`)
- [ ] tau-sub refuses the reserved names
- [ ] `docs/reference/tau-network.md` §1 and §3 describe the grammar; kit regenerated and its freshness check passes

## Blocked by

None.

## Comments

- 2026-09-30: filed with ADR 0013.
