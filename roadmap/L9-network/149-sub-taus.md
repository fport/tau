# 149 · Sub-taus: `tau-sub` with drafting, chat, delegation and tools

Status: done
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

- [x] `tau sub new coach --describe "…"` with a FakeModel writes a valid definition; the allowlist only names catalog tools
- [x] `tau sub chat/ask` answer with the sub-tau's persona and tools only; a tier-2 tool asks for approval
- [x] `ask_sub` from the main tau returns the sub-tau's answer; `create_sub` is refused without approval
- [x] `persona/subs/` is gitignored; tests and ruff pass; `uv build --package tau-sub` works

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: opened with ADR 0012.
- 2026-09-30: done.
  - Commits: f889cdd (gitignore), 3c29cc4, 62d4b31, f3971c5, a0c03e3 (workspace, plus the tau-core discovery test disabling `dist:tau-sub`).
  - Definitions are `persona/subs/<name>.md` with TOML front matter between `+++` lines. The prompt is rendered into `TAU_DATA_DIR/subs/<name>/persona.md` and read with `PersonaLoader`, so tau-core is unchanged.
  - `ask_sub` finds the calling turn's approver through the agent's tier hook (Strands `ToolContext`), wraps it so the owner sees "/coach, a sub-tau your tau asked, wants to: …", and refuses tier 2 when no gate is found.
  - Tests: 103 for tau-sub; the workspace has 1246 passed, and the one failure is the known `login.rs` path.
- 2026-09-30: for 150, cloud mode needs `tau-sub` in the brain image and `persona/subs/*.md` in `tau cloud push|pull`.
