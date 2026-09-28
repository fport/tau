# 048 · Move the hub to the RPi5 with self-replication

Status: needs-hardware
Type: needs-hardware
Layer: Backlog
Packages: tau-core, infra
Blocked by: 009, 014, 032

## What to build

With the RPi5 on the tailnet, "tau, hub'ı RPi5'e taşı" provisions it over SSH (uv, tau, systemd unit, zenohd, LiteLLM compose, secrets), hands over the hub role and demotes the MacBook to a node. Every step is tier 2.

## Acceptance criteria

- [ ] Provisioning is idempotent
- [ ] Handover loses no queued messages
- [ ] The MacBook reappears as a node with its `mac.*` tools
- [ ] A rollback path back to the MacBook exists

## Blocked by

- [009 · `tau hub` daemon with launchd service and self-heal](../L1-agent/009-hub-daemon.md)
- [014 · Telegram relay tracer bullet: webhook → Worker → Durable Object → hub → reply](../L3-cloud/014-telegram-relay-tracer-bullet.md)
- [032 · zenohd on the hub, node liveliness and `tau nodes`](../L5-mesh/032-zenoh-router-and-liveliness.md)

## Comments
