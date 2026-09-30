"""Shared fixtures; make ``guard_helpers`` importable under ``--import-mode=importlib``."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from tau_guard.testing import FakeClock, FakePresence  # noqa: E402


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Real-model tests run only when asked for with ``-m models`` (never in CI)."""
    expression = config.getoption("-m") or ""
    if "models" in expression and "not models" not in expression:
        return
    skip = pytest.mark.skip(reason="opt-in: run with -m models (downloads into a cache)")
    for item in items:
        if "models" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def presence() -> FakePresence:
    return FakePresence()


# A test never opens the guard window: a worker this process (or a hub it starts) spawns inherits
# this and runs headless. Tests of the window path pass a fake window and clear it themselves.
os.environ["TAU_GUARD_WINDOW"] = "0"
