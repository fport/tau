# ADR 0006 · Private-first topology

Date: 2026-09-29 · Status: accepted · Supersedes parts of the 2026-09-28 decisions on state, channel ingress, memory, knowledge base and session recording in `docs/ARCHITECTURE.md`.

## Context

tau will be reachable from outside the home as `tau.<domain>` (a web UI on the phone and any
browser), it will speak and listen, and it will be published so other people can install it.
The owner's requirement is privacy first: someone who compromises tau must not reach the
owner's life data (conversations, facts about the user, memory), the machine tau runs on, or
the devices in the home. Cloudflare products are welcome where they add privacy or reach; the
data itself should stay on the local network.

The 2026-09-28 design put state (sessions, settings, memory, knowledge base) in Cloudflare (D1,
R2, Vectorize, AI Search) behind a `tau-cloud` Worker, and routed Telegram through a Worker and
a Durable Object. Both choices put life data and an approval path on public infrastructure.

## Threat model

Assets: `persona/user.md`, sessions and memory (life data); `.env` and other credentials; the
hub machine (shell and file tools later); home devices and the robot (tier-2 tools). Attackers
arrive through (1) a public endpoint, (2) text that talks the agent into misusing its tools
(prompt injection through Telegram, the web UI, fetched pages, tool results), (3) data at rest
in a third party's store. Model inference is out of scope: prompts go to the configured
provider; the mitigation there is data minimization and the `local` role.

## Decision

1. **One public surface, identity at the edge.** Exactly one hostname, `tau.<domain>`, serves
   the hub's own web UI and API. It reaches the hub through **Cloudflare Tunnel** (`cloudflared`
   on the hub, outbound only) and sits behind a **Cloudflare Access** policy (the owner's
   identity: one-time PIN or an IdP; optionally a device rule). Unauthenticated requests never
   reach the tunnel. The hub opens no inbound port, ever. **Tailscale Serve** is the alternative
   and the default when there is no domain: same web UI, tailnet only, no public DNS.
2. **Telegram without a middleman.** The hub polls `getUpdates` directly (outbound); there is
   no webhook, no Worker and no Durable Object in the path. `chat_id` allowlist on the hub.
   While the hub is offline Telegram keeps updates for about a day, so nothing is lost; the
   "tau is offline" auto-reply is dropped (a tiny optional Worker may add it later).
3. **Life data lives on the hub.** Sessions, settings, memory, knowledge base and routines stay
   under `TAU_DATA_DIR` (files and SQLite). Vector search is local (SQLite vectors + a local
   embedding model; the `local` role or an on-device model). Cloudflare receives only
   client-side encrypted backups in a private **R2** bucket (`age`; the key lives on the hub and
   in the owner's password manager, never in Cloudflare). D1, Vectorize and AI Search hold no
   personal data; the `tau-cloud` Worker becomes optional and small.
4. **Settings are local data.** A settings file under `TAU_DATA_DIR`, hot-reloaded by the hub,
   edited through `/settings`, the web UI and TauBar. Never synced to a third party.
5. **Approvals come only from trusted channels.** A tier-2 approval is accepted from the TUI,
   TauBar, the web UI behind Access (with a per-device key) and Telegram polled directly. No
   intermediary server can produce an approval, because no intermediary exists.
6. **Tools assume hostile input.** Every inbound text is untrusted. Shell, file and other write
   tools are tier 2 or sandboxed; web-fetching tools use an allowlist; tools tau writes wait in
   `tools/_pending/` for approval; reflexes never depend on the model. The mesh (Zenoh, MCP)
   and sshd stay tailnet-only.
7. **Voice is a separate package.** `tau-voice` is a hub service and a channel (a
   `tau.hub_services` component): microphone, local speech-to-text (MLX Whisper) and local
   text-to-speech on the hub; nothing leaves the machine before a wake phrase. The TUI shows
   a microphone state and a push-to-talk key only when the service is present and talks to it
   through events. Voice from the phone uses the web UI's microphone; audio travels over the
   tunnel to the hub and is transcribed there, not by a cloud speech API.
8. **Installable by anyone.** The packages are published on PyPI (`tau-core`, `tau-tui`,
   `tau-voice`, `tau-web`, …); the documented install is `uv tool install tau-core --with
   tau-tui` followed by `tau init` and `tau doctor`. Infrastructure steps (Tailscale, Tunnel,
   Access, Telegram bot, R2 backup) are step-by-step guides on the docs site (MkDocs Material)
   and, where a script is safe, `tau setup <thing>` helpers. Nothing personal is ever needed to
   read the docs or run the installer.

## Consequences

- Layer 3 is no longer "Cloud": it is "Access and data" (Tunnel + Access, direct Telegram,
  local state, encrypted backups). Issues 014, 016, 018, 019, 020, 021, 023 are rewritten;
  013 and 022 keep their human steps with a smaller scope; 026 transcribes on the hub.
- The RPi5 as an always-on hub becomes the natural end state; until then the Mac keeps awake
  on AC. Cost stays near zero (Cloudflare Tunnel, Access and R2 free tiers).
- Local state needs a backup discipline: scheduled encrypted backups and a documented restore.
- The web UI is a new package (`tau-web`), served by the hub. First slice: the existing TUI in
  the browser through `textual-serve`, behind Access; a proper web app follows when voice from
  the phone needs the browser microphone.
- A one-shot `tau ask "…"` command exists for scripts and iOS Shortcuts over SSH/Tailscale;
  it never approves tier-2 calls (they are refused with a pointer to a trusted channel).
- Anything that already assumed the Worker (relay, approvals over the relay, cloud sessions)
  is dropped or moved to the hub; ADR 0003's file session store is the record, not a cache.

## Why not

- **Public Worker + Access on the API:** Access protects the front door, but the Worker would
  still hold the approval path and the data; a bug or a leaked token there reaches the home.
- **Everything through Tailscale only:** most private, but the owner wants a browser UI from
  any device and a shareable install for others; Tunnel + Access gives that without opening
  the hub. Tailscale Serve stays as the no-domain default.
- **Cloud vector search (Vectorize, AI Search):** they cannot search encrypted data, so using
  them means storing life data in clear. Local search on a personal corpus is small and fast.

Amended by ADR 0008 (owner guard).
