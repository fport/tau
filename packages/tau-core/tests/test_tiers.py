"""Tier declarations, the tool catalog, and every tier path through a real Strands loop."""

from __future__ import annotations

import logging

import pytest
from strands import tool
from tau_core import (
    Config,
    Decision,
    EventBus,
    MemorySessionStore,
    TextDelta,
    Tier,
    ToolCatalog,
    ToolFinished,
    ToolUseStarted,
    build_agent,
    tau_tool,
)
from tau_core.testing import (
    FakeModel,
    ScriptedApprover,
    ToolCall,
    UnansweredApprover,
    record_events,
)
from tau_core.tiers import UntieredToolError, effect_of, tier_of

UNTIERED = "'{}' aracı tier bildirmiyor; kaydedilemez. @tau_tool(tier=...) kullanın."

ran: list[str] = []


@tau_tool(tier=Tier.READ)
def read_note() -> str:
    """Notu okur."""
    ran.append("read_note")
    return "not: süt al"


@tau_tool(tier=Tier.DIGITAL_WRITE)
def write_note(text: str) -> str:
    """Nota bir satır ekler.

    Args:
        text: Eklenecek satır.
    """
    ran.append("write_note")
    return f"eklendi: {text}"


@tau_tool(tier=Tier.PHYSICAL, effect="Kapıyı açar.")
def open_door(door: str) -> str:
    """Bir kapıyı açar.

    Args:
        door: Kapının adı.
    """
    ran.append("open_door")
    return f"{door} açıldı"


@tau_tool(tier=Tier.DIGITAL_WRITE)
def broken_write() -> str:
    """Her zaman hata verir."""
    ran.append("broken_write")
    raise RuntimeError("disk dolu")


TOOLS = [read_note, write_note, open_door, broken_write]


@pytest.fixture(autouse=True)
def _reset_ran() -> None:
    ran.clear()


def _bare_tool():
    @tool
    def bare() -> str:
        """Tier yok."""
        return "x"

    return bare


def tool_result_text(model: FakeModel, call: int = 1, block: int = 0) -> tuple[str, str]:
    """``(status, text)`` of a tool result the model received on its ``call``-th request."""
    result = model.calls[call].messages[-1]["content"][block]["toolResult"]
    return result["status"], result["content"][0]["text"]


# --- declarations ------------------------------------------------------------------------------


def test_tau_tool_sets_tier_and_effect() -> None:
    assert tier_of(read_note) is Tier.READ
    assert tier_of(write_note) is Tier.DIGITAL_WRITE
    assert tier_of(open_door) is Tier.PHYSICAL
    assert open_door.tau_effect == "Kapıyı açar."
    assert read_note.tau_effect is None
    assert open_door.tool_name == "open_door"


def test_tau_tool_accepts_int_and_passes_strands_kwargs() -> None:
    @tau_tool(2, name="kapi_ac", description="Ön kapıyı açar.")
    def door() -> str:
        return "açık"

    assert tier_of(door) is Tier.PHYSICAL
    assert door.tool_name == "kapi_ac"
    assert effect_of(door) == "Ön kapıyı açar."


@pytest.mark.parametrize("bad", [3, -1, True, "2"])
def test_tau_tool_refuses_invalid_tier(bad: object) -> None:
    with pytest.raises(ValueError):

        @tau_tool(bad)  # type: ignore[arg-type]
        def nope() -> str:
            """x"""
            return "x"


@pytest.mark.parametrize("bad", [None, True, False, "high", 7])
def test_tier_of_refuses_missing_or_invalid_tier(bad: object) -> None:
    bare = _bare_tool()
    if bad is not None:
        bare.tau_tier = bad
    with pytest.raises(UntieredToolError) as info:
        tier_of(bare)
    assert str(info.value) == UNTIERED.format("bare")
    assert info.value.tool == "bare"


def test_effect_prefers_declared_effect_then_description() -> None:
    assert effect_of(open_door) == "Kapıyı açar."
    assert effect_of(write_note).startswith("Nota bir satır ekler.")


# --- catalog -----------------------------------------------------------------------------------


def test_untiered_tool_cannot_be_registered() -> None:
    catalog = ToolCatalog([read_note])
    with pytest.raises(UntieredToolError) as info:
        catalog.add(_bare_tool())
    assert str(info.value) == UNTIERED.format("bare")
    assert catalog.names() == ["read_note"]


