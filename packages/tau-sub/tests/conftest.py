"""Shared fixtures: a throwaway config, a small tool catalog and clean tool overrides."""

from __future__ import annotations

import dataclasses
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from tau_core import Config
from tau_core.testing import test_config

sys.path.insert(0, str(Path(__file__).parent))

from sub_helpers import CATALOG, OWNER_FACT, SideEffects  # noqa: E402


@pytest.fixture(autouse=True)
def restore_environ() -> Iterator[None]:
    """``Config.load()`` without an env mapping loads ``.env`` into the process; put
    ``os.environ`` back after every test."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def reset_side_effects() -> Iterator[None]:
    SideEffects.reset()
    yield
    SideEffects.reset()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    config = test_config(tmp_path)
    (config.persona_dir / "user.md").write_text(f"{OWNER_FACT}\n", encoding="utf-8")
    return config


@pytest.fixture
def file_config(config: Config) -> Config:
    """``config`` with the file session store, so sessions survive between agents."""
    toml = config.home / "tau.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace('backend = "memory"', 'backend = "file"'),
        encoding="utf-8",
    )
    return config.with_overrides(sessions=dataclasses.replace(config.sessions, backend="file"))


@pytest.fixture
def catalog() -> list:
    return list(CATALOG)
