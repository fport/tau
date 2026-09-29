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

- [ ] 1 · No manual history append remains; a failed or cancelled turn is repaired on the next `stream()` through a `list[Message]` prompt; test covers error, turn limit and crash-restored session
- [ ] 2 · Overlapping `stream()` calls yield the "still answering" notice with no `error` event and unchanged history; `asyncio.Lock` serializes channels
- [ ] 3 · An interrupt raised by a test hook is refused inside the same `stream()`; the agent is never left in interrupt state
- [ ] 4 · `MaxTokensReachedException` ends the turn with `stop_reason="max_tokens"` and a `notice` event
- [ ] 5 · `ContextWindowOverflowException` yields its own notice and an `error` event
- [ ] 6 · `to_turn_event` maps `event_loop_throttled_delay`, `reasoningText`, `tool_stream_event` and logs `force_stop_reason`; unit tests pin the keys; channels show "Model is busy, retrying in N s"
- [ ] 7 · `TauAgent.cancel()` delegates to the SDK; `cancelled` is handled like `limit_turns`; the seven stop reasons are documented on `TurnEnd`
- [ ] 8 · `TierHook` uses `HookOrder.SDK_LAST`; the order-90 mutation test passes; ADR 0001 updated
- [ ] 9 · `[agent] context` and `window_size` build the matching conversation manager; `auto`/`agentic` are rejected with `ConfigError`; ADR 0003 updated
- [ ] 10 · `[agent] max_total_tokens` reaches `Limits.total_tokens`; `limit_total_tokens` has its own notice
- [ ] 11 · `build_system_content` returns the three blocks with a `cachePoint`; `PersonaHook` and `build_agent` use it; `cache` role table maps to `CacheConfig`; `FakeModel` receives and ignores it
- [ ] 12 · Tier and effect live in `ToolSpec.annotations["tau"]`; a `@tau_tool` method keeps its tier; test covers the method case
- [ ] 13 · `SequentialToolExecutor` is chosen when a tier-2 tool is registered; `trace_attributes` carries session id, channel and profile
- [ ] 14 · `build_agent` accepts `hooks` and `plugins`; a plugin tool outside the catalog is refused; documented in the tau-core README and ADR 0005
- [ ] `uv run pytest -q`, `uv run ruff check .` and `uv run ruff format --check .` are green; the strands-agents minor version is pinned in `tau-core`'s `pyproject.toml`

## Blocked by

None - builds on 062 (same wave) for notice texts.

## Comments

- 2026-09-29: opened by the 2026-09-29 wave on the user's request (English UI, premium TUI, Strands audit, plug-and-play setup). Spec: wave decisions section 4, verified against `strands-agents` 1.57.1.
