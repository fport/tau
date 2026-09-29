# 053 · `doctor.sh` misses errors in `~/.tmux.conf`

Status: ready-for-agent
Type: AFK
Layer: L0 · Remote access
Packages: infra/remote
Blocked by: none

## What to build

`doctor.sh` checks the tmux config with `tmux -L tau-doctor -f ~/.tmux.conf start-server \; kill-server`. `start-server` does not report config errors, so a broken config passes as loading without errors. Check it in a way that surfaces errors, on a private socket so the user's running tmux server is never touched.

## Acceptance criteria

- [ ] A `~/.tmux.conf` with an unknown command makes `doctor.sh` report the file, line and error
- [ ] A clean config still passes
- [ ] The check uses its own `-L` socket and leaves no tmux server running
- [ ] Covered by the #002 test suite once it exists

## Blocked by

None - can start immediately

## Notes

Reproduced 2026-09-28 with a config containing `this-is-not-a-command`: `start-server \; kill-server` prints nothing and exits 0. `tmux -L <sock> -f /dev/null new -d \; source-file <conf> \; kill-server` prints `<conf>:2: unknown command: this-is-not-a-command` but also exits 0, so the check has to look at the output, not the exit code.

## Comments

- 2026-09-29: triaged → ready-for-agent. Small shell change on its own `-L` socket; may be folded into 002 (regression test suite) if that is worked first.
