# tau-tui

A [Textual](https://textual.textualize.io/) terminal interface for tau: a chat pane, a live
event pane (tool calls with tier and approval result, errors) and in-TUI approval dialogs for
tier-2 calls. Usable at 80x24 and over SSH/mosh from a phone.

It is its own distribution (`tau-tui`, import `tau_tui`) and uses only the public API of
`tau-core`. It plugs into the `tau` command through the `tau.commands` entry point:

```sh
pip install tau-tui
tau tui
```

Status: skeleton. The command exists and prints a placeholder until issue 008 builds the app.

License: MIT.
