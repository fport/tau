# Roadmap and issues

tau's issues are Markdown files in the repository, under [`roadmap/`](https://github.com/fport/tau/tree/main/roadmap), one file per issue, grouped by layer. There are no GitHub issues. A small script, `roadmap/board.py`, reads the header lines of every file, prints the board and validates the tracker. This page is how to read it and how to work an issue.

## Layers

tau is built in layers; each becomes useful on its own before the next starts. The layer plan itself is in [ARCHITECTURE.md](../ARCHITECTURE.md).

| Layer | Goal |
|---|---|
| L0 · Remote access | Phone → Tailscale → mosh → tmux |
| L1 · Agent | Strands agent, persona, tiers, sessions, TUI, hub daemon |
| L2 · Models | Role routing to the user's provider (Anthropic, OpenAI, Gemini, Ollama) with hard budgets tau enforces itself |
| L3 · Access and data | Tunnel + Access in front of the web UI, Telegram by direct polling, local settings, memory and KB, encrypted R2 backups (the directory keeps its old name `L3-cloud`) |
| L4 · Interface | TauBar, the web UI, tau-voice, Claude Code integration, ambient mode |
| L5 · Mesh | Zenoh + MCP nodes, MQTT bridge, reflex routines |
| L6 · Robot | SO-101 and the workout coach |
| L7 · Lab | AgentCore and other experiments |
| L8 · Distribution | PyPI releases and the docs site |
| Backlog | Waiting on hardware or decisions |

Each layer directory has a `README.md` with the goal, a "done when" sentence and a table of its issues.

## The board

```sh
python3 roadmap/board.py               # everything, grouped by layer
python3 roadmap/board.py --next        # unblocked ready-for-agent issues
python3 roadmap/board.py --human       # unblocked ready-for-human issues
python3 roadmap/board.py --check       # validate the tracker (run after editing issues)
python3 roadmap/board.py --layer L3    # one layer; also `backlog`
```

```text
L1-agent
  003  ready-for-human  Provision model credentials with cost guards
  004  done             Tracer bullet: `tau chat` answers in the Jarvis persona
  006  done             Tool permission tiers with approval and a loop guard
  ...
```

`--next` prints only issues whose every blocker is `done`, so an agent (or you) can pick the top one without reading the graph.

## An issue file

`roadmap/<layer>/<NNN>-<slug>.md`. Ids are global, three digits, never reused; a new issue takes the highest existing id plus one and gets a row in its layer's README. The header lines are machine-read and must keep this form:

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

- **Type** is `AFK` (an agent can do it end to end), `HITL` (needs a human in the loop) or `needs-hardware`.
- **Packages** names the distributions or directories the work touches.
- **Blocked by** lists ids; the board refuses to offer an issue whose blockers are not `done`.
- **Comments** is an append-only log with dated notes.

## Statuses

| Status | Meaning |
|---|---|
| `needs-triage` | new, not evaluated yet |
| `needs-info` | blocked on a question, written under Comments |
| `ready-for-agent` | fully specified; an agent can do it end to end |
| `ready-for-human` | needs the user: a decision, an account, or physical work |
| `needs-hardware` | specified, but the hardware is not here yet |
| `in-progress` | someone, human or agent, is on it |
| `done` | all acceptance criteria met |
| `wontfix` | dropped; the reason is in Comments |

The five triage roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`) match the vocabulary of the engineering skills the repository uses; `needs-hardware`, `in-progress` and `done` are lifecycle states on top.

## Working an issue

1. Pick one with `--next` (agents) or `--human` (you). Never start an issue whose blockers are not `done`.
2. Set `Status: in-progress`.
3. Build the slice, keep the tests green, commit in small Conventional Commits that reference the id (`Refs: 051`).
4. Tick the acceptance criteria, set `Status: done`, and append a dated note under `## Comments`: what changed, which commits, anything the next issue should know.
5. If the spec is wrong or unclear, set `needs-info`, write the question under `## Comments`, and stop.
6. Out-of-scope discoveries become new issues with `Status: needs-triage`.
7. Run `python3 roadmap/board.py --check` after editing any issue file.

Two rules for agents working alone: never take a `ready-for-human` or `needs-hardware` issue, and never bypass the non-negotiables (tier-2 approval, simulation-first robot, no secrets in tracked files) to close one faster.

## Where the plan is explained

- [ARCHITECTURE.md](../ARCHITECTURE.md): every decision with its reasoning, the principles, the layer roadmap and a dated change log.
- [ADRs](../adr/0001-approval-through-strands-hooks.md): one file per significant decision; [0006](../adr/0006-private-first-topology.md) is the private-first topology this site is organized around.
- [`CONTEXT.md`](https://github.com/fport/tau/blob/main/CONTEXT.md): the glossary. Issues, code and docs use its terms exactly.
- [`CLAUDE.md`](https://github.com/fport/tau/blob/main/CLAUDE.md): the instructions coding agents follow in this repository.
