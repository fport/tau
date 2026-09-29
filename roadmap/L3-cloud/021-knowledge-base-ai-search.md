# 021 · Local knowledge base index and `kb_search`

Status: ready-for-agent
Type: AFK
Layer: L3 · Access and data
Packages: tau-core
Blocked by: 020

## What to build

Long-form markdown notes in a `kb/` directory (`[kb] path` in `tau.toml`, default `<home>/kb`, gitignored in this repo) are indexed locally: chunked by heading, embedded with the same `Embedder` seam as memory (020), stored in the same SQLite file (a `kb_chunks` table with file path, heading, content hash, embedding). `tau kb index` is idempotent and incremental (only files whose hash changed are re-embedded; deleted files drop out); the hub re-indexes on an interval or on file change. A `kb_search` tool (tier 0) returns snippets citing file and section; `kb_write` (tier 1) lets tau add or append a note under `kb/tau/` and never touches the user's own files. The Self-RAG loop from 020 retrieves from memory and KB together. No R2, no AI Search: the directory and its index are part of the encrypted backup (018).

## Acceptance criteria

- [ ] A new or changed markdown file is searchable after `tau kb index`, and automatically within the hub's re-index interval
- [ ] `kb_search` returns snippets citing file and heading, ranked by similarity (tests with a seeded `kb/` and the fake embedder)
- [ ] `tau kb index` is idempotent and incremental; unchanged files are not re-embedded and deleted files leave the index
- [ ] `kb_write` is tier 1, writes only under `kb/tau/` and is refused outside it
- [ ] Nothing leaves the hub: no bucket, no cloud index; the tau-core README describes the directory layout and the index

## Blocked by

- [020 · Local memory: Strands `MemoryManager` with a tau `MemoryStore` on SQLite + local embeddings](020-memory-self-rag.md)

## Comments

- 2026-09-29: rewritten for ADR 0006 (private-first). Before: markdown synced to R2 and indexed by Cloudflare AI Search, queried through the Worker, blocked by 014. Now: a local index in the memory database with the same embedder, blocked by 020. The file keeps its old slug so links stay stable.
