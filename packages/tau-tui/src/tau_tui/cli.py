"""``tau tui``: mounted into the ``tau`` command through the ``tau.commands`` entry point."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import click
from tau_core import Config, ConfigError, MissingCredentials, open_session_store

from tau_tui.app import SessionNotFound, build_app, resolve_resume

LOG_FILE = "tau.log"
"""Same file as the other channels: ``<data_dir>/logs/tau.log``."""

HELP_TEXT = "Bu yardımı gösterir ve çıkar."
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


@contextmanager
def file_logging(logs_dir: Path, *, verbose: bool = False) -> Iterator[Path | None]:
    """Log to ``<logs_dir>/tau.log`` while the TUI runs.

    The terminal belongs to Textual, so details (and the tracebacks behind a Turkish notice)
    only reach the log file. The handler is removed again on exit.
    """
    root = logging.getLogger()
    saved_level = root.level
    level = logging.DEBUG if verbose else logging.INFO
    path: Path | None = Path(logs_dir) / LOG_FILE
    handler: logging.Handler | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8")
    except OSError:
        path = None
    if handler is not None:
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
        if root.getEffectiveLevel() > level:
            root.setLevel(level)
    try:
        yield path
    finally:
        if handler is not None:
            root.removeHandler(handler)
            handler.close()
            root.setLevel(saved_level)


@click.command(name="tui", help="tau'yu Textual arayüzünde açar.")
@click.help_option("-h", "--help", help=HELP_TEXT)
@click.option("--profile", metavar="AD", help="Etkin profil (varsayılan: TAU_PROFILE, yoksa 'ev').")
@click.option(
    "--resume",
    is_flag=False,
    flag_value="",
    default=None,
    metavar="[ID]",
    help="Önceki bir oturuma devam eder (ID verilmezse en son oturuma).",
)
@click.pass_context
def tui(ctx: click.Context, profile: str | None, resume: str | None) -> None:
    obj = ctx.find_object(dict) or {}
    try:
        config = Config.load(obj.get("home"))
    except ConfigError as exc:
        click.echo(str(exc), err=True)
        ctx.exit(2)
        return
    profile = profile or obj.get("profile")
    if profile:
        config = config.with_overrides(profile=profile)
    with file_logging(config.logs_dir, verbose=bool(obj.get("verbose"))):
        try:
            store = open_session_store(config)
            session_id, notice = resolve_resume(store, resume)
            app = build_app(config, session_store=store, session_id=session_id, notice=notice)
        except (MissingCredentials, ConfigError, SessionNotFound) as exc:
            click.echo(str(exc), err=True)
            ctx.exit(2)
            return
        try:
            app.run()
        finally:
            app.agent.close()
    click.echo("Hoşça kalın.")
