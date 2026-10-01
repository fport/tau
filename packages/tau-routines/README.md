# tau-routines

Routines for tau: "lamps on at 07:00 on weekdays". A routine is a trigger plus one tool call
with fixed arguments, and no LLM. The hub runs it without a model, without the internet and
without the owner at the Mac. This is the reflex engine of Principle 1, specified in ADR 0015
§4 (`docs/adr/0015-web-app-agentic-chat.md` in the tau repository).

It is its own distribution (`tau-routines`, import `tau_routines`), uses only the public API
of `tau-core` and plugs in through three entry points:

| group | name | what |
|---|---|---|
| `tau.hub_services` | `routines` | the engine that fires routines inside `tau hub run` |
| `tau.commands` | `routine` | `tau routine add\|edit\|list\|pause\|resume\|remove\|log` |
| `tau.tools` | `routines` | `add_routine` (tier 2), `list_routines` (tier 0), `remove_routine` (tier 1) |

## Triggers

| trigger | fires |
|---|---|
| `daily 07:00` | every day at 07:00 |
| `daily 07:00 weekdays` | Monday to Friday; also `weekends`, `mon,wed,fri`, `mon-fri` |
| `once 2026-10-05 07:00` | once, at that local date and time; then the routine is finished |
| `every 15 minutes` | every 15 minutes from its registration; 5 to 10080 minutes |

Times are wall-clock times in the hub's local zone (`TZ`, else the zone `/etc/localtime`
names). `[component.routines] timezone` overrides it. Daylight saving time is followed.

## One approval at registration

Registering a routine is one tier-2 approval on every path:

- `tau routine add` asks through the terminal's approver;
- the `add_routine` tool asks through the approver of the chat it was called in;
- the web app's form (issue 184) will ask through its own.

Each path asks a `TierGate` about one `add_routine` call. So the owner guard (ADR 0008)
applies as on any tier-2 call: a locked Mac refuses before anyone is asked, and an approval
needs the guard's step-up.

The request shows the whole definition in plain words. `add_routine` carries `tau_describe`,
which tau-core's gate puts into the approval request:

```text
Registers the routine "Lamps on": every weekday (Monday to Friday) at 07:00, Europe/Istanbul
time, the hub runs demo_physical_action (tier 2, a physical action: Demo: simulates a physical
action; no real device moves.) with exactly these arguments: action="turn on the desk lamp".
From then on it runs on that clock without asking again, without a model and while nobody is
at the Mac. Pausing or removing it is free; any other change asks again.
```

On approval the routine is stored with `approved_hash`, the SHA-256 of the canonical JSON of
`[id, tool, arguments]`.

**Changes.** A change of the trigger, the tool or the arguments is a new registration of the
same id (`tau routine edit`, or `add_routine` with `replaces`). It asks again, and a rejected
change leaves the routine as it was. Renaming, pausing, resuming and removing change nothing a
routine does and ask nothing.

Without an interactive terminal nobody can answer, so `tau routine add` is refused. Nothing
approves on its own, in the code or in the tests.

## Firing

The engine calls the tool through a `TierGate` built for that one call:

- **`guard=None`.** The engine is an in-hub caller, identified by a registration that was
  approved on a trusted, guarded channel. A routine must work at 07:00 while the Mac is
  locked. `tau_routines/engine.py` is the engine's entry in the repo rule's allowlist
  (`GUARD_NONE_ALLOWED`).
- **A `RefusingApprover`.** Nobody is asked at firing time, so the gate refuses every tier-2
  call that the exemption does not cover.
- **An exemption.** It returns `True` only for the routine's own tool, with arguments that hash
  (with its id) to the stored `approved_hash`. A routine whose file entry changed behind the
  registration is refused by the gate and not run.

The gate consults exemptions for tier 2 only. For a tier-0 or tier-1 tool, the engine applies
the same check itself.

**Missed firings.** Slots missed while the hub was off run once if they are at most
`grace_minutes` old (default 10). Older ones are logged as `missed`. The slot is recorded
before the tool runs, so a crash in the middle never repeats a physical action.

**Failures.** A failed or refused firing is logged, and the routine stays on. After three in a
row it pauses itself, and the log says so. A success clears the count.

**Events.** Every outcome is an agent event `routine` (`{id, name, status, tool, slot, detail,
count}`) on `RoutinesService.events`, next to the gate's own `tool_call` and `approval` events.
Channels subscribe through `hub.find_service("routines").events`. `tau hub status` shows a
`routines` entry.

The engine never builds a model and never opens a connection. A tool that needs an agent (a
`ToolContext`) cannot run as a routine.

## Configuration

```toml
[component.routines]
timezone = "Europe/Istanbul"   # an IANA zone; default: the hub's local zone
grace_minutes = 10             # 0 to 1440
```

Any other key is an error. A bad table stops the hub service, and the hub runs on without
routines; `tau routine` exits with code 2.

## Files

Everything is under `TAU_DATA_DIR/routines/`. The directory has mode `0700`, the files `0600`.

- `routines.json` holds `{"version": 1, "routines": [...]}` and is written atomically.
  - Each routine is `{id, name, trigger, tool, arguments, enabled, created, approved_hash,
    last_slot, failures}`.
  - Every change is a read-modify-write under an exclusive lock on `routines/.lock`. The CLI,
    the tools and the engine never lose each other's changes.
  - The engine notices a change by the file's stamp (mtime, size, inode), within 30 seconds.
  - An entry that does not parse is skipped with a warning and written back unchanged.
- `log.jsonl` has one JSON object per firing, registration, change or removal. At 512 KiB it
  is rotated to `log.jsonl.1`, and three old files are kept.

## Commands

```sh
tau routine add "daily 07:00 weekdays" demo_physical_action "action=turn on the desk lamp" --name "Lamps on"
tau routine add "every 30 minutes" write_note --args '{"text": "stretch"}'
tau routine list
tau routine edit "Lamps on" "action=turn on both lamps"   # asks again
tau routine edit "Lamps on" --name "Morning lamps"         # free
tau routine pause "Morning lamps"
tau routine resume "Morning lamps"                         # what fell due meanwhile is skipped
tau routine log "Morning lamps" -n 50
tau routine remove "Morning lamps" --yes
```

A `NAME=VALUE` value is read as JSON when it is JSON (`3`, `true`, `[1, 2]`), except for an
argument the tool declares as text. `--args` gives all arguments as one JSON object. The
arguments are checked against the tool's input schema before anything is asked.

## Python API

```python
from tau_routines import RoutineContext, RoutineEngine, register

context = RoutineContext.from_config(config)  # settings, tool catalog, store, clock
draft = context.draft(
    trigger="daily 07:00", tool="demo_physical_action", arguments={"action": "lamp on"}
)
outcome = await register(draft, gate=gate, store=context.store, clock=context.clock)
engine = RoutineEngine(context.store, context.settings, tools=context.catalog.values())
await engine.tick()  # tests drive the engine with a fake clock
```

`register` takes the caller's `TierGate` (with its approver and guard), so every channel asks
in its own way.

## Tests

```sh
uv run pytest -q packages/tau-routines
```

The tests run offline:

- a fake clock, so nothing sleeps;
- `ScriptedApprover` and `FakeGuard`, so nothing approves on its own and no camera opens;
- a temporary `TAU_DATA_DIR`.

They cover the acceptance criteria of issue 181:

- one approval, then a weekday firing with no further ask;
- a changed argument asks again;
- a hash mismatch is refused by the gate;
- a routine fires without network or model;
- grace and missed firings;
- three failures pause the routine.
