"""``TauAgent.stream`` against Strands 1.57.1: error paths, stop reasons and the repair turn.

Every case here failed or misbehaved before the correctness pass (issue 064): history was
appended by hand, ``ConcurrencyException`` corrupted the other turn, interrupts left the agent
stuck, ``max_tokens``/overflow/throttle were generic failures, cancel was impossible.
"""

from __future__ import annotations

import asyncio
import logging
import types
from typing import Any

import pytest
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.types.exceptions import (
    ConcurrencyException,
    ContextWindowOverflowException,
    ModelThrottledException,
)
from strands.types.session import SessionMessage
from tau_core import (
    STOP_REASONS,
    Config,
    EventBus,
    MemorySessionStore,
    Notice,
    ReasoningDelta,
    TextDelta,
    Throttled,
    Tier,
    ToolFinished,
    ToolProgress,
    ToolUseStarted,
    TurnEnd,
    build_agent,
    tau_tool,
    to_turn_event,
)
from tau_core.agent import AGENT_ID, TauAgent, turn_limit_text
from tau_core.channels.terminal import render_turn_event
from tau_core.config import AgentConfig
from tau_core.i18n import t
from tau_core.testing import FakeModel, ToolCall, Truncated, record_events


@tau_tool(tier=Tier.READ)
def clock_tool() -> str:
    """Tells the time."""
    return "15:30"


async def collect(agent: TauAgent, prompt: str) -> list:
    return [event async for event in agent.stream(prompt)]


def roles(messages: list[dict[str, Any]]) -> list[str]:
    return [m["role"] for m in messages]


def repair_text(text: str) -> list[dict[str, str]]:
    return [{"text": f"({text})"}]


# --- to_turn_event: the pure mapping of the SDK's dict events -------------------------------


def test_stop_reasons_are_documented_on_turn_end() -> None:
    assert STOP_REASONS == (
        "end_turn",
        "limit_turns",
        "limit_total_tokens",
        "max_tokens",
        "cancelled",
        "interrupt",
        "error",
        "busy",
    )
    for reason in STOP_REASONS:
        assert f"``{reason}``" in (TurnEnd.__doc__ or "")


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        ({"data": "mer", "delta": {"text": "mer"}, "agent": object()}, TextDelta(text="mer")),
        ({"data": ""}, None),
        (
            {"current_tool_use": {"toolUseId": "t1", "name": "clock_tool", "input": ""}},
            ToolUseStarted(tool_use_id="t1", tool="clock_tool", tier=None),
        ),
        ({"current_tool_use": {"toolUseId": "t1", "input": ""}}, None),
        ({"current_tool_use": None}, None),
        ({"reasoningText": "let me think", "reasoning": True}, ReasoningDelta("let me think")),
        ({"reasoningText": None, "reasoning": True}, None),
        (
            {
                "type": "tool_stream",
                "tool_stream_event": {
                    "tool_use": {"toolUseId": "t2", "name": "move_arm", "input": {}},
                    "data": "50 %",
                },
            },
            ToolProgress(tool_use_id="t2", tool="move_arm", text="50 %"),
        ),
        ({"event_loop_throttled_delay": 4}, Throttled(delay_seconds=4.0)),
        ({"init_event_loop": True}, None),
        ({"start_event_loop": True}, None),
        ({"message": {"role": "assistant", "content": []}}, None),
        ({"event": {"messageStart": {"role": "assistant"}}}, None),
    ],
)
def test_to_turn_event_maps_sdk_keys(event: dict, expected) -> None:
    assert to_turn_event(event) == expected


def test_force_stop_is_logged_not_shown(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="tau_core.agent"):
        assert to_turn_event({"force_stop": True, "force_stop_reason": "boom"}) is None
    assert "force-stopped" in caplog.text and "boom" in caplog.text


