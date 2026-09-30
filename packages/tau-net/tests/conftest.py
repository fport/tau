"""Make ``net_helpers`` importable under ``--import-mode=importlib``; shared fixtures."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from net_helpers import ALICE, BOB, UNIVERSE, Pair, connect, make_tau  # noqa: E402
from tau_net import tools  # noqa: E402
from tau_net.testing import FakeNetwork, FakeUniverse  # noqa: E402


@pytest.fixture(autouse=True)
def restore_environ() -> Iterator[None]:
    """``Config.load()`` without an env mapping loads ``.env`` into the process; put
    ``os.environ`` back after every test."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def no_active_node() -> Iterator[None]:
    """A test that starts the hub service registers its node for the tools; clear it."""
    yield
    tools.set_active_node(None)
    tools.node_factory = None


@pytest.fixture
def network() -> FakeNetwork:
    return FakeNetwork()


@pytest.fixture
def universe(network: FakeNetwork) -> FakeUniverse:
    """A universe at ``UNIVERSE`` on the test network."""
    return network.add(FakeUniverse(UNIVERSE))


@pytest.fixture
def pair_factory(tmp_path: Path, network: FakeNetwork) -> Callable[..., Pair]:
    """``pair_factory(**b_kwargs)``: Alice and Bob as accepted contacts of each other."""

    def factory(**b_kwargs: Any) -> Pair:
        a = make_tau(tmp_path, network, ALICE)
        b = make_tau(tmp_path, network, BOB, **b_kwargs)
        a_node, b_node = connect(a, b)
        return Pair(a, b, a_node, b_node, network)

    return factory
