# 019 · Settings as local data with live reload and `/settings`

Status: ready-for-agent
Type: AFK
Layer: L3 · Access and data
Packages: tau-core
Blocked by: none

## What to build

Runtime settings — active profile, ambient configuration (029), budget caps (011), retention, notification preferences, backup schedule (018), voice options (075) — are data on the hub, not config and not a cloud table (ADR 0006 §4): one file `TAU_DATA_DIR/settings.toml`. `tau_core.settings` gives it a typed schema with defaults, `Settings.load()` with validation, atomic writes, and a watcher inside the hub (mtime poll on the heartbeat, or a file watcher) that reloads the file and tells services through a `settings_changed` notice. `/settings` in every channel (terminal, TUI, Telegram once 014 lands) lists settings, shows one key and sets a value through the shared command spec; TauBar (025) and the web UI (074) edit the same file through the control API (`GET /settings`, `PUT /settings/<key>`, loopback only). Every change appends to `TAU_DATA_DIR/settings-audit.jsonl` (channel, time, old → new). No D1, no sync to a third party; the file is part of the encrypted backup (018).

Config (`tau.toml`, `.env`) stays static bootstrap: roles, ports, paths, credentials. A key that exists in both is a `ConfigError` at load time, so the two never drift.

## Acceptance criteria

- [ ] `/settings` lists settings with their current values; `/settings <key> <value>` changes one, and the hub applies it within one heartbeat without a restart (test with a fake clock or watcher)
- [ ] Values are validated against the schema; an invalid value is rejected with an explanation in the UI language and the file is left untouched
- [ ] The control API exposes `GET /settings` and `PUT /settings/<key>` on loopback only, so TauBar and the web UI can use them
- [ ] Every change is appended to `settings-audit.jsonl` with channel and timestamp
- [ ] Edits made outside tau (an editor, a restore from backup) are picked up by the watcher; a corrupt file keeps the last good settings and warns
- [ ] Settings live under `TAU_DATA_DIR` and nowhere else; the tau-core README documents the file, the schema and the command

## Blocked by

None - can start immediately; Telegram gets `/settings` through `tau_core.commands` when 014 lands.

## Comments

- 2026-09-29: reworded `/ayar` → `/settings` (Turkish alias `/ayar` stays accepted, see 062).
- 2026-09-29: rewritten for ADR 0006 (private-first). Before: a D1 table pushed to the hub through the relay, blocked by 014. Now: a local file under `TAU_DATA_DIR`, hot-reloaded by the hub, edited by `/settings`, the control API, TauBar and the web UI; nothing blocks it.
- 2026-09-29: issue 083 shipped the editor for the *bootstrap* config (`tau.toml`, `.env`) behind `/settings` and the TUI's settings screen (`tau_core.settings`, `tau_tui.settings`). This issue keeps its scope: the runtime settings file under `TAU_DATA_DIR` with hot reload, the audit log and the control API. When it lands, `/settings` should grow the runtime keys next to the bootstrap sections rather than replace them, and a key present in both stays a `ConfigError`.
- 2026-09-30: ADR 0008 (owner guard): the guard's knobs (`idle_lock_minutes`, `max_unlock_hours`, `recheck_after_idle_minutes`, `presence_recheck_minutes`, `step_up`, `unlock_liveness`, `unlock_fallback`, the thresholds) move from `[component.guard]` into settings here, and a change that weakens the guard takes effect only after a successful verification, while a strengthening change applies at once (the audit records both). Guard enablement stays anchored in `TAU_DATA_DIR/guard/enrolled` and never becomes a setting.