def test_terminal_renders_throttle_and_ignores_reasoning_and_progress() -> None:
    assert render_turn_event(Throttled(delay_seconds=4.0)) == "  ⏳ Model is busy, retrying in 4 s."
    assert render_turn_event(Throttled(delay_seconds=2.5), "tr") == (
        "  ⏳ Model yoğun, 2.5 sn sonra tekrar deniyorum."
    )
    assert render_turn_event(ReasoningDelta(text="hmm")) is None
    assert render_turn_event(ToolProgress(tool_use_id="t", tool="x", text="1")) is None


# --- 1: no manual history append; the next turn repairs through the SDK ---------------------


async def test_turn_limit_is_repaired_on_the_next_turn(config: Config) -> None:
    config = config.with_overrides(agent=AgentConfig(max_turns=2))
    model = FakeModel(default="")
    model.replies = [lambda m, s: [ToolCall("clock_tool")]] * 2 + ["Peki."]
    store = MemorySessionStore()
    agent = build_agent(config=config, model=model, tools=[clock_tool], session_store=store)

    first = await collect(agent, "saate bak durma")
    assert first[-2:] == [Notice(text=turn_limit_text(2)), TurnEnd(stop_reason="limit_turns")]
    # The loop stopped after the tools ran: the history ends on the tool-result user message.
    assert roles(agent.messages) == ["user", "assistant", "user", "assistant", "user"]

    second = await collect(agent, "yeter")
    assert second[-1] == TurnEnd(stop_reason="end_turn")
    sent = model.calls[-1].messages
    assert roles(sent)[-3:] == ["user", "assistant", "user"]
    assert sent[-2]["content"] == repair_text(turn_limit_text(2))
    assert sent[-1]["content"] == [{"text": "yeter"}]
    stored = store.list_messages(agent.session_id, AGENT_ID)
    assert roles([m.message for m in stored]) == roles(agent.messages)
    assert all("tracking_id" in m for m in agent.messages)


async def test_crash_restored_session_is_repaired(config: Config) -> None:
    store = MemorySessionStore()
    first = build_agent(
        config=config, model=FakeModel(["Bir."]), tools=[], session_store=store, session_id="s-1"
    )
    await first.ask("bir")
    first.close()
    # The hub died after storing the user message and before the reply.
    dangling = {"role": "user", "content": [{"text": "cevapsız kaldı"}]}
    store.create_message("s-1", AGENT_ID, SessionMessage.from_message(dangling, 2))

    model = FakeModel(["Devam."])
    second = build_agent(
        config=config, model=model, tools=[], session_store=store, session_id="s-1"
    )
    assert roles(second.messages) == ["user", "assistant", "user"]

    assert await second.ask("devam") == "Devam."
    sent = model.calls[0].messages
    assert roles(sent) == ["user", "assistant", "user", "assistant", "user"]
    assert sent[3]["content"] == repair_text(t("notice.previous_turn_unfinished"))
    assert sent[4]["content"] == [{"text": "devam"}]


# --- 2: serialized calls; the SDK's concurrency guard becomes a busy notice -----------------


class Yielding(FakeModel):
    """Gives the event loop a chance to switch tasks before every chunk."""

    async def stream(self, *args, **kwargs):
        async for chunk in super().stream(*args, **kwargs):
            await asyncio.sleep(0)
            yield chunk


async def test_overlapping_streams_are_serialized(config: Config) -> None:
    bus = EventBus()
    seen = record_events(bus, "error")
    model = Yielding(["Bir.", "İki."])
    agent = build_agent(config=config, model=model, tools=[], events=bus)

    first, second = await asyncio.gather(collect(agent, "bir"), collect(agent, "iki"))

    assert first[-1] == second[-1] == TurnEnd(stop_reason="end_turn")
    assert not [e for e in first + second if isinstance(e, Notice)]
    assert roles(agent.messages) == ["user", "assistant", "user", "assistant"]
    assert [m["content"][0]["text"] for m in agent.messages] == ["bir", "Bir.", "iki", "İki."]
    assert seen == []


