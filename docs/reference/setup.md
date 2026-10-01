# `tau setup` and its JSON protocol

`tau setup` is the one engine that picks tau's features, installs their packages and sets them up ([ADR 0014](../adr/0014-one-installer-and-onboarding.md)). It has two front doors:

- **The terminal:** `curl -fsSL https://tau.getporti.com/install.sh | sh` installs uv and tau, then starts the wizard.
- **The Mac app:** its first-launch wizard drives the same engine through the JSON mode below.

This page specifies the installer, the wizard, the feature catalog and the JSON protocol. The protocol is the contract between tau-core and the app.

## The installer

```sh
curl -fsSL https://tau.getporti.com/install.sh | less   # read it first
curl -fsSL https://tau.getporti.com/install.sh | sh
```

The script is `cloud/universe/public/install.sh`, served by the universe Worker as `text/plain`. It is POSIX `sh`, and it:

1. refuses anything but macOS or Linux on a 64-bit x86 or ARM CPU;
2. installs [uv](https://docs.astral.sh/uv/) with Astral's official installer when uv is missing (into `~/.local/bin`, or `UV_INSTALL_DIR`), after saying so;
3. runs `uv tool install tau-core --with tau-tui`; an existing tau-core tool is left as it is;
4. starts `tau setup`, reading the answers from the terminal (`/dev/tty`), so the prompts work under `curl | sh`. Without a terminal it prints what to run instead.

It never runs `sudo`. The whole script runs from a `main` function called on its last line, so a download cut short runs nothing.

| Variable | Effect |
|---|---|
| `TAU_INSTALL_VERSION=x.y.z` | Install this version of tau-core and tau-tui instead of the latest. |
| `TAU_INSTALL_NO_SETUP=1` | Install only; run `tau setup` yourself later. |

## The wizard

```sh
tau setup                                   # the checklist, then install and set up
tau setup --yes --features tui,sub          # ask nothing
tau setup --yes --features tui,sub --no-install
tau setup --remove guard                    # uninstall a feature's package
tau setup --upgrade                         # the newest releases, pins dropped
```

1. **Language.** When neither `--lang`, `TAU_LANG` nor `[ui] language` in `tau.toml` gives one, the first question is `Language / Dil (en, tr)`.
2. **Checklist.** Every feature of the catalog, numbered, with its description and state. Numbers toggle a feature, Enter goes on, `q` quits.
    - On the first run (no `tau.toml` yet) the features marked `default` for this platform are chosen.
    - What is set up already shows `✓` and cannot be chosen again. Choosing it says how to remove it.
    - What this platform lacks shows why, for example the guard on Linux.
3. **Install.** The missing packages are installed with one `uv tool install` (below). tau setup then re-executes itself in the new environment and goes on.
4. **Set up**, in this order:
    - `tau init` when there is no `tau.toml`; it asks for the provider and the key at a hidden prompt;
    - "about you": your name, how tau should address you and your languages, written to `persona/user.md` (mode `0600`). An empty name skips it. It is asked while `user.md` is missing or still the shipped example;
    - each chosen feature's steps, in catalog order;
    - `tau doctor`.
5. **Summary.** Each feature is on, partly set up, skipped (with why) or failed, followed by the next commands and this page's link.

Every step asks first (`Y/n`, or `y/N` for an optional one) and can be skipped. A step that fails is reported and the others go on. The exit code is 1 when a step failed, else 0.

A **check step** (remote access, [below](#check-steps)) asks nothing first, because it changes nothing: it runs quietly and shows its result. When something is left that only the owner can do, it shows that action (a page to open, or a command to run in their own terminal, with what it changes), offers to open the page (`y/N`) and waits: **Enter** checks again, `skip` goes on without it. The command it shows is never run by tau.

`--yes` asks nothing:

- the language is the configured one, else English;
- on a first run without `--features` it takes the default features;
- it runs every step that is neither optional nor interactive;
- a check step runs once: when it needs the owner it is skipped with what it needs (`needs you: …`);
- `tau init --yes` falls back to the scripted `fake` provider when no key is present.

`tau setup run FEATURE` runs one feature's steps the same way, even when that feature is set up already. `tau setup status` prints the checklist with the feature ids.

### Installing and the re-execution

When tau runs from a `uv tool` environment (its `sys.prefix` holds `uv-receipt.toml`), the install is one command that describes the whole environment after the change:

```sh
uv tool install --force [--python 3.12] tau-core==0.4.0 \
  --with tau-tui==0.4.0 --with tau-guard==0.4.0 --with tau-net --with tau-sub
```

- **Pins.** tau-core and the lockstep packages (tau-tui and tau-guard, which are released with tau-core) are pinned to the running tau-core's version. tau-net, tau-sub and tau-cloud have their own versions: uv picks the newest release that works with the pinned tau-core.
- **What is kept.** Every feature package that is installed stays in the command. Any other requirement in the receipt (a plugin you added with `--with`) is passed on again, and so is the receipt's Python.
- **Upgrades.** Because of the pins, `uv tool upgrade tau-core` keeps the version. `tau setup --upgrade` reinstalls the same set without pins (`--upgrade`, newest releases).
- **Removal.** `tau setup --remove FEATURE` runs the same command without that feature's package, after a confirmation. Settings and data stay. The guard cannot be removed while it is enrolled: run `tau guard forget` at the Mac first, because a hub without tau-guard but with the enrollment marker stays locked.

After a successful install the wizard writes its state (the language, the chosen features, `--yes`) to `state.json` in a new temporary directory: the directory is `0700` and the file `0600`. It then replaces itself with `os.execv(<uv tool bin>/tau, ["tau", "setup", "--resume", <file>])`. The new process refuses the file when it is a symlink, when it is not owned by the same user, when its mode gives the group or others any access, when it is over 64 KiB or when it is not a version-1 object. It deletes the file and the directory when it reads them, and goes on with the configuration. `TAU_HOME`, `TAU_LANG` and `TAU_PROFILE` reach it through the environment.

Outside a uv tool environment, for example in a repository checkout or a virtualenv, nothing is reinstalled. The wizard names the missing packages, points to `uv sync --all-packages`, and sets up what is installed.

## The feature catalog

The features are data: `packages/tau-core/src/tau_core/templates/features.toml`. tau-core never imports a feature's package. A step is a `tau` subcommand run as a subprocess, and whether that subcommand exists is found through the `tau.commands` entry points. A feature that another package or issue adds is one more `[[feature]]` entry.

| id | package | platforms | default | steps |
|---|---|---|---|---|
| `tui` | tau-tui (lockstep) | macOS, Linux | on | none |
| `app` | none | macOS | off | a note pointing to the [download page](https://tau.getporti.com/download) |
| `sub` | tau-sub | macOS, Linux | on | a note on creating the first sub-tau |
| `telegram` | none (tau-core) | macOS, Linux | off | `tau telegram pair` (interactive) when that command exists; else the manual way |
| `remote` | none (tau-core) | macOS, Linux | off | check steps: `tau remote tailscale`, `tau remote ssh` (shows the one `sudo` command), `tau remote phone`; set up when `tau remote status` exits 0 |
| `guard` | tau-guard (lockstep) | macOS | off | `tau guard doctor` (advisory), `tau guard setup` (interactive, never over SSH), a note to restart the hub |
| `net` | tau-net | macOS, Linux | off | `tau net init`, a note on the spine, `tau net spine init` and `deploy` (optional; the deploy takes a Cloudflare API token), `tau net universe join` and `claim` (optional) |
| `autostart` | none | macOS, Linux | on on macOS | `tau hub install` (macOS); the systemd user unit commands (Linux) |
| `cloud` | tau-cloud (requires `net`) | macOS, Linux | off | a note and the cloud mode guide |

Nothing turns on the network, the guard, Telegram or remote access unless the owner chooses it. No step runs `sudo`, and tier 2 is unchanged. [Setup features](../guides/setup-features.md) walks through each feature for owners: what it needs, what it changes and how to remove it.

### Schema

Top level:

| Key | Meaning |
|---|---|
| `schema` | `1`. |
| `docs` | The docs site's base URL, ending in `/`. A feature's `docs` path is relative to it, and Turkish adds `tr/`. |
| `[[feature]]` | The features, in the order the wizard shows and sets them up. A feature comes after the features it requires. |

`[[feature]]`:

| Key | Type | Meaning |
|---|---|---|
| `id` | string | `[a-z][a-z0-9-]*`, unique. |
| `package` | string | The PyPI distribution (`tau-*`), or absent. |
| `lockstep` | bool | Pinned to tau-core's version (needs `package`). |
| `label`, `description` | message key | Texts in the i18n table (`tau_core/setup/strings.py`, en + tr). |
| `platforms` | list | `darwin`, `linux`. |
| `unavailable` | message key | Why the feature is missing on the other platforms (required when it is). |
| `default` | bool or list | Chosen on a first run: everywhere (`true`) or on the listed platforms. |
| `permissions` | list | macOS permissions the app asks for: `camera`, `notifications`, `microphone`. |
| `requires` | list | Feature ids chosen along with this one. |
| `advanced` | bool | Marked as advanced in the checklist. |
| `docs` | string | The guide, relative to the top-level `docs`. |
| `keep_while_configured` | message key | `--remove` refuses with this text while the feature is set up. |
| `[feature.configured]` | table | When the feature counts as set up (below). Without it, a feature with a package is set up once the package is installed, and a feature without one never is. |
| `[[feature.step]]` | tables | The steps, in order. |

`[feature.configured]` holds when every listed rule holds:

- `files`: every path exists;
- `any_files`: at least one path exists;
- `env`: every variable is set in the environment or `<home>/.env`;
- `command`: `tau <command>` exits 0. It is asked last, because it starts a subprocess, and only on the feature's platforms. Remote access is set up when `tau remote status` passes.

In a path, `{home}` is the configuration root, `{data}` the data dir (`TAU_DATA_DIR`) and a leading `~` the user's home. For example, the guard is set up when `{data}/guard/enrolled` exists, and the network when `{data}/net/identity.json` does.

`[[feature.step]]`:

| Key | Type | Meaning |
|---|---|---|
| `id` | string | Unique within the feature. |
| `kind` | string | `command` (default) or `note`. |
| `label` | message key | Shown before the step. |
| `command` | list | The arguments after `tau`, e.g. `["guard", "setup"]`. Only words and `--flags`, and never `sudo`. |
| `interactive` | bool | Needs the owner at a terminal. The wizard gives it the terminal, `--yes` skips it, and JSON mode reports it as `needs_ui`. |
| `check` | bool | The command is a [check](#check-steps): `tau <command> --json` prints one check object. Not with `interactive`, `advisory` or inputs. |
| `optional` | bool | Asked with the default "no". `--yes` skips it, and JSON mode runs it only when asked for. |
| `advisory` | bool | A nonzero exit is reported, not counted as a failure. `tau guard doctor` fails before setup, as expected. |
| `local_only` | bool | Refused over SSH (`SSH_CONNECTION` or `SSH_TTY` set). |
| `platforms` | list | Only on these platforms (default: the feature's). |
| `when_command` + `unavailable` | list + message key | Run only when `tau <when_command> --help` succeeds; otherwise the text is shown instead. |
| `needs` + `needs_text` | list + message key | Programs that must be on `PATH`; otherwise the text is shown and the step skipped. |
| `text`, `url` | message key, https URL | A note's text and link. |
| `[[feature.step.input]]` | tables | Values the step takes (below). |

`[[feature.step.input]]`:

| Key | Meaning |
|---|---|
| `name` | `[a-z][a-z0-9_]*`. Steps of one feature share values by name, so `spine_dir` is asked once. |
| `label` | Message key for the prompt. |
| `flag` or `positional` | Where a plain value goes in argv: after the flag, or as a positional argument. An empty optional value is left out. |
| `secret` + `env` | A secret never reaches argv: it is written to `<home>/.env` (mode `0600`) under `env` before the step runs, and the step reads it from there. An existing value is kept. The wizard asks for it with hidden input. |
| `required` | Without a value the step is skipped (`no_input`). |
| `default` | The value when none is given. |
| `path` | A leading `~` is expanded. |

The catalog is validated when it loads. An unknown key, platform or permission is refused, and so are a missing message key, a `requires` cycle or order, a secret with a flag, and a command word that is not a plain word. A test keeps every text in both languages.

## The JSON protocol

Three commands serve the app. Each writes UTF-8 JSON to stdout. Anything on stderr is free text for a log and never part of the protocol. Labels and messages come in the UI language: `tau --lang tr setup …`, `TAU_LANG`, else `[ui] language`, else English.

### `tau setup status --json`

One JSON object (indented), exit code 0.

```json
{
  "protocol": 1,
  "version": "0.4.0",
  "platform": "darwin",
  "platform_label": "macOS",
  "language": "en",
  "ssh": false,
  "install": {"mode": "uv-tool", "can_install": true},
  "home": "~/.tau",
  "config": false,
  "about": false,
  "core_steps": ["init", "about", "doctor"],
  "features": [
    {
      "id": "guard",
      "label": "Owner guard",
      "description": "tau answers only while you are at the Mac (face check, Touch ID)",
      "package": "tau-guard",
      "lockstep": true,
      "platforms": ["darwin"],
      "available": true,
      "unavailable_reason": null,
      "default": false,
      "advanced": false,
      "permissions": [{"id": "camera", "label": "camera"}],
      "requires": [],
      "installed": false,
      "version": null,
      "configured": false,
      "state": "missing",
      "docs": "https://docs.tau.getporti.com/guides/guard/",
      "steps": [
        {"id": "doctor", "kind": "command", "label": "Check the guard's prerequisites",
         "interactive": false, "optional": false, "local_only": false,
         "command": ["guard", "doctor"], "inputs": []},
        {"id": "setup", "kind": "command", "label": "Enroll your face and switch the guard on",
         "interactive": true, "optional": false, "local_only": true,
         "command": ["guard", "setup"], "inputs": []},
        {"id": "restart", "kind": "note", "label": "Restart the hub",
         "interactive": false, "optional": false, "local_only": false,
         "text": "The guard starts with the next hub, locked: …", "inputs": []}
      ]
    }
  ]
}
```

- Paths are absolute in the real output (this page shortens them to `~`).
- `install.mode` is `uv-tool` when tau can install packages itself, else `environment` (a checkout or a virtualenv: `install` answers `not_uv_tool`).
- `config` is whether `<home>/tau.toml` exists. `about` is whether `persona/user.md` holds facts of its own.
- `state` is one of:
    - `done`: set up;
    - `installed`: the package is there, the feature is not set up;
    - `missing`: the package is not installed;
    - `available`: nothing to install and nothing says it is set up;
    - `unavailable`: not on this platform, with `unavailable_reason`.
- `steps` lists only this platform's steps. Every step has `check` (a [check step](#check-steps)). A step can also carry `text` and `url` (notes), `needs` (programs) and `when_command`.
- Each input is `{name, label, secret, required, default}`.

### Event lines

`install` and `run` print one JSON object per line, flushed as it happens:

| `event` | Fields | Meaning |
|---|---|---|
| `progress` | `phase` (install), or `feature`, `step`, `status`, `label` and optional `reason`, `detail`, `code`, `command`, `text`, `url` (run) | A phase or a step's state: `running`, `checking` (a key check or a check step), `done`, `failed`, `skipped` or `info` (a note). |
| `check` | `feature`, `step`, `ok`, `summary`, `checks`, `action`, `values` | The result of a [check step](#check-steps). |
| `log` | `line`; in `run` also `feature` and `step` | One line of a subprocess's output (stdout and stderr merged), or a notice such as a key written to `.env`. |
| `needs_ui` | `feature`, `step`, `label`, then either `command` (the arguments after `tau`) and `argv` (the full argv), or `summary` and `action` | A step that needs its own UI, or a check that waits for the owner. With `argv` the step was not run and the app runs it; with `action` there is nothing to run, only something to show. The run stops here. |
| `done` | `ok` and the command's fields | The last line of a run that got to the end. |
| `error` | `code`, `message` (localized) and sometimes `feature` or `exit` | The last line of a run that could not start or could not finish. |

The last line is always exactly one `done` or `error`, and no other line has either. The exit code is 0 for a `done` with `"ok": true`, otherwise 1. A `failed` step makes `ok` false. A `skipped` one does not.

Error codes:

| `code` | From | Meaning |
|---|---|---|
| `unknown_feature` | install, run | No such feature id. |
| `unavailable` | install, run | Not on this platform. |
| `not_uv_tool` | install | Not a uv tool environment; install the packages yourself. |
| `uv_missing` | install | uv is not on `PATH` nor where its installer puts it. |
| `install_failed` | install | uv exited non-zero (`exit`) or could not start. |
| `bad_input` | run | stdin is not the object below, or it names an input the chosen steps do not take. |
| `unknown_step` | run | `steps` names a step the feature does not have on this platform. |
| `not_installed` | run | The feature's package is missing; call `install` first. |
| `bad_provider`, `key_invalid`, `key_refused`, `key_not_written` | run init | The provider is not one tau takes a key for; the key holds spaces or quotes; the provider refused it (`check`, `status`); `.env` could not be written. |

### `tau setup install --features a,b --json`

Installs the packages of the features (and of what they require) with the one `uv tool install` above, and sets nothing up. It does not re-execute: the app starts a new `tau` for its next call.

```json
{"event": "progress", "phase": "plan", "features": ["net", "cloud"], "added": ["tau-net", "tau-cloud"], "packages": ["tau-tui", "tau-net", "tau-cloud"]}
{"event": "progress", "phase": "install", "argv": ["~/.local/bin/uv", "tool", "install", "--force", "tau-core==0.4.0", "--with", "tau-tui==0.4.0", "--with", "tau-net", "--with", "tau-cloud"]}
{"event": "log", "line": "Resolved 42 packages in 1.20s"}
{"event": "done", "ok": true, "installed": ["tau-net", "tau-cloud"], "changed": true}
```

With nothing to install, the stream is the plan and `{"event": "done", "ok": true, "installed": [], "changed": false}`.

### `tau setup run <target> --json`

`target` is a feature id or one of the core steps `init`, `about` and `doctor`. The input is **one JSON object on stdin**, never argv (an empty stdin is `{}`, at most 64 KiB):

```json
{"steps": ["init", "universe"], "inputs": {"name": "Alice's tau", "owner": "Alice"}, "check": true}
```

- `steps` (optional): the step ids to run, in catalog order. By default every step that is not optional runs.
- `inputs` (optional): input values by name, all strings. A secret goes to `<home>/.env` (mode `0600`) and never into argv or the output.
- `check` (optional, `init` only): `false` skips the key check.

A feature's steps run one after the other, each command step as `tau <command>` with its output streamed as `log` lines:

- a step this machine cannot run is `skipped` with a `reason` and a localized `detail`: `platform`, `ssh`, `missing_command`, `needs` or `no_input`;
- a note is `info` with its `text` and `url`;
- an interactive step ends the run with `needs_ui`. The app runs `argv` itself, in a terminal view or through its own UI. For the guard that is enrolment in the app, which holds the camera permission. The app then calls `run` again with the steps in `pending`;
- a check step is `checking`, then a `check` event, then `done`, or `failed` (reason `check`) when it fails with nothing the owner can do. When it fails with an action, `needs_ui` carries that action and the run stops with the check itself first in `pending`, so running `pending` again checks again ([below](#check-steps)).

```text
$ echo '{}' | tau setup run guard --json
{"event": "progress", "feature": "guard", "step": "doctor", "status": "running", "label": "Check the guard's prerequisites", "command": ["guard", "doctor"]}
{"event": "log", "feature": "guard", "step": "doctor", "line": "fail sface: …"}
{"event": "progress", "feature": "guard", "step": "doctor", "status": "done", "reason": "advisory", "detail": "reported problems (exit code 1); the next steps fix the expected ones", "code": 1, "label": "Check the guard's prerequisites"}
{"event": "needs_ui", "feature": "guard", "step": "setup", "label": "Enroll your face and switch the guard on", "command": ["guard", "setup"], "argv": ["~/.local/share/uv/tools/tau-core/bin/python", "-m", "tau_core", "guard", "setup"]}
{"event": "done", "feature": "guard", "ok": true, "configured": false, "results": [{"step": "doctor", "status": "done", "reason": "advisory", "detail": "…", "code": 1}, {"step": "setup", "status": "needs_ui"}], "pending": ["restart"]}
```

`done` for a feature carries `configured`, whether the feature counts as set up now, and `results`, one entry per step with `step`, `status` and optional `reason`, `detail` and `code`.

The core steps:

- **`init`** (inputs `language`, `provider`, `key`). When there is no `tau.toml`, the key is checked with one small request to the provider (unless `"check": false`), written to `<home>/.env` as `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or `GEMINI_API_KEY`, and then `tau init --yes --language … --provider …` runs. A refused key writes nothing. With a `tau.toml` already there the step is `skipped` (`configured`).

    ```text
    $ printf '%s' '{"inputs": {"provider": "anthropic", "key": "sk-…"}}' | tau setup run init --json
    {"event": "progress", "feature": "setup", "step": "init", "status": "checking", "label": "Model provider and key"}
    {"event": "log", "feature": "setup", "step": "init", "line": "wrote ANTHROPIC_API_KEY to ~/.tau/.env (mode 0600)"}
    {"event": "progress", "feature": "setup", "step": "init", "status": "running", "label": "Model provider and key", "command": ["init", "--yes", "--language", "en", "--provider", "anthropic"]}
    {"event": "log", "feature": "setup", "step": "init", "line": "wrote ~/.tau/tau.toml"}
    {"event": "progress", "feature": "setup", "step": "init", "status": "done", "code": 0, "label": "Model provider and key"}
    {"event": "done", "feature": "setup", "step": "init", "ok": true, "results": [{"step": "init", "status": "done", "code": 0}], "pending": []}
    ```

- **`about`** (inputs `name`, `address`, `languages`) writes `persona/user.md`. Without a name it is `skipped` (`no_input`), and a `user.md` with facts of its own is kept (`configured`).
- **`doctor`** runs `tau doctor --json`. Its `done` carries the doctor's `checks` and `ok` is whether none failed.

### Check steps

A step with `check = true` names a command that reports a state instead of changing one. `tau <command> --json` prints one JSON object and exits 0 when the check passes, else 1:

```json
{
  "check": 1,
  "ok": false,
  "summary": "6 problem(s) with SSH, mosh or tmux",
  "checks": [
    {"id": "sshd", "label": "SSH server", "status": "fail", "detail": "off (Remote Login)"},
    {"id": "tmux", "label": "tmux", "status": "ok", "detail": "/opt/homebrew/bin/tmux"},
    {"id": "tmux_conf", "label": "~/.tmux.conf block (tau's tmux settings)", "status": "warn", "detail": "missing"}
  ],
  "action": {
    "kind": "sudo",
    "text": "Run this in your own terminal, as yourself and not with sudo: it asks for your password (sudo) only for the steps that need root. tau never runs it.",
    "command": "bash ~/.local/share/tau/remote/setup-all.sh",
    "sudo": true,
    "url": null,
    "changes": ["installs tmux and mosh with Homebrew", "…", "with sudo: writes /etc/ssh/sshd_config.d/010-tau.conf: keys only …"],
    "script": "~/.local/share/tau/remote/setup-all.sh"
  },
  "values": {"user": "alice", "script": "~/.local/share/tau/remote/setup-all.sh"}
}
```

- `checks` are the lines to show, each `ok`, `fail`, `warn` or `info`. The check passes when no line is `fail`.
- `action` (or `null`) is what only the owner can do. `kind` is `install` (an app or program), `login`, `sudo` (a command that asks for the password), `key` (the phone's key) or `other`. `command` is to **show, with a copy button, never to run**: neither tau nor the app runs it. `sudo` says it asks for the password. `url` is an `https` page the owner may open, `changes` what the command changes, one line each, and `script` the file behind the command, to read first.
- `values` are what the check found, for the app to show its own way. For the phone step: `host` (the MagicDNS name, else the 100.x address), `ip`, `user`, `port`, `mosh`, `startup` and `keys`. They are printed, never written to a file.
- Every text is in the UI language. Paths are absolute in the real output; this page shortens them to `~`.

In JSON mode the engine runs the check and passes its object on as a `check` event (without `"check": 1`). The remote access run on a Mac whose SSH part is not set up yet:

```text
$ echo '{}' | tau setup run remote --json
{"event": "progress", "feature": "remote", "step": "tailscale", "status": "checking", "label": "Tailscale on this machine", "command": ["remote", "tailscale"]}
{"event": "check", "feature": "remote", "step": "tailscale", "ok": true, "summary": "Tailscale is connected as my-mac.tailXXXXXX.ts.net", "checks": […], "action": null, "values": {"cli": "/Applications/Tailscale.app/Contents/MacOS/Tailscale", "state": "Running", "host": "my-mac.tailXXXXXX.ts.net", "ip": "100.x.y.z", "magicdns": true}}
{"event": "progress", "feature": "remote", "step": "tailscale", "status": "done", "code": 0, "label": "Tailscale on this machine"}
{"event": "progress", "feature": "remote", "step": "ssh", "status": "checking", "label": "SSH and mosh", "command": ["remote", "ssh"]}
{"event": "check", "feature": "remote", "step": "ssh", "ok": false, "summary": "6 problem(s) with SSH, mosh or tmux", "checks": […], "action": {"kind": "sudo", "command": "bash ~/.local/share/tau/remote/setup-all.sh", "sudo": true, …}, "values": {…}}
{"event": "needs_ui", "feature": "remote", "step": "ssh", "label": "SSH and mosh", "summary": "6 problem(s) with SSH, mosh or tmux", "action": {"kind": "sudo", "text": "Run this in your own terminal, …", "command": "bash ~/.local/share/tau/remote/setup-all.sh", "sudo": true, "url": null, "changes": […], "script": "~/.local/share/tau/remote/setup-all.sh"}}
{"event": "done", "feature": "remote", "ok": true, "configured": false, "results": [{"step": "tailscale", "status": "done", "code": 0}, {"step": "ssh", "status": "needs_ui"}], "pending": ["ssh", "phone"]}
```

The app shows the action: the text, the command with a copy button and a note that it asks for the password in Terminal, the changes, the script, and a button for `url`. When the owner says they are done, it calls `run` with `{"steps": ["ssh", "phone"]}`, which checks again; when they skip, it calls `run` with the steps after it.

#### Remote access

`tau remote` (tau-core) holds the three checks ([CLI](cli.md#tau-remote)):

| Step | Passes when | Otherwise the action |
|---|---|---|
| `tailscale` | The CLI is found (on `PATH`, or `/Applications/Tailscale.app/Contents/MacOS/Tailscale`) and `tailscale status --json` says `BackendState` `Running`, with a MagicDNS name or a 100.x address. | Missing: macOS, `install` with the page `https://tailscale.com/download/mac` (the Mac App Store or the download); Linux, `install` with the official install script and `sudo tailscale up` (`sudo`). Logged out or off: `login`, `open -a Tailscale` (macOS) or `sudo tailscale up` (Linux). The service down on Linux: `sudo systemctl enable --now tailscaled && sudo tailscale up`. Waiting for approval: the admin console. |
| `ssh` | Port 22 answers; `/etc/ssh/sshd_config.d/010-tau.conf` has `PasswordAuthentication no`, `KbdInteractiveAuthentication no` and only `AllowUsers <you>@<tailnet or localhost>` entries; `/etc/ssh/sshd_config` includes `sshd_config.d` (when readable); a password login on localhost is refused (`ssh -o BatchMode=yes …`, only with port 22 and the drop-in there); `mosh`, `mosh-server` and `tmux` are found; on macOS the `~/.zshenv` block is there. A drop-in that differs from tau's template only warns. | `sudo`: `bash <kit>/setup-all.sh` with what it changes on this platform. Without Homebrew on a Mac that lacks mosh or tmux, the text says to install it first and `url` is `https://brew.sh`. |
| `phone` | Tailscale is connected and `~/.ssh/authorized_keys` holds a key, writable by nobody else. | No address: the Tailscale action. No key: `key`, `bash <kit>/add-key.sh` (no sudo). A key file others can write: `chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys`. |

`<kit>` is `infra/remote` in a repository checkout. An installed tau has none, so tau-core ships a copy of it as package data (`tau_core/remote/kit/`, kept equal to `infra/remote` by a test) and `tau remote ssh` and `phone` write it to `$TAU_DATA_DIR/remote/` (mode `0700`, changed files replaced, `config.local.env` kept) before they show a command. The copy comes with the release the owner installed and works offline; a download would need a pinned commit and a hash per release for the same bytes. `tau remote status`, which `tau setup status` runs for the `configured` rule, writes nothing.

`setup-all.sh` refuses to run as root. On macOS it runs `setup.sh` (Homebrew: tmux and mosh; the `~/.zshenv` and `~/.tmux.conf` blocks; `tau-attach`; the keep-awake agent) and then `setup-sudo.sh` (Tailscale.app when missing; with sudo the drop-in, tested with `sshd -t` and rolled back on failure, host keys, Remote Login). On Linux it runs `setup-linux.sh`: over SSH without a key it stops first; then with sudo the drop-in, openssh-server, mosh and tmux (apt-get, dnf or pacman), the `Include` check, host keys and `sshd -t`; the `~/.tmux.conf` block and `tau-attach`; with sudo the SSH service enabled and reloaded.

## Later issues plug in here

- **172, Telegram pairing:** `tau telegram pair` makes the `telegram` step run. A token taken by the engine would be a `secret` input with `env = "TELEGRAM_BOT_TOKEN"`.
- **173, remote access (done):** the `remote` feature is three [check steps](#check-steps) of `tau remote`; its `sudo` command is shown in a `needs_ui` action, never run.
- **174, spine deploy through the Cloudflare API:** gives `spine-deploy` a secret input with `env = "CLOUDFLARE_API_TOKEN"` and drops `needs = ["node"]`.
- **171, the app's wizard:** reads `status`, installs with `install`, runs each feature with `run`, handles `needs_ui` itself (running `argv`, or showing an `action` and running `pending` again) and asks macOS for the listed `permissions` of the chosen features only.
