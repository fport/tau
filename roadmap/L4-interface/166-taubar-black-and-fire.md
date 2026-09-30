# 166 · TauBar in black and fire: only what is on burns

Status: needs-triage
Type: AFK
Layer: L4 · Interface
Packages: apps/taubar
Blocked by: 089

## What to build

The user found the 089 colours busy (every heading, status line and link in Flare or Ember on navy) and, after several mockups, picked **black with a burning edge**: a black background where only what is on burns, and burns hard. Apply it to the panel and the settings window.

- **Background:** pure black. Window `#050505`, surfaces `#0B0B0B`, lines `#1C1C1C`. No navy.
- **Fire:** the brand's own gradient, `linear-gradient(100deg, #FF2E63 0%, #FF5A3D 35%, #FF8A2A 65%, #FFB25C 100%)` (Signal → Ember → Flare).
- **Only the active things burn:** the hub card and the hub row while the hub is up, the selected sleep mode, launch at login while on, every switch that is on, and the guard row and "Lock now" (115) under the same rule. An active item stays black inside with a 1.5 px fire-gradient edge and a glow (`0 0 16px rgba(255,90,40,.6), 0 0 44px rgba(255,46,99,.3)`). Its heading and title are set in the fire gradient as text, with a soft glow. The selected sleep mode's icon is a portal orb: `radial-gradient(circle, #FFF4E0, #FFB25C 28%, #FF7A3D 58%, #FF2E63)`.
- **Everything off or unselected is dead grey:** title `#6E6E6E`, detail `#4A4A4A`, switch track `#262626`, no colour at all. Telegram, the last crash and the plain actions (logs, settings, quit) stay neutral grey.
- **The mark:** the neon ring mark (`docs/brand` geometry, bloom) at 48 px or more in the settings header; the fire-gradient coin in the panel.

The rejected directions, for the record: tidied palettes on zinc, navy, near-black and mono, and neon fire on warm black or on the poster navy with neon edges and beams. Each lit too much, or not hard enough.

## Open questions

- Light mode: the brand keeps neon to dark backgrounds. Should TauBar stay dark always, or use flat fire (no glow) on a light background?
- The panel sits on macOS's popover material (089). Pure black means an opaque black panel instead, or a black tint over the material.

## Acceptance criteria

- [ ] The panel and the settings window are black, and colour appears only on what is on or selected
- [ ] Turning the hub, a sleep mode or launch at login on and off moves the fire with it
- [ ] Body text on black keeps at least 4.5:1 contrast; nothing that works in 089 and 115 is lost
- [ ] The user approves it on the installed TauBar

## Blocked by

- [089 · A nicer TauBar menu and settings window](089-taubar-ui-polish.md)

## Comments

- 2026-09-30: the user picked "B · burning edge" of the black-and-fire mockups (the other was the same with the active item filled with fire) and asked to do the design work later.
