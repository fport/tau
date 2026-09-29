# 054 · Show the conversation channel in the dynamic context

Status: ready-for-agent
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: none

## What to build

`persona/persona.md` tells tau to use at most two sentences in notifications and voice replies, but the system prompt never says which channel a conversation is on. `build_agent` receives `channel` (`terminal`, `tui`, later `telegram`, `voice`, `notification`) and does not pass it to `default_context_factory`, so the model cannot tell a voice or notification channel from the terminal and the brevity rule cannot be applied per channel.

Add an optional `channel: str | None` field to `DynamicContext`, rendered as `- Channel: terminal` (`unknown` when None; dynamic-context labels are English, see 062), and pass it from `build_agent`. Tie the brevity rule in `persona.md` to the voice and notification channels.

## Acceptance criteria

- [ ] `DynamicContext` has an optional `channel` field rendered as `- Channel: <name>` / `- Channel: unknown`
- [ ] `build_agent` passes its `channel` argument into the dynamic context; `tau chat` shows `terminal`, `tau tui` shows `tui`
- [ ] `persona/persona.md` ties the "at most two sentences" rule to the voice and notification channels
- [ ] `tests/test_persona.py` covers the rendered line and the `build_agent` wiring with `FakeModel.calls[i].system_prompt`

## Blocked by

None - can start immediately. Touches `agent.py` and `persona.py`, so it must not run in parallel with other work on those files, and it should land before 026/031 (voice) and the first proactive notifications.

## Comments

- 2026-09-29: proposed by the agent that closed #005 (bug found outside its file ownership).
- 2026-09-29: triaged → ready-for-agent. Serial with other `agent.py`/`persona.py` edits (064 touches both); land after 064. Label wording follows the English dynamic-context labels introduced by 062.
