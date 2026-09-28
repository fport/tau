# L3 · Cloud

**Goal:** Cloudflare becomes tau's durable state and its door to the outside world (Telegram relay, sessions, settings, memory, KB).

**Done when:** Telegram works end to end through the relay (including offline queueing and approvals), and sessions, settings, memory and KB live in Cloudflare.

| # | Issue | Type | Blocked by |
|---|---|---|---|
| 013 | [Create the Telegram bot and a scoped Cloudflare API token](013-telegram-bot-and-cloudflare-token.md) | HITL | – |
| 014 | [Telegram relay tracer bullet: webhook → Worker → Durable Object → hub → reply](014-telegram-relay-tracer-bullet.md) | AFK | 009, 013 |
| 015 | [Hub startup status report on Telegram](015-startup-status-report.md) | AFK | 014 |
| 016 | [Offline queue: "tau is offline" reply and flush on reconnect](016-offline-queue.md) | AFK | 014 |
| 017 | [Tier-2 approvals with Telegram inline buttons](017-telegram-approvals.md) | AFK | 006, 014 |
| 018 | [Session recording in D1 and `/devam` on Telegram](018-session-recording-d1.md) | AFK | 007, 014 |
| 019 | [Settings as data with live reload and `/ayar`](019-settings-as-data.md) | AFK | 014 |
| 020 | [Memory with Vectorize and a Self-RAG loop](020-memory-self-rag.md) | AFK | 014 |
| 021 | [Knowledge base: markdown → R2 → AI Search with `kb_search`](021-knowledge-base-ai-search.md) | AFK | 014 |
| 022 | [Move the getporti domain's DNS to Cloudflare](022-move-dns-to-cloudflare.md) | HITL | – |
| 023 | [Custom domain and Cloudflare Access for tau-cloud](023-custom-domain-and-access.md) | AFK | 014, 022 |

Live status: `python3 roadmap/board.py`
