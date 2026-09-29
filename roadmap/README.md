# Roadmap

tau is built in layers. Each layer becomes useful on its own before the next one starts. Decisions behind the plan live in [`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md); the vocabulary lives in [`CONTEXT.md`](../CONTEXT.md).

| Layer | Goal |
|---|---|
| [L0 · Remote access](L0-remote/README.md) | Phone → Tailscale → mosh → tmux → Claude Code |
| [L1 · Agent](L1-agent/README.md) | Strands agent, persona, tiers, sessions, hub daemon |
| [L2 · Models](L2-models/README.md) | Role routing through a LiteLLM proxy with hard budgets |
| [L3 · Access and data](L3-cloud/README.md) | Tunnel + Access in front of the web UI, Telegram by direct polling, local settings/memory/KB, encrypted R2 backups (the directory keeps its old name) |
| [L4 · Interface](L4-interface/README.md) | TauBar, web UI, tau-voice, Claude Code integration, ambient mode |
| [L5 · Mesh](L5-mesh/README.md) | Zenoh + MCP nodes, MQTT bridge, reflex routines |
| [L6 · Robot](L6-robot/README.md) | SO-101 and the workout coach |
| [L7 · Lab](L7-lab/README.md) | AgentCore and other experiments |
| [L8 · Distribution](L8-distribution/README.md) | PyPI releases and the docs site |
| [Backlog](backlog/README.md) | Waiting on hardware or decisions |

```sh
python3 roadmap/board.py           # everything, grouped by layer
python3 roadmap/board.py --next    # what an agent can pick up now
python3 roadmap/board.py --human   # what needs you now
python3 roadmap/board.py --check   # validate after editing issues
```

## Issue files

One file per issue: `roadmap/<layer>/<NNN>-<slug>.md`. IDs are global, three digits, never reused. A new issue takes the highest existing id + 1, and also gets a row in its layer's README.

The header lines are read by `board.py` and must stay in this form:

```markdown
# 051 · Short imperative title

Status: needs-triage
Type: AFK
Layer: L5 · Mesh
Packages: tau-mesh
Blocked by: 032, 033

## What to build

End-to-end behavior of this vertical slice, not layer-by-layer steps.

## Acceptance criteria

- [ ] Observable, testable outcome

## Blocked by

- [032 · Title](032-slug.md)

## Comments
```

## Statuses

| Status | Meaning |
|---|---|
| `needs-triage` | New, not evaluated yet |
| `needs-info` | Blocked on a question; the question is in Comments |
| `ready-for-agent` | Fully specified; an AFK agent can do it end to end |
| `ready-for-human` | Needs the user: a decision, an account, or physical work |
| `needs-hardware` | Specified, but the hardware is not here yet |
| `in-progress` | Someone (human or agent) is on it |
| `done` | All acceptance criteria met |
| `wontfix` | Dropped; the reason is in Comments |

## Working an issue

1. Pick an issue with `--next` (agents) or `--human` (you). Never start an issue whose blockers are not `done`.
2. Set `Status: in-progress`.
3. Build the slice, keep tests green, commit in small Conventional Commits.
4. Tick the acceptance criteria, set `Status: done`, and append a dated note under `## Comments`: what changed, which commits, anything the next issue should know.
5. If the spec is wrong or unclear, set `needs-info`, write the question under `## Comments`, and stop.
6. Out-of-scope discoveries become new issues with `Status: needs-triage`.
