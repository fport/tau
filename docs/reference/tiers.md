# Tiers and approvals

Every tool tau can call declares a **tier**: how much it can change the world. Tier 0 and tier 1 calls run by themselves; a tier 2 call waits for your explicit approval on the channel it came from, every time. Nothing in tau approves on its own, not the model, not a plugin, not a test. The mechanism is [ADR 0001](../adr/0001-approval-through-strands-hooks.md).

## The three tiers

| Tier | Name | Meaning | What happens |
|---|---|---|---|
| 0 | `Tier.READ` | reads, no side effects | runs freely; logged at `DEBUG` |
| 1 | `Tier.DIGITAL_WRITE` | changes digital state: files, notes, messages | runs; logged at `INFO` with arguments and result |
| 2 | `Tier.PHYSICAL` | acts on the physical world, or activates code tau wrote itself | waits for an approval; logged at `INFO` with the decision |

A tool without a tier cannot be registered. The shipped tools are `current_time` (tier 0) and `demo_physical_action` (tier 2, a demo that moves nothing and exists to show the flow).

```python
from tau_core import Tier, tau_tool


@tau_tool(tier=Tier.PHYSICAL, effect="Switches the desk lamp on or off.")
def desk_lamp(state: str) -> str:
    """Switches the desk lamp on or off.

    Args:
        state: "on" or "off".
    """
```

`effect` is the one sentence the approval prompt shows; it defaults to the tool's description. Both are English, because the model reads them.

## The gate

Every call passes `TierGate`, wired into the Strands agent as `TierHook` at `HookOrder.SDK_LAST`, so the `tool_use` the gate sees is the one Strands runs, whatever other hooks rewrote before it.

1. **Unknown tool** (not in the catalog): refused with `Tool '<name>' is not registered; it was not run.` and an `error` agent event. Logged at `WARNING`.
2. **Tier 0 and 1:** allowed.
3. **Tier 2:** allowed when an exemption matches; otherwise the channel's `Approver` decides. Anything but `Decision.APPROVED` refuses the call.
4. **Every call of every tier** emits a `tool_call` agent event: `tool`, `tier`, `arguments`, `status`, `result_summary`, `approval`, `duration_ms`, `tool_use_id`. Every tier-2 question emits an `approval` event.

When any registered tool is tier 2, `build_agent` uses the SDK's sequential tool executor, so two approved physical calls in one model turn never run at the same time. Prompts are asked one at a time.

## What the model sees on refusal

The refusal is the tool result; the turn goes on and the model answers with it in hand:

```text
The user did not approve this action: <tool>. Do not perform it; tell the user briefly.
```

The persona adds its own rule: after a refusal tau reports it briefly and does not try the same action another way. The terminal shows `✗ <tool>: not approved`; the TUI shows the card as rejected.

## Approvers

A channel implements `Approver` (a `name` and `async decide(request) -> Decision`) and passes it to `build_agent`. The request carries `tool`, `tier`, `arguments`, `effect`, `session_id` and `channel`.

| Approver | Channel | Approves on | Timeout |
|---|---|---|---|
| `TerminalApprover` | `tau chat` | `y`, `yes`, `e`, `evet` on stdin, whatever the UI language | none; a blocked `input()` cannot be cancelled |
| `TuiApprover` | `tau tui` | `y`/`e` or the **Approve** button, after the arming delay | none by default |
| `AutoRejectApprover` | the default when a channel passes none | never | – |
| `ScriptedApprover` | tests only | a scripted list of decisions | – |
| `TelegramApprover` | Telegram | the **Approve** inline button, pressed in an allowlisted chat | `approval_timeout_seconds`, then rejected |
| TauBar, web UI | planned (issues 025, 074) | a button on an enrolled device | yes, as rejected |

The terminal prompt:

```text
⚠️  Approval needed (tier 2)
  Tool: demo_physical_action
  Arguments: {"action": "turn on the desk lamp"}
  Effect: Demo: simulates a physical action; no real device moves.
  Approve? [y/N]
```

Arguments are printed as sorted JSON with control and bidirectional characters escaped, so a model cannot hide part of what it asked for.

### The arming delay

The TUI's dialog accepts `y`, `e` and **Approve** only **0.5 seconds** after it opens; the hint reads `(arming…)` until then. Keys typed for the chat, a paste, or a burst over mosh cannot approve by accident. Focus starts on **Reject**, so Enter rejects. The terminal has no such delay because its prompt is a separate `input()` line.

### Timeouts

`TierGate(timeout_seconds=…)` wins; else the approver's own `timeout_seconds`; else none. When the time runs out the question is cancelled and the decision is `timeout`, which refuses the call. Silence never approves. Anything else that is not an explicit approval refuses too: a dialog closed another way, an approver that raises, an invalid answer, a cancelled wait.

## Exemptions

Registered **routines** (the reflex engine, issue 037) must run without a prompt every time they fire. That is what exemptions are for:

```python
agent = build_agent(exemptions=[fn])
undo = agent.gate.add_exemption(fn)
```

`fn(tool_name, arguments)` receives a copy of the arguments and must return `True` to exempt. It is asked only for tier-2 calls to known tools; one that raises does not exempt; the call is still recorded with `approval: "exempt"`. Registering a tier-2 routine needs one approval; its firings do not.

## Rules that never bend

- **Tier-2 actions always go through approval.** Never bypassed, never auto-approved, also in tests: tests script decisions with `ScriptedApprover([Decision.APPROVED])` and simulate silence with `UnansweredApprover`.
- **Approvals come only from trusted channels**: the TUI, TauBar, the web UI behind Access with a per-device key, Telegram polled directly. No intermediary server can produce one, because none exists ([ADR 0006](../adr/0006-private-first-topology.md)).
- **Approval requests carry no jokes.** The persona states what it will do, with which arguments, and the real-world effect, in plain sentences.
- **Robot: simulation by default.** Real mode is an explicit opt-in per session and every motion is tier 2.
- **Tools tau writes itself** land in `tools/_pending/` and wait for approval before they can run (issue 034).
- **Every inbound text is untrusted.** Shell, file and other write tools are tier 2 or sandboxed; fetch tools are allowlisted.

## Agent events and the log

Every decision is on record twice: as an agent event in the session (`events.jsonl`, replayed into the TUI's events pane on `/resume`) and in `<TAU_DATA_DIR>/logs/tau.log`. Tier-0 calls log at `DEBUG` (not in the file unless `-v`), tiers 1 and 2 at `INFO` with arguments, result summary and the approval decision, unknown tools at `WARNING`.

`TierGate.check()` and `record()` do not need Strands, so the reflex engine and the MCP server will use the same policy without an LLM in the loop.