async def test_sdk_concurrency_guard_becomes_a_busy_turn(config: Config) -> None:
    gate = asyncio.Event()
    entered = asyncio.Event()

    class Blocking(FakeModel):
        async def stream(self, *args, **kwargs):
            entered.set()
            await gate.wait()
            async for chunk in super().stream(*args, **kwargs):
                yield chunk

    bus = EventBus()
    seen = record_events(bus)
    model = Blocking(["Birinci.", "İkinci."])
    agent = build_agent(config=config, model=model, tools=[], events=bus)

    async def raw_turn() -> None:  # a caller that bypasses TauAgent's lock
        async for _ in agent.agent.stream_async("birinci"):
            pass

    task = asyncio.create_task(raw_turn())
    await entered.wait()
    before = [dict(m) for m in agent.messages]

    turn = await collect(agent, "ikinci")

    assert turn == [Notice(text=t("notice.busy")), TurnEnd(stop_reason="busy")]
    assert agent.messages == before  # the other turn's history was not touched
    assert seen == []  # no error event
    gate.set()
    await task
    assert [m["content"][0]["text"] for m in agent.messages] == ["birinci", "Birinci."]


# --- 3: an interrupt is refused inside the same turn -----------------------------------------


class InterruptingHook(HookProvider):
    def __init__(self) -> None:
        self.responses: list[Any] = []

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before)

    def before(self, event: BeforeToolCallEvent) -> None:
        response = event.interrupt("x", reason="test")  # raises the first time
        self.responses.append(response)
        event.cancel_tool = "refused by the test hook"


async def test_interrupt_is_refused_and_the_agent_is_not_left_stuck(config: Config) -> None:
    hook = InterruptingHook()
    bus = EventBus()
    seen = record_events(bus, "error")
    model = FakeModel([[ToolCall("clock_tool")], "Yapamadım.", "Sonraki."])
    agent = build_agent(config=config, model=model, tools=[clock_tool], hooks=[hook], events=bus)

    turn = await collect(agent, "saat")

    assert turn[0] == ToolUseStarted(tool_use_id="t1", tool="clock_tool", tier=0)
    assert Notice(text=t("notice.interrupt_refused")) in turn
    [finished] = [e for e in turn if isinstance(e, ToolFinished)]
    assert (finished.status, finished.summary) == ("rejected", "refused by the test hook")
    assert "".join(e.text for e in turn if isinstance(e, TextDelta)) == "Yapamadım."
    assert turn[-1] == TurnEnd(stop_reason="end_turn")
    assert hook.responses == [{"tau": "rejected"}]
    assert [e.data["where"] for e in seen] == ["interrupt"]
    assert not agent.agent._interrupt_state.activated
    # The next plain turn works: the agent is not stuck in interrupt state.
    assert await agent.ask("tekrar") == "Sonraki."
    assert roles(agent.messages) == ["user", "assistant", "user", "assistant", "user", "assistant"]


# --- 4: max_tokens keeps the partial reply -----------------------------------------------------


async def test_max_tokens_is_a_notice_not_an_error(config: Config) -> None:
    bus = EventBus()
    seen = record_events(bus)
    model = FakeModel([Truncated("Uzun bir cevap"), "Devamı."])
    agent = build_agent(config=config, model=model, tools=[], events=bus)

    turn = await collect(agent, "anlat")

    assert "".join(e.text for e in turn if isinstance(e, TextDelta)) == "Uzun bir cevap"
    assert turn[-2:] == [Notice(text=t("notice.max_tokens")), TurnEnd(stop_reason="max_tokens")]
    assert [(e.kind, e.data["reason"]) for e in seen] == [("notice", "max_tokens")]
    # The SDK kept the partial reply, so nothing needs repairing on the next turn.
    assert roles(agent.messages) == ["user", "assistant"]
    assert agent.messages[1]["content"] == [{"text": "Uzun bir cevap"}]
    assert await agent.ask("devam et") == "Devamı."
    assert roles(model.calls[1].messages) == ["user", "assistant", "user"]


# --- 5: context window overflow ---------------------------------------------------------------


