# 018 · Session recording in D1 and `/resume` on Telegram

Status: ready-for-agent
Type: AFK
Layer: L3 · Cloud
Packages: cloud/tau-cloud, tau-core
Blocked by: 007, 014

## What to build

A D1 backend for the session store behind the `tau-cloud` API — the hub never calls the D1 REST API directly. `/sessions` and `/resume` also work from Telegram. Everything is kept permanently.

## Acceptance criteria

- [ ] Sessions from the TUI and from Telegram land in D1 through the Worker API
- [ ] `/sessions` lists and `/resume` resumes sessions on Telegram
- [ ] Switching between file and D1 backends is config only
- [ ] D1 migrations are versioned in the repo
- [ ] The Worker API requires authentication

## Blocked by

- [007 · Session persistence and `/devam` resume](../L1-agent/007-session-persistence-resume.md)
- [014 · Telegram relay tracer bullet: webhook → Worker → Durable Object → hub → reply](014-telegram-relay-tracer-bullet.md)

## Comments

- 2026-09-29: reworded `/devam` → `/resume` (Turkish aliases stay accepted, see 062). Backend choice (D1-backed `SessionRepository` vs Strands `Storage`/`SnapshotSessionManager`) is decided in 071 before this starts.