def test_extend_is_all_or_nothing() -> None:
    catalog = ToolCatalog()
    with pytest.raises(UntieredToolError):
        catalog.extend([read_note, _bare_tool(), open_door])
    assert len(catalog) == 0
    with pytest.raises(UntieredToolError):
        ToolCatalog([write_note, _bare_tool()])


def test_catalog_lookup() -> None:
    catalog = ToolCatalog(TOOLS)
    assert catalog.names() == ["read_note", "write_note", "open_door", "broken_write"]
    assert catalog.tools() == TOOLS
    assert catalog.tier("open_door") is Tier.PHYSICAL
    assert catalog.tier("ghost") is None
    assert catalog.get("write_note") is write_note and catalog.get("ghost") is None
    assert "read_note" in catalog and "ghost" not in catalog
    catalog.remove("read_note")
    catalog.remove("ghost")  # unknown names are ignored
    assert "read_note" not in catalog and len(catalog) == 3


def test_catalog_replacement_warns(caplog: pytest.LogCaptureFixture) -> None:
    @tau_tool(Tier.READ, name="open_door")
    def harmless() -> str:
        """x"""
        return "x"

    catalog = ToolCatalog([open_door])
    with caplog.at_level(logging.WARNING, logger="tau_core.tiers"):
        catalog.add(harmless)
    assert catalog.get("open_door") is harmless
    assert "open_door registered twice" in caplog.text


def test_build_agent_refuses_untiered_tool(config: Config) -> None:
    with pytest.raises(UntieredToolError):
        build_agent(config=config, model=FakeModel(), tools=[read_note, _bare_tool()])


# --- each tier path through build_agent -----------------------------------------------------


async def run_turn(agent, prompt: str = "hadi") -> list:
    return [event async for event in agent.stream(prompt)]


async def test_tier0_runs_freely(config: Config) -> None:
    bus = EventBus()
    seen = record_events(bus)
    approver = ScriptedApprover()
    model = FakeModel([[ToolCall("read_note")], "Süt alacaksınız."])
    agent = build_agent(config=config, model=model, tools=TOOLS, approver=approver, events=bus)

    turn = await run_turn(agent)

    assert ran == ["read_note"] and approver.requests == []
    assert [e.kind for e in seen] == ["tool_call"]
    data = seen[0].data
    assert (data["tool"], data["tier"], data["status"], data["approval"]) == (
        "read_note",
        0,
        "ok",
        None,
    )
    assert data["result_summary"] == "not: süt al" and data["arguments"] == {}
    assert ToolUseStarted(tool_use_id="t1", tool="read_note", tier=0) in turn


async def test_tier1_runs_and_is_logged(config: Config, caplog: pytest.LogCaptureFixture) -> None:
    bus = EventBus()
    seen = record_events(bus)
    approver = ScriptedApprover()
    model = FakeModel([[ToolCall("write_note", {"text": "ekmek"})], "Ekledim."])
    agent = build_agent(config=config, model=model, tools=TOOLS, approver=approver, events=bus)

    with caplog.at_level(logging.DEBUG, logger="tau_core.approval"):
        await run_turn(agent)

    assert ran == ["write_note"] and approver.requests == []
    assert [e.kind for e in seen] == ["tool_call"]
    assert seen[0].data["tier"] == 1 and seen[0].data["arguments"] == {"text": "ekmek"}
    assert seen[0].data["result_summary"] == "eklendi: ekmek"
    [record] = [r for r in caplog.records if r.getMessage().startswith("tool_call")]
    assert record.levelno == logging.INFO
    message = record.getMessage()
    assert '"text": "ekmek"' in message and "eklendi: ekmek" in message
    assert "approval=None" in message


