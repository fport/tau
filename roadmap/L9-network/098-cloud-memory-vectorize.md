# 098 · Cloud-mode memory: a Vectorize-backed `MemoryStore`

Status: needs-triage
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-cloud, cloud/spine
Blocked by: 020, 094

## What to build

Local memory (020) uses SQLite and local embeddings. In cloud mode the container has no durable disk, so memory needs another home:

- Memory rows go to D1 through the spine.
- Vectors go to a Vectorize index behind the spine, with embeddings from Workers AI or the configured provider.
- The store implements the same `MemoryStore` interface as 020 and is picked by configuration.

It never runs in local mode.

## Acceptance criteria

- [ ] The cloud memory store passes 020's store contract tests against a fake spine
- [ ] `remember` / `recall` work in a cloud-mode tau; deleting a memory removes the row and the vector
- [ ] The Vectorize binding only exists in the cloud configuration

## Blocked by

- [020 · Local memory](../L3-cloud/020-memory-self-rag.md)
- [094 · tau-cloud](094-tau-cloud.md)

## Comments

- 2026-09-30: filed with ADR 0007.
