# 088 · Opening TauBar again does not show its window

Status: needs-triage
Type: AFK
Layer: L4 · Interface
Packages: apps/taubar
Blocked by: none

## What to build

The TauBar guide says that opening TauBar.app again (Spotlight, Finder, `open -a TauBar`) shows its settings window, the way in when the menu bar icon is hidden. On the user's Mac it does not: with TauBar running from `/Applications`, `open -a /Applications/TauBar.app` left the app with no window (`System Events` counts 0 windows for the `taubar` process). The first-run window also went unnoticed. `RunEvent::Reopen` may not reach an accessory (`LSUIElement`) app this way; find what does (e.g. handle the reopen Apple event, or a second launch that signals the running instance) and verify it by hand.

## Acceptance criteria

- [ ] With TauBar running and its menu bar icon hidden, opening TauBar.app from Spotlight or `open -a TauBar` shows the settings window in front
- [ ] The guide's "No τ in the menu bar?" note matches what happens

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: found while installing TauBar on the user's Mac. The icon was hidden by Hidden Bar (a menu bar manager that pushes items left of its separator off screen, x = -2595), so the window was the only other way in.
- 2026-09-30: narrowed. Since 091 a second launch reaches the running TauBar, which calls `open_settings` (`show()` + `set_focus()` on the existing `settings` window), yet CGWindowList reports that window `onscreen false`. An accessory app (`ActivationPolicy::Accessory`) may need to activate itself, or switch to `Regular` while the window is open, before macOS orders its window front. Verify by hand on the user's Mac.

