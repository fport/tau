# 155 · Handle-based addresses (`host/@handle`) in tau-net and the spine

Status: done
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-net, cloud/spine
Blocked by: –

## What to build

[ADR 0013](../../docs/adr/0013-hosted-taus-handles-and-public-pages.md) §3. The address grammar widens to `host[:port]` **or** `host[:port]/@handle` (handle `^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$`). Card and inbox URLs are `<scheme>://<address>/.well-known/tau.json` and `<scheme>://<address>/net/inbox`. Sub-tau targets `<address>/<name>` must parse unambiguously with both forms (names never start with `@`; reserved sub names `net`, `app`, `api`, `auth`, `claim`, `hub` are refused by tau-sub). The spine accepts such addresses in `from` (it fetches the sender's card at the longer URL); a spine's own address stays a plain host. Regenerate the spine kit.

## Acceptance criteria

- [x] tau-net: address parsing/validation, card fetch, send, contacts and `tau net send/add` work with `tau.example.com/@alice` and `tau.example.com/@alice/coach`
- [x] cloud/spine: `address.ts` and the inbox checks accept path senders; vitest covers both forms and bad ones (`/@`, `/@Upper`, `/@a/b/c`)
- [x] tau-sub refuses the reserved names
- [x] `docs/reference/tau-network.md` §1 and §3 describe the grammar; kit regenerated and its freshness check passes

## Blocked by

None.

## Comments

- 2026-09-30: filed with ADR 0013.
- 2026-09-30: done. As built:
  - Grammar (tau-net `tau_net.encoding`, the spine's `src/address.ts`, the same as `cloud/shared/net`): host `^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*(:[0-9]{1,5})?$`, handle `^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$`, address = host + optional `/@handle`; a host part over 260 characters is refused. tau-net adds `HOST_PATTERN`, `HANDLE_PATTERN`, `is_valid_host`, `validate_host`, `parse_host`, `split_address`, `handle_of`, `RESERVED_SUB_NAMES`; `host_of` strips port and handle; `base_url` keeps the path (`https://tau.example.com/@alice`).
  - `parse_target` takes `host[/@handle][/name]`; anything after the name, and a reserved name (`net`, `app`, `api`, `auth`, `claim`, `hub`), is refused. tau-sub refuses the reserved names in `validate_name` (a file with one is listed as broken and never public).
  - A universe host (`[component.net] universe`, `UniverseClient`, `FakeUniverse`) and a spine address (`tau net spine init --address`) must be plain hosts. `UniverseClient.tau(address)` percent-encodes `/` and `@` in `GET /api/taus/<address>`.
  - `tau_net.testing`: `FakeNetwork` routes `/@handle` paths to a `FakeSpine` whose address has that handle (a stand-in for tau-host); `route_key(url)` is public.
  - Spine: `tau-spine` 0.2.0 (package.json and `VERSION`), kit `0.2.0+34aba9917da1`. `from` may be a handle address (card fetched under its path, KV cache key `peer:<full address>`); the spine's own address stays a plain host, so a handle recipient is `wrong_recipient`.
