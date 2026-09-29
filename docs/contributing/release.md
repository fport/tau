# Releasing

tau ships as two PyPI distributions, `tau-core` and `tau-tui`, released together with the same
version. A release is one tag away: push `vX.Y.Z` and the `release` workflow builds both
packages, smoke-tests the wheels, publishes them to PyPI through trusted publishing and creates
the GitHub release with the files attached. The docs site deploys itself on every push to
`main`. This is the "installable by anyone" half of
[ADR 0006](../adr/0006-private-first-topology.md).

## Versioning

- Both packages carry the same version. `tau-tui` depends on `tau-core` and is released with
  it, even when only one of them changed.
- The tag is `v` plus the version in `packages/tau-core/pyproject.toml`, for example
  `v0.3.0`. The workflow refuses a tag that does not match it, and a `tau-tui` version that
  differs from `tau-core`.
- Versions follow [PEP 440](https://peps.python.org/pep-0440/). A pre-release such as
  `0.3.0rc1` is tagged `v0.3.0rc1` and becomes a GitHub pre-release.

## Cut a release

!!! note "Before you start"
    `main` is green in CI and everything you want to ship is merged. Tags are cut from `main`.

1. Bump both versions (this also updates `uv.lock`):

    ```sh
    uv version --package tau-core 0.3.0
    uv version --package tau-tui 0.3.0
    ```

2. Commit and tag:

    ```sh
    git commit -am "chore(release): v0.3.0"
    git tag -a v0.3.0 -m "tau v0.3.0"
    git push origin main v0.3.0
    ```

3. Watch the run under **Actions → release**. The `build` job checks the tag against the
   version, builds the sdists and wheels, installs them into a fresh virtualenv and runs
   `tau --help`, `tau version`, `tau init --yes`, `tau doctor`, `tau components`, a scripted
   `tau chat` and `tau tui --help`, then repeats the documented `uv tool install`. `publish`
   uploads each package (one job per package) and `github-release` creates the release.

4. Write the changelog. The release is created with notes generated from the pull requests
   and commits since the previous tag. Open it under **Releases**, edit the notes into a few
   lines a user can read (what changed for someone running `tau`, what to do after
   upgrading) and save.

5. Verify from a clean machine, or a scratch tool directory:

    ```sh
    UV_TOOL_DIR=/tmp/tau-tools UV_TOOL_BIN_DIR=/tmp/tau-bin uv tool install tau-core --with tau-tui
    /tmp/tau-bin/tau version
    ```

!!! tip "Something went wrong halfway"
    Rerun the workflow from the Actions tab: publishing skips files PyPI already has
    (`skip-existing`) and the GitHub release is updated rather than duplicated. If the code
    itself was wrong, fix it on `main`, bump to the next patch version and tag again; a
    version that reached PyPI can never be uploaded twice.

## Dry run

The same workflow without the upload. Under **Actions → release → Run workflow** pick `main`,
or the tag you are about to publish, and leave **dry run** ticked. From a shell:

```sh
gh workflow run release.yml --ref main                       # build, smoke test, artifacts
gh workflow run release.yml --ref v0.3.0 -f dry_run=false    # publish an existing tag by hand
```

The built files are attached to the run as the `dist` artifact. The smoke test also runs
locally, against wheels built into a scratch directory:

```sh
uv build --package tau-core --out-dir /tmp/tau-dist
uv build --package tau-tui --out-dir /tmp/tau-dist
uv venv --python 3.12 /tmp/tau-venv
uv pip install --python /tmp/tau-venv/bin/python /tmp/tau-dist/*.whl
/tmp/tau-venv/bin/tau init --yes --home /tmp/tau-home --provider fake --language en
/tmp/tau-venv/bin/tau --home /tmp/tau-home doctor
printf '/status\nhello\n/quit\n' | /tmp/tau-venv/bin/tau --home /tmp/tau-home chat
```

The `fake` provider answers "Okay." and needs no credentials.

## One-time setup

### PyPI: trusted publishing

No API token is stored on GitHub. The `publish` job presents its GitHub OIDC token to PyPI,
which answers with a short-lived upload token for the projects that trust this workflow
([trusted publishers](https://docs.pypi.org/trusted-publishers/)). Configure it once per
project:

1. Sign in to PyPI and open [Publishing](https://pypi.org/manage/account/publishing/).
2. Under **Add a new pending publisher** (a project that does not exist yet is created by its
   first upload) fill in:

    | Field | Value |
    |---|---|
    | PyPI project name | `tau-core` |
    | Owner | `fport` |
    | Repository name | `tau` |
    | Workflow name | `release.yml` |
    | Environment name | `pypi` |

3. Repeat with the project name `tau-tui` and the environment name `pypi-tui`. PyPI accepts
   only one pending publisher per (repository, workflow, environment) tuple, so each package
   publishes from its own GitHub environment; the workflow's matrix already maps
   `tau-core → pypi` and `tau-tui → pypi-tui`.
4. On GitHub, **Settings → Environments → New environment** → `pypi`, then `pypi-tui`
   (or `gh api -X PUT repos/fport/tau/environments/pypi` and the same for `pypi-tui`).
   Optional: add yourself as a required reviewer, so every tag waits for a click before
   anything is uploaded. The first run creates a missing environment; the reviewer rule is
   the reason to create it by hand.

!!! warning "Names must match exactly"
    PyPI compares the owner, repository name, workflow file name and environment name with
    the claims in the OIDC token. A typo shows up as `invalid-publisher` in the `publish` job.
    Fix the publisher on PyPI and rerun; no code change is needed.

### Cloudflare Pages: the docs site

The `docs` workflow builds the site with `mkdocs build --strict` on every push to `main` that
touches `docs/**` or `mkdocs.yml`, and deploys it with `wrangler pages deploy` to the Pages
project `tau-docs`, served at `docs.tau.getporti.com`. Without the secrets below it only
builds, which is what forks and dry runs get.

1. Create the Pages project once: dashboard → **Workers & Pages → Create → Pages → Upload
   assets**, name `tau-docs`; or, with a logged-in wrangler,
   `npx wrangler pages project create tau-docs --production-branch main`.
2. Under the project's **Custom domains** add `docs.tau.getporti.com`. The zone is on
   Cloudflare, so the DNS record is created for you.
3. Create an API token (**My Profile → API Tokens → Create Token**; the *Edit Cloudflare
   Workers* template, or a custom token with *Account · Cloudflare Pages · Edit*) and note the
   account id from the dashboard sidebar.
4. In the GitHub repository, **Settings → Secrets and variables → Actions**: add
   `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID`.
5. Deploy the first time by hand, **Actions → docs → Run workflow** with **deploy** ticked,
   or push a docs change to `main`.

!!! note "Previews"
    A manual run from a branch other than `main` with **deploy** ticked publishes a preview
    deployment (`<branch>.tau-docs.pages.dev`). Production is only ever deployed from `main`.

## What the workflows check

| Check | Where | Fails when |
|---|---|---|
| `ruff check`, `ruff format --check`, `pytest`, `uv build` | `ci.yml`, every push and pull request | lint, formatting or a test fails, or a package does not build |
| `mkdocs build --strict` | `ci.yml` and `docs.yml` | a page listed in `nav` is missing or a link points nowhere |
| tag ↔ version | `release.yml` | the tag is not `v<tau-core version>`, or `tau-tui` has another version |
| wheel smoke test | `release.yml` | the `tau` command, its `tui` subcommand, the templates `tau init` writes or the entry points are missing from the wheels |
