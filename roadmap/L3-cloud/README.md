# L3 · Access and data

**Goal:** tau reachable from anywhere through one private door, with every piece of life data on the hub ([ADR 0006](../../docs/adr/0006-private-first-topology.md)): Cloudflare Tunnel + Access in front of the hub's web UI (Tailscale Serve without a domain), Telegram polled directly by the hub, local settings, memory and knowledge base, and client-side encrypted backups to R2.

**Done when:** Telegram works end to end by direct polling (including inline-button approvals and the startup report), `tau.<domain>` serves the web UI behind Access with no inbound port on the hub, settings, memory and KB live under `TAU_DATA_DIR`, and a scheduled encrypted backup has been restored once in a drill.

The directory keeps its old name `L3-cloud`, and rewritten issues keep their file names, so ids and links stay stable.

| # | Issue | Type | Blocked by |
|---|---|---|---|
| 013 | [Create the Telegram bot and record the allowed chat id](013-telegram-bot-and-cloudflare-token.md) | HITL | – |
| 014 | [Telegram channel by direct polling: `getUpdates` loop on the hub → agent → reply](014-telegram-relay-tracer-bullet.md) | AFK | 013 |
| 015 | [Hub startup status report on Telegram](015-startup-status-report.md) | AFK | 014 |
| 016 | [Offline queue: "tau is offline" reply and flush on reconnect](016-offline-queue.md) *(wontfix)* | AFK | – |
| 017 | [Tier-2 approvals with Telegram inline buttons](017-telegram-approvals.md) | AFK | 006, 014 |
| 018 | [Encrypted backups of `TAU_DATA_DIR` to R2 with a restore drill](018-session-recording-d1.md) | AFK | 081 |
| 019 | [Settings as local data with live reload and `/settings`](019-settings-as-data.md) | AFK | – |
| 020 | [Local memory: Strands `MemoryManager` with a tau `MemoryStore` on SQLite + local embeddings](020-memory-self-rag.md) | AFK | – |
| 021 | [Local knowledge base index and `kb_search`](021-knowledge-base-ai-search.md) | AFK | 020 |
| 022 | [Move the getporti domain's DNS to Cloudflare](022-move-dns-to-cloudflare.md) | HITL | – |
| 023 | [`hub.tau.<domain>` through Cloudflare Tunnel + Access in front of the hub's web UI, Tailscale Serve as the no-domain default](023-custom-domain-and-access.md) | AFK | 022, 074, 076 |
| 068 | [Interrupt-based tier-2 approvals for out-of-process channels](068-interrupt-based-approvals.md) | AFK | 017 |
| 070 | [Long-term memory through Strands `MemoryManager` with a tau `MemoryStore` over the Worker](070-memory-manager-store.md) *(wontfix, folded into 020)* | AFK | – |
| 071 | [Decide `SessionRepository` vs Strands `Storage`/`SnapshotSessionManager` before the D1 backend](071-storage-vs-snapshot-session-manager.md) *(wontfix)* | AFK | – |
| 076 | [`tau setup tunnel` and `infra/tunnel`: cloudflared, Access policy, Tailscale Serve, doctor checks](076-tau-setup-tunnel.md) | AFK | 022, 081 |
| 081 | [Create a Cloudflare token scoped to Tunnel, Access and R2, and the private backup bucket](081-cloudflare-token-and-backup-bucket.md) | HITL | – |
| 090 | [The Telegram poller sometimes needs 30 s to start after a hub restart](090-telegram-poller-slow-start.md) | AFK | – |

Live status: `python3 roadmap/board.py --layer L3`
