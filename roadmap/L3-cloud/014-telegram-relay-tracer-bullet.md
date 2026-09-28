# 014 · Telegram relay tracer bullet: webhook → Worker → Durable Object → hub → reply

Status: ready-for-agent
Type: AFK
Layer: L3 · Cloud
Packages: cloud/tau-cloud, tau-core
Blocked by: 009, 013

## What to build

The first external channel, end to end. Telegram delivers updates by webhook to the `tau-cloud` Worker. The Worker verifies Telegram's secret token, drops anything that is not from the allowlisted chat, and hands the message to a Durable Object. The hub keeps an outbound, authenticated WebSocket to that Durable Object; the message reaches the hub, the agent answers, and the reply goes back through the relay to Telegram. The hub never opens an inbound port.

## Acceptance criteria

- [ ] A message from the allowlisted account gets a Jarvis reply on Telegram
- [ ] Messages from any other chat are dropped at the Worker and never reach the hub
- [ ] The webhook secret is verified; the hub ↔ Durable Object WebSocket is authenticated
- [ ] The hub reconnects with backoff after network loss
- [ ] Only one hub connection is accepted at a time; a second one is rejected with a clear error
- [ ] The Worker deploys with one command, secrets via `wrangler secret`, tests in the Workers Vitest pool

## Blocked by

- [009 · `tau hub` daemon with launchd service and self-heal](../L1-agent/009-hub-daemon.md)
- [013 · Create the Telegram bot and a scoped Cloudflare API token](013-telegram-bot-and-cloudflare-token.md)

## Comments
