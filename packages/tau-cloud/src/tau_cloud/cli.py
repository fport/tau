"""``tau cloud``: cloud mode from the owner's machine and inside the brain container.

- ``push`` uploads ``tau.toml``, ``persona/persona.md``, ``persona/net.md`` and the sub-tau
  files (``persona/subs/*.md``) to the spine; ``persona/user.md`` only with ``--include-user``
  or a yes to its own question. Other entries of ``persona/subs/`` are refused and named, and
  the spine's sub-tau files that are gone here are removed from it (only when
  ``persona/subs/`` exists here, so a machine without sub-taus never empties the spine's).
- ``pull`` downloads them into ``TAU_HOME`` and never replaces a local file without ``--force``;
  it never deletes a local file, and it skips any name the spine lists outside the file set.
- ``status`` shows the spine's health, the files it holds and the brain's health.
- ``run`` is the brain container's entrypoint (``CMD ["tau", "cloud", "run"]``).

The spine comes from ``TAU_SPINE_URL`` and ``TAU_SPINE_TOKEN`` (the environment on top of
``<home>/.env``). Output lines go through ``tau_core.i18n``; help texts and error lines are
English. Exit codes: 0 ok, 1 error with one line on stderr, 2 when ``tau.toml`` itself cannot
be loaded.

Tests pass fakes through the click context object: ``cloud_env`` (the variables),
``cloud_transport`` (a :class:`tau_net.spine.Transport`), ``cloud_interactive`` (whether
questions may be asked; default: stdin is a terminal) and ``cloud_hub_runner`` (a
:data:`HubRunner` that ``run`` calls instead of the real hub).
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import tomllib
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

import click
from tau_core import Config, ConfigError, t
from tau_core.builder import env_with_dotenv
from tau_core.cli import help_option
from tau_core.config import resolve_home
from tau_core.i18n import DEFAULT_LANGUAGE, LANGUAGES
from tau_net.config import SPINE_TOKEN_ENV, SPINE_URL_ENV, NetConfigError, spine_from_env
from tau_net.spine import SpineClient, SpineError

from tau_cloud import strings as _strings  # noqa: F401  (registers the message keys)
from tau_cloud._version import __version__
from tau_cloud.files import (
    CONFIG_FILE,
    FILE_NAMES,
    SUBS_DIR,
    USER_FILE,
    FileError,
    LocalFile,
    RemoteListing,
    cloud_config,
    delete_remote,
    download,
    is_sub_file,
    list_remote,
    read_local,
    remote_listing,
    scan_subs,
    upload,
    write_local,
)
from tau_cloud.health import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    HOST_ENV,
    PORT_ENV,
    HealthServer,
    hub_status_reader,
)

__all__ = ["MARKER_FILE", "HubRunner", "cloud", "run_hub"]

MARKER_FILE = ".tau-cloud-run"
"""Written into ``TAU_HOME`` by ``tau cloud run``: the files there came from the spine."""
MARKER_TEXT = (
    "Written by `tau cloud run`: the files in this directory are replaced from the spine at "
    "every start.\n"
)

HubRunner = Callable[[click.Context, Config, HealthServer], int]
"""``(ctx, config, health) -> exit code``: runs the hub in this process until it stops."""


# -- plumbing ----------------------------------------------------------------------------------


def _obj(ctx: click.Context) -> dict[str, Any]:
    return ctx.find_object(dict) or {}


def _fail(ctx: click.Context, error: BaseException | str) -> NoReturn:
    message = " ".join(str(error).split()) or type(error).__name__
    click.echo(f"tau cloud: {message}", err=True)
    ctx.exit(1)
    raise AssertionError("unreachable")  # pragma: no cover


def _home(ctx: click.Context) -> Path:
    return resolve_home(_obj(ctx).get("home"))


def _env(ctx: click.Context, home: Path) -> dict[str, str]:
    """The variables the commands read: the injected ones, else the process environment on
    top of ``<home>/.env`` (the rule of ``Config.load``)."""
    injected = _obj(ctx).get("cloud_env")
    return dict(injected) if injected is not None else env_with_dotenv(home, os.environ)


def _language(home: Path, env: Mapping[str, str]) -> str:
    """``TAU_LANG`` (``tau --lang`` sets it), else ``[ui] language`` of ``tau.toml`` when it
    can be read, else English. Works before a ``tau.toml`` exists (``pull`` on a new machine)."""
    wanted = env.get("TAU_LANG")
    if wanted in LANGUAGES:
        return wanted
    try:
        raw = tomllib.loads((home / CONFIG_FILE).read_text(encoding="utf-8"))
        language = raw.get("ui", {}).get("language")
    except (OSError, ValueError, AttributeError):
        language = None
    return language if language in LANGUAGES else DEFAULT_LANGUAGE


class _Say:
    def __init__(self, language: str):
        self.language = language

    def __call__(self, key: str, /, **kwargs: Any) -> None:
        click.echo(t(key, self.language, **kwargs))

    def text(self, key: str, /, **kwargs: Any) -> str:
        return t(key, self.language, **kwargs)


def _spine(ctx: click.Context, env: Mapping[str, str]) -> SpineClient:
    try:
        spine = spine_from_env(env, transport=_obj(ctx).get("cloud_transport"))
    except NetConfigError as exc:
        _fail(ctx, exc)
    if spine is None:
        _fail(
            ctx,
            f"{SPINE_URL_ENV} and {SPINE_TOKEN_ENV} must be set (the spine's URL and its "
            "HUB_TOKEN secret, in the environment or in .env).",
        )
    return spine


def _health(ctx: click.Context, spine: SpineClient) -> dict[str, Any]:
    try:
        return spine.health()
    except SpineError as exc:
        _fail(ctx, f"{spine.url}: {exc}")


def _cloud_spine(ctx: click.Context, env: Mapping[str, str]) -> SpineClient:
    """The spine, after checking that it runs in cloud mode (else one line and exit 1)."""
    spine = _spine(ctx, env)
    mode = _health(ctx, spine).get("mode")
    if mode != "cloud":
        _fail(
            ctx,
            f"the spine at {spine.url} runs in {mode} mode and keeps no files or sessions; "
            "deploy the cloud configuration first (docs/guides/cloud-mode.md).",
        )
    return spine


def _interactive(ctx: click.Context) -> bool:
    injected = _obj(ctx).get("cloud_interactive")
    if injected is not None:
        return bool(injected)
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _read(ctx: click.Context, home: Path, name: str) -> LocalFile | None:
    try:
        return read_local(home, name)
    except FileError as exc:
        _fail(ctx, exc)


def _listing(ctx: click.Context, spine: SpineClient) -> RemoteListing:
    try:
        return remote_listing(spine)
    except SpineError as exc:
        _fail(ctx, f"{spine.url}: {exc}")


def _shown(name: str) -> str:
    """A name a spine listed, safe to print: no control characters, at most 120 characters."""
    return "".join(ch if ch.isprintable() else "?" for ch in name)[:120]


@click.group(
    name="cloud",
    help="Cloud mode: your tau's hub runs as a container in your own Cloudflare account and "
    "keeps sessions, config and persona in the spine (ADR 0007).",
    short_help="Cloud mode: sync config and persona with the spine, run the brain.",
)
@help_option()
def cloud() -> None:
    pass


# -- push --------------------------------------------------------------------------------------


@cloud.command(
    name="push",
    help="Upload tau.toml, persona/persona.md, persona/net.md and the sub-tau files "
    "(persona/subs/*.md: definitions and public notes) to the spine, where the brain "
    "container reads them at its next start. Other entries of persona/subs/ are skipped, and "
    "sub-tau files you removed here are removed from the spine too. persona/user.md goes up "
    "only with --include-user, or when you answer yes to its own question in a terminal: it "
    "is then stored in your own Cloudflare account. .env is never uploaded.",
    short_help="Upload tau.toml and the persona files to the spine.",
)
@help_option()
@click.option(
    "--include-user",
    is_flag=True,
    help="Also upload persona/user.md (what tau knows about you) to your Cloudflare account.",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Upload without asking. persona/user.md still needs --include-user.",
)
@click.pass_context
def push_command(ctx: click.Context, include_user: bool, yes: bool) -> None:
    home = _home(ctx)
    env = _env(ctx, home)
    say = _Say(_language(home, env))
    if _read(ctx, home, CONFIG_FILE) is None:
        _fail(ctx, f"{home / CONFIG_FILE} does not exist; run `tau init` first or pass --home.")
    try:
        Config.load(home, env=env)
    except ConfigError as exc:
        click.echo(str(exc), err=True)
        ctx.exit(2)
    spine = _cloud_spine(ctx, env)

    files: list[LocalFile] = []
    for name in FILE_NAMES:
        if name == USER_FILE:
            continue
        file = _read(ctx, home, name)
        if file is not None:
            files.append(file)
        elif name != "persona/net.md":
            say("cloud.push.missing", name=name)
    try:
        sub_names, refused = scan_subs(home)
    except FileError as exc:
        _fail(ctx, exc)
    for entry in refused:
        reason = say.text(f"cloud.refused.{entry.reason}")
        say("cloud.push.refused", name=entry.name, reason=reason)
    for name in sub_names:
        file = _read(ctx, home, name)
        if file is not None:
            files.append(file)
    # Sub-tau files the spine holds that are gone here: a removed or renamed sub-tau must not
    # live on in the cloud. Without a persona/subs/ here the spine's copies stay.
    remote_subs = [f.name for f in _listing(ctx, spine).files if is_sub_file(f.name)]
    stale: list[str] = []
    if (home / SUBS_DIR).is_dir():
        stale = [name for name in remote_subs if not os.path.lexists(home / name)]
    elif remote_subs:
        say("cloud.push.subs_kept", count=len(remote_subs))
    user = _read(ctx, home, USER_FILE)
    interactive = _interactive(ctx)
    if not yes:
        if not interactive:
            _fail(ctx, "nothing was uploaded: pass --yes to upload without a question.")
        say("cloud.push.plan", url=spine.url, files=", ".join(f.name for f in files))
        if stale:
            say("cloud.push.plan_remove", files=", ".join(stale))
        if not click.confirm(say.text("cloud.push.confirm"), default=False):
            say("cloud.push.cancelled")
            ctx.exit(1)
    if user is not None:
        if include_user:
            files.append(user)
        elif interactive and not yes:
            say("cloud.push.user_warning")
            if click.confirm(say.text("cloud.push.user_confirm"), default=False):
                files.append(user)
            else:
                say("cloud.push.user_skipped")
        else:
            say("cloud.push.user_skipped")

    for file in files:
        try:
            stored = upload(spine, file)
        except SpineError as exc:
            _fail(ctx, f"{file.name}: {exc}")
        say("cloud.push.uploaded", name=stored.name, size=stored.size)
    for name in stale:
        try:
            delete_remote(spine, name)
        except SpineError as exc:
            _fail(ctx, f"{name}: {exc}")
        say("cloud.push.removed", name=name)
    say("cloud.push.done")


# -- pull --------------------------------------------------------------------------------------


@cloud.command(
    name="pull",
    help="Download the files the spine holds (tau.toml, the persona files and the sub-tau "
    "files in persona/subs/) into TAU_HOME. A local file that differs is kept unless you pass "
    "--force; no local file is ever deleted.",
    short_help="Download tau.toml and the persona files from the spine.",
)
@help_option()
@click.option("--force", is_flag=True, help="Replace local files that differ from the spine's.")
@click.pass_context
def pull_command(ctx: click.Context, force: bool) -> None:
    home = _home(ctx)
    env = _env(ctx, home)
    say = _Say(_language(home, env))
    spine = _cloud_spine(ctx, env)
    listing = _listing(ctx, spine)
    for name in listing.ignored:
        say("cloud.pull.refused", name=_shown(name))
    remote = listing.files
    if not remote:
        say("cloud.pull.empty")
        ctx.exit(1)
    kept = 0
    for entry in remote:
        try:
            text = download(spine, entry.name)
            if text is None:
                continue
            result = write_local(home, entry.name, text, force=force)
        except (SpineError, FileError) as exc:
            _fail(ctx, f"{entry.name}: {exc}")
        say(f"cloud.pull.{result.outcome}", path=result.path)
        kept += result.outcome == "kept"
    if kept:
        say("cloud.pull.force_hint")
        ctx.exit(1)


# -- status ------------------------------------------------------------------------------------


def _when(updated_at: int) -> str:
    if updated_at <= 0:
        return "?"
    return f"{datetime.fromtimestamp(updated_at).astimezone():%d.%m.%Y %H:%M}"


@cloud.command(
    name="status",
    help="Show the spine's health and mode, the files it holds and the brain container's health.",
    short_help="Show the spine, its files and the brain.",
)
@help_option()
@click.pass_context
def status_command(ctx: click.Context) -> None:
    home = _home(ctx)
    env = _env(ctx, home)
    say = _Say(_language(home, env))
    spine = _spine(ctx, env)
    health = _health(ctx, spine)
    mode = health.get("mode")
    say(
        "cloud.status.spine",
        url=spine.url,
        address=health.get("address"),
        mode=mode,
        version=health.get("version"),
    )
    if mode != "cloud":
        say("cloud.status.not_cloud", mode=mode)
        ctx.exit(1)
    try:
        remote = list_remote(spine)
    except SpineError as exc:
        _fail(ctx, f"{spine.url}: {exc}")
    if remote:
        say("cloud.status.files")
        for entry in remote:
            say("cloud.status.file", name=entry.name, size=entry.size, when=_when(entry.updated_at))
    else:
        say("cloud.status.files_none")
    # A cold start can outlast the client's timeout; that is "unavailable", not an error.
    try:
        brain = spine.request("GET", "/hub/brain")
        answer = brain.json() if brain.ok else None
    except (SpineError, ValueError):
        answer = None
    if not isinstance(answer, dict):
        say("cloud.status.brain_down")
        return
    hub = answer.get("hub")
    version = answer.get("version", "?")
    if isinstance(hub, dict):
        say(
            "cloud.status.brain_hub",
            version=version,
            pid=hub.get("pid"),
            uptime=hub.get("uptime_s"),
        )
    else:
        say("cloud.status.brain_starting", version=version)


# -- run ---------------------------------------------------------------------------------------


def run_hub(ctx: click.Context, config: Config, health: HealthServer) -> int:
    """The default :data:`HubRunner`: ``tau hub run`` itself (the same click command, so the
    same assembly, logging, lock and clean stop on SIGTERM), in this process."""
    from tau_core.hub.cli import hub

    command = hub.get_command(ctx, "run")
    if command is None:  # pragma: no cover  (tau-core always has it)
        raise click.ClickException("tau-core has no `tau hub run`")
    try:
        ctx.invoke(command)
    except click.exceptions.Exit as exc:
        return int(exc.exit_code or 0)
    return 0


def _health_port(ctx: click.Context, env: Mapping[str, str]) -> int:
    raw = (env.get(PORT_ENV) or "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        port = -1
    if not 0 <= port < 65536:
        _fail(ctx, f"{PORT_ENV} must be a port number, not {raw!r}.")
    return port


def _stop_guard() -> Callable[[], None]:
    """Until the hub installs its own handlers, SIGTERM stops ``run`` like Ctrl-C does (as the
    container's PID 1 the process would otherwise ignore it). Returns the undo function."""
    if threading.current_thread() is not threading.main_thread():
        return lambda: None

    def interrupt(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, interrupt)
    return lambda: signal.signal(signal.SIGTERM, previous)


def _pull_for_run(ctx: click.Context, spine: SpineClient, home: Path) -> int:
    """Every file of the set the spine holds, written into ``home`` (replacing what is there);
    ``tau.toml`` patched for cloud mode. Sub-tau files ``home`` holds from an earlier start
    that the spine no longer lists are removed. Returns how many files were pulled."""
    if (home / CONFIG_FILE).exists() and not (home / MARKER_FILE).is_file():
        _fail(
            ctx,
            f"{home} holds a tau.toml that `tau cloud run` did not write. It is the brain "
            "container's entrypoint and replaces the files it pulls; run it with TAU_HOME set "
            "to an empty directory.",
        )
    (home / "persona").mkdir(parents=True, exist_ok=True)
    count = 0
    for name in FILE_NAMES:
        try:
            text = download(spine, name)
            if text is None:
                if name == CONFIG_FILE:
                    _fail(
                        ctx,
                        f"the spine at {spine.url} holds no tau.toml yet; run `tau cloud push` "
                        "on your machine first.",
                    )
                continue
            if name == CONFIG_FILE:
                text = cloud_config(text)
            write_local(home, name, text, force=True)
        except (SpineError, FileError) as exc:
            _fail(ctx, f"{name}: {exc}")
        count += 1
    listing = _listing(ctx, spine)
    wanted = [entry.name for entry in listing.files if is_sub_file(entry.name)]
    for name in wanted:
        try:
            text = download(spine, name)
            if text is None:
                continue
            write_local(home, name, text, force=True)
        except (SpineError, FileError) as exc:
            _fail(ctx, f"{name}: {exc}")
        count += 1
    try:
        present, _ = scan_subs(home)
        for name in present:
            if name not in wanted:
                (home / name).unlink()
    except (FileError, OSError) as exc:
        _fail(ctx, f"{SUBS_DIR}: {exc}")
    (home / MARKER_FILE).write_text(MARKER_TEXT, encoding="utf-8")
    return count


@cloud.command(
    name="run",
    help="The brain container's entrypoint: pull tau.toml, the persona files and the sub-tau "
    "files from the spine into TAU_HOME (sessions and network state set to the spine), answer "
    "GET /health "
    f"on {DEFAULT_HOST}:{DEFAULT_PORT} ({HOST_ENV} and {PORT_ENV} override them), then run "
    "`tau hub run` until SIGTERM. Needs TAU_SPINE_URL and TAU_SPINE_TOKEN and a spine in "
    "cloud mode. It refuses a TAU_HOME holding a tau.toml it did not write.",
    short_help="Run the hub as the brain container (entrypoint).",
)
@help_option()
@click.pass_context
def run_command(ctx: click.Context) -> None:
    home = _home(ctx)
    env = _env(ctx, home)
    say = _Say(_language(home, env))
    undo = _stop_guard()
    try:
        spine = _cloud_spine(ctx, env)
        count = _pull_for_run(ctx, spine, home)
        say("cloud.run.pulled", count=count, url=spine.url, home=home)
        try:
            config = Config.load(home)
        except ConfigError as exc:
            click.echo(str(exc), err=True)
            ctx.exit(2)
        health = HealthServer(
            _health_port(ctx, env),
            host=(env.get(HOST_ENV) or "").strip() or DEFAULT_HOST,
            version=__version__,
            hub_status=hub_status_reader(config.hub.control_port),
        )
        try:
            health.start()
        except OSError as exc:
            _fail(ctx, f"the health endpoint cannot listen on port {health.port}: {exc}")
        say("cloud.run.health", host=health.host, port=health.port)
        runner: HubRunner = _obj(ctx).get("cloud_hub_runner") or run_hub
        try:
            code = runner(ctx, config, health)
        finally:
            health.stop()
    except KeyboardInterrupt:
        code = 0
    finally:
        undo()
    ctx.exit(code)
