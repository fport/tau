"""Shared fixtures for tau-core tests. Everything runs offline with FakeModel."""

from __future__ import annotations

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
