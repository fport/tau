# 176 · The whole site in the portal's language: black sky, a full-page universe

Status: done
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/universe (public, client)
Blocked by: –

## What to build

The landing's opening (a16aadc) set the site's language: pure black, grey stars, fire only on
what is alive, HUD labels and thin lines. The rest of the site still wears the older Void-blue
theme and reads like an ordinary website: bands with borders below the hero, a boxed graph on
`/universe`, navy panels on the reading pages. The owner asked for every page to follow the
opening.

- **Black everywhere.** The site's tokens are pure black (the landing's values), and a quiet
  star field with a little parallax stands behind every page. Fire (Signal, Ember, Flare) is
  kept for what is alive or what you act on: an online tau, a live link, the primary button,
  the current place. Everything else is grey.
- **The landing below the hero** continues the flight instead of turning into a website: the
  sections float in the same sky, what tau is and who can read what are drawn in the
  universe's marks (grey triangles that light as they come into view, readers as lit
  squares), and the last section is a portal into `/universe`.
- **`/universe` fills the page.** The universe is drawn by the landing's canvas engine,
  shared rather than copied, over the whole viewport: drag to turn, wheel or pinch to zoom,
  a click (or `#<address>`) flies the camera to a tau and pins its card, `#<address>/<name>`
  one of its sub-taus. The title and counts, the search, the legend, the list of taus (the
  keyboard path) and "Add your tau" are HUD overlays on the sky. The d3 graph goes.
- **Reading pages** (`how-it-works`, person, sub-tau, claim, 404, soon) lose the navy: black
  panels with 1 px lines, accents only on the current or live thing, the star field behind.
- English and Turkish pages change together.

## Acceptance criteria

- [x] No Void-blue surface is left on the site; `theme-color` is black on every page.
- [x] The star field stands behind every page, drawn once per scroll or resize, still under
      `prefers-reduced-motion`, and the pages work without it.
- [x] The landing's sections below the hero follow the opening; checked at 360 to 2560 px in
      both languages with no horizontal scroll.
- [x] `/universe` is the full-page universe on the shared canvas engine: turn, zoom, select,
      search, `#<address>` and `#<address>/<name>`, the list as the keyboard path, the empty,
      few and failed states; d3 is no longer a dependency.
- [x] Reading pages keep their content and layout, on black.
- [x] `bun run typecheck`, `bun run test` and `bun run build` pass; screenshots of every page
      in both languages checked.

## Comments

- 2026-10-01: filed at the owner's request after the landing's opening landed.
- 2026-10-01: done. As built:
  - **Sky.** site.css's `:root` block puts the landing's black tokens on every page (plus
    `--glass`, `--glass-2` for panels over the sky); tau-host keeps the theme's Void.
    `client/starfield.ts` is a fixed canvas of grey stars in three depths with a little scroll
    parallax, drawn on scroll and resize only; `client/sky.ts` (404, soon) and `client/how.ts`
    (how it works, plus the storyline's scroll-spy) load it where no other script does.
  - **Engine.** `client/painter.ts` holds the world and the painter the landing used, shared by
    `landing.ts` and `universe.ts`, with a focus for the universe page (dim, reticle, sub-tau
    names) and owner outlines (a dashed grey hull around an owner's taus when there are two or
    more). `cosmos.ts` gained `fitBox`, `closeUp`, `ownerKey` and `hull`, all tested.
  - **`/universe`.** Full viewport, no page scroll: fly-in with streaks, drift when idle, drag to
    turn, wheel or pinch to zoom, arrow keys and +/- on the focused canvas, `#<address>` and
    `#<address>/<name>` fly the camera and open the card. HUD: title, count and search at the
    top left, legend and hint at the bottom left, tools (zoom, whole universe, Taus, Add your
    tau) at the bottom right, one panel (list, card, join) at the right or as a bottom sheet
    under 48rem. Its own `styles/universe.css`. d3-force and d3-polygon are gone, and with
    them the layout helpers only the graph used.
  - **Landing below the hero** (`client/fold.ts`): the traits as a constellation whose marks
    light in view, readers as lit squares in glass panels, and the portal drawing itself over
    the last section with the live count.
  - **Reading pages:** no grid, grey kickers and rules, glass panels, the storyline lit only at
    the chapter being read, sub-tau rings burning only when the sub-tau can answer.
  - Checked in headless Chrome at 360 to 2560 px in both languages, the empty and failed
    universe, reduced motion; no horizontal scroll. 310 tests pass.
