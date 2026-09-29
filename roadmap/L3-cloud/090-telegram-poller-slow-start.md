# 090 · The Telegram poller sometimes needs 30 s to start after a hub restart

Status: needs-triage
Type: AFK
Layer: L3 · Access and data
Packages: tau-core
Blocked by: none

## What to build

From `starting hub service telegram` to `telegram: polling as @…` the hub's log shows 1.0 s for the first three starts (2026-09-29 22:22, 22:26, 23:56) and 30–31 s for the next three (00:02 after a `kill -9` under launchd, 02:09 when TauBar took over after `tau hub uninstall`, 02:14 when TauBar restarted a hub killed with `kill -9`). The bot is deaf for those 30 s. 30 s is `HttpBotApi`'s default request timeout, so one of the start-up calls (`getMe`, `deleteWebhook`, `setMyCommands`) probably waits a full timeout once, e.g. a connect to one address of `api.telegram.org` that hangs before the next address is tried. It did not reproduce by hand: the same calls in the hub's exact environment took 0.2 s each, and IPv6 and IPv4 connects took 0.07 s.

Find the call that waits (log each start-up call with its duration at DEBUG, or measure in the next slow start), then fix it: a shorter connect timeout than read timeout, trying the next address sooner, or starting to poll before the command menu is set.

## Acceptance criteria

- [ ] The cause of the 30 s start is named, with the evidence
- [ ] After a hub restart the poller polls within a few seconds, or the log says what it is waiting for

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: found while testing TauBar's crash restart live (the hub itself was back in 1.8 s).
