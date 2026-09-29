# 064 · Strands-correctness pass over tau-core (strands-agents 1.57.1)

Status: in-progress
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: none

## What to build

An audit of tau-core against the installed SDK (strands-agents 1.57.1) found fourteen places where tau either bypasses the SDK's own mechanism, ignores a stream event or stop reason, or leaves the agent in a state the SDK does not expect. Implement all fourteen, each with tests, after the i18n pass (062) so notice texts go through the message table.

1. `TauAgent.stream()` error path never appends to history by hand: delete `_close_dangling_turn` and the manual `MessageAddedEvent`. At the start of every `stream(prompt)`, if history ends with a `user` message, send a `list[Message]` prompt (`assistant` notice block, then the new `user` message) so the SDK appends both through `_append_messages`. The notice is the last reason kept in `TauAgent._pending_repair`, defaulting to "previous turn did not finish".
2. Catch `strands.types.exceptions.ConcurrencyException` before the generic handler: yield a `Notice` ("I am still answering the previous turn."), no `error` event, no history change; serialize `TauAgent.stream` with an `asyncio.Lock`.
3. Handle `stop_reason == "interrupt"`: read `result.interrupts`, resume once inside the same `stream()` with `interruptResponse` blocks answering `{"tau": "rejected"}`, keep streaming the continuation, yield a `Notice` that an unsupported interrupt was refused and emit an `error` event. Never end `stream()` with the agent in interrupt state. Test with a hook that calls `event.interrupt("x", reason="test")`.
4. `MaxTokensReachedException` → `Notice` (max-tokens text), `notice` event, `TurnEnd(stop_reason="max_tokens")`, no repair.
5. `ContextWindowOverflowException` re-raised by the SDK → specific `Notice` + `error` event.
6. Map ignored stream keys through a pure `to_turn_event(event: dict) -> TurnEvent | None`: `event_loop_throttled_delay` → `Throttled(delay_seconds)`, `reasoningText` → `ReasoningDelta(text)`, `tool_stream_event` → `ToolProgress(tool_use_id, tool, text)`, `force_stop_reason` → warning log. Unit tests pinned to these keys.
7. `TauAgent.cancel()` → `self.agent.cancel()`; `stop_reason == "cancelled"` handled like `limit_turns` (notice + repair next turn). `TurnEnd.stop_reason` values documented: `end_turn`, `limit_turns`, `limit_total_tokens`, `max_tokens`, `cancelled`, `interrupt`, `error`.
8. `TierHook` registers both callbacks with `order=HookOrder.SDK_LAST`; a test proves a hook at order 90 that mutates `tool_use["input"]` is what the approval request sees. ADR 0001 updated (guarantee comes from `HookOrder.SDK_LAST`, not list position; drop the outdated "no tool-result event" sentence).
9. Conversation window explicit: `[agent] context = "sliding" | "summarize"` (default `sliding`), `window_size = 60` → `SlidingWindowConversationManager` / `SummarizingConversationManager`. Never `context_manager="auto"`/`"agentic"` (they register untiered SDK tools). ADR 0003 notes that the store keeps everything while the model sees a window.
10. `[agent] max_total_tokens` (optional) → `Limits(turns=..., total_tokens=...)`; `limit_total_tokens` gets its own notice.
11. System prompt as content blocks for caching: `PersonaLoader.build_system_content(context) -> list[SystemContentBlock]` (`[persona + "## User"]`, `cachePoint`, `["## Now" + context]`) next to the existing `build_system_prompt` string; `PersonaHook` assigns the list; `build_agent` passes it at construction. Optional `[models.roles.<role>] cache = { strategy = "auto" }` → `CacheConfig` for bedrock/anthropic (fake ignores it).
12. Tier metadata in `ToolSpec.annotations["tau"] = {"tier": int, "effect": str | None}` set by `tau_tool`; `tier_of`/`effect_of` read the annotation first, old attributes second, so a `@tau_tool` method on a class keeps its tier through `DecoratedFunctionTool.__get__`. Test the method case.
13. `tool_executor=SequentialToolExecutor()` when any registered tool is tier 2; default otherwise. `trace_attributes={"tau.session_id", "tau.channel", "tau.profile"}`.
14. `build_agent(hooks: Iterable[HookProvider] = (), plugins: Iterable = ())` passthroughs; `TierHook` still wins by order; plugin-provided tools not in the `ToolCatalog` stay refused (fail closed), documented.

