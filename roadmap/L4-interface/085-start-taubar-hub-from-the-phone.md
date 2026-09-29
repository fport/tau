# 085 · Start or restart the hub TauBar supervises from the phone

Status: needs-triage
Type: AFK
Layer: L4 · Interface
Packages: apps/taubar, tau-core
Blocked by: 084

## What to build

With TauBar running the hub (084), `tau hub stop` over SSH leaves the hub stopped and TauBar's switch off until someone clicks it on the Mac. From the phone there is no way back: `launchctl kickstart` does not apply, and `tau hub run` in tmux starts a hub TauBar does not supervise (TauBar shows it as "started outside TauBar"). Give the SSH user a command that asks TauBar to start or restart its hub, for example `tau hub start` / `tau hub restart` that talk to TauBar through a local, user-only channel (a file TauBar watches under its own directory, or a Unix socket), falling back to a clear message when TauBar is not running. Nothing new may listen on a network port.

## Acceptance criteria

- [ ] From an SSH session, one command starts the hub under TauBar after `tau hub stop`, and one restarts it (new pid, supervised)
- [ ] The command says what happened, and what to do when TauBar is not running
- [ ] No network listener is added; only the logged-in user can use the channel

## Blocked by

- [084 · TauBar runs the hub](084-taubar-runs-the-hub.md)

## Comments

- 2026-09-30: found while building 084. A restart after a code update (`git pull`) is the common case from the phone.
