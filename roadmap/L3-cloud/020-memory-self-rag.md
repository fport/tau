# 020 · Local memory: Strands `MemoryManager` with a tau `MemoryStore` on SQLite + local embeddings

Status: ready-for-agent
Type: AFK
Layer: L3 · Access and data
Packages: tau-core
Blocked by: none

## What to build

Long-term memory stays on the hub (ADR 0006 §3). `TAU_DATA_DIR/memory.sqlite` holds short facts (text, source session, created/updated, tags, embedding blob); vector search is local (cosine over the stored embeddings at first, `sqlite-vec` when the corpus grows) with a local embedding model behind an `Embedder` seam: Ollama through the `local` role when 012 is configured, otherwise an on-device model from an optional extra (`tau-core[memory]`); tests use a deterministic fake. The store reaches the agent through Strands' `MemoryManager` plugin with a tau `MemoryStore` implementation (the decision 070 was filed for; taken by the Memory row of `docs/ARCHITECTURE.md`): relevant memories are retrieved before each model call and injected into the context, new facts are extracted after the turn on the `fast` role. Explicit tools stay for the user: `remember` (tier 1), `recall` (tier 0), and `/memory` lists, edits and deletes (`/memory forget <id>`). The Self-RAG loop: decide whether retrieval is needed, retrieve from memory (and KB once 021 exists), grade relevance, rewrite the query and retry once if results are weak.

Rules folded in from 070: any tool the plugin registers goes through the `ToolCatalog` and the tier gate (fail closed, 064); no retrieval or extraction for reflexes or when the embedder is unavailable (degrade to no injection, never an error); the extra model calls count against the budget (011); the tier gate stays last (`HookOrder.SDK_LAST`, ADR 0005). If the plugin's contract in the pinned strands-agents version does not fit these rules, the explicit tools carry retrieval alone and the reason is recorded in the comments. The embedding model name and dimensions are stored with the index; `tau memory reindex` re-embeds after a model change. The file is part of the encrypted backup (018); nothing reaches Cloudflare in clear.

## Acceptance criteria

- [ ] A fact remembered in one turn is recallable in the very next turn, and is injected before the model call (visible in `FakeModel.calls[i]` in a test)
- [ ] The grading step filters irrelevant results (seeded data test); the re-query happens at most once
- [ ] `/memory` lists, edits and deletes memories in both channels; `remember` is tier 1, `recall` tier 0; any plugin-registered tool is tiered or refused
- [ ] An unavailable embedder or a locked database degrades to no injection with a log line, never a failed turn; reflexes never trigger retrieval
- [ ] Embedding model and dimensions are stored with the index; `tau memory reindex` exists and is idempotent
- [ ] Everything lives in `TAU_DATA_DIR/memory.sqlite`; the only network calls are to the model roles (verified with the fake embedder)

## Blocked by

None - can start immediately; the `local` role (012) is used when configured, the on-device embedder otherwise.

## Comments

- 2026-09-29: reworded `/hafiza` → `/memory` (Turkish alias stays accepted, see 062). Whether the store is exposed to the agent through Strands `MemoryManager` with a tau `MemoryStore` over the Worker is decided in 070 before this starts.
- 2026-09-29: rewritten for ADR 0006 (private-first). Before: a D1 row plus a Vectorize embedding through the `tau-cloud` Worker, blocked by 014. Now: SQLite plus local embeddings on the hub; the `MemoryManager`/`MemoryStore` decision from 070 is taken here (adopted, per the Memory row of `docs/ARCHITECTURE.md`) and 070's evaluation rules are acceptance criteria; 070 is closed as wontfix pointing here. The file keeps its old slug so links stay stable.