Out of scope, filed as follow-ups: 067 (ModelRouter failover), 068 (interrupt-based approvals), 069 (MCP ToolProvider tiers), 070 (MemoryManager store), 071 (Storage vs SnapshotSessionManager), and the OpenAIModel note on 010.

## Acceptance criteria

- [x] 1 · No manual history append remains; a failed or cancelled turn is repaired on the next `stream()` through a `list[Message]` prompt; test covers error, turn limit and crash-restored session
- [x] 2 · Overlapping `stream()` calls yield the "still answering" notice with no `error` event and unchanged history; `asyncio.Lock` serializes channels
- [x] 3 · An interrupt raised by a test hook is refused inside the same `stream()`; the agent is never left in interrupt state
- [x] 4 · `MaxTokensReachedException` ends the turn with `stop_reason="max_tokens"` and a `notice` event
- [x] 5 · `ContextWindowOverflowException` yields its own notice and an `error` event
- [x] 6 · `to_turn_event` maps `event_loop_throttled_delay`, `reasoningText`, `tool_stream_event` and logs `force_stop_reason`; unit tests pin the keys; channels show "Model is busy, retrying in N s"
- [x] 7 · `TauAgent.cancel()` delegates to the SDK; `cancelled` is handled like `limit_turns`; the seven stop reasons are documented on `TurnEnd` (plus an eighth, `busy`, see the comment)
- [x] 8 · `TierHook` uses `HookOrder.SDK_LAST`; the order-90 mutation test passes; ADR 0001 updated
- [x] 9 · `[agent] context` and `window_size` build the matching conversation manager; `auto`/`agentic` are rejected with `ConfigError`; ADR 0003 updated
- [x] 10 · `[agent] max_total_tokens` reaches `Limits.total_tokens`; `limit_total_tokens` has its own notice
- [x] 11 · `build_system_content` returns the three blocks with a `cachePoint`; `PersonaHook` and `build_agent` use it; `cache` role table maps to `CacheConfig`; `FakeModel` receives and ignores it
- [x] 12 · Tier and effect live in `ToolSpec.annotations["tau"]`; a `@tau_tool` method keeps its tier; test covers the method case
- [x] 13 · `SequentialToolExecutor` is chosen when a tier-2 tool is registered; `trace_attributes` carries session id, channel and profile
- [x] 14 · `build_agent` accepts `hooks` and `plugins`; a plugin tool outside the catalog is refused; documented in the tau-core README and ADR 0001 (ADR 0005 is written by issue 065 and should quote the same rule)
- [ ] `uv run pytest -q`, `uv run ruff check .` and `uv run ruff format --check .` are green; the strands-agents minor version is pinned in `tau-core`'s `pyproject.toml` (suite and lint are green; the pin is still `>=1.57` because tightening it re-locks the workspace, which this pass was not allowed to do)

## Blocked by

None - builds on 062 (same wave) for notice texts.

## Comments

