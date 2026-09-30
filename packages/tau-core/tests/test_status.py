"""``/status`` and ``/model`` reports (``tau_core.status``)."""

from __future__ import annotations

import logging

import pytest
from tau_core import (
    Config,
    ModelInfo,
    Tier,
    build_agent,
    describe_model,
    role_lines,
    status_lines,
    status_report,
    tau_tool,
)
from tau_core.builder import Check
from tau_core.config import RoleConfig
from tau_core.sessions import MemorySessionStore
from tau_core.status import check_hub, stored_message_count, stored_role, tau_versions
from tau_core.testing import FakeModel


@tau_tool(tier=Tier.READ)
def probe() -> str:
    """Reads something."""
    return "x"


@tau_tool(tier=Tier.PHYSICAL, effect="Moves the test arm.")
def move() -> str:
    """Moves something."""
    return "moved"


HUB_DOWN = Check(
    "hub", "info", "hub is not running (nothing answers on http://127.0.0.1:7877/health)"
)


def test_describe_model_reads_the_instance_not_the_config(config: Config) -> None:
    agent = build_agent(config=config, model=FakeModel(), tools=[])
    assert describe_model(agent) == describe_model(agent)
    info = describe_model(agent)
    assert (info.provider, info.model_id, info.fallback_of) == ("fake", "fake", None)

    class AnthropicModel(FakeModel):  # the class name is what the report keys on
        pass

    roles = dict(config.roles)
    roles["brain"] = RoleConfig(
        provider="bedrock",
        model_id="b",
        fallback=RoleConfig(provider="anthropic", model_id="claude-x"),
    )
    fallback_config = config.with_overrides(roles=roles)
    on_fallback = build_agent(config=fallback_config, model=AnthropicModel(), tools=[])
    assert describe_model(on_fallback).provider == "anthropic"
    assert describe_model(on_fallback).fallback_of == "bedrock"

    class ExampleModel(FakeModel):  # an entry-point provider: the role's provider is reported
        pass

    unknown = build_agent(config=config, model=ExampleModel(), tools=[], role="fast")
    assert describe_model(unknown) == describe_model(unknown)
    assert (describe_model(unknown).provider, describe_model(unknown).fallback_of) == ("fake", None)


def test_status_lines_in_both_languages(config: Config) -> None:
    store = MemorySessionStore()
    agent = build_agent(
        config=config,
        model=FakeModel(),
        tools=[probe, move],
        session_store=store,
        session_id="20260929-120000-abcd",
    )
    store.write_meta(agent.session_id, title="Lambayı kapat")
    lines = status_lines(agent, language="en", hub=HUB_DOWN)
    assert lines[0] == "Profile: home"
    assert lines[1] == (
        "Session: 20260929-120000-abcd · Lambayı kapat · 0 messages stored · role brain"
    )
    assert lines[2] == "Model: brain → fake · fake"
    assert lines[3] == "Context: sliding, window 60 · 0 messages in memory"
    assert lines[4] == "Tools: 2 registered · 1 need approval (tier 2)"
    assert lines[5] == "UI language: en"
    assert lines[6].startswith("Versions: tau-core ")
    assert lines[7] == "Hub: hub is not running (nothing answers on http://127.0.0.1:7877/health)"
    assert not any("KEY" in line or "SECRET" in line for line in lines)

    tr = status_lines(agent, language="tr", hub=None)
    assert tr[0] == "Profil: home"
    assert tr[1].startswith("Oturum: 20260929-120000-abcd · Lambayı kapat")
    assert tr[3] == "Bağlam: sliding, pencere 60 · bellekte 0 mesaj"
    assert tr[4] == "Araçlar: 2 kayıtlı · 1 onay ister (tier 2)"
    assert tr[5] == "Arayüz dili: tr" and tr[6].startswith("Sürümler: ")
    assert len(tr) == 7  # no hub line without a check

    untracked = build_agent(config=config, model=FakeModel(), tools=[])
    assert " · (untitled) · 0 messages stored" in status_lines(untracked)[1]


def test_status_reports_the_fallback(config: Config) -> None:
    class AnthropicModel(FakeModel):
        pass

    roles = dict(config.roles)
    roles["brain"] = RoleConfig(
        provider="bedrock", model_id="b", fallback=RoleConfig(provider="anthropic", model_id="c")
    )
    agent = build_agent(config=config.with_overrides(roles=roles), model=AnthropicModel(), tools=[])
    assert status_lines(agent)[2] == (
        "Model: brain → anthropic (fallback; bedrock has no credentials) · fake"
    )


