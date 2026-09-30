# 105 · Keep the hub link within the Workers Free plan: WebSocket hibernation instead of a DO-held long poll

Status: needs-triage
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/spine, tau-net
Blocked by: 092, 093

## What to build

The hub's long poll (`GET /hub/updates?timeout=25`) waits inside the `HubSignal` Durable Object. A hub that polls around the clock keeps that object active all day:

- 128 MB × 86 400 s ≈ 10 800 GB-s per day;
- the Workers Free plan includes 13 000 GB-s per day.

That fits, but with little headroom, and a second poller (a `tau net poll` next to a running hub) could push it over. Past the limit, Durable Object calls fail for the rest of the day.

Options:

1. **WebSocket hibernation.** The hub keeps one WebSocket open to the Durable Object. The object hibernates between envelopes and is not billed while it hibernates. This needs a WebSocket client in tau-net (a small dependency such as `websockets`), with reconnect logic.
2. **Worker-side D1 polling.** The Worker checks D1 about once a second inside the request and uses no Durable Object at all. This costs D1 reads (about 86 400 small queries a day) instead of Durable Object duration.
3. **A lower duty cycle.** The hub waits between polls. This costs latency.

Measure the real usage on a deployed spine (095) before choosing.

## Acceptance criteria

- [ ] The dashboard numbers of a spine polled for 24 h are recorded under Comments
- [ ] The chosen link keeps a 24/7 hub under half of the Free plan's Durable Object budget, or the README says plainly what it costs

## Blocked by

- [092 · Spine Worker](092-spine-worker.md)
- [093 · tau-net](093-tau-net.md)

## Comments

- 2026-09-30: filed from the 092 report (the Free-plan estimate came from the spine agent).
