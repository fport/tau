# 020 · Memory with Vectorize and a Self-RAG loop

Status: ready-for-agent
Type: AFK
Layer: L3 · Cloud
Packages: cloud/tau-cloud, tau-core
Blocked by: 014

## What to build

`remember` stores a short fact: a D1 row is the source of truth and its Workers AI embedding is upserted into Vectorize immediately. `recall` searches it. The agent runs a Self-RAG loop: decide whether retrieval is needed, retrieve from memory (and KB once #021 exists), grade relevance, and rewrite the query and retry once if results are weak.

## Acceptance criteria

- [ ] A fact remembered in one turn is recallable in the very next turn
- [ ] The grading step filters irrelevant results (test with seeded data)
- [ ] The user can list, edit and delete memories (e.g. `/hafiza`)
- [ ] Embedding model and index dimensions are documented; a re-index command exists

## Blocked by

- [014 · Telegram relay tracer bullet: webhook → Worker → Durable Object → hub → reply](014-telegram-relay-tracer-bullet.md)

## Comments
