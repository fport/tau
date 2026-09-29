# 082 · `test_doctor_all_green_on_the_test_config` fails while a real hub runs

Status: needs-triage
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: none

## What to build

`tau_core.testing.test_config` fixes `[hub] control_port = 7877`, the default port of a real hub. `test_doctor_all_green_on_the_test_config` asserts `info hub: hub is not running`, so it fails on a machine where `tau hub run` (or the launchd service) is up: the doctor finds the real hub on 7877 and reports `ok hub: hub is running`. Tests should not depend on what else runs on the machine: give the test config a port nothing listens on (or an unused ephemeral one), or make the test tolerate a running hub.

## Acceptance criteria

- [x] The tau-core suite passes with a real hub running on 7877
- [ ] No test talks to a real hub's control API

## Blocked by

None - can start immediately.

## Comments

- 2026-09-29: found while testing 014 live with a hub running.
- 2026-09-30: hit again while working on 084 with the live hub up. Commit 297b0bc points this one test at a port nothing listens on (`TAU_HUB_PORT`), and the tau-core suite passes with the real hub on 7877 (611 passed). Not done: `test_config` still fixes `control_port = 7877`, so other tests that probe `/health` (the `/status` command, `tau doctor` without an override) may still reach a live hub; they pass either way, but the second criterion needs an audit or an unused port in `test_config`. Left for triage.
