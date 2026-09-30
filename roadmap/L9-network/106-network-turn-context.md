# 106 · Network turns without the owner's profile: a context option in `build_agent`

Status: needs-triage
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-core, tau-net
Blocked by: 093

## What to build

A network turn passes `context_sources=[]`, so live nodes and the budget stay out of the prompt. The `## Now` block still carries the time, the profile (`home`, `travel`, `sport`) and the host role, and "travel" already tells another tau that the owner is away.

Two changes are needed:

- **tau-core:** give `build_agent` (or `PersonaLoader`) an option that drops the profile and the role from `## Now`; the time can stay.
- **tau-net:** use that option for network turns.

Also, the session title of a network turn is currently the first line of the frame. Give it a readable one instead, like `tau network · <name>`.

## Acceptance criteria

- [ ] A network turn's system prompt holds no profile and no role (test with a FakeModel that records the prompt)
- [ ] Owner turns are unchanged
- [ ] Network sessions show a readable title in `/sessions`

## Blocked by

- [093 · tau-net](093-tau-net.md)

## Comments

- 2026-09-30: filed from the 093 report.
