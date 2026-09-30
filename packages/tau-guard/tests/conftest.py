"""Shared fixtures; make ``guard_helpers`` importable under ``--import-mode=importlib``."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from tau_guard.testing import FakeClock, FakePresence  # noqa: E402


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def presence() -> FakePresence:
    return FakePresence()
