# 175 · Docs and site for the installer and the app

Status: done
Type: AFK
Layer: L8 · Distribution
Packages: docs, README, cloud/universe
Blocked by: 169, 170

## What to build

[ADR 0014](../../docs/adr/0014-one-installer-and-onboarding.md).

- The landing's "Run it on your machine" way shows the one-liner and the app download.
- `docs/getting-started` leads with them.
- The README's step 1 becomes the one-liner.
- A page lists every setup feature with what it needs and what it changes.

Everything EN + TR.

## Acceptance criteria

- [x] mkdocs strict build; site tests; every page has its twin

## Comments

- 2026-10-01: filed with ADR 0014.
- 2026-10-01: done (170 was still in progress: its workflow builds `tau.dmg`, the first release waits for the owner's signing secrets and a tag). As built:
    - **Landing** (EN + TR): the local way's button is "Download the Mac app" (`/download`), its note names the one command, and a row under the three ways holds `curl -fsSL https://tau.getporti.com/install.sh | sh` as a `.command` with a copy button (`client/copy.ts`, shared with the download page: clipboard, else the text is selected). A footer link to `/download`. The landing still carries no GitHub link.
    - **`/download` and `/tr/download`** in the black style with the star field (`client/download.ts`): the app (`tau.dmg` from `https://github.com/fport/tau/releases/latest/download/tau.dmg`, macOS 13+, Apple silicon and Intel) next to the one command; the first open while the app is not notarised (System Settings → Privacy & Security → Open Anyway; right-click → Open on macOS 13 and 14) with why; the wizard's eight steps; the terminal way (reading the script first, `TAU_INSTALL_NO_SETUP=1`); by hand (`uv tool install tau-core --with …`); the features, linking the docs' setup features page. Served like `/how-it-works`: in `PAGES`, `run_worker_first`, `RESERVED_NAMES` and the dev server; CSP unchanged, no inline script or style. On a phone the commands wrap at their spaces with the copy button below. In Turkish, Latin names in upper-case labels carry `lang="en"` so they do not turn into "LİNUX".
    - The soon page's button and how it works' local way point to `/download` (the soon page linked a docs path that does not exist).
    - **Tests:** `test/pages.test.ts` adds the twin, the landing's local way in both languages and the download page's content; the Turkish link rule allows the disk image as the one outside link. 314 tests, typecheck and build pass.
    - **Docs** (EN + TR): new `guides/setup-features` (first under Guides) with every catalog feature: what it is and installs, platforms, permissions, its steps (at the Mac, the one `sudo` command, tokens), adding it later and removing it. `getting-started/install` leads with the Mac app and the one-liner, then `tau setup`, then the manual way; `three-ways` and the docs home follow. Telegram, guard and network guides open with "the easy way: `tau setup` → …" (the phone guide had it). The tutorial pairs Telegram with `tau telegram pair` and points to the short way. The setup reference drops two stale notes (the app, Node.js for the spine); the universe reference lists `/download`.
    - **README** (EN + TR): the app download in step 1 and the header, the tau app in step 4, `tau telegram pair` in step 5; the tables name `apps/tau` (the old `apps/taubar` and `apps/tau-desktop` links were dead) and the installer, whose `tau setup` ships with the next tau-core release (0.4.0 on PyPI predates it).
    - Screenshots of `/download` and the landing, EN + TR, desktop (1440 px) and phone (390 px), checked: no horizontal scroll.
    - Left: the app's guide is still `guides/taubar` and `CONTEXT.md`/`ARCHITECTURE.md` still say TauBar (the rename is pending separately); the catalog's `setup.note.app.download` still says the app is not released. The download link works for visitors once the first release is published from a public repository.
