# tau-sim

Simulated devices for tau: stand-ins for hardware that is not on hand yet. The first one is a
**lamp**. tau, the web app and routines drive it with the same tools and tiers a real lamp will
have, so nothing changes for them when a real one arrives (ADR 0015 §5).

Nothing in this package talks to hardware. Every answer, card and status line says the lamp
is simulated.

It is its own distribution (`tau-sim`, import `tau_sim`), uses only the public API of
`tau-core` and plugs in through three entry points:

| group | name | what |
|---|---|---|
| `tau.tools` | `sim` | `lamp_list` (tier 0), `lamp_set` (tier 2) |
| `tau.hub_services` | `sim` | the `sim` hub service, a `DeviceSource` |
| `tau.commands` | `sim` | `tau sim lamps` |

## The lamps

Name them in `tau.toml`:

```toml
[component.sim]
lamps = ["desk", "living-room"]   # default ["desk"]; [] means none
```

- A name is a slug: lowercase letters, digits and hyphens, at most 40 characters.
- Unknown keys, a name that is not a slug and a repeated name are configuration errors.
- The tools also accept what people say: `"Living room lamp"` means `living-room`.

## The tools

- **`lamp_list`** (tier 0) lists every lamp and whether it is on.
- **`lamp_set(name, on)`** (tier 2) switches one lamp.
  - It stands for a physical action, so every call asks for your approval, as a real lamp will.
  - The approval shows: "Switches a simulated lamp on or off. It is a simulation: no real
    device changes."
  - Switching a lamp to the state it already has changes nothing.

Every answer, the failures too, says the lamp is simulated, so the model never tells you that
a real lamp changed.

"Turn on the desk lamp" then goes: tau calls `lamp_set("desk", true)`, you approve, the
simulated lamp is on, and `lamp_list` shows it on.

## The state

- **Where.** `TAU_DATA_DIR/sim/lamps.json`:

  ```json
  {"lamps": {"desk": {"on": true, "updated": "2026-10-01T07:00:00+00:00"}}, "version": 1}
  ```

- **How it is written.** Atomically (a temporary file, then a rename), mode `0600` in a `0700`
  directory, under an `flock` on `lamps.lock`. A tool call in `tau tui` and the hub's service
  never lose each other's change.
- **New lamps.** A lamp the file does not know yet starts off.
- **A broken file** is read as empty, so every lamp is off again. It is a simulation.

## The hub service

`sim` (`tau.hub_services`) implements tau-core's `DeviceSource`:

- `devices()` returns a `DeviceState` per lamp: `id` `sim:lamp:<name>`, `kind` `lamp`,
  `simulated` true, `state` `{"on": …}` and `updated` in UTC.
- `subscribe(callback)` calls back with the new `DeviceState` whenever a lamp changes. That
  includes a `lamp_set` in another process, such as `tau tui`: the service looks at the state
  file every half second, and a `stat` is all it costs while nothing changes.
- `GET /status` gains a `sim` key with each lamp's state as last seen.

The web app (`tau-web`, 178) serves every `DeviceSource` at `/api/devices` and pushes changes
as `device` events.

## Switching it off

Like any component (`tau components` shows the state):

```toml
[components.tools]
disabled = ["dist:tau-sim"]          # lamp_list and lamp_set

[components.hub]
services = ["telegram", "spend"]     # every hub service you want, without "sim"
```

## A real lamp

A real lamp arrives as an MCP node with the same tool names (069 decides its tiers). Routines
that call `lamp_set` keep working. `demo_physical_action` in tau-core stays the minimal example
of a tier-2 tool; `lamp_set` is the first device.

## Development

```sh
uv run pytest -q packages/tau-sim
uv build --package tau-sim
```

The tests use a temporary `TAU_DATA_DIR` and `tau_core.testing`: `ScriptedApprover` for every
approval, `FakeGuard` for the owner guard, `FakeModel` for the model.
