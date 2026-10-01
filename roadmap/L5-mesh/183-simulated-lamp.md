# 183 · A simulated lamp: the first device the app and routines can drive

Status: done
Type: AFK
Layer: L5 · Mesh
Packages: tau-sim, tau-core
Blocked by: –

## What to build

No smart lamp is on hand, so the first device is simulated ([ADR 0015](../../docs/adr/0015-web-app-agentic-chat.md) §5). Nothing in this issue talks to real hardware.

**`packages/tau-sim`** (import `tau_sim`; check the PyPI name first):

- **Tools** (`tau.tools`):
  - `lamp_list` (tier 0) returns the lamps and their state;
  - `lamp_set(name, on: bool)` (tier 2, `effect="physical"`) switches one.
- **Config.** The lamps come from `[sim] lamps = ["desk", "living-room"]` (default `["desk"]`).
- **State.** It lives in `TAU_DATA_DIR/sim/lamps.json`, written atomically.
- **Marking.** Every answer says the lamp is simulated, and so does every channel that shows it.

**Device sources in tau-core's public API.** Add a small protocol:

```python
class DeviceSource(Protocol):
    def devices(self) -> list[DeviceState]: ...
    def subscribe(self, callback: Callable[[DeviceState], None]) -> Callable[[], None]: ...
```

- `DeviceState` is `{id, name, kind, simulated, state, updated}`.
- The `sim` hub service implements it. tau-web (178) finds every hub service that does and serves `/api/devices`, with changes pushed as `device` events.
- The mesh (032, 033) implements the same protocol later.

**Retire `demo_physical_action`.** `lamp_set` replaces it in tests and docs that use it as the example tier-2 tool, or it stays as an alias until those move. Choose one and say which in the comment.

## Acceptance criteria

- [x] With tau-sim installed, "turn on the desk lamp" asks for approval and then switches the simulated lamp; `lamp_list` shows it on
- [x] The hub's `sim` service implements `DeviceSource`; a state change reaches subscribers
- [x] Every answer and card marks the lamp as simulated
- [x] `tau-sim` builds as its own wheel and can be disabled through `[components]`

## Blocked by

None - can start immediately.

## Comments

- 2026-10-01: filed with ADR 0015. The owner has no smart lamp yet (2026-10-01). A real one arrives as an MCP node with the same tool names, and 069 decides its tiers.
- 2026-10-01: the end-to-end check "a routine turns the lamp on at its time" lives in 184, which has both 181 and this issue as blockers. This issue stays independent of 181.
- 2026-10-01: done (574892b, 5639b49, 8568b0b), built by a subagent and reviewed.
  - **tau-core:** `tau_core.devices` has `DeviceState`, `DeviceSource` and `to_json`. The top level exports them as `DeviceState`, `DeviceSource` and `device_to_json`. Device ids look like `sim:lamp:<name>`.
  - **tau-sim:** `lamp_list` is tier 0. `lamp_set` is tier 2, and its effect text says it is a simulation. The `sim` hub service is a `DeviceSource` and notices a change made by another process through the state file's mtime. There is also a read-only `tau sim lamps` command.
  - **Config:** the lamps live in `[component.sim] lamps` (default `["desk"]`), following the `[component.<name>]` convention rather than the `[sim]` table written above.
  - **`demo_physical_action`** stays as the minimal example.
  - **PyPI name:** `tau-sim` is taken by an unrelated project, so the owner picks a free name before publishing (`tau-devices` and `tau-simulator` were free on 2026-10-01). The package is not in `release.yml` yet. Once tau-core ships `tau_core.devices`, raise tau-sim's `tau-core` floor.
