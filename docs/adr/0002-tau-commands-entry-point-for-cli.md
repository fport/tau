# 0002 · `tau.commands` entry point for CLI subcommands

- Status: accepted (issue 004)
- Date: 2026-09-29

## Context

The `tau` command is installed by `tau-core`, but some of its subcommands live in other
distributions (`tau tui` in `tau-tui`, later perhaps `tau mesh` or `tau robot`). A package in
another repository must be able to add a subcommand with `pip install`, without any change to
`tau-core`. ARCHITECTURE also reserves a `tau.channels` group for later.

## Decision

- A new entry point group **`tau.commands`**: each entry point resolves to a `click.Command`
  (a group is fine) and is mounted under `tau` with the entry point's name. `tau-core` itself
  registers `chat` and `hub` this way; `tau-tui` registers `tui`.
- The `tau` group loads a command only when it is invoked or when help lists it, so
  `tau version` stays fast and a broken plugin only logs a warning (with its distribution name).
- Global `--home` and `--profile` are exported as `TAU_HOME` and `TAU_PROFILE` for the duration
  of the command, so every plugin's `Config.load()` sees them without depending on tau-core's
  CLI internals.
- **`tau.channels` stays reserved for L3**: long-running, hub-hosted channels (Telegram relay,
  voice, the tau MCP server) that the hub starts and supervises. A CLI subcommand is not a
  channel in that sense, even when it offers a conversation (`tau chat`, `tau tui`).
- Tools use their own group, **`tau.tools`** (an `AgentTool`, a list of them, or a zero-argument
  factory; every tool must declare a tier).

## Consequences

- Plugins depend on `click`, which `tau-core` already requires.
- Two plugins registering the same command name: the first loaded wins; later ones are ignored.
