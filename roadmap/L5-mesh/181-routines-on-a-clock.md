# 181 · Routines on a clock: the `tau-routines` hub service, one approval at registration

Status: done
Type: AFK
Layer: L5 · Mesh
Packages: tau-routines, tau-core
Blocked by: –

## What to build

"Lamps on at 07:00 on weekdays" runs without an LLM, without the internet and without the owner at the Mac ([ADR 0015](../../docs/adr/0015-web-app-agentic-chat.md) §4).

**The package.** A new distribution `packages/tau-routines` (import `tau_routines`; check the PyPI name first). It provides:

- one `tau.hub_services` component, `routines`;
- the `tau.commands` entry point `tau routine add|list|pause|resume|remove|log`;
- the `tau.tools` tools `add_routine` (tier 2), `list_routines` (tier 0) and `remove_routine` (tier 1).

**The model.**

- A routine is `{id, name, trigger, tool, arguments, enabled, created, approved_hash}`.
- Triggers:
  - `daily HH:MM`, optionally on chosen weekdays;
  - `once <local datetime>`;
  - `every N minutes`, with N at least 5.
- Times use the hub's local zone, and `[routines] timezone` overrides it.
- State lives in `TAU_DATA_DIR/routines/routines.json`, written atomically with mode `0600`. The log is `routines/log.jsonl`, rotated.

**Registration.** Every path is one tier-2 approval: `tau routine add`, the `add_routine` tool, and the app's form in 184.

- **The approval request shows the full definition** in plain words: the trigger, the tool, its tier and the exact arguments.
  - `tau routine add` asks through the terminal's approver.
  - The form and the tool ask through their channel's approver.
- **What gets stored.** On approval the service stores `approved_hash`, a hash of `(id, tool, canonical arguments)`.
- **Changes.** Editing the trigger, tool or arguments clears the hash and asks again. Pause, resume, rename and remove are free.

**Firing.**

- The engine calls the tool through a `TierGate` built with `guard=None`: the routine engine is one of the two new entries in the repo rule's allowlist.
- The gate also gets the `RefusingApprover`, and an `Exemption` that returns `True` only when the call hashes to the routine's `approved_hash`.
- A firing missed while the hub was off runs only within `[routines] grace_minutes` (default 10). Otherwise it is logged as `missed`.
- A failure is logged and the routine stays enabled. After three failures in a row it pauses itself and says so in the log.
- Every firing is an agent event (`routine {id, status}`), so channels can show it.

**No network needed.** The engine keeps time on its own and never touches a model or the cloud.

## Acceptance criteria

- [x] `tau routine add "daily 07:00 weekdays" demo_physical_action …` asks for one approval; the routine fires at 07:00 on the next weekday with no further approval (test with a fake clock)
- [x] A changed argument asks again; a routine whose stored hash does not match its call is refused by the gate, not run (test)
- [x] With networking disabled and no model configured the routine still fires (test)
- [x] Missed firings within the grace run once, older ones are logged as missed; three failures pause the routine
- [x] The repo rule allows `guard=None` in exactly the engine's file; every other rule in `test_repo_rules.py` still passes
- [x] `tau-routines` builds as its own wheel and is in CI (the release workflow waits for the owner's PyPI publisher, see Comments)

## Blocked by

None - can start immediately; the tier gate and `Exemption` (006) are done.

## Comments

- 2026-10-01: filed with ADR 0015. 037 keeps the event triggers (`desk.presence=present → …`) and builds them on this engine once 032 lands. The simulated lamp (183) is the first real target.
- 2026-10-01: done (79714ff, c5061ff; the hub test fix 446a2fa), built by a subagent and reviewed.
  - **Commands and tools:** `tau routine add|list|edit|pause|resume|remove|log`; the tools `add_routine` (tier 2), `list_routines` (tier 0) and `remove_routine` (tier 1).
  - **Approval text:** a tool may now carry `tau_describe` (`tau_core.tiers.effect_for`). The gate uses it to word each call in the approval, so every registration path shows the trigger, tool, tier and exact arguments.
  - **Firing:** the engine calls the tool with `AgentTool.stream`, through `TierGate.check` and `record`, with `guard=None` (only in `engine.py`), the `RefusingApprover` and the hash-bound exemption.
    - The slot is recorded before the tool runs, so a crash never repeats a physical action.
    - Each firing has a 120 s timeout.
    - Resuming a paused routine skips the slots that fell due meanwhile.
  - **Config:** `[component.routines] timezone` and `grace_minutes`. The default zone is `TZ`, then `/etc/localtime`.
  - **The hub service** notices changes through the file's mtime, size and inode, and sleeps until the next slot or 30 s.
  - **Not done:**
    - `release.yml` waits for a PyPI publisher for `tau-routines`; the name is free.
    - The docs pages, CONTEXT and `tau setup`'s features come with 184.
  - **Also in this change:** `test_telegram_pairing`'s hub test now waits for Telegram's route instead of racing the services' start.
