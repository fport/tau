"""Budgets, spend recording and failover around a role's model (ADR 0011). Offline: the
providers are ``FakeModel``s, and ``OpenAIModel``/``GeminiModel`` are only constructed."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest
from strands.models.openai import OpenAIModel
from strands.types.exceptions import EventLoopException, ModelThrottledException
from tau_core import Config
from tau_core.agent import Notice, TurnEnd, build_agent, model_error_text
from tau_core.budget import RoleModel, is_unavailable
from tau_core.config import BudgetConfig, Price, RoleConfig
from tau_core.models import (
    BudgetDegraded,
    BudgetExhausted,
    FailedOver,
    missing_credentials,
    required_env,
    resolve_model,
)
from tau_core.persona import TIMEZONE
from tau_core.prices import cost, price_for
from tau_core.spend import ledger_for, period_bounds
from tau_core.testing import FakeModel, test_config

NOW = datetime(2026, 9, 30, 14, 0, tzinfo=TIMEZONE)
REQUEST = httpx.Request("POST", "http://127.0.0.1:11434/v1/chat/completions")


class Usage(FakeModel):
    """A FakeModel whose answers report token usage (the plain one reports 1 in, 1 out)."""

    def __init__(self, replies=None, *, usage: dict | None = None, **kwargs: Any) -> None:
        super().__init__(replies, **kwargs)
        self.usage = usage or {"inputTokens": 1000, "outputTokens": 500, "totalTokens": 1500}

    async def stream(self, *args: Any, **kwargs: Any):
        async for event in super().stream(*args, **kwargs):
            if "metadata" in event:
                event = {"metadata": {**event["metadata"], "usage": dict(self.usage)}}
            yield event


class Unreachable(FakeModel):
    """A provider that cannot be reached: the error comes before any event."""

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    async def stream(self, *args: Any, **kwargs: Any):
        raise self.error
        yield  # pragma: no cover - an async generator


def config_with(tmp_path: Path, **roles: RoleConfig) -> Config:
    config = test_config(tmp_path)
    return config.with_overrides(roles={**config.roles, **roles})


def role_model(
    config: Config,
    inner,
    *,
    role="brain",
    model_id="claude-sonnet-5",
    provider="anthropic",
    budget=None,
    **kwargs,
) -> RoleModel:
    return RoleModel(
        inner,
        role=role,
        provider=provider,
        model_id=model_id,
        config=config,
        budget=budget,
        clock=lambda: NOW,
        **kwargs,
    )


async def drain(model, **kwargs) -> list:
    return [event async for event in model.stream([], None, "system", **kwargs)]


def spend(config: Config, role: str, dollars: float) -> None:
    ledger_for(config).record(
        role=role,
        provider="anthropic",
        model_id="m",
        usage={"inputTokens": 1, "outputTokens": 1},
        cost_usd=dollars,
        at=NOW.timestamp(),
    )


# -- prices ------------------------------------------------------------------------------------


def test_cost_counts_cached_tokens_once_per_provider() -> None:
    price = Price(input=2.0, output=10.0, cache_read=0.2, cache_write=2.5)
    anthropic = {
        "inputTokens": 1000,
        "outputTokens": 500,
        "cacheReadInputTokens": 2000,
        "cacheWriteInputTokens": 400,
    }
    # Anthropic: inputTokens excludes the cache.
    assert cost(anthropic, price, "anthropic") == pytest.approx(
        (1000 * 2 + 500 * 10 + 2000 * 0.2 + 400 * 2.5) / 1e6
    )
    # OpenAI/Gemini: inputTokens includes the cached tokens.
    openai_usage = {"inputTokens": 3000, "outputTokens": 500, "cacheReadInputTokens": 2000}
    assert cost(openai_usage, price, "openai") == pytest.approx((1000 * 2 + 500 * 10 + 400) / 1e6)
    # Unknown cache prices count at the input price, never cheaper.
    plain = Price(input=1.0, output=1.0)
    assert cost(
        {"inputTokens": 0, "outputTokens": 0, "cacheReadInputTokens": 10}, plain, "anthropic"
    ) == pytest.approx(10 / 1e6)


def test_price_lookup(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    assert price_for(config, "anthropic", "claude-sonnet-5") == Price(2.0, 10.0, 0.2, 2.5)
    assert price_for(config, "ollama", "anything") == Price(0.0, 0.0, 0.0, 0.0)
    assert price_for(config, "openai", "no-such-model") is None
    own = config.with_overrides(prices={"no-such-model": Price(1.0, 2.0)})
    assert price_for(own, "openai", "no-such-model") == Price(1.0, 2.0)


# -- providers ---------------------------------------------------------------------------------


def test_direct_providers_and_their_credentials(tmp_path: Path) -> None:
    assert required_env(RoleConfig("openai", "gpt-6-luna")) == [["OPENAI_API_KEY"]]
    assert required_env(RoleConfig("gemini", "g")) == [["GEMINI_API_KEY"], ["GOOGLE_API_KEY"]]
    assert missing_credentials(RoleConfig("gemini", "g"), {"GOOGLE_API_KEY": "k"}) == []
    assert required_env(RoleConfig("openai", "m", params={"api_key_env": "MY_KEY"})) == [["MY_KEY"]]
    assert required_env(RoleConfig("ollama", "q")) == []
    config = config_with(
        tmp_path,
        gpt=RoleConfig("openai", "gpt-6-luna", max_tokens=100, params={"base_url": "http://x/v1"}),
        gem=RoleConfig("gemini", "gemini-3.1-flash-lite", max_tokens=100),
        local=RoleConfig("ollama", "qwen3.5:9b", params={"reasoning_effort": "none"}),
    )
    gpt = resolve_model("gpt", config, env={"OPENAI_API_KEY": "sk-o"})
    assert type(gpt) is OpenAIModel
    assert gpt.client_args == {"api_key": "sk-o", "base_url": "http://x/v1"}
    assert gpt.get_config()["params"] == {"max_completion_tokens": 100}
    gem = resolve_model("gem", config, env={"GEMINI_API_KEY": "g-key"})
    assert type(gem).__name__ == "GeminiModel"
    assert gem.get_config()["params"] == {"max_output_tokens": 100}
    local = resolve_model("local", config, env={})
    assert local.client_args["base_url"] == "http://127.0.0.1:11434/v1"
    assert local.client_args["max_retries"] == 0
    assert local.client_args["timeout"].connect == 3.0  # a sleeping Mac fails fast
    assert local.get_config()["params"] == {"max_tokens": 4096, "reasoning_effort": "none"}


def test_resolve_wraps_only_roles_with_a_budget_or_failover(tmp_path: Path) -> None:
    config = config_with(
        tmp_path,
        brain=RoleConfig("fake", "b", budget=BudgetConfig(1.0, "day", "fast")),
        fast=RoleConfig("fake", "f"),
        local=RoleConfig("ollama", "qwen3.5:9b", failover="fast"),
    )
    brain = resolve_model("brain", config, env={})
    assert isinstance(brain, RoleModel) and isinstance(brain.inner, FakeModel)
    assert (brain.tau_provider, brain.tau_role, brain.role) == ("fake", "brain", "brain")
    assert brain.get_config()["model_id"] == "fake"  # delegated
    assert isinstance(resolve_model("fast", config, env={}), FakeModel)  # nothing to enforce
    local = resolve_model("local", config, env={})
    assert isinstance(local, RoleModel) and local.budget is None


# -- the budget --------------------------------------------------------------------------------


async def test_calls_are_priced_and_recorded(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    model = role_model(config, Usage(["Merhaba."]), budget=BudgetConfig(15.0, "month"))
    await drain(model)
    since, _ = period_bounds("month", NOW)
    assert ledger_for(config).spent("brain", since) == pytest.approx((1000 * 2 + 500 * 10) / 1e6)
    unpriced = role_model(
        config,
        Usage(),
        model_id="mystery",
        provider="openai",
        budget=BudgetConfig(1.0, "day"),
        role="odd",
    )
    await drain(unpriced)
    assert ledger_for(config).unpriced("odd", since) == 1


async def test_spent_budget_without_degrade_raises(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    spend(config, "brain", 15.0)
    inner = Usage(["never"])
    model = role_model(config, inner, budget=BudgetConfig(15.0, "month"))
    with pytest.raises(BudgetExhausted) as info:
        await drain(model)
    assert inner.calls == []  # the provider is never called
    exc = info.value
    assert (exc.role, exc.spend, exc.max_budget) == ("brain", 15.0, 15.0)
    assert exc.reset_at == datetime(2026, 10, 1, tzinfo=TIMEZONE)
    assert exc.notice("en") == (
        "The brain budget is spent ($15.00 of $15.00) and resets at 01.10.2026 00:00. To raise "
        "the cap, change it in tau.toml."
    )
    assert exc.notice("tr").startswith("brain bütçesi doldu ($15.00 / $15.00); 01.10.2026 00:00")


async def test_spent_budget_degrades_and_the_stand_in_pays(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    spend(config, "brain", 20.0)
    fast = role_model(
        config,
        Usage(["Hızlı."]),
        role="fast",
        model_id="claude-haiku-4-5",
        budget=BudgetConfig(1.0, "day"),
    )
    built: list[int] = []

    def factory():
        built.append(1)
        return fast

    model = role_model(
        config,
        Usage(["never"]),
        budget=BudgetConfig(15.0, "month"),
        degrade="fast",
        degrade_factory=factory,
    )
    events = await drain(model)
    assert any("contentBlockDelta" in e for e in events)
    assert model.take_notices() == [
        BudgetDegraded("brain", "fast", datetime(2026, 10, 1, tzinfo=TIMEZONE))
    ]
    assert model.take_notices() == []
    since, _ = period_bounds("day", NOW)
    assert ledger_for(config).spent("fast", since) == pytest.approx((1000 + 500 * 5) / 1e6)
    await drain(model)
    assert built == [1]  # built once, on first use


async def test_both_budgets_spent(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    spend(config, "brain", 20.0)
    spend(config, "fast", 2.0)
    fast = role_model(config, Usage(), role="fast", budget=BudgetConfig(1.0, "day"))
    model = role_model(
        config,
        Usage(),
        budget=BudgetConfig(15.0, "month"),
        degrade="fast",
        degrade_factory=lambda: fast,
    )
    with pytest.raises(BudgetExhausted) as info:
        await drain(model)
    assert info.value.also is not None and info.value.also.role == "fast"
    assert info.value.notice("en") == (
        "The brain budget is spent until 01.10.2026 00:00, and fast, which stands in for it, "
        "is spent too until 01.10.2026 00:00."
    )


# -- failover ----------------------------------------------------------------------------------


def test_is_unavailable() -> None:
    assert is_unavailable(openai.APIConnectionError(request=REQUEST))
    assert is_unavailable(EventLoopException(ConnectionRefusedError("refused")))
    assert is_unavailable(
        openai.InternalServerError("boom", response=httpx.Response(503, request=REQUEST), body=None)
    )
    assert is_unavailable(httpx.ConnectTimeout("slow"))
    assert not is_unavailable(ModelThrottledException("slow down"))
    assert not is_unavailable(
        openai.BadRequestError("bad", response=httpx.Response(400, request=REQUEST), body=None)
    )
    assert not is_unavailable(RuntimeError("model says no"))


async def test_unreachable_model_fails_over(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config = test_config(tmp_path)
    fast = Usage(["Ben fast."])
    model = role_model(
        config,
        Unreachable(openai.APIConnectionError(request=REQUEST)),
        role="local",
        provider="ollama",
        model_id="qwen3.5:9b",
        failover="fast",
        failover_factory=lambda: fast,
    )
    with caplog.at_level(logging.WARNING, logger="tau_core.budget"):
        events = await drain(model)
    assert any("contentBlockDelta" in e for e in events) and len(fast.calls) == 1
    assert model.take_notices() == [FailedOver("local", "fast")]
    assert FailedOver("local", "fast").notice("en") == (
        "local is not reachable right now; fast answered instead."
    )
    assert "role local: ollama qwen3.5:9b is not reachable (Connection error.); fast" in caplog.text


async def test_failover_only_for_unreachable_and_before_streaming(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    for error in (RuntimeError("model says no"), ModelThrottledException("slow down")):
        model = role_model(
            config,
            Unreachable(error),
            failover="fast",
            failover_factory=lambda: FakeModel(["never"]),
        )
        with pytest.raises(type(error)):
            await drain(model)

    class Midway(FakeModel):
        async def stream(self, *args, **kwargs):
            yield {"messageStart": {"role": "assistant"}}
            raise openai.APIConnectionError(request=REQUEST)

    model = role_model(
        config, Midway(), failover="fast", failover_factory=lambda: FakeModel(["never"])
    )
    with pytest.raises(openai.APIConnectionError):
        await drain(model)
    assert model.take_notices() == []
    without = role_model(config, Unreachable(openai.APIConnectionError(request=REQUEST)))
    with pytest.raises(openai.APIConnectionError):
        await drain(without)


# -- through a TauAgent ------------------------------------------------------------------------


async def test_agent_turn_degrades_and_says_so(tmp_path: Path) -> None:
    config = config_with(
        tmp_path,
        brain=RoleConfig(
            "fake", "fake", budget=BudgetConfig(0.5, "month", "fast"), params={"default": "never"}
        ),
        fast=RoleConfig("fake", "fake", params={"default": "Hızlı cevap."}),
    )
    spend(config, "brain", 1.0)
    ledger_for(config).record(
        role="brain", provider="fake", model_id="fake", usage={}, cost_usd=1.0
    )
    agent = build_agent(config=config, role="brain", tools=[], context_sources=[])
    turn = [event async for event in agent.stream("merhaba")]
    notices = [e for e in turn if isinstance(e, Notice)]
    assert len(notices) == 1 and notices[0].text.startswith("The brain budget is spent until ")
    assert notices[0].text.endswith("; fast answered instead.")
    assert turn[-1] == TurnEnd(stop_reason="end_turn")
    assert agent.messages[-1]["content"][0]["text"] == "Hızlı cevap."


async def test_agent_turn_reports_a_spent_budget_without_a_trace(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config = config_with(
        tmp_path, brain=RoleConfig("fake", "fake", budget=BudgetConfig(0.5, "day"))
    )
    config = config.with_overrides(ui=config.ui.__class__(language="tr"))
    ledger_for(config).record(
        role="brain", provider="fake", model_id="fake", usage={}, cost_usd=1.0
    )
    agent = build_agent(config=config, role="brain", tools=[], context_sources=[])
    with caplog.at_level(logging.WARNING):
        turn = [event async for event in agent.stream("merhaba")]
    assert len(turn) == 2 and turn[1] == TurnEnd(stop_reason="error")
    assert turn[0].text.startswith("brain bütçesi doldu ($1.00 / $0.50); ")
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]  # no stack trace
    assert "model call refused" in caplog.text


def test_model_error_text_prefers_the_notice() -> None:
    wrapped = EventLoopException(BudgetExhausted("brain", spend=2.0, max_budget=1.0))
    assert model_error_text(wrapped, "en").startswith("The brain budget is spent ($2.00 of $1.00)")
    assert model_error_text(RuntimeError("x"), "en") == (
        "Model call failed: x. Details are in the log."
    )