async def test_context_overflow_has_its_own_notice(config: Config) -> None:
    def overflow(messages, system_prompt):
        raise ContextWindowOverflowException("prompt is too long")

    bus = EventBus()
    seen = record_events(bus)
    model = FakeModel([overflow] * 10 + ["Yeni başlangıç."])
    agent = build_agent(config=config, model=model, tools=[], events=bus)

    turn = await collect(agent, "çok uzun")

    assert turn == [Notice(text=t("notice.overflow")), TurnEnd(stop_reason="error")]
    assert [(e.kind, e.data["where"]) for e in seen] == [("error", "context")]
    assert roles(agent.messages) == ["user"]
    model.replies = ["Yeni başlangıç."]
    assert await agent.ask("peki") == "Yeni başlangıç."
    assert model.calls[-1].messages[-2]["content"] == repair_text(t("notice.overflow"))


# --- 6: throttling is visible ------------------------------------------------------------------


async def test_throttle_retry_is_reported(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    import strands.event_loop._retry as retry_module

    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(retry_module, "asyncio", types.SimpleNamespace(sleep=fake_sleep))

    def throttled(messages, system_prompt):
        raise ModelThrottledException("slow down")

    model = FakeModel([throttled, "Geldi."])
    agent = build_agent(config=config, model=model, tools=[])

    turn = await collect(agent, "merhaba")

    assert turn[0] == Throttled(delay_seconds=4.0)  # the SDK's default initial delay
    assert slept == [4]
    assert "".join(e.text for e in turn if isinstance(e, TextDelta)) == "Geldi."
    assert turn[-1] == TurnEnd(stop_reason="end_turn")
    assert roles(agent.messages) == ["user", "assistant"]


# --- 7: cancel -----------------------------------------------------------------------------------


async def test_cancel_ends_the_turn_with_a_notice(config: Config) -> None:
    bus = EventBus()
    seen = record_events(bus)
    model = FakeModel()
    agent = build_agent(config=config, model=model, tools=[], events=bus)

    def cancel_then_reply(messages, system_prompt):
        agent.cancel()  # the SDK notices at the next chunk and discards the partial reply
        return "asla gösterilmez"

    model.replies = [cancel_then_reply, "Buradayım."]

    turn = await collect(agent, "uzun iş")

    assert turn == [Notice(text=t("notice.cancelled")), TurnEnd(stop_reason="cancelled")]
    assert [(e.kind, e.data["reason"]) for e in seen] == [("notice", "cancelled")]
    # A cancel during model streaming: the SDK stores its own placeholder as the reply
    # (strands 1.57.1, event_loop.py), so the history already alternates and nothing is
    # repaired. A cancel around tool execution leaves a user message and is repaired.
    assert roles(agent.messages) == ["user", "assistant"]
    assert agent.messages[1]["content"] == [{"text": "Cancelled by user"}]

    assert await agent.ask("devam") == "Buradayım."
    assert roles(model.calls[1].messages) == ["user", "assistant", "user"]
    assert model.calls[1].messages[2]["content"] == [{"text": "devam"}]


# --- 10: total token budget ----------------------------------------------------------------------


async def test_total_token_limit_has_its_own_notice(config: Config) -> None:
    config = config.with_overrides(agent=AgentConfig(max_turns=12, max_total_tokens=1))
    bus = EventBus()
    seen = record_events(bus, "turn_limit")
    model = FakeModel([[ToolCall("clock_tool")], "asla", "Peki."])
    agent = build_agent(config=config, model=model, tools=[clock_tool], events=bus)

    turn = await collect(agent, "saat")

    # FakeModel reports 2 tokens per call: the budget trips at the top of the second cycle,
    # after the tool the first call asked for ran.
    assert len(model.calls) == 1
    assert [e for e in turn if isinstance(e, ToolFinished)][0].tool == "clock_tool"
    assert turn[-2:] == [
        Notice(text=t("notice.total_tokens")),
        TurnEnd(stop_reason="limit_total_tokens"),
    ]
    assert [e.data for e in seen] == [{"max_total_tokens": 1}]
    assert roles(agent.messages) == ["user", "assistant", "user"]

    model.replies = ["Peki."]
    assert await agent.ask("tamam") == "Peki."
    assert model.calls[-1].messages[-2]["content"] == repair_text(t("notice.total_tokens"))


# --- review round: dangling tool uses, stuck interrupts, idle cancel, budgets ------------------


async def test_crash_restored_session_ending_on_a_tool_use_is_repaired(config: Config) -> None:
    """The hub died after the assistant toolUse was stored and before the tool result (for
    example while a tier-2 approval was pending). The SDK inserts its own toolResult, then the
    repair pair, so roles keep alternating and the store mirrors the agent."""
    store = MemorySessionStore()
    first = build_agent(
        config=config,
        model=FakeModel(["Bir."]),
        tools=[clock_tool],
        session_store=store,
        session_id="s-2",
    )
    await first.ask("bir")
    first.close()
    user = {"role": "user", "content": [{"text": "saat"}]}
    tool_use = {
        "role": "assistant",
        "content": [{"toolUse": {"toolUseId": "t9", "name": "clock_tool", "input": {}}}],
    }
    store.create_message("s-2", AGENT_ID, SessionMessage.from_message(user, 2))
    store.create_message("s-2", AGENT_ID, SessionMessage.from_message(tool_use, 3))

    model = FakeModel(["Devam."])
    second = build_agent(
        config=config, model=model, tools=[clock_tool], session_store=store, session_id="s-2"
    )
    assert roles(second.messages) == ["user", "assistant", "user", "assistant"]

    assert await second.ask("devam") == "Devam."
    sent = model.calls[0].messages
    assert roles(sent) == ["user", "assistant", "user", "assistant", "user", "assistant", "user"]
    assert sent[4]["content"][0]["toolResult"]["toolUseId"] == "t9"
    assert sent[5]["content"] == repair_text(t("notice.previous_turn_unfinished"))
    assert sent[6]["content"] == [{"text": "devam"}]
    stored = store.list_messages("s-2", AGENT_ID)
    assert roles([m.message for m in stored]) == roles(second.messages)


async def test_repair_text_survives_a_window_trim(config: Config) -> None:
    """The sliding window trims inside the SDK's finally, before tau sees the stop reason: the
    history may not be longer afterwards, but its last message is still the new one."""
    config = config.with_overrides(agent=AgentConfig(max_turns=1, window_size=2))
    model = FakeModel(["bir", "iki", [ToolCall("clock_tool")], "Peki."])
    agent = build_agent(config=config, model=model, tools=[clock_tool])
    await agent.ask("1")
    await agent.ask("2")
    before = len(agent.messages)

    turn = await collect(agent, "3")

    assert turn[-1] == TurnEnd(stop_reason="limit_turns")
    assert len(agent.messages) <= before and roles(agent.messages) == ["assistant", "user"]
    await agent.ask("4")
    sent = model.calls[-1].messages
    assert sent[-2]["content"] == repair_text(turn_limit_text(1))
    assert sent[-1]["content"] == [{"text": "4"}]


async def test_busy_turn_keeps_the_pending_repair_and_writes_no_title(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SDK's guard raises before anything is appended: the notice of the failed turn must
    still be the repair text later, and the refused prompt must not become the title."""

    def broken(messages, system_prompt):
        raise RuntimeError("kopdu")

    store = MemorySessionStore()
    model = FakeModel([broken, "Son."])
    agent = build_agent(config=config, model=model, tools=[], session_store=store)
    first = await collect(agent, "a")
    assert first[-1] == TurnEnd(stop_reason="error")
    assert store.read_meta(agent.session_id)["title"] == "a"  # the prompt did enter the history
    store.write_meta(agent.session_id, title="")

    async def guarded(*args, **kwargs):  # what Agent.stream_async does while another runs
        raise ConcurrencyException("Agent is already processing a request.")
        yield  # pragma: no cover - makes this an async generator

    with monkeypatch.context() as patch:
        patch.setattr(agent.agent, "stream_async", guarded)
        busy = await collect(agent, "b")
    assert busy == [Notice(text=t("notice.busy")), TurnEnd(stop_reason="busy")]
    assert not store.read_meta(agent.session_id).get("title")  # "b" never ran
    assert roles(agent.messages) == ["user"]

    assert await agent.ask("c") == "Son."
    texts = [m["content"][0].get("text") for m in model.calls[-1].messages]
    assert texts == ["a", "(Model call failed: kopdu. Details are in the log.)", "c"]
    assert store.read_meta(agent.session_id)["title"] == "c"


class ReInterrupting(HookProvider):
    """Interrupts every tool call under a new name, so no answer ever satisfies it."""

    def __init__(self) -> None:
        self.n = 0

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before)

    def before(self, event: BeforeToolCallEvent) -> None:
        self.n += 1
        event.interrupt(f"x{self.n}", reason="test")


async def test_hopeless_interrupt_is_given_up_and_the_next_turn_is_plain(config: Config) -> None:
    config = config.with_overrides(agent=AgentConfig(max_turns=3))
    hook = ReInterrupting()
    bus = EventBus()
    seen = record_events(bus, "error")
    model = FakeModel([[ToolCall("clock_tool")], "Sonraki."])
    agent = build_agent(config=config, model=model, tools=[clock_tool], hooks=[hook], events=bus)

    turn = await collect(agent, "saat")

    assert turn[-1] == TurnEnd(stop_reason="interrupt")
    assert len([e for e in turn if isinstance(e, Notice)]) == 4  # 1 + max_turns refusals
    assert hook.n == 4 and len(model.calls) == 1
    assert not agent.agent._interrupt_state.activated
    assert [e.data["where"] for e in seen] == ["interrupt"] * 4
    assert roles(agent.messages) == ["user", "assistant"]  # the toolUse without its result

    # The next plain turn calls the model: the SDK supplies the missing tool result, tau the
    # repair notice, then the prompt.
    assert await agent.ask("tekrar") == "Sonraki."
    sent = model.calls[-1].messages
    assert roles(sent) == ["user", "assistant", "user", "assistant", "user"]
    assert sent[2]["content"][0]["toolResult"]["content"] == [{"text": "Tool was interrupted."}]
    assert sent[3]["content"] == repair_text(t("notice.interrupt_refused"))
    assert sent[4]["content"] == [{"text": "tekrar"}]
    assert not agent.agent._interrupt_state.activated


class ApprovalLike(HookProvider):
    """An approval-style plugin: interrupts on every tool call, cancels unless answered 'A'."""

    def __init__(self) -> None:
        self.answers: list[Any] = []

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before)

    def before(self, event: BeforeToolCallEvent) -> None:
        answer = event.interrupt("approve", reason=str(event.tool_use["name"]))
        self.answers.append(answer)
        if answer != "A":
            event.cancel_tool = "not approved"


async def test_interrupts_on_several_tool_calls_in_one_turn_are_all_refused(
    config: Config,
) -> None:
    hook = ApprovalLike()
    model = FakeModel([[ToolCall("clock_tool")]] * 4 + ["Bitti.", "Sonraki."])
    agent = build_agent(config=config, model=model, tools=[clock_tool], hooks=[hook])

    turn = await collect(agent, "saat")

    assert turn[-1] == TurnEnd(stop_reason="end_turn")
    assert "".join(e.text for e in turn if isinstance(e, TextDelta)) == "Bitti."
    assert hook.answers == [{"tau": "rejected"}] * 4
    finished = [e for e in turn if isinstance(e, ToolFinished)]
    assert [(e.status, e.summary) for e in finished] == [("rejected", "not approved")] * 4
    assert len(model.calls) == 5 and not agent.agent._interrupt_state.activated
    assert await agent.ask("tekrar") == "Sonraki."
    assert roles(model.calls[-1].messages)[-3:] == ["user", "assistant", "user"]


async def test_interrupt_continuations_share_the_turn_budget(config: Config) -> None:
    """Limits are per SDK invocation; answering an interrupt starts a new one. The turn's
    max_turns still bounds the model calls of the whole turn."""
    config = config.with_overrides(agent=AgentConfig(max_turns=2))
    hook = ApprovalLike()
    bus = EventBus()
    seen = record_events(bus, "turn_limit")
    model = FakeModel(default="")
    model.replies = [lambda m, s: [ToolCall("clock_tool")]] * 10 + ["Peki."]
    agent = build_agent(config=config, model=model, tools=[clock_tool], hooks=[hook], events=bus)

    turn = await collect(agent, "saat")

    assert turn[-2:] == [Notice(text=turn_limit_text(2)), TurnEnd(stop_reason="limit_turns")]
    assert len(model.calls) == 2 and hook.answers == [{"tau": "rejected"}]
    assert [e.data for e in seen] == [{"max_turns": 2}]
    assert not agent.agent._interrupt_state.activated
    model.replies = ["Peki."]
    assert await agent.ask("yeter") == "Peki."
    sent = model.calls[-1].messages
    assert roles(sent)[-4:] == ["assistant", "user", "assistant", "user"]
    assert sent[-2]["content"] == repair_text(turn_limit_text(2))


async def test_session_restored_in_interrupt_state_recovers(config: Config) -> None:
    """The crash window: the SDK persisted the interrupt stop, the process died before tau
    refused it. The rebuilt agent must not refuse every prompt with the SDK's TypeError."""
    store = MemorySessionStore()
    first = build_agent(
        config=config,
        model=FakeModel([[ToolCall("clock_tool")], "asla"]),
        tools=[clock_tool],
        hooks=[ReInterrupting()],
        session_store=store,
        session_id="s-int",
    )
    async for _ in first.agent.stream_async("saat"):  # the raw SDK stream, up to the stop
        pass
    assert first.agent._interrupt_state.activated
    first.close()

    bus = EventBus()
    seen = record_events(bus, "error")
    model = FakeModel(["Devam.", "Tekrar."])
    second = build_agent(
        config=config,
        model=model,
        tools=[clock_tool],
        session_store=store,
        session_id="s-int",
        events=bus,
    )
    assert second.agent._interrupt_state.activated  # restored as persisted

    turn = await collect(second, "devam")

    assert turn[0] == Notice(text=t("notice.interrupt_refused"))
    assert turn[-1] == TurnEnd(stop_reason="end_turn")
    assert [e.data for e in seen] == [{"message": "stale interrupt cleared", "where": "interrupt"}]
    assert not second.agent._interrupt_state.activated
    sent = model.calls[0].messages
    assert roles(sent) == ["user", "assistant", "user", "assistant", "user"]
    assert "toolResult" in sent[2]["content"][0]
    assert sent[3]["content"] == repair_text(t("notice.interrupt_refused"))
    assert await second.ask("tekrar") == "Tekrar."
    stored = store.list_messages("s-int", AGENT_ID)
    assert roles([m.message for m in stored]) == roles(second.messages)
    # The cleared state reached the store: a third rebuild starts plain.
    second.close()
    third = build_agent(
        config=config,
        model=FakeModel(),
        tools=[clock_tool],
        session_store=store,
        session_id="s-int",
    )
    assert not third.agent._interrupt_state.activated


async def test_cancel_while_idle_is_ignored(config: Config) -> None:
    model = FakeModel(["Bir.", "İki."])
    agent = build_agent(config=config, model=model, tools=[])

    agent.cancel()  # Esc pressed while nothing runs

    assert not agent.agent.cancel_signal.is_set()
    turn = await collect(agent, "selam")
    assert turn[-1] == TurnEnd(stop_reason="end_turn")
    assert "".join(e.text for e in turn if isinstance(e, TextDelta)) == "Bir."
    assert [m["content"][0]["text"] for m in agent.messages] == ["selam", "Bir."]
    agent.cancel()  # again after the turn ended
    assert await agent.ask("tekrar") == "İki."
