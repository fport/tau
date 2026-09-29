"""The logging helper exported from the public API (issue 059)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from tau_core import configure_logging, reset_logging


@pytest.fixture(autouse=True)
def _clean() -> None:
    yield
    reset_logging()


def _tau_handlers() -> list[logging.Handler]:
    return [h for h in logging.getLogger().handlers if getattr(h, "_tau", False)]


def test_console_and_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = configure_logging(tmp_path / "logs")
    assert path == tmp_path / "logs" / "tau.log"
    log = logging.getLogger("tau_core.test")
    log.info("kept in the file only")
    log.warning("shown on stderr")
    for handler in _tau_handlers():
        handler.flush()
    err = capsys.readouterr().err
    assert "warning: shown on stderr" in err and "kept in the file" not in err
    text = path.read_text(encoding="utf-8")
    assert "kept in the file only" in text and "shown on stderr" in text
    assert len(_tau_handlers()) == 2


def test_console_off_keeps_stderr_silent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = configure_logging(tmp_path / "logs", console=False)
    assert path is not None
    logging.getLogger("tau_core.test").warning("full-screen UI owns the terminal")
    for handler in _tau_handlers():
        handler.flush()
    assert capsys.readouterr().err == ""
    assert "full-screen UI owns the terminal" in path.read_text(encoding="utf-8")
    assert len(_tau_handlers()) == 1


def test_reset_removes_handlers_and_restores_the_level() -> None:
    root = logging.getLogger()
    before = root.level
    assert configure_logging(None, verbose=True) is None
    assert root.level == logging.DEBUG and len(_tau_handlers()) == 1
    configure_logging(None)  # calling again replaces, never stacks
    assert len(_tau_handlers()) == 1
    reset_logging()
    assert _tau_handlers() == [] and root.level == before
