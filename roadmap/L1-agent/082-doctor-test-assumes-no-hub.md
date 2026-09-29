# 082 · `test_doctor_all_green_on_the_test_config` fails while a real hub runs

Status: needs-triage
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: none

## What to build

`tau_core.testing.test_config` fixes `[hub] control_port = 7877`, the default port of a real hub. `test_doctor_all_green_on_the_test_config` asserts `info hub: hub is not running`, so it fails on a machine where `tau hub run` (or the launchd service) is up: the doctor finds the real hub on 7877 and reports `ok hub: hub is running`. Tests should not depend on what else runs on the machine: give the test config a port nothing listens on (or an unused ephemeral one), or make the test tolerate a running hub.

## Acceptance criteria

- [ ] The tau-core suite passes with a real hub running on 7877
- [ ] No test talks to a real hub's control API

## Blocked by

None - can start immediately.

## Comments

- 2026-09-29: found while testing 014 live with a hub running.
