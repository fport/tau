"""Make ``helpers`` importable under ``--import-mode=importlib``."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def pin_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """The welcome card prints tau-core's version; pin it so a release never churns snapshots."""
    monkeypatch.setattr("tau_tui.app.core_version", "0.0.0")


@pytest.fixture(autouse=True)
def restore_environ() -> Iterator[None]:
    """A settings save exports credentials and ``TAU_PROFILE`` into the process; put
    ``os.environ`` back after every test, keys that did not exist before included."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def isolated_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """``HOME`` is a fresh temp directory for every test, so nothing here can read the
    developer's real ``~/.tau`` (``Path.home()`` and ``~`` follow ``HOME``) and no real
    credential from ``~/.tau/.env`` can steer a provider detection or a snapshot."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    return home
