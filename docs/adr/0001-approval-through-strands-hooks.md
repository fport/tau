# 0001 · Tier-2 approval through Strands hooks

- Status: accepted (first version, issue 004; refined by issue 006)
- Date: 2026-09-29

## Context

Every tool has a tier (0 read, 1 digital write, 2 physical action or self-written code). Tier-2
calls need an explicit user decision through whichever channel the conversation came from
(terminal, TUI, Telegram, TauBar). The same policy must also serve code that runs outside a
Strands agent loop: the reflex engine (issue 037) and the tau MCP server (issue 028).

Strands Agents offers two ways to stop a tool call: a `BeforeToolCallEvent` hook that sets
`cancel_tool` (the model receives a tool result with `status: "error"` and our text), and the
interrupt API (`event.interrupt(...)`), which suspends the whole invocation until it is resumed
with a response.

## Decision

- **`TierGate`** (in `tau_core.approval`) is the policy. `check(tool, arguments, tool_use_id)`
  returns `(allowed, refusal_text, approval)`; `record(...)` emits a `tool_call` agent event for
  every tier. It knows nothing about Strands and can be called by the reflex engine or the MCP
  server directly.
- **`TierHook`** is a thin Strands adapter: an async `BeforeToolCallEvent` callback asks the gate
  and sets `event.cancel_tool = refusal_text` when the call is not allowed; an
  `AfterToolCallEvent` callback records status, result summary, approval and duration.
- **`Approver`** is a protocol (`name`, `async decide(request) -> Decision`) implemented per
  channel: `TerminalApprover` now, `TuiApprover` (008), Telegram (017), TauBar (025).
- The default approver when a channel supplies none is **`AutoRejectApprover`**. There is no
  approver that approves everything, not even in tests; tests script decisions with
  `ScriptedApprover([Decision.APPROVED])` and assert the recorded requests.
- **Fail closed:** a tool name the catalog does not know (hallucinated, or registered with
  Strands behind tau's back) is refused with `Tool '{tool}' is not registered; it was not run.`
  and an `error` event. A failing approver or exemption also rejects (full list below).
- Refusals reach the model as the tool result:
  `The user did not approve this action: {tool}. Do not perform it; tell the user briefly.`
- **Exemptions** (`(tool, arguments) -> bool`) let registered routines (037) skip per-call
  approval; the exempt call is still recorded with `approval: "exempt"`.
- Approval prompts are serialized per gate, so parallel tool calls never ask at the same time.
- A per-turn loop guard uses Strands `Limits(turns=agent.max_turns)`; hitting it ends the turn
  with a notice in the UI language and a `turn_limit` event.

## Refinements (issue 006)

- **Timeouts.** `TierGate(timeout_seconds=...)` wraps `approver.decide()` in
  `asyncio.wait_for`; when it runs out the question is cancelled and the decision is
  `Decision.TIMEOUT`, which refuses the call with the same refusal text (the approval event and
  the `tool_call` event say `timeout`). When the gate has no timeout, the approver's optional
  `timeout_seconds` attribute applies, so a channel states its natural wait (minutes for a
  Telegram button) without `build_agent` knowing about it; the gate's value wins when both are
  set. The default is no timeout: silence never approves, a timeout only ends the wait.
  `TerminalApprover` has none because `input()` blocks a worker thread that cannot be cancelled
  and would swallow the next line the user types.
- **Everything that fails closed:** an unknown tool; a registered tool whose tier became invalid;
  an approver that raises, is not awaitable or answers anything but a `Decision` value; a
  timeout; an exception inside the gate itself (`TierHook` then cancels the call with the
  refusal text). An exemption that raises counts as "not exempt", so the approver is asked.
- **Exemptions** are consulted only for tier-2 calls to known tools, must return `True` (a
  merely truthy value does not exempt) and receive a copy of the arguments.
  `TierGate.add_exemption()` returns an undo function, the hook the routine registry (037)
  uses at runtime. Exempt calls emit no `approval` event; their `tool_call` event says
  `approval: "exempt"`.
- **What is approved is what runs.** Approval requests, exemptions and events get deep copies of
  the arguments, so nothing that only looks at a call can change the input the tool receives.
  Strands runs the tool with the `tool_use` left by the last `BeforeToolCallEvent` callback, so
  `TierHook` must stay the last registered hook that could rewrite it (`build_agent` registers
  it after the persona hook).
- **The terminal prompt** shows the tool, the arguments as JSON with sorted keys, and the effect
  on one line; control, C1 and bidi/format characters coming from the model are escaped so they
  cannot rewrite or hide the prompt. Only `y`/`yes`/`e`/`evet` (any case, surrounding spaces
  ignored) approves, whatever the UI language.
- **Serialization** is one prompt at a time per gate, with the lock created per event loop so a
  gate outlives the loop it was first used in.
- **Logging:** `tool_call` records log tier 0 at `DEBUG`, tiers 1 and 2 at `INFO` (arguments,
  status, result summary, approval), unknown tools at `WARNING`; approval decisions at `INFO`,
  timeouts at `WARNING`, approver failures at `ERROR`. The `tau chat` file log keeps `INFO`.
- **Registration:** `tau_tool` and `tier_of` refuse booleans and values outside 0-2;
  `ToolCatalog.extend` registers all tools or none.
- **Loop guard:** `[agent].max_turns` counts model calls per user turn; the tools the last
  allowed call requested still run, an answer given on the last allowed call is not cut, and
  the next user turn starts with a fresh budget.

## Why not Strands interrupts (yet)

Interrupts pause the invocation and need the caller to resume it with the answer, which fits
approvals that must survive a restart (a Telegram approval that arrives after the hub was
restarted). For the terminal and the TUI the user answers within the same process, and
`cancel_tool` keeps the loop simple and testable. Revisit when Telegram approvals (017) have to
outlive the process.

## Consequences

- Channels only implement `Approver`; the policy stays in one place.
- Approval timeouts are enforced by the gate; a channel only states how long it is willing to
  wait (`timeout_seconds` on its approver) and must keep `decide()` cancellable.
- Tool calls are observed authoritatively through `AfterToolCallEvent`; the Strands stream has no
  tool-result event, so UIs read `tool_call` agent events instead.

## Amended (2026-09-29, issues 062 and 064)

- The gate texts the model reads are fixed English: `refusal_text` is "The user did not
  approve this action: {tool}. Do not perform it; tell the user briefly." and
  `unknown_tool_text` is "Tool '{tool}' is not registered; it was not run." The user-facing
  notices (turn limit, model error, max tokens, cancelled, throttled, overflow) come from the
  `tau_core.i18n` message table in the UI language (`Config.ui.language`).
- "What is approved is what runs" no longer relies on registration order. `TierHook`
  registers both callbacks with `order=HookOrder.SDK_LAST`, so the `tool_use` the gate sees is
  the one Strands runs, whatever hooks a plugin or `build_agent(hooks=...)` adds. A hook that
  mutates `tool_use["input"]` at any lower order is observed by the approval request; a test
  pins this.
- Plugin-provided tools that are not in the `ToolCatalog` stay refused (fail closed); a
  component that wants its tools to run registers them through `tau.tools`.
- The last consequence above is outdated: tool calls are still observed authoritatively
  through `AfterToolCallEvent` and UIs read `tool_call` agent events, but the claim that the
  Strands stream has no tool-result event is dropped (`tool_stream_event` is mapped to a
  `ToolProgress` turn event).
