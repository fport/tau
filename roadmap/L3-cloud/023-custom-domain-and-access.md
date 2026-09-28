# 023 · Custom domain and Cloudflare Access for tau-cloud

Status: ready-for-agent
Type: AFK
Layer: L3 · Cloud
Packages: cloud/tau-cloud
Blocked by: 014, 022

## What to build

Serve the relay at `api.tau.<domain>`, re-point the Telegram webhook, and protect every non-webhook route with Cloudflare Access (service token for the hub; user login for the future dashboard).

## Acceptance criteria

- [ ] The Telegram webhook works on the custom domain
- [ ] Non-webhook routes reject requests without Access credentials
- [ ] The hub authenticates with a service token
- [ ] Configuration lives in the repo (wrangler config / IaC), not only in dashboard clicks

## Blocked by

- [014 · Telegram relay tracer bullet: webhook → Worker → Durable Object → hub → reply](014-telegram-relay-tracer-bullet.md)
- [022 · Move the getporti domain's DNS to Cloudflare](022-move-dns-to-cloudflare.md)

## Comments
