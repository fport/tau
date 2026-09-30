# 113 · Guarded channels: TUI lock screen, terminal lock prompt, `/guard`, Telegram lock, live lock propagation

Status: done
Type: AFK
Layer: L10 · Guard
Packages: tau-core, tau-tui
Blocked by: 110

## What to build

The channels show the guard. `tau tui` and `tau chat` start locked when a guard is active. They unlock with the challenge prompts, and they lock again the moment the hub locks: on idle, screen lock, sleep, max age, a hub restart or `/guard lock` from Telegram. A lock takes the running turn and any pending approval with it. Telegram can lock but never unlock. Everything is built and tested against `FakeGuard` (110), so this slice does not wait for the real service. The decisions are in [ADR 0008](../../docs/adr/0008-owner-guard.md) (decisions 1, 5, 10, 11 and 17).

### `/guard` in every channel

- **The command.** `SlashCommand("guard", ...)` with argument `[lock|unlock]` goes into `SLASH_COMMANDS` **just before `quit`**. Add handlers in the terminal, the TUI and Telegram, and update every pinned test and snapshot: the command order, the `command_hint` string, the `help_lines` endings, the TUI menu's option count and height, and tau-tui's `test_commands.py`.
- **No guard.** With no active guard, `/guard` answers that the guard is off.
- **While locked**, only `ALLOWED_WHILE_LOCKED` (`help`, `lang`, `quit`, `guard`) run. Everything else, including `/compact`, `/sessions`, `/resume`, `/clear` and `/status`, is refused with the lock notice.

### TUI (`tau_tui`)

- **One guard.** `build_app` resolves the guard once (process-scoped), holds it on the app and passes it to every `build_agent` call through `guard=`: on `/new`, `/resume`, `/model`, `/compact` and after a settings save.
- **The lock comes first.** With a guard active, the app starts locked before the first agent build. The lock screen appears before anything else, and the setup wizard and the start-up settings screen (the missing-credentials path) never open while locked.
- **`GuardScreen(ModalScreen)`** is opaque: the rule goes in the App CSS, because `ModalScreen` is translucent there. It has an ASCII twin.
  - Enter unlocks, and the challenge prompts from `on_progress` render as they arrive ("look at the camera", "turn left", …, with the live hints `too_dark` and `face_too_small`).
  - Esc cancels a running attempt, and ctrl+q quits. `check_action` refuses every other action while locked.
  - `ctrl+l` locks from anywhere.
  - On `camera_*` verdicts, and after two face failures, it offers the unlock fallback when the guard reports one (114).
  - Without a hub, it shows `guard.start_hub`.
- **Live lock propagation.** A background worker long-polls `guard.watch()` while unlocked. On a transition to locked it:
  1. pushes the lock screen;
  2. cancels the running turn through the Esc path;
  3. dismisses an open `ApprovalScreen` as `REJECTED`.
- **The composer.** The submit path checks the watched state before it clears the composer, and keeps the text when locked. A `recheck` admission runs the passive check automatically and resends the kept prompt.
- **Step-up.** Step-up progress and challenge prompts come from the `guard` agent events (`action: challenge`). They show in the busy line with a bell.
- **Header.** A one-cell lock glyph, with an ASCII twin, appears only when a guard is active; a camera-on glyph appears while an attempt runs.
- **After an unlock**, an "Unlocked" notice shows the failed-attempt count. No model call is made, and a prompt kept from before the lock stays in the composer, not sent.
- **Stop reason.** Add a `tui.turn.stop.locked` key.

### Terminal (`tau chat`, `tau_core/channels/terminal.py`)

- **One guard.** The guard is resolved once into `ReplState.guard` and passed to every build (`_switch_to`).
- **The lock prompt.**
  - A locked banner shows at start.
  - Enter on an empty line unlocks, printing each progress step, and Ctrl-C during an attempt cancels it without leaving the REPL.
  - Only `ALLOWED_WHILE_LOCKED` commands run while locked.
- **Checks.** The state is checked again before every prompt.
- **Screen.** Entering the lock prompt clears the screen and the scrollback (`\x1b[2J\x1b[3J\x1b[H`). The docs say what a terminal cannot hide, such as the scrollback of a terminal app that ignores the sequence.
- **Events.** The REPL subscribes to its agent's event bus for `guard` events, so step-up challenge prompts print.
- **After a lock.** `TurnEnd("locked")` re-enters the lock prompt, and a `recheck` is handled automatically.

### Telegram (`tau_core/channels/telegram.py`)

