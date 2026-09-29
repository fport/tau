# 009 · `tau hub` daemon with launchd service and self-heal

Status: in-progress
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: 004

## What to build

`tau hub` runs tau as a long-lived process in the hub role (`TAU_ROLE=hub`), installed as a launchd user agent on macOS, with a systemd unit template for the future RPi5 hub. It restarts on crash and on the next start knows why it died. It exposes a local-only control API (health, status) for TauBar, hooks and other local processes.

## Acceptance criteria

- [ ] `tau hub install|uninstall|status` manages the launchd agent
- [ ] Killing the process relaunches it within seconds; the crash reason shows on the next `status`
- [ ] The control API listens on 127.0.0.1 only and has a health endpoint
- [ ] Only one hub instance can run per machine
- [ ] A systemd unit template exists
- [ ] Tests cover crash-report persistence and the single-instance lock

## Blocked by

- [004 · Tracer bullet: `tau chat` answers in the Jarvis persona](004-tau-chat-tracer-bullet.md)

## Comments
