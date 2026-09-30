# 153 · A persistent spend ledger and every provider key in cloud mode

Status: needs-triage
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-cloud, tau-core, cloud/spine
Blocked by: 094

## What to build

ADR 0011 moved budgets into tau-core, with a SQLite ledger at `TAU_DATA_DIR/spend.sqlite3`. In cloud mode, `TAU_DATA_DIR` is the container's `/data`, which is lost on every restart, so a restart forgets the day's and the month's spend and the budget starts from zero. Two fixes:

1. **Keep the ledger across restarts.** Options:
   - the spend rows through the spine's state or D1 routes, behind a ledger interface in tau-core;
   - a periodic snapshot of the ledger into the spine state, restored at `tau cloud run`.

   Decide and build one.
2. **Pass the new provider keys to the brain container.** Its pass-through list in `cloud/spine/src/brain.ts` knows only Anthropic and AWS. Add `OPENAI_API_KEY`, `GEMINI_API_KEY` and `GOOGLE_API_KEY`, update the cloud-mode guide's secrets table, and regenerate the spine kit.

## Acceptance criteria

- [ ] A container restart keeps the spend of the day and the month; a budget reached before the restart is still reached after it
- [ ] The container receives OpenAI and Gemini keys when set; the guide lists them

## Blocked by

- [094 · tau-cloud](094-tau-cloud.md)

## Comments

- 2026-09-30: filed from the L2 session's note on ADR 0011 (the ledger lives in `TAU_DATA_DIR`).