- **No guard on turns.** `_build` keeps `guard=None` (110).
- **The commands.**
  - `/guard` shows the state.
  - `/guard lock` locks with trigger `telegram`: the owner's remote kill switch.
  - `/guard unlock` answers that unlocking happens only at the Mac.
- **Reaching the service.** Inside the hub, the service finds the guard lazily through `hub.find_service("guard")` plus an `isinstance(Guard)` check. `TelegramService` keeps the `hub` from `start()`.
- **Replies** go through i18n keys.

## Acceptance criteria

- [x] `/guard` sits just before `/quit` in `SLASH_COMMANDS`; the terminal, the TUI and Telegram handle it; all pinned tests and snapshots are updated and green; with no guard it answers that the guard is off
- [x] TUI: with a `FakeGuard` in `locked` state, the lock screen is the first screen, the transcript is not visible behind it (snapshot with a custom check), the setup wizard and the settings screen never open, and every action except Enter, Esc, ctrl+q and the allowed commands is refused
- [x] TUI: Enter runs `unlock` and every scripted progress step appears before the verdict; Esc during an attempt calls `cancel`; after an unlock the "Unlocked" notice shows the failure count and `FakeModel` records no call
- [x] TUI: flipping the `FakeGuard` to locked from outside pushes the lock screen within 2 s, cancels a running turn and dismisses an open approval dialog as `REJECTED`
- [x] TUI: a prompt submitted while locked stays in the composer; a `recheck` admission runs the passive check and resends the prompt
- [x] TUI: during a tier-2 step-up the challenge steps show in the busy line (scripted `FakeGuard` progress through the gate's `guard` events)
- [x] TUI: the same guard object is passed to every agent build (`/new`, `/resume`, `/model`, settings save); the header shows the lock glyph only when a guard is active; no snapshot changes when no guard is active except the `/guard` menu entry
- [x] Terminal: the locked banner shows at start; Enter unlocks and prints each step; Ctrl-C cancels an attempt and the REPL keeps running; only the allowed commands run while locked; entering the lock prompt writes `\x1b[2J\x1b[3J\x1b[H`; step-up challenge steps print through the event bus; `TurnEnd("locked")` returns to the lock prompt
- [x] Telegram: `/guard` shows the state, `/guard lock` locks with trigger `telegram`, `/guard unlock` answers that unlocking happens only at the Mac; Telegram turns keep running while the guard is locked
- [x] Every new UI string is an i18n key in `en` and `tr`; no Turkish text in code outside the `tr` column

## Blocked by

- [110 · Guard seams in tau-core](110-guard-seams-in-tau-core.md)

## Comments

- 2026-09-30: filed with ADR 0008.
- 2026-09-30: notes from 110's verification fixes:
  - `resolve_guard` never memoizes `None` now. While the process-scoped guard is `None`, resolve it again before each build and each submit (one stat), so a window opened before `tau guard setup` shows the lock screen as soon as the marker appears instead of staying unguarded.
  - `Guard.lock()` returns `None` and never raises; `HubGuard.lock` only logs an error when the hub did not confirm. After `/guard lock`, ctrl+l or Telegram `/guard lock`, re-read `status()` and show a "lock failed" notice (a new i18n key) unless the state is `locked`, so a channel never believes a lock that did not reach the hub.
  - `TierGate` now refuses an approved tier-2 call when the guard locked while the approval dialog was open (approval `locked`); the TUI still dismisses the open dialog on a lock.
  - The repo rules refuse `self.guard = None` and any other constant assigned to `.guard`; initialise the attribute from `resolve_guard(...)` or keep it in a dataclass field.
  - Until this issue adds `tui.turn.stop.locked`, the TUI footer shows the raw word `locked` for a refused turn.
- 2026-09-30: done. Commits: fc3e28b (`/guard` in the shared commands, the `tau chat` lock prompt), 3bdc343 (Telegram `/guard`, tau-core README), db69fb0 (TUI lock screen, live locks, step-up line, header glyphs, `/guard`, ctrl+l / F5, snapshots). Tests: `test_terminal_guard.py` (18), Telegram `/guard` tests in `test_telegram.py` (5), tau-tui `test_guard.py` (23), a CLI test, three new snapshots (lock at start, lock over a chat, step-up); full suite 1203 passed, 1 failed (the known personal-path finding of issue 130, unrelated). Everything is tested against `FakeGuard`.
  - Deviations: the TUI builds its first agent only after the first unlock (the strict reading of "before the first agent build"; `--resume` and the start notice wait too). `tau chat` still builds its agent before the lock prompt but prints nothing of the session (no ready banner, `--resume` waits) until the unlock. The setup screen is not shown while a guard marker exists for the data directory: `tau tui` exits 2 with a message, because there is no configuration to unlock with. The command menu grew to 16 rows (14 commands), so the transcript keeps 3 rows at 80x24. Any guard state other than `unlocked`, `verifying` included, counts as locked in every channel. The unlock fallback (Touch ID after two face failures or a `camera_*` verdict) is not offered: the `Guard` protocol has no way to report one yet (114). The docs site is untouched (the parallel session owns `docs/getting-started/*` and `docs/reference/*`); what a terminal cannot hide (an app that ignores `\x1b[3J`, tmux copy mode) is in the tau-core README and the `terminal.py` docstring. fc3e28b alone leaves tau-tui's menu pins red until db69fb0.
  - Notes for 111: the channels lock (and cancel TUI turns) on every state but `unlocked`, so a recheck or a step-up must keep the state `unlocked`; the "Unlocked" notice shows `method` from the verdict or the status (`—` when missing) and the larger of the channel's own count and `status.failures`, so the status right after an unlock should still carry the count. The TUI long-polls `watch(since)` with `since` = the last `seq` it saw (starting at -1), so a hub restart must answer a lower `seq` promptly or the next change is seen only after the long poll ends.
  - Notes for 114: add a way for the guard to report an available fallback (a `GuardStatus` field or a verdict hint); the lock screen and the lock prompt would offer it there.
  - Notes for the docs pass: `/guard` in `docs/reference/slash-commands.md`, ctrl+l / F5 in `docs/getting-started/talk.md`, the lock screen and the terminal's limits in the guard guide.
- 2026-09-30: verification fixes. Commits: b85eda7 (the tier gate admits once more after a passed step-up), 6527630 (`progress_text`, `verdict_text`, `method_text` and `COUNTED_FAILURES` in `tau_core.guard`; the unlock method goes through i18n, `guard.method.*`; `help_lines(only=)`), de487b7 (`tau chat`), d33e627 (Telegram), d3464c1 (key map and glyph notes), 3e13b8b (TUI). Tests: 1224 passed, 1 failed (the known personal-path finding of issue 130); every intermediate commit passes the tau-core and tau-tui suites.
  - A guard found after the agent was built (a window opened before `tau guard setup`) no longer leaves the agent at `guard=None`: both channels rebuild it on the same session and role with the guard at the unlock and before every turn and `/compact` (`_arm`); when that rebuild fails nothing is sent (`guard.rearm_failed`). In the TUI the activation goes through the lock path, so the open approval is rejected and the running turn cancelled; `enter_lock` is idempotent and still stops what runs when the lock screen is already up.
  - TUI: an `unlocked` status with a lower `seq` than the last one applied is dropped (a slow `/guard` could unlock the screen while the hub was locked); the watcher survives a state it cannot apply and locks; Esc and a lock cancel a running recheck (no resend, the prompt goes back into the composer, footer "Cancelled" for Esc) and call `guard.cancel` for a step-up's camera; a dialog or lock screen dismissed before it mounted no longer crashes; an unknown command on the lock screen is answered there.
  - Terminal: entering the lock prompt takes readline's in-memory history out (Up at `locked>` recalls nothing) and puts it back at the unlock; `/help` at the lock prompt lists only the allowed commands. The README and the module docstring state the terminal's limit: it reads the guard only between lines (a lock while it waits at `you>`, at an approval prompt or during a streaming turn is seen at the next line; the guard still refuses the turn's tier-1/2 calls). No watcher thread was added.
  - Deviation, now the same in both channels: after a refused turn the guard's state decides. A failed or cancelled recheck keeps the channel unlocked while the guard reports `unlocked` (the terminal says the prompt was not sent); read-only commands (`/sessions`, `/status`) keep working in that window, as the transcript is visible anyway. A refusal whose status reads `unlocked` no longer enters the terminal's lock prompt.
  - Not changed: fc3e28b alone still leaves tau-tui's menu pins red until db69fb0; those commits are not rewritten. The lock glyph `⚿` stays (ambiguous East Asian width like `◆` and `●`; noted in the glyph table and the tau-tui README).
  - Notes for 111: after a passed step-up the gate calls `admit` once more (`recheck` counts as admitted), so the state must stay `unlocked` right after a step-up; a hub restart must come back locked (the TUI drops an `unlocked` status whose `seq` is lower than the last one it applied).
