# tau

Personal "smart body" agent platform. A Strands agent runs on the **hub** (MacBook now, RPi5 later), talks to the user through Telegram, a TUI, the TauBar tray app and voice, reaches devices through **nodes** (MCP for capabilities, Zenoh for events), and keeps its state in Cloudflare.

Read before non-trivial work:

- `docs/ARCHITECTURE.md` — every decision, the principles and the layer roadmap (Turkish)
- `CONTEXT.md` — glossary; use its terms exactly
- `roadmap/README.md` — how issues are tracked and worked

## Language

- Talk to the user in Turkish.
- English for new code, identifiers, comments, commit messages, issues and package READMEs.
- Existing files keep their language: `docs/ARCHITECTURE.md` and everything in `infra/remote/` are Turkish. Don't translate them unasked.
- tau's own user-facing output (persona, Telegram, CLI messages) is Turkish.

## Repo map

```
docs/ARCHITECTURE.md   decisions + roadmap          CONTEXT.md    glossary
roadmap/               file-based issue tracker     CLAUDE.md     this file
infra/remote/          L0: Tailscale + OpenSSH + tmux/mosh setup (done, see its README)
packages/              publishable Python packages (tau-core, tau-tui, tau-mesh, tau-robot, …) — from #004 on
apps/taubar/           Tauri v2 + React tray app — from #024 on
cloud/tau-cloud/       Cloudflare Worker (TypeScript) — from #014 on
persona/  tools/       persona files; hot-reloaded tools (+ tools/_pending/)
```

Directories that don't exist yet are created by the issue that introduces them; follow the layout in `docs/ARCHITECTURE.md`.

## Packages and modularity

This repo is the center. Everything is built so it can be published or split out later.

- Every directory in `packages/` is an independently publishable PyPI distribution named `tau-<name>` with the flat import name `tau_<name>`. Do not use a `tau` namespace package: `tau` is taken on PyPI (as are `tau-hub` and `tau-agent`).
- Each package has its own `pyproject.toml`, version, README and tests, and depends on other packages only through their public API as declared dependencies — no path hacks, no private imports.
- Extension goes through entry points (`tau.tools`, and later `tau.nodes`, `tau.channels`). A package developed in another repo plugs in with `pip install`, without changes here.
- Split a package into its own repo when it needs its own release cadence, firmware or contributors; tau then consumes it from PyPI and the entry-point contract stays the same.
- Python 3.12+ with a uv workspace. TypeScript parts (`cloud/`, `apps/taubar`) use pnpm.

## Working on issues

- `python3 roadmap/board.py --next` lists what an agent may pick up. Only take `ready-for-agent` issues whose blockers are `done`.
- Never work `ready-for-human` or `needs-hardware` issues on your own; they need the user.
- Follow the workflow in `roadmap/README.md`: `in-progress` → build → tick acceptance criteria → `done` with a dated note under `## Comments`. Run `python3 roadmap/board.py --check` after editing issue files.
- Unclear spec: set `needs-info`, write the question under `## Comments`, stop. Out-of-scope findings become new `needs-triage` issues.

## Non-negotiables

- **Tiers:** tier-2 actions (physical world, activating self-written tools) always go through approval. Never bypass or auto-approve it, including in tests (use fakes for the approver instead).
- **Robot:** simulation is the default. Never enable real mode or move real hardware unless the user says so in the current session.
- **Reflexes** (routines, safety stops) must work without an LLM and without the cloud.
- **Models:** code asks for a role (`brain`/`fast`/`local`), never a hardcoded model id. Never add `litellm` as a Python dependency — the proxy runs as a digest-pinned container (PyPI compromise, March 2026).
- **Secrets:** never commit them. Local `.env` (gitignored), `wrangler secret` for Cloudflare.
- **Privacy:** the repo may go public, so nothing personal goes into tracked files: no hostnames, tailnet names, IP addresses, emails, account ids or key fingerprints. Use example values (`my-mac.tailXXXXXX.ts.net`, `100.x.y.z`, `SHA256:...`). Real values the user shares go into the gitignored `.env`, with the name and an example value in `.env.example`.
- **State:** the hub reaches D1/R2/Vectorize only through the `tau-cloud` Worker API. Raw telemetry never goes into D1.
- **Remote access:** changing `infra/remote/sshd/tau.conf` must keep password auth off and `AllowUsers` restricted to tailnet + localhost; re-run `infra/remote/doctor.sh`.

## Commits

Conventional Commits in English: `type(scope): summary` — scopes like `remote`, `core`, `tui`, `mesh`, `robot`, `cloud`, `taubar`, `roadmap`, `docs`. Small, logical commits; reference the issue id in the body (`Refs: 004`).

## Commands

```sh
python3 roadmap/board.py [--next|--human|--check|--layer L1]   # roadmap
infra/remote/doctor.sh                                         # remote access health
infra/remote/setup.sh                                          # re-apply remote access (idempotent)
```

Python and TypeScript commands are added here by the issues that introduce them (#004, #014, #024).

## Agent skills

### Issue tracker

Local markdown files under `roadmap/`, one per issue, grouped by layer. See `docs/agents/issue-tracker.md`.

### Triage labels

The `Status:` line of each issue file, using the five canonical roles plus `needs-hardware`, `in-progress`, `done`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/ARCHITECTURE.md` (+ `docs/adr/` for new decisions). See `docs/agents/domain.md`.
