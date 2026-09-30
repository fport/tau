# 130 · TauBar's login tests trip the "no personal paths" repo rule

Status: needs-triage
Type: AFK
Layer: L4 · Interface
Packages: apps/taubar, tau-core
Blocked by: none

## What to build

`packages/tau-core/tests/test_repo_rules.py::test_no_personal_paths_in_tracked_files` fails on `main`: `apps/taubar/src-tauri/src/login.rs` (from fbe8371) uses `/Users/someone/...` as example paths in its Rust tests. The rule matches any `/Users/<name>` so that a real home directory never lands in a tracked file. Make the two agree, preferably by changing the Rust tests: build the paths from a placeholder the rule already accepts (for example `/path/to/home`), or from a temporary directory.

## Acceptance criteria

- [ ] `uv run pytest -q` has no failure in `test_repo_rules.py`
- [ ] TauBar's `cargo test` still covers the same "installed copy vs. elsewhere" cases
- [ ] The repo rule is not weakened for real home paths

## Blocked by

None - can start immediately

## Comments

- 2026-09-30: found while running the full suite for 010–012; the failure predates that work (it is present at fbe8371).
