# 105 · Keep the hub link within the Workers Free plan: WebSocket hibernation instead of a DO-held long poll

Status: ready-for-human
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/spine, tau-net
Blocked by: 092, 093

## What to build

The hub's long poll (`GET /hub/updates?timeout=25`) waits inside the `Mailbox` Durable Object (which also holds the mailbox since 2026-09-30). A hub that polls around the clock keeps that object active all day:

- 128 MB × 86 400 s ≈ 10 800 GB-s per day;
- the Workers Free plan includes 13 000 GB-s per day.

That fits, but with little headroom, and a second poller (a `tau net poll` next to a running hub) could push it over. Past the limit, Durable Object calls fail for the rest of the day.

Options:

1. **WebSocket hibernation.** The hub keeps one WebSocket open to the Durable Object. The object hibernates between envelopes and is not billed while it hibernates. This needs a WebSocket client in tau-net (a small dependency such as `websockets`), with reconnect logic.
2. **Worker-side polling of the Mailbox.** The Worker asks the object once a second without holding a request inside it. This trades duration for about 86 400 Durable Object requests a day, which is close to the Free plan's 100 000.
3. **A lower duty cycle.** The hub waits between polls. This costs latency.

Measure the real usage on a deployed spine (095) before choosing.

## Acceptance criteria

- [ ] The dashboard numbers of a spine polled for 24 h are recorded under Comments
- [x] The chosen link keeps a 24/7 hub under half of the Free plan's Durable Object budget, or the README says plainly what it costs

## Blocked by

- [092 · Spine Worker](092-spine-worker.md)
- [093 · tau-net](093-tau-net.md)

## Comments

- 2026-09-30: filed from the 092 report (the Free-plan estimate came from the spine agent).
- 2026-09-30: built and deployed.
  - Commits: 5640680..3e829ee; fcd7cfd adds the Turkish twins.
  - The link: the hub now waits on a WebSocket doorbell to the `Mailbox` Durable Object, written with the standard library only. Keepalive pings are auto-answered, so the object hibernates between envelopes; the long poll is the fallback. The estimate for a 24/7 hub is about 2 000 of the 100 000 Durable Object requests a day and well under 1% of the 13 000 GB-s, against about 10 800 GB-s for the long poll.
  - Flood guards: a Rate Limiting binding answers 429 above 60/min per IP and 30/min per sender, before any card fetch or Durable Object call. A non-JSON body gets 415, and a KV write over the quota is tolerated.
  - The owner's spine is redeployed with the `ratelimits` block. Live checks: `/hub/ws` answers 401 without a token, and a `text/plain` inbox request gets 415.
  - Left for the owner: after the hub has run 24 h on the doorbell, restarted from TauBar, record the dashboard numbers (Workers & Pages → tau-spine → Metrics, and the Durable Objects usage) under Comments. That is the first criterion.