async def test_tier2_approved_runs(config: Config, caplog: pytest.LogCaptureFixture) -> None:
    bus = EventBus()
    seen = record_events(bus)
    approver = ScriptedApprover([Decision.APPROVED])
    model = FakeModel([[ToolCall("open_door", {"door": "ön"})], "Açtım."])
    agent = build_agent(
        config=config, model=model, tools=TOOLS, approver=approver, events=bus, channel="test"
    )

    with caplog.at_level(logging.INFO, logger="tau_core.approval"):
        turn = await run_turn(agent)

    assert ran == ["open_door"]
    [request] = approver.requests
    assert (request.tool, request.tier, request.arguments, request.effect) == (
        "open_door",
        Tier.PHYSICAL,
        {"door": "ön"},
        "Kapıyı açar.",
    )
    assert request.channel == "test" and request.session_id == agent.session_id
    assert [e.kind for e in seen] == ["approval", "tool_call"]
    assert seen[0].data["decision"] == "approved" and seen[0].data["channel"] == "scripted"
    assert seen[0].data["request_id"] == request.request_id
    assert seen[1].data["approval"] == "approved" and seen[1].data["status"] == "ok"
    [finished] = [e for e in turn if isinstance(e, ToolFinished)]
    assert (finished.status, finished.approval) == ("ok", "approved")
    [record] = [r for r in caplog.records if r.getMessage().startswith("tool_call")]
    assert record.levelno == logging.INFO and "approval=approved" in record.getMessage()


@pytest.mark.parametrize("decision", [Decision.REJECTED, Decision.TIMEOUT])
async def test_tier2_not_approved_refusal_reaches_model(config: Config, decision: Decision) -> None:
    bus = EventBus()
    seen = record_events(bus)
    model = FakeModel([[ToolCall("open_door", {"door": "ön"})], "Açmadım."])
    agent = build_agent(
        config=config, model=model, tools=TOOLS, approver=ScriptedApprover([decision]), events=bus
    )

    turn = await run_turn(agent)

    assert ran == []
    assert tool_result_text(model) == (
        "error",
        "Kullanıcı bu eylemi onaylamadı: open_door. Eylemi yapma, kullanıcıya kısaca bildir.",
    )
    assert [e.kind for e in seen] == ["approval", "tool_call"]
    assert seen[0].data["decision"] == decision.value
    assert seen[1].data["status"] == "rejected" and seen[1].data["approval"] == decision.value
    assert seen[1].data["duration_ms"] is None
    [finished] = [e for e in turn if isinstance(e, ToolFinished)]
    assert (finished.status, finished.approval) == ("rejected", decision.value)
    assert "".join(e.text for e in turn if isinstance(e, TextDelta)) == "Açmadım."


async def test_tier2_default_approver_rejects(config: Config) -> None:
    model = FakeModel([[ToolCall("open_door", {"door": "ön"})], "Açmadım."])
    agent = build_agent(config=config, model=model, tools=TOOLS)
    await run_turn(agent)
    assert ran == []
    assert tool_result_text(model)[1].startswith("Kullanıcı bu eylemi onaylamadı: open_door.")


async def test_tier2_timeout_through_approver_attribute(config: Config) -> None:
    # build_agent has no timeout parameter; a channel approver declares its own.
    bus = EventBus()
    seen = record_events(bus, "approval", "tool_call")
    approver = UnansweredApprover(timeout_seconds=0.01)
    model = FakeModel([[ToolCall("open_door", {"door": "ön"})], "Yanıt gelmedi."])
    agent = build_agent(config=config, model=model, tools=TOOLS, approver=approver, events=bus)

    turn = await run_turn(agent)

    assert ran == [] and len(approver.requests) == 1 and approver.cancelled == 1
    assert [e.data.get("decision", e.data.get("approval")) for e in seen] == ["timeout", "timeout"]
    [finished] = [e for e in turn if isinstance(e, ToolFinished)]
    assert (finished.status, finished.approval) == ("rejected", "timeout")
    assert tool_result_text(model)[1].startswith("Kullanıcı bu eylemi onaylamadı: open_door.")


async def test_tier2_exempt_runs_without_prompt(config: Config) -> None:
    bus = EventBus()
    seen = record_events(bus)
    approver = ScriptedApprover()
    model = FakeModel([[ToolCall("open_door", {"door": "garaj"})], "Rutin çalıştı."])
    agent = build_agent(
        config=config,
        model=model,
        tools=TOOLS,
        approver=approver,
        events=bus,
        exemptions=[lambda name, args: name == "open_door" and args == {"door": "garaj"}],
    )

    await run_turn(agent)

    assert ran == ["open_door"] and approver.requests == []
    assert [e.kind for e in seen] == ["tool_call"]
    assert seen[0].data["approval"] == "exempt" and seen[0].data["tier"] == 2


