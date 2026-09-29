from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

import pytest
from tau_core import (
    AgentEvent,
    Config,
    Decision,
    EventBus,
    MemorySessionStore,
    Notice,
    TextDelta,
    Tier,
    ToolFinished,
    ToolUseStarted,
    TurnEnd,
    build_agent,
    tau_tool,
)
from tau_core.approval import AutoRejectApprover
from tau_core.config import AgentConfig
from tau_core.persona import PersonaLoader
from tau_core.sessions import new_session_id
from tau_core.testing import FakeModel, ScriptedApprover, ToolCall
from tau_core.tiers import ToolCatalog, UntieredToolError

REFUSAL = "Kullanıcı bu eylemi onaylamadı: lamp. Eylemi yapma, kullanıcıya kısaca bildir."

lamp_calls: list[str] = []


@tau_tool(tier=Tier.READ)
def clock_tool() -> str:
    """Saati söyler."""
    return "15:30"


@tau_tool(tier=Tier.PHYSICAL, effect="Masa lambasını açar.")
def lamp(state: str) -> str:
    """Masa lambasını açar veya kapatır.

    Args:
        state: "on" ya da "off".
    """
    lamp_calls.append(state)
    return f"lamba {state}"


@pytest.fixture(autouse=True)
def _reset_lamp() -> None:
    lamp_calls.clear()


async def collect(agent, prompt: str) -> list:
    return [event async for event in agent.stream(prompt)]


def events_of(bus: EventBus) -> list[AgentEvent]:
    seen: list[AgentEvent] = []
    bus.subscribe(seen.append)
    return seen


async def test_turkish_reply_and_tier0_tool(config: Config) -> None:
    model = FakeModel([[ToolCall("clock_tool", {})], "Saat 15:30, efendim."])
    bus = EventBus()
    seen = events_of(bus)
    agent = build_agent(config=config, model=model, tools=[clock_tool, lamp], events=bus)

    turn = await collect(agent, "Saat kaç?")

    started = [e for e in turn if isinstance(e, ToolUseStarted)]
    finished = [e for e in turn if isinstance(e, ToolFinished)]
    assert started == [ToolUseStarted(tool_use_id="t1", tool="clock_tool", tier=0)]
    assert finished == [
        ToolFinished(
            tool_use_id="t1", tool="clock_tool", status="ok", summary="15:30", approval=None
        )
    ]
    assert turn.index(started[0]) < turn.index(finished[0])
    assert "".join(e.text for e in turn if isinstance(e, TextDelta)) == "Saat 15:30, efendim."
    assert turn[-1] == TurnEnd(stop_reason="end_turn")

    tool_calls = [e for e in seen if e.kind == "tool_call"]
    assert len(tool_calls) == 1
    data = tool_calls[0].data
    assert data["tool"] == "clock_tool" and data["tier"] == 0 and data["status"] == "ok"
    assert data["approval"] is None and data["tool_use_id"] == "t1"
    assert isinstance(data["duration_ms"], int)
    assert tool_calls[0].session_id == agent.session_id


async def test_ask_returns_text(config: Config) -> None:
    agent = build_agent(config=config, model=FakeModel(["Buyurun efendim."]), tools=[])
    assert await agent.ask("merhaba") == "Buyurun efendim."
    assert agent.messages[-1]["role"] == "assistant"


async def test_tier2_rejected_by_default_approver(config: Config) -> None:
    model = FakeModel([[ToolCall("lamp", {"state": "on"})], "Peki, açmıyorum."])
    bus = EventBus()
    seen = events_of(bus)
    agent = build_agent(config=config, model=model, tools=[lamp], events=bus)
    assert isinstance(agent.gate.approver, AutoRejectApprover)

    turn = await collect(agent, "Lambayı aç")

    assert lamp_calls == []
    finished = [e for e in turn if isinstance(e, ToolFinished)]
    assert finished[0].status == "rejected" and finished[0].approval == "rejected"
    # The refusal reaches the model as the tool result.
    tool_result = model.calls[1].messages[-1]["content"][0]["toolResult"]
    assert tool_result["status"] == "error"
    assert tool_result["content"][0]["text"] == REFUSAL
    kinds = [e.kind for e in seen]
    assert kinds == ["approval", "tool_call"]
    approval = seen[0].data
    assert approval["decision"] == "rejected" and approval["channel"] == "auto-reject"
    assert approval["effect"] == "Masa lambasını açar." and approval["tier"] == 2
    assert seen[1].data["status"] == "rejected" and seen[1].data["duration_ms"] is None


