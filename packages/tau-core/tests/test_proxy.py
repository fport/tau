"""The ``proxy`` and ``ollama`` providers and ``ProxyModel``: budgets, degrade, proxy down.

Nothing here reaches a network: ``OpenAIModel.stream`` and the key lookup are replaced, and
the response hook is fed a hand-made ``httpx.Response``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import openai
import pytest
from strands.models.openai import OpenAIModel
from strands.types.exceptions import EventLoopException, ModelThrottledException
from tau_core import Config
from tau_core import proxy as proxy_module
from tau_core.agent import Notice, TurnEnd, build_agent, model_error_text
from tau_core.config import BudgetConfig, RoleConfig
from tau_core.models import (
    BudgetDegraded,
    BudgetExhausted,
    ProxyUnavailable,
    proxy_key_env,
    proxy_url,
    required_env,
    resolve_model,
)
from tau_core.proxy import ProxyModel, is_budget_error, parse_timestamp
from tau_core.spend import tracker_for
from tau_core.testing import FakeModel, test_config

URL = "http://proxy.test"
RESET = "2026-10-01T00:00:00+00:00"
REQUEST = httpx.Request("POST", f"{URL}/v1/chat/completions")


def budget_error(message: str = "Budget has been exceeded! Current cost: 0.2") -> Exception:
    """What Strands raises for the proxy's 429: a throttle wrapping the openai error."""
    error = openai.RateLimitError(
        message,
        response=httpx.Response(429, request=REQUEST),
        body={"message": message, "type": "budget_exceeded", "code": "429"},
    )
    try:
        raise ModelThrottledException(str(error)) from error
    except ModelThrottledException as throttled:
        return throttled


def patch_stream(monkeypatch: pytest.MonkeyPatch, *behaviour: Any) -> list[str]:
    """Replace ``OpenAIModel.stream``: each call takes the next item, an exception to raise
    before any event or a text to stream. Returns the model groups that were called."""
    queue = list(behaviour)
    called: list[str] = []

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        called.append(self.get_config()["model_id"])
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockDelta": {"delta": {"text": item}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "end_turn"}}

    monkeypatch.setattr(OpenAIModel, "stream", stream)
    return called


def patch_key_info(monkeypatch: pytest.MonkeyPatch, **info: Any) -> list[tuple[str, str]]:
    seen: list[tuple[str, str]] = []

    def fetch(base_url: str, api_key: str, *, timeout: float = 3.0) -> dict:
        seen.append((base_url, api_key))
        return {"spend": 0.2, "max_budget": 0.1, "budget_reset_at": RESET, **info}

    monkeypatch.setattr(proxy_module, "fetch_key_info", fetch)
    return seen


def proxy_model(**kwargs: Any) -> ProxyModel:
    return ProxyModel(
        base_url=URL, api_key="sk-test", model_id="brain", params={"max_tokens": 64}, **kwargs
    )


async def drain(generator: AsyncGenerator) -> list:
    return [event async for event in generator]


def proxy_config(tmp_path: Path, *, degrade: str | None = "fast") -> Config:
    config = test_config(tmp_path)
    roles = dict(config.roles)
    roles["brain"] = RoleConfig(
        "proxy", "brain", max_tokens=64, budget=BudgetConfig(1.0, "1mo", degrade)
    )
    return config.with_overrides(roles=roles)


# -- providers ----------------------------------------------------------------------------------


def test_proxy_key_and_url_names() -> None:
    assert proxy_key_env(RoleConfig("proxy", "brain")) == "TAU_PROXY_KEY_BRAIN"
    assert proxy_key_env(RoleConfig("proxy", "vision-2")) == "TAU_PROXY_KEY_VISION_2"
    own = RoleConfig("proxy", "brain", params={"api_key_env": "MY_KEY", "base_url": URL + "/"})
    assert proxy_key_env(own) == "MY_KEY"
    assert required_env(own) == [["MY_KEY"]]
    assert proxy_url(own, {}) == URL
    assert proxy_url(RoleConfig("proxy", "b"), {"TAU_PROXY_URL": "http://h:1/"}) == "http://h:1"
    assert proxy_url(None, {}) == "http://127.0.0.1:4000"
    assert required_env(RoleConfig("ollama", "qwen")) == []


def test_resolve_proxy_role_builds_a_proxy_model(tmp_path: Path) -> None:
    config = proxy_config(tmp_path)
    env = {"TAU_PROXY_KEY_BRAIN": "sk-brain", "TAU_PROXY_URL": URL}
    model = resolve_model("brain", config, env=env)
    assert isinstance(model, ProxyModel)
    assert model.client_args == {"base_url": f"{URL}/v1", "api_key": "sk-brain"}
    assert model.get_config()["model_id"] == "brain"
    assert model.get_config()["params"] == {"max_tokens": 64}
    assert (model.tau_provider, model.tau_role, model.role) == ("proxy", "brain", "brain")
    assert model._degrade_role == "fast"
    # The request client carries the header hook; Strands builds one per request from these.
    args = model._resolve_client_args()
    assert args["base_url"] == f"{URL}/v1" and args["api_key"] == "sk-brain"
    assert model._on_response in args["http_client"].event_hooks["response"]


