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
  Strands behind tau's back) is refused with `'{tool}' aracı kayıtlı değil; çalıştırılmadı.`
  and an `error` event. A failing approver or exemption also rejects.
- Refusals reach the model as the tool result:
  `Kullanıcı bu eylemi onaylamadı: {tool}. Eylemi yapma, kullanıcıya kısaca bildir.`
- **Exemptions** (`(tool, arguments) -> bool`) let registered routines (037) skip per-call
  approval; the exempt call is still recorded with `approval: "exempt"`.
- Approval prompts are serialized per gate, so parallel tool calls never ask at the same time.
- A per-turn loop guard uses Strands `Limits(turns=agent.max_turns)`; hitting it ends the turn
  with a Turkish notice and a `turn_limit` event.

## Why not Strands interrupts (yet)

Interrupts pause the invocation and need the caller to resume it with the answer, which fits
approvals that must survive a restart (a Telegram approval that arrives after the hub was
restarted). For the terminal and the TUI the user answers within the same process, and
`cancel_tool` keeps the loop simple and testable. Revisit when Telegram approvals (017) have to
outlive the process.

## Consequences

- Channels only implement `Approver`; the policy stays in one place.
- Approval timeouts are the gate's job, not the channel's (issue 006 adds `timeout_seconds`
  with `asyncio.wait_for` → `Decision.TIMEOUT`).
- Tool calls are observed authoritatively through `AfterToolCallEvent`; the Strands stream has no
  tool-result event, so UIs read `tool_call` agent events instead.
