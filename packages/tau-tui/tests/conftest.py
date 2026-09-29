"""Make ``helpers`` importable under ``--import-mode=importlib``."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def pin_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """The welcome card prints tau-core's version; pin it so a release never churns snapshots."""
    monkeypatch.setattr("tau_tui.app.core_version", "0.0.0")
