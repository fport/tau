# 006 · Tool permission tiers with approval and a loop guard

Status: done
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: 004

## What to build

Every tool declares a tier: 0 read, 1 digital write, 2 physical action or self-written code. Tier 0 runs freely, tier 1 runs and is logged, tier 2 waits for an approval through a channel-agnostic approval interface. The terminal channel implements it as a prompt showing tool, arguments and expected effect. A per-turn tool-iteration guard stops runaway loops. Leave a hook so registered routines (#037) can be exempt from per-call approval.

## Acceptance criteria

- [x] A tool without a declared tier cannot be registered
- [x] A tier-2 call in `tau chat` shows an approval prompt; rejecting returns a clean refusal to the model
- [x] Every tier-1 and tier-2 call is logged with arguments, result summary and approval decision
- [x] Approval is an interface that other channels (Telegram #017, TauBar #025) can implement
- [x] The iteration guard is configurable; hitting it ends the turn with a Turkish explanation
- [x] Tests cover each tier path and the guard

## Blocked by

- [004 · Tracer bullet: `tau chat` answers in the Jarvis persona](004-tau-chat-tracer-bullet.md)

## Comments

### 2026-09-29 · done (agent)

Hardened the tier gate built in 004 and covered it with tests. `uv run ruff check . && uv run ruff format --check . && uv run pytest -q` is green offline.

- `TierGate(timeout_seconds=...)` waits with `asyncio.wait_for`; on expiry the question is cancelled and the decision is `timeout` (refused with the usual refusal text). Without a gate timeout the approver's optional `timeout_seconds` attribute applies, so a channel sets its own wait without `build_agent` changes. `TerminalApprover` has none (a blocked `input()` cannot be cancelled). Default: no timeout.
- Fail closed everywhere: unknown tools, tools whose tier became invalid, approvers that raise, are not awaitable or answer anything but a `Decision` value, timeouts, and an exception inside the gate (`TierHook` then cancels the call). A raising exemption counts as "not exempt".
- Exemptions are asked only for tier-2 calls to known tools, must return `True`, and get a deep copy of the arguments; `TierGate.add_exemption(fn)` returns an undo function (the runtime hook for #037). Approval requests and events also get deep copies, so an approver cannot change what runs.
- The terminal prompt escapes control, C1 and bidi characters from the model's arguments and keeps the effect on one line; only `e`/`evet` approves.
- The approval lock is per event loop (a shared `asyncio.Lock` breaks when a gate is reused in a new loop under contention).
- `tau_tool`/`tier_of` refuse bools and out-of-range tiers; `ToolCatalog.extend` is all-or-nothing.
- Log levels: tier 0 `DEBUG`, tiers 1-2 `INFO` with arguments, result summary and approval, unknown tools `WARNING`, timeouts `WARNING`, approver failures `ERROR`.
- `tau_core.testing` gained `UnansweredApprover` (never answers; for timeout tests) and `record_events(bus, *kinds)`.
- Tests: `test_tiers.py` (declarations, catalog, every tier path through `build_agent`), `test_approval.py` (the gate without Strands, approvers, timeouts, exemptions, the terminal prompt with a fake input function, log levels), `test_loop_guard.py` (configured from `tau.toml`, exact call count, notice, `turn_limit` event in the session record, fresh budget per turn, repeated tier-2 calls). README `## Tiers and approval` and ADR 0001 describe the result.

Criteria notes: the `tau chat` prompt itself is exercised end to end by `test_cli.py` (004); this issue tests `TerminalApprover` directly.

Found outside this issue's files and fixed at merge time (`fix(core): keep the history alternating after the loop guard trips`): after the loop guard tripped, `TauAgent.stream` left the history ending with a user `toolResult` message, so the next prompt sent two user messages in a row, which the Bedrock Converse API rejects. `agent.py` now closes the turn with the notice as an assistant message; `test_loop_guard.py::test_history_stays_alternating_after_the_guard` is a regular passing test (the strict xfail marker is gone). `Config.load` now also rejects `max_turns = true`.

Deviations from the brief (all additive): the approver `timeout_seconds` fallback, `TierGate.add_exemption()`/`effective_timeout()`, `TerminalApprover.timeout_seconds = None`, exemptions must return `True`, and the two testing helpers. Commit trailers use the attribution line this session's environment specifies.

Commits:
- `docs(roadmap): start 006`
- `feat(core): harden the tier gate and the approval prompt`
- `test(core): cover tier declarations, the catalog and every tier path`
- `test(core): cover the approval gate, timeouts and the terminal prompt`
- `test(core): cover the per-turn loop guard`
- `docs(core): document tiers and approval, refine ADR 0001`
- `docs(roadmap): close 006`

For later issues:
- 008 (TUI): `TuiApprover.decide` awaits a Future; if it sets `timeout_seconds`, cancelling that await must close the modal. Tests can use `ScriptedApprover`, `UnansweredApprover` and `record_events`.
- 017/025 (Telegram, TauBar): implement `Approver` (`name`, async `decide`), set `timeout_seconds` on the approver, keep `decide` cancellable; the `approval` event's `channel` is `approver.name`, `ApprovalRequest.channel` is the conversation channel.
- 028 (MCP server) and 037 (reflexes): call `TierGate.check()`/`record()` directly; routines register with `gate.add_exemption(fn)`.
- Keep `TierHook` the last `BeforeToolCallEvent` hook that could rewrite `tool_use`: Strands runs the tool with the `tool_use` left by the last callback.