def test_resolve_ollama_role_directly(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    roles = {**config.roles, "local": RoleConfig("ollama", "qwen3.5:9b", max_tokens=100)}
    model = resolve_model("local", config.with_overrides(roles=roles), env={})
    assert type(model) is OpenAIModel
    assert model.client_args["base_url"] == "http://127.0.0.1:11434/v1"
    assert model.get_config()["params"] == {"max_tokens": 100}
    elsewhere = resolve_model(
        "local",
        config.with_overrides(roles=roles),
        env={"TAU_OLLAMA_URL": "http://my-mac.tailXXXXXX.ts.net:11434"},
    )
    assert elsewhere.client_args["base_url"] == "http://my-mac.tailXXXXXX.ts.net:11434/v1"


# -- recognising a spent budget ------------------------------------------------------------------


def test_is_budget_error_follows_the_chain() -> None:
    assert is_budget_error(budget_error())
    wrapped = EventLoopException(budget_error())
    assert is_budget_error(wrapped)
    assert is_budget_error(RuntimeError("Authentication Error, ExceededTokenBudget: Current"))
    plain_429 = openai.RateLimitError(
        "slow down",
        response=httpx.Response(429, request=REQUEST),
        body={"message": "slow down", "type": "rate_limit_error"},
    )
    assert not is_budget_error(plain_429)
    assert not is_budget_error(RuntimeError("boom"))


def test_parse_timestamp() -> None:
    assert parse_timestamp(RESET) == datetime(2026, 10, 1, tzinfo=UTC)
    assert parse_timestamp("2026-10-01T00:00:00Z") == datetime(2026, 10, 1, tzinfo=UTC)
    assert parse_timestamp("2026-10-01T00:00:00") == datetime(2026, 10, 1, tzinfo=UTC)
    assert parse_timestamp(None) is None and parse_timestamp("soon") is None


# -- ProxyModel.stream ---------------------------------------------------------------------------


async def test_spent_budget_without_degrade_raises_budget_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = patch_stream(monkeypatch, budget_error())
    seen = patch_key_info(monkeypatch)
    model = proxy_model()
    model.tau_role = "brain"
    with pytest.raises(BudgetExhausted) as info:
        await drain(model.stream([], None, None))
    exc = info.value
    assert called == ["brain"]  # refused once, never retried as throttling
    assert seen == [(URL, "sk-test")]
    assert (exc.role, exc.spend, exc.max_budget) == ("brain", 0.2, 0.1)
    assert exc.reset_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert exc.notice("en") == (
        "The brain budget is spent ($0.20 of $0.10) and resets at 01.10.2026 03:00. To raise "
        "the cap, change it in tau.toml and run tau proxy keys."
    )
    assert exc.notice("tr").startswith("brain bütçesi doldu ($0.20 / $0.10); 01.10.2026 03:00")


async def test_spent_budget_degrades_to_the_cheaper_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_stream(monkeypatch, budget_error())
    patch_key_info(monkeypatch)
    model = proxy_model()
    fast = FakeModel(["Hızlı cevap."])
    built: list[int] = []

    def factory() -> FakeModel:
        built.append(1)
        return fast

    model.set_degrade("fast", factory)
    events = await drain(model.stream([], None, "system"))
    assert any("contentBlockDelta" in event for event in events)
    assert len(fast.calls) == 1 and fast.calls[0].system_prompt == "system"
    (notice,) = model.take_notices()
    assert notice == BudgetDegraded("brain", "fast", datetime(2026, 10, 1, tzinfo=UTC))
    assert notice.notice("en") == (
        "The brain budget is spent until 01.10.2026 03:00; fast answered instead."
    )
    assert model.take_notices() == []  # each notice once
    # The degrade model is built once and reused.
    patch_stream(monkeypatch, budget_error())
    await drain(model.stream([], None, None))
    assert built == [1] and len(fast.calls) == 2


async def test_both_budgets_spent(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_stream(monkeypatch, budget_error())
    patch_key_info(monkeypatch)
    model = proxy_model()

    class Spent(FakeModel):
        async def stream(self, *args, **kwargs):
            raise BudgetExhausted("fast", reset_at=datetime(2026, 9, 30, 21, 0, tzinfo=UTC))
            yield  # pragma: no cover - an async generator

    model.set_degrade("fast", Spent)
    with pytest.raises(BudgetExhausted) as info:
        await drain(model.stream([], None, None))
    assert info.value.also is not None and info.value.also.role == "fast"
    assert info.value.notice("en") == (
        "The brain budget is spent until 01.10.2026 03:00, and fast, which stands in for it, "
        "is spent too until 01.10.2026 00:00."
    )
    assert model.take_notices() == []


async def test_unknown_budget_state_still_gives_a_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_stream(monkeypatch, budget_error())

    def unreachable(base_url: str, api_key: str, *, timeout: float = 3.0) -> dict:
        raise OSError("connection refused")

    monkeypatch.setattr(proxy_module, "fetch_key_info", unreachable)
    with pytest.raises(BudgetExhausted) as info:
        await drain(proxy_model().stream([], None, None))
    assert info.value.notice("en").startswith(
        "The brain budget is spent ($? of $?) and resets at the end of its period."
    )


async def test_unreachable_proxy_becomes_proxy_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_stream(monkeypatch, openai.APIConnectionError(request=REQUEST))
    with pytest.raises(ProxyUnavailable) as info:
        await drain(proxy_model().stream([], None, None))
    assert info.value.notice("en") == (
        f"The model proxy at {URL} is not answering. Start it with infra/litellm/proxy.sh up."
    )


async def test_other_errors_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_stream(monkeypatch, RuntimeError("model says no"))
    with pytest.raises(RuntimeError, match="model says no"):
        await drain(proxy_model().stream([], None, None))


async def test_an_error_after_streaming_started_is_not_degraded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        yield {"messageStart": {"role": "assistant"}}
        raise budget_error()

    monkeypatch.setattr(OpenAIModel, "stream", stream)
    model = proxy_model()
    model.set_degrade("fast", lambda: FakeModel(["never"]))
    with pytest.raises(ModelThrottledException):
        await drain(model.stream([], None, None))
    assert model.take_notices() == []


# -- response headers ----------------------------------------------------------------------------


async def test_response_hook_logs_fallbacks_and_feeds_spend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    config = proxy_config(tmp_path)
    env = {"TAU_PROXY_KEY_BRAIN": "sk-brain", "TAU_PROXY_URL": URL}
    patch_key_info(monkeypatch, spend=0.1, max_budget=1.0, budget_duration="1mo")
    tracker = tracker_for(config, env)
    assert tracker.refresh()["brain"].spend == 0.1

    model = proxy_model()
    model.tau_role = "brain"
    response = httpx.Response(
        200,
        request=REQUEST,
        headers={
            "x-litellm-attempted-fallbacks": "1",
            "x-litellm-model-group": "fast",
            "x-litellm-model-name": "anthropic/claude-haiku",
            "x-litellm-key-spend": "0.42",
        },
    )
    with caplog.at_level(logging.WARNING, logger="tau_core.proxy"):
        await model._on_response(response)
    assert (
        "role brain: the proxy fell back from model group brain to fast "
        "(anthropic/claude-haiku)" in caplog.text
    )
    assert tracker.snapshot()["brain"].spend == 0.42

    caplog.clear()
    quiet = httpx.Response(200, request=REQUEST, headers={"x-litellm-attempted-fallbacks": "0"})
    with caplog.at_level(logging.WARNING, logger="tau_core.proxy"):
        await model._on_response(quiet)
    assert caplog.text == ""


# -- through a TauAgent --------------------------------------------------------------------------


async def test_agent_turn_degrades_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = proxy_config(tmp_path)
    monkeypatch.setenv("TAU_PROXY_KEY_BRAIN", "sk-brain")
    monkeypatch.setenv("TAU_PROXY_URL", URL)
    patch_stream(monkeypatch, budget_error())
    patch_key_info(monkeypatch)
    agent = build_agent(config=config, role="brain", tools=[], context_sources=[])
    turn = [event async for event in agent.stream("merhaba")]
    notices = [event for event in turn if isinstance(event, Notice)]
    assert notices == [
        Notice(text="The brain budget is spent until 01.10.2026 03:00; fast answered instead.")
    ]
    assert turn[-1] == TurnEnd(stop_reason="end_turn")
    assert [m["role"] for m in agent.messages] == ["user", "assistant"]


async def test_agent_turn_reports_a_spent_budget_without_a_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    config = proxy_config(tmp_path, degrade=None)
    config = config.with_overrides(ui=config.ui.__class__(language="tr"))
    monkeypatch.setenv("TAU_PROXY_KEY_BRAIN", "sk-brain")
    monkeypatch.setenv("TAU_PROXY_URL", URL)
    patch_stream(monkeypatch, budget_error(), "Tekrar buradayım.")
    patch_key_info(monkeypatch)
    agent = build_agent(config=config, role="brain", tools=[], context_sources=[])
    with caplog.at_level(logging.WARNING):
        turn = [event async for event in agent.stream("merhaba")]
    text = BudgetExhausted(
        "brain", spend=0.2, max_budget=0.1, reset_at=datetime(2026, 10, 1, tzinfo=UTC)
    ).notice("tr")
    assert turn == [Notice(text=text), TurnEnd(stop_reason="error")]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]  # no stack trace
    assert "model call refused" in caplog.text
    # The next turn repairs the history and answers once the key works again.
    assert await agent.ask("tekrar") == "Tekrar buradayım."


def test_model_error_text_prefers_the_notice() -> None:
    wrapped = EventLoopException(ProxyUnavailable(URL))
    assert model_error_text(wrapped, "tr").startswith(f"{URL} adresindeki model proxy'si")
    assert model_error_text(RuntimeError("x"), "en") == (
        "Model call failed: x. Details are in the log."
    )
