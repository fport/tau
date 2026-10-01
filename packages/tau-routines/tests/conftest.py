"""Shared fixtures: a throwaway config with a fixed zone, a fake clock and clean overrides.

No test sleeps, opens a socket, asks a real person, opens a camera or touches the owner's
data dir: the clock is a :class:`~routine_helpers.Clock`, approvers are ``ScriptedApprover``,
guards are ``FakeGuard`` and ``TAU_DATA_DIR`` is under ``tmp_path``.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from tau_core import Config

sys.path.insert(0, str(Path(__file__).parent))

from routine_helpers import CATALOG, Clock, SideEffects, local, routine_config  # noqa: E402
from tau_routines import (  # noqa: E402
    RoutineContext,
    RoutineEngine,
    RoutineSettings,
    RoutineStore,
    tools,
)


@pytest.fixture(autouse=True)
def restore_environ() -> Iterator[None]:
    """``Config.load()`` without an env mapping loads ``.env`` into the process; put
    ``os.environ`` back after every test."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def clean_overrides() -> Iterator[None]:
    SideEffects.reset()
    yield
    tools.context_factory = None
    SideEffects.reset()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return routine_config(tmp_path)


@pytest.fixture
def clock() -> Clock:
    """Friday 2 October 2026, 08:00 in the test zone."""
    return Clock(local(2026, 10, 2, 8, 0))


@pytest.fixture
def store(config: Config) -> RoutineStore:
    return RoutineStore.for_config(config)


@pytest.fixture
def context(config: Config, clock: Clock) -> RoutineContext:
    return RoutineContext.from_config(config, tools=CATALOG, clock=clock)


@pytest.fixture
def engine(config: Config, store: RoutineStore, clock: Clock) -> RoutineEngine:
    return RoutineEngine(store, RoutineSettings.from_config(config), tools=CATALOG, clock=clock)
