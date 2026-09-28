# 041 · Greet on sit: presence → wave

Status: ready-for-agent
Type: AFK
Layer: L6 · Robot
Packages: tau-robot, tau-core
Blocked by: 036, 037, 038, 039

## What to build

A registered routine: `tau/desk/presence = present` → `arm.play("wave")`, with a cooldown (e.g. once per 30 minutes) and configured hours. Runs in simulation by default and on the real arm only when real mode is enabled.

## Acceptance criteria

- [ ] Unlocking the Mac plays the wave in simulation
- [ ] The cooldown is respected
- [ ] Works with no internet
- [ ] The motion is produced with the method chosen in #038

## Blocked by

- [036 · Desk presence: screen unlock → `tau/desk/presence`](../L5-mesh/036-desk-presence-event.md)
- [037 · Reflex engine for user-registered routines](../L5-mesh/037-reflex-routine-engine.md)
- [038 · Decide how SO-101 motions are produced](038-decide-so101-motion-method.md)
- [039 · SO-101 simulation node with MCP tools](039-so101-sim-node.md)

## Comments
