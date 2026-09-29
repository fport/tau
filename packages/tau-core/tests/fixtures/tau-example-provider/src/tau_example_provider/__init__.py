"""Test fixture: a provider (``tau.providers``) and a session backend (``tau.sessions``)."""

from __future__ import annotations

from collections.abc import Mapping

from tau_core import Config, MemorySessionStore, SessionStore
from tau_core.config import RoleConfig
from tau_core.testing import FakeModel


def make_model(role_cfg: RoleConfig, env: Mapping[str, str]) -> FakeModel:
    """A scripted model that identifies itself, so tests can tell it from the built-in fake."""
    return FakeModel(default=f"fake2 for {role_cfg.model_id} ({env.get('EXAMPLE_API_KEY')})")


make_model.required_env = [["EXAMPLE_API_KEY"]]  # type: ignore[attr-defined]


class ExampleSessionStore(MemorySessionStore):
    """An in-memory store with a marker attribute for the tests."""

    example = True


def make_store(config: Config) -> SessionStore:
    return ExampleSessionStore()
