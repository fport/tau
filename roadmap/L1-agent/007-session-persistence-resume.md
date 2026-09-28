# 007 · Session persistence and `/devam` resume

Status: ready-for-agent
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: 004

## What to build

Conversations are recorded as sessions — messages, tool calls, approvals — through a pluggable session store. The first backend writes local files. `/devam` lists recent sessions and resumes one with full context. The store interface must allow the D1 backend (#018) without touching callers.

## Acceptance criteria

- [ ] Quit and restart `tau chat`; `/devam` resumes the last session with context intact
- [ ] Session records include tool calls and approval decisions
- [ ] The backend is chosen by config; the file backend is just one implementation
- [ ] Nothing is deleted automatically (retention: keep everything)
- [ ] Tests cover record and resume

## Blocked by

- [004 · Tracer bullet: `tau chat` answers in the Jarvis persona](004-tau-chat-tracer-bullet.md)

## Comments
