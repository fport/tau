# 093 · tau-net: identity, signed and sealed envelopes, contacts, network turns and `tau net`

Status: done
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-net
Blocked by: none

## What to build

A new package `tau-net` (import `tau_net`) that implements the hub side of `docs/reference/tau-network.md` (§1–§3, §6, §7):

- **Crypto and transport:** the Ed25519 + X25519 identity (`TAU_DATA_DIR/net/identity.json` or `TAU_NET_IDENTITY`), signing, verification and sealing of envelopes, and the `SpineClient` that tau-cloud reuses.
- **Contacts:** the contact state machine with key pinning.
- **`net` hub service:** a long poll of the spine that handles each update and then acknowledges it.
- **Network turns:** `persona.md` plus the public note `persona/net.md` in place of `user.md`, no tools, auto-reject approver, the untrusted-text frame, and auto-reply limits.
- **Owner tools:** `net_contacts`, `net_log` and `net_send` (tier 2).
- **CLI:** the `tau net` command group.
- **Test helpers:** `FakeSpine` and `FakeNetwork` in `tau_net.testing`, so two taus can talk in a test without sockets.

## Acceptance criteria

- [x] The §3 test vector verifies; sealing round-trips and any tampering fails
- [x] Two taus over `FakeNetwork`: request, accept, message, bounded auto-reply, log on both sides
- [x] A network turn's system prompt never contains `user.md`; the agent has no tools; `[no reply]`, `max_hops` and the hourly cap stop replies
- [x] `net_send` is tier 2: refused without an approval, sent with a scripted approval, only to accepted contacts
- [x] The service stays idle without spine settings or an identity, never crashes the hub, reports `net` in `/status`
- [x] Workspace tests, ruff and `uv build --package tau-net` pass; `.env.example` and `persona/net.example.md` hold example values only

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: opened with ADR 0007; built together with 092 against the reference page.
- 2026-09-30: done.
  - Commits: ddcc1de..bf1ea57 (package), 2522693 (env names, `persona/net.md` ignore, tau-core discovery tests).
  - 132 tau-net tests pass; the workspace has 952 passed, and the one failure is the pre-existing `login.rs` path, filed by the L2 session.
  - A live exchange between two `wrangler dev` spines worked:
    - the network turn's stored prompt had the injected `<<<END MESSAGE>>>` defused to `‹‹‹END MESSAGE›››`;
    - the `user.md` fact appeared nowhere;
    - `max_hops = 3` stopped the back-and-forth after three replies.
  - Where the reference was silent, the implementation choices are now recorded in `docs/reference/tau-network.md`.
  - Follow-ups: 101 (notifications), 103 (key rotation), 106 (profile in network turns, readable session titles), 107 (doctor hook, inter-process lock).
