"""Shared fixtures: a cloud-mode fake spine with the session and brain routes, and a store on
it. No sockets (the fake spine is the transport), no credentials (FakeModel)."""

from __future__ import annotations

import itertools
import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from tau_cloud.sessions import SpineSessionStore  # noqa: E402
from tau_cloud.testing import FakeCloud, install_cloud_routes  # noqa: E402
from tau_core.logs import reset_logging  # noqa: E402
from tau_net.spine import SpineClient  # noqa: E402
from tau_net.testing import DEFAULT_HUB_TOKEN, FakeSpine  # noqa: E402

ADDRESS = "spine.example"
START = 1_790_000_000.0


@pytest.fixture(autouse=True)
def restore_environ() -> Iterator[None]:
    """``Config.load()`` without an env mapping loads ``.env`` into the process; put
    ``os.environ`` back after every test."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)
    reset_logging()  # `tau hub run` configures logging into the test's data dir


@pytest.fixture
def clock() -> Callable[[], float]:
    """One second later on every call, so every write has its own ``updated_at``."""
    ticks = itertools.count()
    return lambda: START + next(ticks)


@pytest.fixture
def spine(clock: Callable[[], float]) -> FakeSpine:
    return FakeSpine(ADDRESS, mode="cloud", clock=clock)


@pytest.fixture
def cloud(spine: FakeSpine) -> FakeCloud:
    return install_cloud_routes(spine)


@pytest.fixture
def client(spine: FakeSpine, cloud: FakeCloud) -> SpineClient:
    return SpineClient(spine.url, DEFAULT_HUB_TOKEN, transport=spine)


@pytest.fixture
def spine_store(client: SpineClient) -> SpineSessionStore:
    return SpineSessionStore(client, retry_delay=0)
