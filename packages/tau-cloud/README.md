# tau-cloud

tau's **cloud mode**: the same Python hub (`tau hub run`) runs as a Cloudflare Container that
the owner's spine Worker manages, in the owner's own Cloudflare account, and keeps its life
data in the spine: sessions in D1, `tau.toml` and the persona files in KV. Nothing moves to
Cloudflare until the owner deploys the cloud configuration of the spine and runs
`tau cloud push`. The decision is ADR 0007; the contract is §5 of
`docs/reference/tau-network.md`; the walkthrough is `docs/guides/cloud-mode.md`.

It is its own distribution (`tau-cloud`, import `tau_cloud`), uses only the public API of
`tau-core` and `tau-net`, and plugs in through two entry points:

| group | name | what |
|---|---|---|
| `tau.sessions` | `spine` | the session backend `[sessions] backend = "spine"` |
| `tau.commands` | `cloud` | `tau cloud push\|pull\|status\|run` |

## The `spine` session backend

`SpineSessionStore` stores sessions through the spine's session API with tau-net's
`SpineClient`, with the semantics of the file store: ids are validated before any request,
creating a session or a message twice and updating what does not exist raise Strands'
`SessionException`, updates keep `created_at`, meta merges and events append (both create a
missing session), and nothing is ever deleted. A spine that cannot be reached, or that says
no, raises `SpineStoreError` with its URL and error code: a write is never dropped silently.

```toml
[sessions]
backend = "spine"     # tau cloud run sets this in the container
```

It reads `TAU_SPINE_URL` and `TAU_SPINE_TOKEN` (the environment on top of `.env`). Opening the
store sends no request.

## Commands

```sh
tau cloud push                  # tau.toml, persona/persona.md, persona/net.md, persona/subs/*.md; asks first
tau cloud push --include-user   # also persona/user.md (stored in your Cloudflare account)
tau cloud push --yes            # no question (scripts); user.md still needs --include-user
tau cloud pull                  # download into TAU_HOME; keeps local files that differ
tau cloud pull --force          # replace them
tau cloud status                # spine health and mode, the files it holds, the brain
tau cloud run                   # the brain container's entrypoint
```

- **The file set** is exactly `tau.toml`, `persona/persona.md`, `persona/user.md`,
  `persona/net.md` and the sub-tau files (ADR 0012): `persona/subs/<file>`, where `<file>`
  matches `[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.md` (definitions such as `coach.md`, public notes
  such as `coach.public.md`). Nothing else is read or sent; `.env` is never uploaded.
- **Sub-tau files.** `push` sends the `.md` files directly in `persona/subs/` and refuses the
  rest of that directory, naming each with its reason (`Skipped persona/subs/Bad Name.md: only
  .md files with a plain name ...`): an odd name (spaces, a leading dot, another extension), a
  subdirectory, or a symbolic link, which could send a file from outside such as
  `persona/user.md`. When `persona/subs/` exists here, sub-tau files the spine holds that are
  gone here are removed from the spine (`DELETE /hub/files/<name>`) and listed before the
  question; a machine without the directory leaves them alone. `pull` checks every name the
  spine lists again, skips the ones outside the set (`Skipped <name>: not a name of the
  cloud-mode file set.`), writes sub-tau files 0600 in a 0700 `persona/subs/` and never
  deletes a local file.
- **`persona/user.md`** holds what tau knows about its owner. `push` uploads it only with
  `--include-user`, or when the owner answers yes to its own question in a terminal. A
  non-interactive run without the flag leaves it out and says so.
- **`run`** pulls the files into `TAU_HOME` (creating `persona/`; sub-tau files the spine no
  longer holds are removed from `persona/subs/`), rewrites the pulled
  `tau.toml` with tomlkit so `[sessions] backend = "spine"` and `[component.net] store =
  "spine"` (every other key and comment stays), answers `GET /health` on `0.0.0.0:8080`
  (`TAU_CLOUD_HEALTH_PORT` overrides the port) with
  `{"ok": true, "version": ..., "hub": <the hub's /status or null>}`, then runs `tau hub run`
  in the same process and exits with its code. SIGTERM stops the hub cleanly. Without
  `TAU_SPINE_URL`/`TAU_SPINE_TOKEN`, or with a spine that is not in cloud mode, it exits 1
  with one line. It refuses a `TAU_HOME` that holds a `tau.toml` it did not write, so it
  never overwrites your own configuration.

## Tests

`tau_cloud.testing.install_cloud_routes(fake_spine)` adds the session and brain routes, with
the semantics of `cloud/spine/src/store.ts`, to a `tau_net.testing.FakeSpine` in cloud mode.

```sh
uv run pytest -q packages/tau-cloud
```
