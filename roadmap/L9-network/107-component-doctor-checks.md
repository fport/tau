# 107 · `tau doctor` checks from components

Status: needs-triage
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-core, tau-net, tau-cloud
Blocked by: 093

## What to build

`run_doctor` has a hard-coded Telegram check. tau-net has a Telegram-style `doctor_check(config, env, hub_status)`, but `tau doctor` cannot reach it, so `tau net status` prints it itself.

Give components a public hook: an attribute on the `tau.hub_services` factory, or a `tau.doctor` entry-point group. `tau doctor` then shows the checks of the net service (identity, spine, card) and of cloud mode (spine mode, brain) next to the built-in ones.

Two small inter-process issues belong in the same pass:

- The tau-net file store locks per process only. A `tau net` command that runs next to a running hub can lose a write, so the store needs an inter-process lock, such as `fcntl.flock` on a lock file under `TAU_DATA_DIR/net/`.
- A `tau net poll --once` next to a running hub competes for the same mailbox. Refuse it while the hub's `net` service is polling, or make it read-only.

## Acceptance criteria

- [ ] `tau doctor` lists the `net` check (and `cloud` when tau-cloud is installed) through the public hook; the Telegram check moves to the same hook
- [ ] Two processes writing contacts at once lose nothing (test with two processes)
- [ ] `tau net poll --once` next to a running hub is refused with a clear message

## Blocked by

- [093 · tau-net](093-tau-net.md)

## Comments

- 2026-09-30: filed from the 093 report.
