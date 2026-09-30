# ADR 0007 · Cloud mode and the tau network

Date: 2026-09-30 · Status: accepted · Amends [ADR 0006](0006-private-first-topology.md): §3 ("life data lives on the hub") becomes the default of two deployment modes, and taus gain a way to talk to each other. Every other rule of 0006 stands.

## Context

Two wishes from the owner, on top of the private-first design of ADR 0006:

1. **Anyone can run a tau without a machine at home.** Someone who installs tau should be able to deploy it into their own Cloudflare account and talk to it from Telegram, with nothing running on their laptop.
2. **Taus talk to each other.** My tau can ask your tau when you are free, and the two can exchange a few messages on our behalf.

The private default must survive both: a tau that runs at home keeps its life data at home, and joining the network must not put that data, or an approval path, on public infrastructure.

## Decision

1. **Two deployment modes, the same code.**
   - **Local** (default): the hub runs on the owner's machine and ADR 0006 applies unchanged. Life data stays under `TAU_DATA_DIR`.
   - **Cloud** (opt-in): the same Python hub (`tau hub run`) runs as a **Cloudflare Container** that the owner's spine Worker manages, in the owner's own Cloudflare account. Its life data lives in that account: sessions and small state in **D1**, persona files and `tau.toml` in **KV**, media later in **R2**. Choosing cloud mode means the owner accepts that Cloudflare stores this data under its own at-rest encryption, not the owner's key. Nothing moves to Cloudflare until the owner deploys the cloud configuration and runs `tau cloud push`. No code path in local mode copies life data to Cloudflare.
2. **The spine.** Every tau that joins the network has one Worker, `tau-spine` (`cloud/spine`), in its owner's account. The spine's hostname is the tau's **address**. It serves the tau's public **card** and a **mailbox**.
   - In local mode the spine only stores and forwards. It keeps sealed envelopes until the hub acknowledges them, and remembers envelope ids for a day to stop replays. It holds no contacts and no plaintext, and it cannot approve anything. The hub reaches it outbound with a long poll, so the hub still opens no inbound port.
   - In cloud mode the spine also hosts the brain container and the store API it uses (D1, KV).
3. **A federated network, like e-mail.** No central server exists. A tau's card at `https://<address>/.well-known/tau.json` publishes an Ed25519 signing key and an X25519 box key. Every **envelope** is signed by the sender and sealed end to end to the recipient's box key (X25519 + HKDF-SHA256 + ChaCha20-Poly1305). The receiving spine verifies the signature as a spam filter. The receiving hub verifies it again and is the only party that can open the box. The keys live on the hub (`TAU_DATA_DIR/net/identity.json`); in cloud mode they live in a Worker secret handed to the container.
4. **Contacts gate the brain.** Only accepted **contacts** reach the model. A contact request waits until the owner accepts it through a trusted channel (`tau net accept`; later the TUI, TauBar and Telegram). The contact's keys are pinned on acceptance, and a key change is refused, never followed silently.
5. **Network turns are narrow.** A message from a contact runs as a **network turn**, in a separate session per contact, with a reduced agent:
   - The prompt holds `persona.md` plus the owner's public note (`persona/net.md`) in place of `user.md`.
   - The agent has no tools and every approval is refused, so a network turn can never run a tier-2 action.
   - The incoming text is framed as untrusted.
   - Auto-replies are bounded by a reply depth (`hops`) and a per-contact hourly cap, so two taus cannot loop forever.

   The owner's own agent reaches the network through three tools:
   - `net_contacts` and `net_log` (tier 0).
   - `net_send` (tier 2). It speaks for the owner to a third party, so it needs an approval like a physical action does.
6. **Deploying stays reproducible and personal-data free.**
   - `cloud/spine` tracks example configurations without resource ids, and `pnpm run configure` writes the gitignored `wrangler.jsonc`.
   - `pnpm dev` runs the spine locally (Miniflare keeps KV and the Durable Object on disk). `pnpm run deploy` lets Wrangler provision KV on the first deploy. In local mode the mailbox lives in the SQLite-backed `Mailbox` Durable Object and the spine needs no D1, because the Workers Free plan allows only 10 D1 databases per account (amended 2026-09-30); cloud mode adds D1 for its store.
   - Local mode fits the Workers Free plan. Cloud mode needs Workers Paid for Containers, and Docker to build the image.

## Consequences

- The CLAUDE.md state rule becomes: local mode is the default and keeps ADR 0006. Cloud mode is an explicit deployment by the owner. In local mode, D1, KV and Vectorize hold no personal data; the spine's mailbox holds only sealed envelopes in transit.
- New components: `tau-net` (identity, envelopes, contacts, the `net` hub service, tools, `tau net`) and `tau-cloud` (the `spine` session backend, `tau cloud push|pull|status|run`), plus the TypeScript project `cloud/spine`. `cloud/spine` replaces the planned `cloud/tau-cloud` offline-notice Worker.
- New glossary terms: deployment mode, spine, address, card, envelope, contact, mailbox, network turn.
- Telegram in cloud mode: the poller runs inside the container (outbound), and the spine's cron keeps the container awake. A webhook path that lets the container sleep is a follow-up issue.
- Memory and KB in cloud mode need a Vectorize-backed store once local memory (020) exists. E-mail routing (`*@domain` → a tau), voice calls through a Durable Object and R2 media are follow-up issues.
- Cost:
  - The local-mode spine stays within the Workers Free plan (a few requests per minute).
  - Cloud mode costs Workers Paid ($5/month) plus container time. A container kept awake is billed for its memory the whole month.

## Why not

- **A central directory or relay** (one "tau-net" Worker everyone registers with): one operator would see every conversation's metadata, and one outage would stop the whole network. Federation costs a card fetch per new sender and nothing else.
- **A second brain in TypeScript** (Cloudflare Agents SDK in a Durable Object): it runs on the Free plan, but the tier gate, the approval rules and the persona would exist twice and drift. The container runs the code that is already tested.
- **Plain-text messages through the spines**: a compromised spine or a leaked Cloudflare token would expose every conversation. Sealing is a few lines of code with `cryptography` on the hub, and the spine never needs the plaintext.
- **A WebSocket from the hub to the spine**: it needs a new dependency and reconnect logic. A long poll mirrors the Telegram poller the hub already runs, and a Durable Object wakes the waiting poll when mail arrives.
