"""The per-turn loop guard: Strands ``Limits(turns=[agent].max_turns)`` and its Turkish notice."""

from __future__ import annotations

from pathlib import Path

import pytest
from tau_core import (
    Config,
    ConfigError,
    Decision,
    EventBus,
    MemorySessionStore,
    Notice,
    TextDelta,
    Tier,
    ToolFinished,
    TurnEnd,
    build_agent,
    tau_tool,
)
from tau_core.config import AgentConfig
from tau_core.testing import FakeModel, ScriptedApprover, ToolCall, record_events, test_config

polls: list[str] = []


@tau_tool(tier=Tier.READ)
def poll_sensor() -> str:
    """Sensörü okur."""
    polls.append("poll")
    return "21 derece"


@tau_tool(tier=Tier.PHYSICAL, effect="Pencereyi açar.")
def open_window() -> str:
    """Pencereyi açar."""
    polls.append("window")
    return "açıldı"


@pytest.fixture(autouse=True)
def _reset_polls() -> None:
    polls.clear()


def notice_text(n: int) -> str:
    return (
        f"Bu turda araç çağrısı sınırına ulaştım ({n} tur). "
        "Durdum; devam etmemi isterseniz söyleyin."
    )


def runaway_model(tool: str = "poll_sensor") -> FakeModel:
    """A model that asks for ``tool`` forever."""
    model = FakeModel(default="")
    model.replies = [lambda messages, system: [ToolCall(tool)]] * 100
    return model


def with_max_turns(config: Config, n: int) -> Config:
    return config.with_overrides(agent=AgentConfig(max_turns=n))


def write_max_turns(tmp_path: Path, value: str) -> Path:
    home = test_config(tmp_path).home
    toml = home / "tau.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8").replace("max_turns = 12", f"max_turns = {value}"),
        encoding="utf-8",
    )
    return home


async def run_turn(agent, prompt: str = "sürekli sensöre bak") -> list:
    return [event async for event in agent.stream(prompt)]


async def test_guard_is_configured_in_tau_toml(tmp_path: Path) -> None:
    home = write_max_turns(tmp_path, "3")
    config = Config.load(home, env={"TAU_DATA_DIR": str(tmp_path / "data")})
    assert config.agent.max_turns == 3
    bus = EventBus()
    seen = record_events(bus, "turn_limit")
    model = runaway_model()
    agent = build_agent(config=config, model=model, tools=[poll_sensor], events=bus)

    turn = await run_turn(agent)

    assert len(model.calls) == 3 and len(polls) == 3
    assert [e for e in turn if isinstance(e, Notice)] == [Notice(text=notice_text(3))]
    assert turn[-1] == TurnEnd(stop_reason="limit_turns")
    assert [e.data for e in seen] == [{"max_turns": 3}]
    assert seen[0].session_id == agent.session_id


@pytest.mark.parametrize("value", ["0", "-2", '"12"', "1.5"])
def test_invalid_guard_is_a_config_error(tmp_path: Path, value: str) -> None:
    home = write_max_turns(tmp_path, value)
    with pytest.raises(ConfigError) as info:
        Config.load(home, env={"TAU_DATA_DIR": str(tmp_path / "data")})
    assert "max_turns" in str(info.value)


@pytest.mark.parametrize("n", [1, 2, 5])
async def test_guard_stops_a_runaway_loop(config: Config, n: int) -> None:
    model = runaway_model()
    agent = build_agent(config=with_max_turns(config, n), model=model, tools=[poll_sensor])

    turn = await run_turn(agent)

    assert len(model.calls) == n
    # Tools asked for in the last allowed turn still run; nothing runs after the cap.
    assert len([e for e in turn if isinstance(e, ToolFinished)]) == len(polls) == n
    notices = [e for e in turn if isinstance(e, Notice)]
    assert notices == [Notice(text=notice_text(n))]
    assert turn[-2:] == [Notice(text=notice_text(n)), TurnEnd(stop_reason="limit_turns")]


async def test_answer_on_the_last_allowed_turn_is_not_cut(config: Config) -> None:
    bus = EventBus()
    seen = record_events(bus, "turn_limit", "notice")
    model = FakeModel([[ToolCall("poll_sensor")], [ToolCall("poll_sensor")], "Oda 21 derece."])
    agent = build_agent(
        config=with_max_turns(config, 3), model=model, tools=[poll_sensor], events=bus
    )

    turn = await run_turn(agent)

    assert len(model.calls) == 3
    assert "".join(e.text for e in turn if isinstance(e, TextDelta)) == "Oda 21 derece."
    assert not [e for e in turn if isinstance(e, Notice)]
    assert turn[-1] == TurnEnd(stop_reason="end_turn") and seen == []


async def test_each_turn_gets_a_fresh_budget(config: Config) -> None:
    model = runaway_model()
    agent = build_agent(config=with_max_turns(config, 2), model=model, tools=[poll_sensor])
    first = await run_turn(agent)
    assert first[-1] == TurnEnd(stop_reason="limit_turns")

    model.replies = [[ToolCall("poll_sensor")], "Şimdi 21 derece."]
    second = await run_turn(agent, "bir kez daha bak")

    assert second[-1] == TurnEnd(stop_reason="end_turn")
    assert "".join(e.text for e in second if isinstance(e, TextDelta)) == "Şimdi 21 derece."
    assert not [e for e in second if isinstance(e, Notice)]


async def test_guard_stops_repeated_rejected_tier2_calls(config: Config) -> None:
    approver = ScriptedApprover()  # rejects every request
    model = runaway_model("open_window")
    agent = build_agent(
        config=with_max_turns(config, 3), model=model, tools=[open_window], approver=approver
    )

    turn = await run_turn(agent, "pencereyi aç")

    assert polls == []  # never ran
    assert len(approver.requests) == 3  # every attempt was asked, none approved
    assert [e.approval for e in turn if isinstance(e, ToolFinished)] == ["rejected"] * 3
    assert turn[-1] == TurnEnd(stop_reason="limit_turns")


async def test_guard_counts_approved_tier2_calls_too(config: Config) -> None:
    approver = ScriptedApprover([Decision.APPROVED] * 2)
    model = runaway_model("open_window")
    agent = build_agent(
        config=with_max_turns(config, 2), model=model, tools=[open_window], approver=approver
    )
    turn = await run_turn(agent, "pencereyi aç")
    assert polls == ["window", "window"]
    assert turn[-1] == TurnEnd(stop_reason="limit_turns")


async def test_turn_limit_is_recorded_in_the_session(config: Config) -> None:
    store = MemorySessionStore()
    agent = build_agent(
        config=with_max_turns(config, 2),
        model=runaway_model(),
        tools=[poll_sensor],
        session_store=store,
    )
    await run_turn(agent)
    events = store.read_events(agent.session_id)
    assert [e.kind for e in events] == ["tool_call", "tool_call", "turn_limit"]
    assert events[-1].data == {"max_turns": 2}


async def test_history_stays_alternating_after_the_guard(config: Config) -> None:
    model = runaway_model()
    agent = build_agent(config=with_max_turns(config, 2), model=model, tools=[poll_sensor])
    await run_turn(agent)
    model.replies = ["Tamam."]
    await run_turn(agent, "peki")

    roles = [message["role"] for message in model.calls[-1].messages]
    assert all(a != b for a, b in zip(roles, roles[1:], strict=False)), roles