def test_role_lines(config: Config) -> None:
    roles = dict(config.roles)
    roles["brain"] = RoleConfig(
        provider="bedrock", model_id="b", fallback=RoleConfig(provider="anthropic", model_id="c")
    )
    agent = build_agent(config=config.with_overrides(roles=roles), model=FakeModel(), tools=[])
    assert role_lines(agent) == [
        "Model role: brain (fake)",
        "Roles in tau.toml:",
        "  brain  bedrock (fallback anthropic) · current",
        "  fast   fake",
        "  local  fake",
    ]
    assert role_lines(agent, "tr")[:2] == ["Model rolü: brain (fake)", "tau.toml'daki roller:"]
    assert role_lines(agent, "tr")[2].endswith("(yedek anthropic) · geçerli")


def test_stored_role_and_count(config: Config, caplog: pytest.LogCaptureFixture) -> None:
    store = MemorySessionStore()
    assert stored_role(None, "s", config) is None
    assert stored_role(store, None, config) is None
    assert stored_role(store, "missing", config) is None
    store.write_meta("s", role="fast")
    assert stored_role(store, "s", config) == "fast"
    store.write_meta("s", role="gone")
    with caplog.at_level(logging.WARNING):
        assert stored_role(store, "s", config) is None  # a role tau.toml no longer defines
    assert "remembers role 'gone'" in caplog.text

    assert stored_message_count(None, "s") is None
    assert stored_message_count(store, "never-created") is None
    agent = build_agent(config=config, model=FakeModel(), tools=[], session_store=store)
    assert stored_message_count(store, agent.session_id) == 0


def test_tau_versions_lists_core_first() -> None:
    versions = tau_versions()
    assert versions[0][0] == "tau-core" and versions[0][1]


def test_describe_model_reads_the_provider_tags(
    config: Config, clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """m6: an entry-point provider (the ``fake2`` fixture) has any class name; ``resolve_model``
    tags the instance, so the report names the provider and a fallback correctly."""
    monkeypatch.setenv("EXAMPLE_API_KEY", "k")
    roles = dict(config.roles)
    roles["plug"] = RoleConfig(provider="fake2", model_id="p")
    roles["brain"] = RoleConfig(
        provider="bedrock", model_id="b", fallback=RoleConfig(provider="fake2", model_id="f")
    )
    plugged = config.with_overrides(roles=roles)
    direct = build_agent(config=plugged, role="plug", tools=[])
    assert type(direct.agent.model).__name__ == "FakeModel"  # would read as "fake" untagged
    assert direct.agent.model.tau_provider == "fake2"
    assert describe_model(direct) == ModelInfo("fake2", "fake", None)
    on_fallback = build_agent(config=plugged, role="brain", tools=[])  # no AWS credentials
    assert describe_model(on_fallback) == ModelInfo("fake2", "fake", "bedrock")
    assert status_lines(on_fallback)[2] == (
        "Model: brain → fake2 (fallback; bedrock has no credentials) · fake"
    )
    assert role_lines(direct)[0] == "Model role: plug (fake2)"


def test_hub_check_never_raises(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    """m5: an ``http.client`` error is not an ``OSError``; the check must report, not raise."""
    import asyncio
    import http.client

    class Opener:
        def open(self, url, timeout=None):
            raise http.client.IncompleteRead(b"")

    monkeypatch.setattr("tau_core.builder._OPENER", Opener())
    check = check_hub(config)
    assert check.status == "warn"
    assert check.detail.startswith("control API check failed on http://127.0.0.1:7877/health: ")
    assert "IncompleteRead" in check.detail
    agent = build_agent(config=config, model=FakeModel(), tools=[])
    lines = asyncio.run(status_report(agent))
    assert lines[-1].startswith("Hub: control API check failed on ")


def test_status_reports_the_budget(config: Config) -> None:
    from datetime import datetime

    from tau_core.config import BudgetConfig
    from tau_core.persona import TIMEZONE
    from tau_core.spend import RoleSpend, ledger_for

    roles = {**config.roles, "brain": RoleConfig("fake", "fake", budget=BudgetConfig(15, "month"))}
    budgeted = config.with_overrides(roles=roles)
    agent = build_agent(config=budgeted, model=FakeModel(), tools=[], context_sources=[])
    since = datetime(2026, 9, 1, tzinfo=TIMEZONE)
    reset = datetime(2026, 10, 1, tzinfo=TIMEZONE)
    spends = {"brain": RoleSpend("brain", "fake", "fake", 0.42, "month", since, reset, 15.0)}
    lines = status_lines(agent, language="en", spends=spends)
    assert lines[-1] == "Budget: brain $0.42 of $15.00 this month (resets 01.10.2026 00:00)"
    ledger_for(budgeted).record(
        role="brain", provider="fake", model_id="fake", usage={}, cost_usd=1.25
    )
    assert status_lines(agent, language="tr")[-1].startswith("Bütçe: brain $1.25 of $15.00")
    plain = status_lines(build_agent(config=config, model=FakeModel(), tools=[]))
    assert not any(line.startswith("Budget") for line in plain)  # no budget, no line
