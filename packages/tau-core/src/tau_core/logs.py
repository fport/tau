"""Logging setup for tau's command-line entry points.

Details go to ``<data_dir>/logs/tau.log``; the terminal only gets short warnings, never a
traceback (the user sees a short notice, the log keeps the details).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

LOG_FILE = "tau.log"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_saved_level: int | None = None


class _ShortFormatter(logging.Formatter):
    """One line, no traceback."""

    def format(self, record: logging.LogRecord) -> str:
        return f"{record.levelname.lower()}: {record.getMessage()}"


class _StderrHandler(logging.StreamHandler):
    """Writes to whatever ``sys.stderr`` is at emit time (test runners swap it)."""

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    @property  # type: ignore[override]
    def stream(self):  # noqa: D401
        return sys.stderr

    @stream.setter
    def stream(self, value) -> None:
        pass


def reset_logging() -> None:
    """Remove the handlers :func:`configure_logging` added and restore the root level."""
    global _saved_level
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_tau", False):
            root.removeHandler(handler)
            handler.close()
    if _saved_level is not None:
        root.setLevel(_saved_level)
        _saved_level = None


def configure_logging(
    logs_dir: Path | None = None, *, verbose: bool = False, console: bool = True
) -> Path | None:
    """Terminal at WARNING (INFO with ``verbose``); file at INFO when ``logs_dir`` is given.

    ``console=False`` adds no stderr handler (a full-screen UI that owns the terminal); the
    file still receives every record. Returns the log file path, or ``None`` without a file.
    Calling it again replaces the setup.
    """
    global _saved_level
    root = logging.getLogger()
    level = _saved_level
    reset_logging()
    _saved_level = root.level if level is None else level
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    if console:
        handler = _StderrHandler()
        handler.setLevel(logging.INFO if verbose else logging.WARNING)
        handler.setFormatter(_ShortFormatter())
        handler._tau = True  # type: ignore[attr-defined]
        root.addHandler(handler)

    if logs_dir is None:
        return None
    path = Path(logs_dir) / LOG_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
    except OSError:
        return None
    file_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    file_handler._tau = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)
    return path
