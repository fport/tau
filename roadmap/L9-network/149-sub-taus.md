# 149 · Sub-taus: `tau-sub` with drafting, chat, delegation and tools

Status: in-progress
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-sub
Blocked by: none

## What to build

The local half of ADR 0012, as a new package `tau-sub`:

- **Definitions** in `persona/subs/<name>.md`: TOML front matter followed by the persona text.
- **Commands.** `tau sub new NAME [--describe TEXT]` drafts a sub-tau with the brain; without `--describe` it writes a template. `tau sub list|show|chat|ask|edit|remove` manage and use them.
- **Tools.** `ask_sub` (tier 0) delegates from the main tau; `create_sub` (tier 2) lets the main tau make one.
- **Sessions.** Each sub-tau has its own, on the channel `sub:<name>`.
- **Tier gate.** Every tool a sub-tau calls goes through the gate with the approver of the turn that started it.

## Acceptance criteria

- [ ] `tau sub new coach --describe "…"` with a FakeModel writes a valid definition; the allowlist only names catalog tools
- [ ] `tau sub chat/ask` answer with the sub-tau's persona and tools only; a tier-2 tool asks for approval
- [ ] `ask_sub` from the main tau returns the sub-tau's answer; `create_sub` is refused without approval
- [ ] `persona/subs/` is gitignored; tests and ruff pass; `uv build --package tau-sub` works

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: opened with ADR 0012.
