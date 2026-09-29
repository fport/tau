# 048 · Move the hub to the RPi5 with self-replication

Status: needs-hardware
Type: needs-hardware
Layer: Backlog
Packages: tau-core, infra
Blocked by: 009, 014, 032

## What to build

With the RPi5 on the tailnet, "tau, hub'ı RPi5'e taşı" provisions it over SSH (uv, tau, systemd unit, zenohd, LiteLLM compose, secrets), hands over the hub role and demotes the MacBook to a node. Every step is tier 2. The handover moves everything bound to the hub role: the data dir (restored from the latest encrypted backup, 018, or copied over the tailnet), the Telegram poller (the old hub stops polling before the new one starts: one `getUpdates` consumer per token, 014), the tunnel connector (076) and the backup schedule.

## Acceptance criteria

- [ ] Provisioning is idempotent
- [ ] Handover loses no Telegram updates: the old hub stops polling before the new one starts and the offset moves with the data dir
- [ ] The MacBook reappears as a node with its `mac.*` tools
- [ ] A rollback path back to the MacBook exists

## Blocked by

- [009 · `tau hub` daemon with launchd service and self-heal](../L1-agent/009-hub-daemon.md)
- [014 · Telegram channel by direct polling: `getUpdates` loop on the hub → agent → reply](../L3-cloud/014-telegram-relay-tracer-bullet.md)
- [032 · zenohd on the hub, node liveliness and `tau nodes`](../L5-mesh/032-zenoh-router-and-liveliness.md)

## Comments
- 2026-09-29: rewritten for ADR 0006 (private-first): no relay; the handover moves the data dir, the Telegram poller, the tunnel connector and the backup schedule with the hub role.
