# 130 · TauBar's login tests trip the "no personal paths" repo rule

Status: done
Type: AFK
Layer: L4 · Interface
Packages: apps/taubar, tau-core
Blocked by: none

## What to build

`packages/tau-core/tests/test_repo_rules.py::test_no_personal_paths_in_tracked_files` fails on `main`: `apps/taubar/src-tauri/src/login.rs` (from fbe8371) uses a made-up home directory under `/Users/` as example paths in its Rust tests. The rule matches any `/Users/<name>` so that a real home directory never lands in a tracked file. Make the two agree, preferably by changing the Rust tests: build the paths from a placeholder the rule already accepts (for example `/path/to/home`), or from a temporary directory.

## Acceptance criteria

- [x] `uv run pytest -q` has no failure in `test_repo_rules.py`
- [x] TauBar's `cargo test` still covers the same "installed copy vs. elsewhere" cases
- [x] The repo rule is not weakened for real home paths

## Blocked by

None - can start immediately

## Comments

- 2026-09-30: found while running the full suite for 010–012; the failure predates that work (it is present at fbe8371).
- 2026-09-30: done while working on 089: the login tests use the placeholder home `/path/to/home`; the same cases (system and per-user Applications, elsewhere, not a bundle) are covered and the rule is untouched.
- 2026-09-30: fixed on the guard/taubar branch alongside 115. `login.rs` builds its test paths from the placeholder home `/path/to/home` (`home.join(...)`), covering the same cases: `/Applications`, `<home>/Applications`, the build folder, a subfolder of `/Applications`, `<home>/Downloads` and a bare binary. This issue's own text no longer quotes a `/Users/<name>` path either (the rule scans every tracked file). The rule in `test_repo_rules.py` is unchanged; `uv run pytest -q` and `cargo test` pass.
