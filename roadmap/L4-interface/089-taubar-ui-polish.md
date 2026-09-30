# 089 · A nicer TauBar menu and settings window

Status: done
Type: AFK
Layer: L4 · Interface
Packages: apps/taubar
Blocked by: none

## What to build

TauBar v0 works (024, 084), but the user finds the menu plain: status lines, switches and sleep modes are one long native list. Design a tidier menu and settings window with the brand palette and the tau mark from `docs/brand/`: a clear hub status (state, uptime, Telegram poller) at the top, grouped switches, and the sleep modes as one choice. Keep the native menu where macOS expects it and keep every action reachable without the window.

## Acceptance criteria

- [x] A design the user approves before it is built (a quick prototype or mockup is fine)
- [x] Menu and window follow the brand palette and stay readable in light and dark mode
- [x] Nothing that works in v0 is lost (switches, sleep modes, logs, quit)

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: the user, on first sight of the TauBar menu: "it could have a nicer UI".
- 2026-09-30: three clickable mockups of a popover (control center, native tidied, instrument); the user picked **native tidied**: a borderless translucent panel under the icon on a left click, in the order of the old menu (hub switch in the header, hub/Telegram/crash rows with round icons, the sleep modes as one choice, launch at login, logs, settings, quit). The native menu stays on the right click.
- 2026-09-30: done. f0d653c adds the panel (`panel.rs`, `Panel.tsx`): a transparent window with the popover material under the icon, opened by a left click, hidden on focus loss or Esc, its height fitted to the page, the icon pressed while open; the native menu moved to the right click and also takes the left click if the panel cannot be created. The snapshot gains `hub.panel` (the hub rows without labels). 5e6353b gives the settings window a light theme (Ink text and mark, Ember only as a fill). ba14059 updates the README and the guide; `bun run dev` in a browser previews both views through `src/devmock.ts`. Checked with a second copy (`TAUBAR_HOME`, another identifier) and screenshots: material, corners, shadow, fitted height and hiding on focus loss work; the browser preview checked light and dark. Vite merged the preloads of two dynamic CSS imports in one ternary and dropped `panel.css`; each view module now imports its own stylesheet. Not seen yet: the pressed icon and the position under a visible icon (the test copy's icon sat behind the menu bar overflow). A guard row (115) fits as one more `InfoRow` in the panel's hub group.
