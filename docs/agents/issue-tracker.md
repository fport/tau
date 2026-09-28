# Issue tracker: local markdown in `roadmap/`

Issues for this repo live as markdown files under `roadmap/`, grouped by layer. There are no GitHub issues.

## Conventions

- One directory per layer: `roadmap/L0-remote/`, `roadmap/L1-agent/`, … `roadmap/backlog/`. Each has a `README.md` with the layer goal and an issue table.
- One file per issue: `roadmap/<layer>/<NNN>-<slug>.md`. IDs are global, three digits, never reused; a new issue takes the highest id + 1 and gets a row in its layer README.
- Header lines right under the title (`Status:`, `Type:`, `Layer:`, `Packages:`, `Blocked by:`) are machine-read by `roadmap/board.py`; keep their format.
- Triage state is the `Status:` line (see `triage-labels.md`).
- Conversation history and progress notes append to the bottom under `## Comments`, dated.
- A PRD for a larger feature, if ever needed, goes in the layer directory as `PRD-<slug>.md`.
- After editing issues run `python3 roadmap/board.py --check`.

## When a skill says "publish to the issue tracker"

Create a new issue file in the right layer directory using the template in `roadmap/README.md`, and add its row to that layer's README.

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will usually give the id (e.g. `014`); find it with `ls roadmap/*/014-*.md`.
