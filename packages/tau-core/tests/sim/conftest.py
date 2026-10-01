"""Shared fixtures: a throwaway config and data dir, clean tool overrides and environment."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from tau_core import Config
from tau_core.sim import tools
from tau_core.testing import test_config


@pytest.fixture(autouse=True)
def restore_environ() -> Iterator[None]:
    """``Config.load()`` without an env mapping loads ``.env`` into the process; put
    ``os.environ`` back after every test."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def clean_tool_overrides() -> Iterator[None]:
    yield
    tools.config_factory = None


@pytest.fixture
def make_config(tmp_path: Path) -> Callable[[str], Config]:
    """``make_config(toml)``: :func:`test_config` with ``toml`` appended to its ``tau.toml``,
    loaded again; the data dir is ``tmp_path/data``, never the owner's."""

    def make(extra: str = "") -> Config:
        config = test_config(tmp_path)
        if not extra:
            return config
        with (config.home / "tau.toml").open("a", encoding="utf-8") as handle:
            handle.write("\n" + extra)
        return Config.load(config.home, env={"TAU_DATA_DIR": str(config.data_dir)})

    return make


@pytest.fixture
def config(make_config: Callable[[str], Config]) -> Config:
    """The simulated lamps switched on (opt-in) with two lamps, ``desk`` and ``living-room``."""
    return make_config('[component.sim]\nenabled = true\nlamps = ["desk", "living-room"]\n')


@pytest.fixture
def use_config(config: Config) -> Config:
    """``config``, also for the tools."""
    tools.config_factory = lambda: config
    return config
