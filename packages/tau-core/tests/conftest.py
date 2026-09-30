"""Shared fixtures for tau-core tests. Everything runs offline with FakeModel."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from tau_core import Config, registry
from tau_core.persona import TIMEZONE
from tau_core.testing import test_config

CREDENTIAL_VARS = (
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_PROFILE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK",
    "ANTHROPIC_API_KEY",
)
TAU_VARS = ("TAU_HOME", "TAU_DATA_DIR", "TAU_PROFILE", "TAU_ROLE", "TAU_HUB_PORT")
PROXY_VARS = (
    "LITELLM_MASTER_KEY",
    "TAU_PROXY_URL",
    "TAU_PROXY_KEY_BRAIN",
    "TAU_PROXY_KEY_FAST",
    "TAU_PROXY_KEY_LOCAL",
    "TAU_OLLAMA_URL",
)


@pytest.fixture(autouse=True)
def restore_environ() -> Iterator[None]:
    """A test that exports a value into the process (``set_credential(..., export=True)``,
    ``/settings profile``) never leaks it into the next test: ``os.environ`` is put back as it
    was, including keys that did not exist before (which ``monkeypatch.delenv`` does not track)."""
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def fresh_registry() -> Iterator[None]:
    """No cached component lookup or in-process registration leaks between tests."""
    registry.reset()
    yield
    registry.reset()


@pytest.fixture(autouse=True)
def no_real_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test sees a real bot token, so no hub a test assembles ever polls Telegram."""
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_IDS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def no_real_proxy(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No test reaches a LiteLLM proxy that happens to run on this machine: the proxy
    variables are unset and no spend tracker outlives its test."""
    from tau_core import spend

    for name in PROXY_VARS:
        monkeypatch.delenv(name, raising=False)
    spend.forget_trackers()
    yield
    spend.forget_trackers()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return test_config(tmp_path)


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 9, 29, 15, 30, tzinfo=TIMEZONE)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove credentials and tau variables from the process environment."""
    for name in CREDENTIAL_VARS + TAU_VARS:
        monkeypatch.delenv(name, raising=False)