async def test_tier2_approved_runs(config: Config) -> None:
    approver = ScriptedApprover([Decision.APPROVED])
    model = FakeModel([[ToolCall("lamp", {"state": "on"})], "Lamba açıldı, efendim."])
    agent = build_agent(config=config, model=model, tools=[lamp], approver=approver, channel="test")

    turn = await collect(agent, "Lambayı aç")

    assert lamp_calls == ["on"]
    finished = [e for e in turn if isinstance(e, ToolFinished)][0]
    assert (finished.status, finished.approval, finished.summary) == ("ok", "approved", "lamba on")
    request = approver.requests[0]
    assert (request.tool, request.tier, request.arguments) == (
        "lamp",
        Tier.PHYSICAL,
        {"state": "on"},
    )
    assert request.effect == "Masa lambasını açar." and request.channel == "test"
    assert request.session_id == agent.session_id


async def test_exemption_skips_approval(config: Config) -> None:
    approver = ScriptedApprover()
    model = FakeModel([[ToolCall("lamp", {"state": "off"})], "Tamam."])
    agent = build_agent(
        config=config,
        model=model,
        tools=[lamp],
        approver=approver,
        exemptions=[lambda name, args: name == "lamp" and args == {"state": "off"}],
    )
    turn = await collect(agent, "kapat")
    assert lamp_calls == ["off"] and approver.requests == []
    assert [e for e in turn if isinstance(e, ToolFinished)][0].approval == "exempt"


def test_untiered_tool_refused(config: Config) -> None:
    from strands import tool

    @tool
    def bare() -> str:
        """Tier yok."""
        return "x"

    with pytest.raises(UntieredToolError) as info:
        ToolCatalog().add(bare)
    assert (
        str(info.value)
        == "'bare' aracı tier bildirmiyor; kaydedilemez. @tau_tool(tier=...) kullanın."
    )
    with pytest.raises(UntieredToolError):
        build_agent(config=config, model=FakeModel(), tools=[bare])


async def test_unknown_tool_fails_closed(config: Config) -> None:
    bus = EventBus()
    seen = events_of(bus)
    model = FakeModel([[ToolCall("ghost", {})], "Yapamadım."])
    agent = build_agent(config=config, model=model, tools=[clock_tool], events=bus)
    turn = await collect(agent, "hayalet")
    finished = [e for e in turn if isinstance(e, ToolFinished)][0]
    assert finished.status == "rejected"
    text = model.calls[1].messages[-1]["content"][0]["toolResult"]["content"][0]["text"]
    assert text == "'ghost' aracı kayıtlı değil; çalıştırılmadı."
    assert [e.kind for e in seen] == ["error", "tool_call"]


async def test_loop_guard(config: Config) -> None:
    config = config.with_overrides(agent=AgentConfig(max_turns=2))
    bus = EventBus()
    seen = events_of(bus)
    model = FakeModel(default="")
    model.replies = [lambda messages, system: [ToolCall("clock_tool", {})]] * 10
    agent = build_agent(config=config, model=model, tools=[clock_tool], events=bus)

    turn = await collect(agent, "sonsuza kadar saat sor")

    notices = [e for e in turn if isinstance(e, Notice)]
    assert notices == [
        Notice(
            text="Bu turda araç çağrısı sınırına ulaştım (2 tur). "
            "Durdum; devam etmemi isterseniz söyleyin."
        )
    ]
    assert turn[-1] == TurnEnd(stop_reason="limit_turns")
    assert len(model.calls) == 2
    limits = [e for e in seen if e.kind == "turn_limit"]
    assert len(limits) == 1 and limits[0].data == {"max_turns": 2}


async def test_model_error_becomes_notice(config: Config, caplog: pytest.LogCaptureFixture) -> None:
    class Broken(FakeModel):
        async def stream(self, *args, **kwargs):
            raise RuntimeError("bağlantı koptu")
            yield  # pragma: no cover

    bus = EventBus()
    seen = events_of(bus)
    store = MemorySessionStore()
    agent = build_agent(config=config, model=Broken(), tools=[], events=bus, session_store=store)
    with caplog.at_level(logging.ERROR):
        turn = await collect(agent, "merhaba")
    assert turn == [
        Notice(text="Model çağrısı başarısız oldu: bağlantı koptu. Ayrıntı günlükte."),
        TurnEnd(stop_reason="error"),
    ]
    assert [e.kind for e in seen] == ["error"]
    assert seen[0].data["where"] == "model"
    # History stays alternating (user, assistant) in memory and in the store.
    assert [m["role"] for m in agent.messages] == ["user", "assistant"]
    stored = store.list_messages(agent.session_id, "tau")
    assert [m.message["role"] for m in stored] == ["user", "assistant"]