- 2026-09-29: all fourteen fixes implemented against strands-agents 1.57.1 (`uv run pytest -q`: 468 passed, up from 403; ruff check and format clean). What changed:
  - `tau_core.agent`: `stream()` rebuilt around a per-loop `asyncio.Lock`, `_build_prompt` (the `[assistant repair, user]` list prompt when the history ends on a user message; `_pending_repair` holds the last notice), a pure `to_turn_event()`, and explicit handling of `ConcurrencyException` (`busy`), `MaxTokensReachedException` (`max_tokens`, `notice` event), `ContextWindowOverflowException` (`error` with `where: context`), `interrupt` (resumed with `{"tau": "rejected"}`, at most 3 times), `cancelled`, `limit_turns` and `limit_total_tokens`. `_close_dangling_turn` and the manual `MessageAddedEvent` are gone. New events `ReasoningDelta`, `ToolProgress`, `Throttled`; `TauAgent.cancel()`; `STOP_REASONS` and `to_turn_event` exported. `build_agent` gained `hooks=`/`plugins=`, `conversation_manager_for(config.agent)`, `SequentialToolExecutor` when a tier-2 tool is present, and `trace_attributes`.
  - `tau_core.approval`: `TierHook` registers both callbacks at `HookOrder.SDK_LAST`.
  - `tau_core.tiers`: `tau_tool` writes `tool_spec["annotations"]["tau"]` through the validated setter; `tier_of`/`effect_of` read it first.
  - `tau_core.config`: `AgentConfig(context, window_size, max_total_tokens)` with validation (`auto`/`agentic` rejected), `RoleConfig.cache` (`strategy`, `ttl`, `system_prompt_ttl`, `tools_ttl`). `tau_core.models`: the cache table becomes `CacheConfig` for bedrock and anthropic.
  - `tau_core.persona`: `build_system_content()` (persona + `## User` | `cachePoint` | `## Now`); `PersonaHook` and `build_agent` use it; `build_system_prompt()` stays.
  - `tau_core.testing`: `FakeCall.system_prompt_content`, `Truncated(text)` reply (streams then stops with `max_tokens`).
  - Terminal channel renders `Throttled` as a dim line and ignores `ReasoningDelta`/`ToolProgress`.
  - Docs: tau-core README (config keys, persona blocks, tiers/annotations, "Turns and stop reasons"), `tau.toml` comments, ADR 0001 and 0003 amended sections.
  - Decisions worth knowing: (a) `busy` is an eighth `TurnEnd.stop_reason`, used only when the SDK's own concurrency guard fires (a caller that bypasses the lock, e.g. from another event loop); the lock itself queues turns instead of dropping them. (b) A cancel during model streaming needs no repair in 1.57.1: the SDK appends its own "Cancelled by user" placeholder (`event_loop.py` appends the message the stop carried); a cancel around tool execution leaves a user message and is repaired like `limit_turns`. (c) The repair notice defaults to `notice.previous_turn_unfinished` for a crash-restored session. (d) `interrupt` remains a documented stop reason for the rare case a hook keeps re-interrupting after being answered.
  - Tests: `test_stream_contract.py` (fixes 1-7, 10), `test_hook_order.py` (8, 13, 14), plus additions in `test_config.py` (9, 10, cache), `test_models.py` (cache → `CacheConfig`), `test_persona.py` (11), `test_tiers.py` (12), `test_agent.py` (conversation managers, window vs store). `test_agent.py::test_model_error_becomes_notice`, `test_approval.py::test_tool_that_lost_its_tier_fails_closed` and `test_persona.py::test_persona_hook_sets_system_prompt` follow the new contracts.

- 2026-09-29 (review round): two reviewers verified the pass against the installed SDK and found six issues, all fixed with regression tests (`uv run pytest -q`: 468 → 482 passed; ruff clean). (1) A crash-restored history ending on an assistant `toolUse` (hub killed while an approval was pending) sent two consecutive user messages: `_build_prompt` now repairs every *dangling* last message (`user`, or `assistant` with a `toolUse`); the SDK inserts its "Tool was interrupted." result first. (2) The interrupt give-up path left the SDK in interrupt state forever (every later prompt failed with "must resume from interrupt"): refusals are now bounded by `[agent] max_turns` instead of 3, the continuation gets the turn's remaining `Limits` budget (turns and total tokens are per SDK invocation), and when refusals do not clear it tau calls `_InterruptState.deactivate()` and repairs next turn; a session restored in interrupt state is cleared the same way at the start of its first turn (`error` event, notice). (3) `TauAgent.cancel()` while idle cancelled the *next* turn (the SDK clears its signal only when an invocation ends): cancel is now a no-op unless a turn is in flight, and a late signal is cleared in the turn's `finally`. (4) A hook registered above `HookOrder.SDK_LAST` ran after the gate and could rewrite or un-cancel an approved call: `build_agent` now checks the registry (`hooks_behind_gate`) and raises `ConfigError`; the After callback records a refused call that ran, or an approved call whose arguments changed, as `error` with an `error` event (`where: tier_gate`) for hooks added after build. (5) The repair notice degraded to the generic text after a sliding-window trim and was dropped by a `busy` turn: "did the SDK append" is decided by identity of the last message, `_pending_repair` is cleared only once the SDK appended, and the session title is written only for a prompt that entered the history. (6) The tool-spec annotation carrying the tier is documented as trusted for in-process tools only (`tiers.py`, ADR 0001, note on 069). ADR 0001 and the README no longer say "resumes once" / "registration order plays no part" without the `SDK_LAST` check; `INTERRUPT_RESUMES` is gone.
- 2026-09-29: opened by the 2026-09-29 wave on the user's request (English UI, premium TUI, Strands audit, plug-and-play setup). Spec: wave decisions section 4, verified against `strands-agents` 1.57.1.
