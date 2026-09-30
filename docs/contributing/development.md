# Development setup

The repository is a uv workspace of independently publishable Python packages plus, later, TypeScript parts managed with pnpm. This page gets you to a green test run and explains the checks CI enforces.

## Requirements

- Python 3.12 (uv installs it if needed)
- [uv](https://docs.astral.sh/uv/)
- git

## Clone and sync

```sh
git clone https://github.com/fport/tau.git
cd tau
uv sync --all-packages --group dev
```

`--all-packages` installs every workspace member in editable mode: `tau-core`, `tau-tui` and the three test-fixture distributions under `packages/tau-core/tests/fixtures/` (`tau-example-tool`, `tau-example-provider`, `tau-example-service`). `--group dev` adds pytest, pytest-asyncio, pytest-textual-snapshot and ruff. A separate `docs` group holds MkDocs Material and mkdocs-static-i18n.

Never `pip install` into the system Python; everything runs through `uv run`.

## Layout

```text
packages/
├── tau-core/            build_agent, persona, tiers, roles, sessions, the tau CLI, tau hub
│   ├── src/tau_core/
│   └── tests/           pytest; fixtures/ holds the three example plugin distributions
└── tau-tui/             the Textual interface
    ├── src/tau_tui/
    └── tests/           pilot tests and SVG snapshots
persona/                 persona.md (tracked), user.example.md (tracked), user.md (gitignored)
infra/remote/            Tailscale + OpenSSH + tmux/mosh setup scripts
infra/services/          rendered launchd plist and systemd unit examples
roadmap/                 the issue tracker: one markdown file per issue, board.py
docs/                    this site, ARCHITECTURE.md, the ADRs
tau.toml · .env.example  the repository's own configuration root
```

Every directory under `packages/` is a PyPI distribution named `tau-<name>` with the flat import name `tau_<name>`. There is no `tau` namespace package. Packages depend on each other only through public APIs and declared dependencies: no path hacks, no private imports.

## Run tau from the checkout

The repository root holds a `tau.toml`, so it is a configuration root:

```sh
uv run tau doctor
uv run tau chat
uv run tau tui
uv run tau components
```

Credentials go into `.env` at the root (gitignored; names in `.env.example`). Sessions and logs go to `~/.local/share/tau`, never into the checkout.

## Tests

```sh
uv run pytest -q                              # everything, offline
uv run pytest packages/tau-core -q
uv run pytest packages/tau-tui -q             # pilot + snapshot tests
uv run pytest -q -k approval                  # a subset
```

The suite needs no credentials and no network. `tau_core.testing` provides the pieces:

| Helper | Use |
|---|---|
| `FakeModel([...])` | a scripted Strands model: text replies, tool calls (`ToolCall`), truncation (`Truncated`) |
| `ScriptedApprover([Decision.APPROVED, ...])` | scripted approval decisions; tier 2 is still never auto-approved |
| `UnansweredApprover` | never answers, for timeout tests |
| `test_config(tmp_path, **overrides)` | a throwaway `TAU_HOME` and `TAU_DATA_DIR` under a temporary directory, so tests never read your real files |
| `record_events(bus, *kinds)` | collect agent events from an `EventBus` |

Rules that tests enforce (and that you must not weaken):

- tier-2 calls always go through an approver; no test auto-approves;
- no model id appears under `packages/*/src` (`test_repo_rules.py`);
- the tracked persona files hold no email, address, tailnet name or home path;
- the shipped templates equal the repository's `tau.toml`, `persona/persona.md` and `persona/user.example.md`;
- the rendered service files in `infra/services/` equal the package templates.

### TUI snapshots

The TUI has fourteen SVG snapshots under `packages/tau-tui/tests/__snapshots__/test_snapshots/` as `.raw` files (pytest-textual-snapshot 1.0 with syrupy 6). Every snapshot uses the fixed session id `20260929-120000-abcd` (the setup screen, which has no session, is checked for paths only), the pinned version `0.0.0` on the welcome card (`build_app(version=...)`, so a release never changes a snapshot), a fixed clock, UTC event times, no motion and no durations, and is taken after the streams stopped; the settings snapshot runs with `show_paths=False` so no directory of the test machine appears.

```sh
uv run pytest packages/tau-tui --snapshot-update    # after an intended visual change
```

Review a regenerated file before committing it; it must never contain a local path, which the test also checks. Behaviour tests read the widgets through text oracles (`Transcript.text`, `EventLog.text`, `HintBar.text`, …) so that behaviour changes do not churn the snapshots.

## Lint and format

```sh
uv run ruff check .
uv run ruff format .          # CI runs `ruff format --check .`
```

Ruff runs with `line-length = 100`, target `py312`, rules `E`, `F`, `I`, `UP`, `B`. `docs/` and `roadmap/` are excluded (the board and the brand renderer predate the workspace).

## Build a wheel

```sh
uv build --package tau-core
uv build --package tau-tui
ls dist/
```

Each package builds on its own from its `pyproject.toml` (hatchling). Publishing is described in [Releasing](release.md).

## CI

`.github/workflows/ci.yml` runs on every push to `main` and on pull requests, on Ubuntu with Python 3.12:

```sh
uv sync --all-packages --group dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv build --package tau-core
uv build --package tau-tui
```

Make the same six commands pass locally before you push.

## The docs site

```sh
uv sync --group docs
uv run --group docs mkdocs serve          # http://127.0.0.1:8000
uv run --group docs mkdocs build --strict # what the deploy runs; no warnings allowed
```

Pages are Markdown under `docs/`, the navigation is in `mkdocs.yml`. `--strict` fails on a missing page, a broken relative link or a bad snippet path. Links to files outside `docs/` (the roadmap, the packages) must be absolute GitHub URLs.

### English pages and their Turkish twins

The site is bilingual through [mkdocs-static-i18n](https://ultrabug.github.io/mkdocs-static-i18n/) with the suffix layout. `page.md` is English and the source; `page.tr.md` next to it is its Turkish twin, served under `/tr/`. A page without a twin is served in English under `/tr/` as well (`fallback_to_default`), so ADRs, reference pages and anything not translated yet still work there, and a link from a Turkish page to such a page lands on the English one.

- Twins exist for the home page, `getting-started/` and `guides/`. ADRs, issues and most reference pages stay English only.
- **Change an English page and its twin together.** If you cannot translate the change, put `<!-- tr: out of date -->` at the top of the twin so the drift is visible until someone updates it.
- A twin starts with `<!-- tr twin of <page>.md, translated YYYY-MM-DD -->`; update the date when you bring it level with the English page.
- Commands, code blocks, paths, config keys, environment variables, CLI output and URLs stay exactly as in the English page, and `<!-- verified: ... -->` markers are copied unchanged.
- A heading that another page links to by anchor keeps its English anchor in the twin, for example `## 2. Spine'ını deploy et { #2-deploy-your-spine }`, so the same link works in both languages.
- Nav labels are translated in `mkdocs.yml`, under the `i18n` plugin's `nav_translations`. A new nav entry needs its Turkish label there, or it shows in English on the Turkish site.
- Search indexes both languages (`lang: [en, tr]` on the `search` plugin).

## Conventions

- **Language.** Code, identifiers, comments, commit messages, issues and docs are English; the docs site adds Turkish twins of its guides (see [above](#english-pages-and-their-turkish-twins)). tau's own persona is Turkish by default and mirrors the user; the UI chrome follows `[ui] language`.
- **Commits.** [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): summary`, scopes such as `core`, `tui`, `remote`, `roadmap`, `docs`, `cloud`, `taubar`. Small, logical commits; reference the issue id in the body (`Refs: 004`).
- **Privacy.** Nothing personal in tracked files: no hostnames, tailnet names, IPs, emails, account ids or key fingerprints. Use `my-mac.tailXXXXXX.ts.net`, `100.x.y.z`, `SHA256:...`. Real values go into the gitignored `.env`, with the name and an example value in `.env.example`.
- **Models.** Code asks for a role, never a model id; ids and prices are data (`tau.toml`, `templates/models.toml`, `templates/prices.toml`). Providers are called directly and tau enforces the budgets itself ([ADR 0011](../adr/0011-budgets-in-tau-no-litellm.md)); `litellm` is never added in any form.
- **Vocabulary.** [`CONTEXT.md`](https://github.com/fport/tau/blob/main/CONTEXT.md) is the glossary; use its terms exactly. Decisions are in [ARCHITECTURE.md](../ARCHITECTURE.md) and the ADRs; a new decision gets a new ADR.
- **Issues.** Work is tracked in `roadmap/`; see [Roadmap and issues](roadmap.md).
