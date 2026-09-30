# L9 · Cloud mode and the tau network

**Goal:** tau runs where its owner wants it and talks to other taus ([ADR 0007](../../docs/adr/0007-cloud-mode-and-tau-network.md)), and opted-in taus show on the public map at `tau.<domain>/universe` ([ADR 0010](../../docs/adr/0010-public-site-and-tau-universe.md)). Local mode stays the private default of ADR 0006. Cloud mode runs the same hub as a Cloudflare Container in the owner's own account. Every tau can have a spine Worker that gives it an address on a federated network of taus, with signed and end-to-end sealed envelopes.

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
| 108 | [Move sessions and network state between local and cloud mode](108-move-between-modes.md) | AFK | 094 |
| 140 | [Public site at `tau.<domain>` with the tau universe page](140-public-site-universe.md) | AFK | – |
| 141 | [tau-net universe client: join, leave, status and hourly reports](141-universe-client.md) | AFK | – |
| 142 | [Spine kit: `tau net spine init\|deploy` from the tau-net wheel](142-spine-kit.md) | AFK | – |
| 143 | [Go live: `tau.getporti.com`, the owner's tau in the universe, the docs](143-go-live-site-and-universe.md) | AFK | 140, 141, 142 |
| 144 | [Docs: build your own tau from zero, verified on a clean home](144-build-your-own-tau-docs.md) | AFK | 141, 142 |
| 145 | [Publish tau-net and tau-cloud on PyPI](145-publish-tau-net-tau-cloud.md) | HITL | 142 |
| 146 | [The public site explains how tau works, in English and Turkish](146-site-how-it-works-bilingual.md) | AFK | – |
| 147 | [The docs site in English and Turkish](147-docs-bilingual.md) | AFK | – |
| 148 | [A README a newcomer understands, in English and Turkish](148-readme-rewrite.md) | AFK | 146, 149 |
| 149 | [Sub-taus: `tau-sub` with drafting, chat, delegation and tools](149-sub-taus.md) | AFK | – |
| 150 | [Public sub-taus over the network and in the universe](150-sub-taus-network-universe.md) | AFK | 149, 105, 146 |
| 151 | [Sub-taus from `tau chat`, the TUI and Telegram: `/sub NAME …`](151-sub-tau-slash-commands.md) | AFK | 149 |
| 152 | [Generated interfaces in the web UI](152-generated-ui.md) | AFK | 074 |
| 153 | [A persistent spend ledger and every provider key in cloud mode](153-cloud-spend-ledger.md) | AFK | 094 |
| 154 | [`tau init` asks for the provider key](154-init-asks-for-the-key.md) | AFK | – |
| 155 | [Handle-based addresses (`host/@handle`) in tau-net and the spine](155-handle-addresses.md) | AFK | – |
| 156 | [`visit` envelopes and web sub-taus on the hub](156-visit-envelopes-and-web-sub-taus.md) | AFK | – |
| 157 | [Handle claims: `tau net universe claim` and the `claim` request](157-universe-handle-claims.md) | AFK | 155 |
| 158 | [The protocol's TypeScript half in `cloud/shared/net`](158-shared-net-typescript.md) | AFK | – |
| 159 | [tau-host: accounts, the brain in a Durable Object and the owner's app](159-tau-host-core.md) | AFK | – |
| 160 | [Universe v3: handles, claims, slugs and the page APIs](160-universe-handles-and-pages-api.md) | AFK | – |
| 161 | [The site opens on the universe: hard theme, characters, person and sub-tau pages](161-site-hard-theme-characters-pages.md) | AFK | – |
| 162 | [Hosted taus on the network and in the universe](162-hosted-taus-on-the-network.md) | AFK | 158, 159 |
| 163 | [Visitors talk to web sub-taus through the universe](163-visitor-chat-relay.md) | AFK | 156, 158, 159, 160 |
| 164 | [Docs, README and site: three ways to start](164-docs-three-ways.md) | AFK | 154, 159, 161 |
| 165 | [Go live: hosted taus on `tau.getporti.com`](165-hosted-go-live.md) | HITL | 159–163 |
| 167 | [One GitHub account with a hosted tau and a hub-run tau: who holds the handle](167-one-handle-two-taus.md) | AFK | 165 |
| 168 | [A claim button in tau-host's app for taus on an own host](168-claim-from-the-host-app.md) | AFK | 162 |

Live status: `python3 roadmap/board.py --layer L9`
