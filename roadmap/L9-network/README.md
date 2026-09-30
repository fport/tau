# L9 · Cloud mode and the tau network

**Goal:** tau runs where its owner wants it and talks to other taus ([ADR 0007](../../docs/adr/0007-cloud-mode-and-tau-network.md)). Local mode stays the private default of ADR 0006. Cloud mode runs the same hub as a Cloudflare Container in the owner's own account. Every tau can have a spine Worker that gives it an address on a federated network of taus, with signed and end-to-end sealed envelopes.

**Done when:**

- Two taus on two deployed spines exchange messages and auto-replies within the limits.
- One tau runs in cloud mode, answers on Telegram and keeps its sessions across a container restart.
- Both setups are documented step by step on the docs site with example values only.

Protocol and API: [`docs/reference/tau-network.md`](../../docs/reference/tau-network.md).

| # | Issue | Type | Blocked by |
|---|---|---|---|
| 092 | [Spine Worker: card, sealed mailbox and hub long poll, locally and deployed](092-spine-worker.md) | AFK | – |
| 093 | [tau-net: identity, signed and sealed envelopes, contacts, network turns and `tau net`](093-tau-net.md) | AFK | – |
| 094 | [tau-cloud: the hub in a Cloudflare Container with the spine store](094-tau-cloud.md) | AFK | 092, 093 |
| 095 | [Deploy your spine and exchange a first message with another tau](095-deploy-spine-live.md) | HITL | 092, 093 |
| 096 | [Run tau in cloud mode live: Workers Paid, image build, secrets, Telegram from the container](096-cloud-mode-live.md) | HITL | 094 |
| 097 | [Telegram in cloud mode through a webhook on the spine, so the container can sleep](097-cloud-telegram-webhook.md) | AFK | 094 |
| 098 | [Cloud-mode memory: a Vectorize-backed `MemoryStore`](098-cloud-memory-vectorize.md) | AFK | 020, 094 |
| 099 | [E-mail routing: `*@<domain>` to the tau it names](099-email-routing.md) | AFK | 092 |
| 100 | [Voice calls in cloud mode through a Durable Object](100-cloud-voice.md) | AFK | 075, 094 |
| 101 | [Contact requests and network messages reach the owner in the TUI, TauBar and Telegram](101-network-notifications.md) | AFK | 093 |
| 102 | [Deploy a spine without cloning the repo](102-spine-without-clone.md) | AFK | 078, 092 |
| 103 | [Card key rotation and contact re-keying](103-key-rotation.md) | AFK | 093 |
| 104 | [R2 media store in cloud mode](104-cloud-media-r2.md) | AFK | 094 |
| 105 | [Keep the hub link within the Workers Free plan: WebSocket hibernation instead of a DO-held long poll](105-spine-free-plan-link.md) | AFK | 092, 093 |
| 106 | [Network turns without the owner's profile: a context option in `build_agent`](106-network-turn-context.md) | AFK | 093 |
| 107 | [`tau doctor` checks from components](107-component-doctor-checks.md) | AFK | 093 |

Live status: `python3 roadmap/board.py --layer L9`