async def test_persona_hook_rereads_changed_file(config: Config, fixed_now: datetime) -> None:
    model = FakeModel(["bir", "iki"])
    agent = build_agent(config=config, model=model, tools=[], clock=lambda: fixed_now)
    await agent.ask("ilk")
    persona_file = config.persona_dir / "persona.md"
    persona_file.write_text("Yeni persona: çok resmi konuş.\n", encoding="utf-8")
    stat = persona_file.stat()
    os.utime(persona_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    await agent.ask("ikinci")

    first, second = (call.system_prompt or "" for call in model.calls)
    assert first.startswith("Sen tau'sun")
    assert second.startswith("Yeni persona: çok resmi konuş.")
    for prompt in (first, second):
        assert "## Kullanıcı\nKullanıcıya 'siz' diye hitap et." in prompt
        assert "- Tarih ve saat: 29.09.2026 15:30, Salı (Europe/Istanbul)" in prompt
        assert "- Profil: ev" in prompt
        assert "- Canlı node'lar: bilinmiyor" in prompt
        assert "- Bugünkü bütçe: bilinmiyor" in prompt


async def test_profile_and_context_sources(config: Config) -> None:
    model = FakeModel(["tamam"])
    agent = build_agent(
        "spor",
        config=config,
        model=model,
        tools=[],
        context_sources=[lambda: {"nodes": ["mac", "arm"]}, lambda: {"budget": "2,40 $ kaldı"}],
    )
    await agent.ask("durum")
    prompt = model.calls[0].system_prompt or ""
    assert "- Profil: spor" in prompt
    assert "- Canlı node'lar: mac, arm" in prompt
    assert "- Bugünkü bütçe: 2,40 $ kaldı" in prompt
    assert agent.config.profile == "spor"


def test_missing_user_file_defaults_to_siz(config: Config) -> None:
    (config.persona_dir / "user.md").unlink()
    loader = PersonaLoader(config.persona_dir)
    assert loader.read().user is None


async def test_session_round_trip(config: Config, fixed_now: datetime) -> None:
    store = MemorySessionStore()
    session_id = new_session_id(lambda: fixed_now)
    assert session_id.startswith("20260929-123000-")
    first = build_agent(
        config=config,
        model=FakeModel([[ToolCall("clock_tool", {})], "Saat 15:30."]),
        tools=[clock_tool],
        session_id=session_id,
        session_store=store,
    )
    await first.ask("Saat kaç, lütfen söyler misiniz?")
    first.close()

    model = FakeModel(["Az önce saati sordunuz."])
    second = build_agent(
        config=config, model=model, tools=[clock_tool], session_id=session_id, session_store=store
    )
    assert second.messages == first.messages
    await second.ask("Ne sormuştum?")
    sent = model.calls[0].messages
    assert sent[0]["content"][0]["text"] == "Saat kaç, lütfen söyler misiniz?"
    assert len(sent) == 5  # user, tool use, tool result, reply, new user message

    meta = store.read_meta(session_id)
    assert meta["title"] == "Saat kaç, lütfen söyler misiniz?"
    assert meta["channel"] == "terminal" and meta["profile"] == "ev"
    events = store.read_events(session_id)
    assert [e.kind for e in events] == ["tool_call"]
    summary = store.list_sessions()[0]
    assert summary.session_id == session_id and summary.message_count == 6


async def test_discovered_tools_and_untiered_plugin_skipped(
    config: Config, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    agent = build_agent(config=config, model=FakeModel())
    assert {"current_time", "demo_physical_action", "example_echo"} <= set(agent.catalog.names())

    from strands import tool

    @tool
    def rogue() -> str:
        """Tier yok."""
        return "x"

    rogue.tau_distribution = "tau-rogue"
    monkeypatch.setattr("tau_core.agent.discover_tools", lambda: [rogue, clock_tool])
    with caplog.at_level(logging.WARNING, logger="tau_core.agent"):
        agent = build_agent(config=config, model=FakeModel())
    assert agent.catalog.names() == ["clock_tool"]
    assert "tau-rogue" in caplog.text and "'rogue' aracı tier bildirmiyor" in caplog.text


def test_build_agent_is_self_contained(tmp_path: Path, config: Config) -> None:
    # No store, no network, no hub state: nothing is written under the data dir.
    agent = build_agent(config=config, model=FakeModel(), tools=[])
    assert agent.store is None
    assert not config.data_dir.exists()
