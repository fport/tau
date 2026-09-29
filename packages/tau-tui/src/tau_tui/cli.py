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

HELP_TEXT = "Show this help and exit."
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


@contextmanager
def file_logging(logs_dir: Path, *, verbose: bool = False) -> Iterator[Path | None]:
    """Log to ``<logs_dir>/tau.log`` while the TUI runs; nothing reaches stderr meanwhile.

    The terminal belongs to Textual, so details (and the tracebacks behind a short notice)
    only reach the log file. Stream handlers on the root logger (the ``tau`` group's stderr
    handler) are detached for the duration and restored on exit, as is the file handler.
    Local until tau-core exports its logging helper (issue 059).
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
    muted = [
        h
        for h in root.handlers
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
    ]
    for stream_handler in muted:
        root.removeHandler(stream_handler)
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
        for stream_handler in muted:
            root.addHandler(stream_handler)


@click.command(name="tui", help="Open tau in the Textual interface.")
@click.help_option("-h", "--help", help=HELP_TEXT)
@click.option(
    "--profile", metavar="NAME", help="Active profile (default: TAU_PROFILE, else 'home')."
)
@click.option(
    "--resume",
    is_flag=False,
    flag_value="",
    default=None,
    metavar="[ID]",
    help="Resume an earlier session (the most recent one when ID is omitted).",
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
            session_id, notice = resolve_resume(store, resume, language=config.ui.language)
            app = build_app(config, session_store=store, session_id=session_id, notice=notice)
        except (MissingCredentials, ConfigError, SessionNotFound) as exc:
            click.echo(str(exc), err=True)
            ctx.exit(2)
            return
        try:
            app.run()
        finally:
            app.agent.close()
    click.echo("Goodbye.")
