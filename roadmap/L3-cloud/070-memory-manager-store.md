# 070 · Long-term memory through Strands `MemoryManager` with a tau `MemoryStore` over the Worker

Status: needs-triage
Type: AFK
Layer: L3 · Cloud
Packages: tau-core, cloud/tau-cloud
Blocked by: 020

## What to build

020 builds memory as two tools (`remember`, `recall`) and a Self-RAG loop. Strands also has a `MemoryManager` plugin that retrieves relevant memories before each model call and stores new ones after the turn, on top of a `MemoryStore` interface. Decide whether tau's memory should be wired through that plugin with a tau `MemoryStore` implementation that talks only to the `tau-cloud` Worker API (D1 row as the source of truth, Vectorize for search, never raw D1 from the hub), so the model gets memories injected automatically instead of having to call `recall`.

Evaluate the plugin against tau's rules: the tier gate must see any tool the plugin registers (fail closed, see 064 item 14), retrieval must not run for reflexes or when the cloud is unreachable, and the budget (011) must count the extra model calls. Then either implement the store and switch 020's retrieval to it, or record why the explicit tools stay.

## Acceptance criteria

- [ ] Decision recorded (ADR or comment) with the plugin's behaviour in strands-agents' pinned version
- [ ] If adopted: a `MemoryStore` over the Worker API passes the plugin's contract tests offline (fake Worker); no D1/Vectorize access from the hub
- [ ] Memories injected before a model call are visible in the system prompt or messages in a `FakeModel` test; an unreachable Worker degrades to no injection, not an error
- [ ] Any tool the plugin registers is tiered or refused; `/memory` (020) still lists, edits and deletes memories

## Blocked by

- [020 · Memory with Vectorize and a Self-RAG loop](020-memory-self-rag.md)

## Comments

- 2026-09-29: filed as a follow-up of the Strands-correctness pass (064); kept out of that wave because it depends on the Worker API from 014/020.