async def test_exemption_does_not_cover_other_arguments(config: Config) -> None:
    model = FakeModel([[ToolCall("open_door", {"door": "ön"})], "Açmadım."])
    agent = build_agent(
        config=config,
        model=model,
        tools=TOOLS,
        exemptions=[lambda name, args: args == {"door": "garaj"}],
    )
    await run_turn(agent)
    assert ran == []


async def test_unknown_tool_fails_closed_even_if_exempt(config: Config) -> None:
    bus = EventBus()
    seen = record_events(bus)
    approver = ScriptedApprover([Decision.APPROVED])
    model = FakeModel([[ToolCall("launch_rocket", {"now": True})], "Yapamam."])
    agent = build_agent(
        config=config,
        model=model,
        tools=TOOLS,
        approver=approver,
        events=bus,
        exemptions=[lambda name, args: True],
    )

    turn = await run_turn(agent)

    assert approver.requests == [] and approver.decisions == [Decision.APPROVED]
    assert tool_result_text(model) == (
        "error",
        "'launch_rocket' aracı kayıtlı değil; çalıştırılmadı.",
    )
    assert [e.kind for e in seen] == ["error", "tool_call"]
    assert seen[0].data == {
        "message": "'launch_rocket' aracı kayıtlı değil; çalıştırılmadı.",
        "where": "tier_gate",
        "tool": "launch_rocket",
    }
    assert seen[1].data["tier"] is None and seen[1].data["status"] == "rejected"
    assert ToolUseStarted(tool_use_id="t1", tool="launch_rocket", tier=None) in turn


async def test_tool_removed_from_catalog_is_refused(config: Config) -> None:
    # The gate looks tools up live: a tool dropped from the catalog stops running at once.
    model = FakeModel([[ToolCall("read_note")], "Okuyamadım."])
    agent = build_agent(config=config, model=model, tools=TOOLS)
    agent.catalog.remove("read_note")
    await run_turn(agent)
    assert ran == []
    assert tool_result_text(model)[1] == "'read_note' aracı kayıtlı değil; çalıştırılmadı."


async def test_tool_error_is_recorded(config: Config) -> None:
    bus = EventBus()
    seen = record_events(bus, "tool_call")
    model = FakeModel([[ToolCall("broken_write")], "Olmadı."])
    agent = build_agent(config=config, model=model, tools=TOOLS, events=bus)
    await run_turn(agent)
    assert ran == ["broken_write"]
    assert seen[0].data["status"] == "error" and "disk dolu" in seen[0].data["result_summary"]
    assert seen[0].data["approval"] is None and seen[0].data["tier"] == 1


async def test_mixed_batch_runs_only_what_is_allowed(config: Config) -> None:
    bus = EventBus()
    seen = record_events(bus, "tool_call")
    store = MemorySessionStore()
    approver = ScriptedApprover([Decision.REJECTED])
    model = FakeModel(
        [
            [
                ToolCall("read_note"),
                ToolCall("write_note", {"text": "yumurta"}),
                ToolCall("open_door", {"door": "ön"}),
            ],
            "Notu okudum, satırı ekledim, kapıyı açmadım.",
        ]
    )
    agent = build_agent(
        config=config,
        model=model,
        tools=TOOLS,
        approver=approver,
        events=bus,
        session_store=store,
    )

    await run_turn(agent)

    assert sorted(ran) == ["read_note", "write_note"]
    assert len(approver.requests) == 1
    by_tool = {e.data["tool"]: e.data for e in seen}
    assert {name: (d["tier"], d["status"], d["approval"]) for name, d in by_tool.items()} == {
        "read_note": (0, "ok", None),
        "write_note": (1, "ok", None),
        "open_door": (2, "rejected", "rejected"),
    }
    # Every tier's call is also in the session record.
    stored = [e for e in store.read_events(agent.session_id) if e.kind == "tool_call"]
    assert sorted(e.data["tool"] for e in stored) == ["open_door", "read_note", "write_note"]


async def test_gate_failure_fails_closed(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    model = FakeModel([[ToolCall("read_note")], "Olmadı."])
    agent = build_agent(config=config, model=model, tools=TOOLS)

    async def explode(*args, **kwargs):
        raise RuntimeError("gate bug")

    monkeypatch.setattr(agent.gate, "check", explode)
    await run_turn(agent)
    assert ran == []
    assert tool_result_text(model)[1].startswith("Kullanıcı bu eylemi onaylamadı: read_note.")
