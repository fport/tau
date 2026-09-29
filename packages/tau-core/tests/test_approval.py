"""TierGate as a policy outside the Strands loop, approvers, timeouts and the terminal prompt."""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime

import pytest
from tau_core import ApprovalRequest, Approver, Decision, EventBus, Tier, ToolCatalog, tau_tool
from tau_core.approval import (
    AutoRejectApprover,
    TerminalApprover,
    TierGate,
    format_approval_prompt,
    refusal_text,
    unknown_tool_text,
)
from tau_core.testing import ScriptedApprover, UnansweredApprover, record_events


@tau_tool(tier=Tier.READ)
def look() -> str:
    """Etrafa bakar."""
    return "boş oda"


@tau_tool(tier=Tier.DIGITAL_WRITE)
def save(text: str) -> str:
    """Bir not kaydeder.

    Args:
        text: Not.
    """
    return "kaydedildi"


@tau_tool(tier=Tier.PHYSICAL, effect="Robot kolu verilen konuma götürür.")
def move_arm(target: dict) -> str:
    """Robot kolu hareket ettirir.

    Args:
        target: Hedef konum.
    """
    return "hareket etti"


@tau_tool(tier=Tier.PHYSICAL)
def feed_cat() -> str:
    """Kedinin mama kabını doldurur."""
    return "mama verildi"


def make_gate(approver: Approver | None = None, **kwargs) -> tuple[TierGate, list]:
    bus = EventBus()
    seen = record_events(bus)
    gate = TierGate(
        ToolCatalog([look, save, move_arm, feed_cat]),
        approver or AutoRejectApprover(),
        bus,
        session_id=kwargs.pop("session_id", "s1"),
        channel=kwargs.pop("channel", "terminal"),
        **kwargs,
    )
    return gate, seen


def request(**overrides) -> ApprovalRequest:
    values = {
        "request_id": "abc123",
        "tool": "move_arm",
        "tier": Tier.PHYSICAL,
        "arguments": {"target": {"x": 1, "y": 2}},
        "effect": "Robot kolu verilen konuma götürür.",
        "session_id": "s1",
        "channel": "terminal",
    }
    values.update(overrides)
    return ApprovalRequest(**values)


# --- approvers ---------------------------------------------------------------------------------


def test_approvers_implement_the_protocol() -> None:
    for approver in (
        TerminalApprover(input_func=lambda prompt: ""),
        AutoRejectApprover(),
        ScriptedApprover(),
        UnansweredApprover(),
    ):
        assert isinstance(approver, Approver)
    assert TerminalApprover.name == "terminal" and TerminalApprover.timeout_seconds is None
    assert AutoRejectApprover.name == "auto-reject"


async def test_auto_reject_always_rejects() -> None:
    approver = AutoRejectApprover()
    assert [await approver.decide(request()) for _ in range(3)] == [Decision.REJECTED] * 3


async def test_scripted_approver_rejects_when_exhausted() -> None:
    approver = ScriptedApprover([Decision.APPROVED])
    first, second = await approver.decide(request()), await approver.decide(request())
    assert (first, second) == (Decision.APPROVED, Decision.REJECTED)
    assert len(approver.requests) == 2


async def test_a_custom_channel_only_implements_decide() -> None:
    # What Telegram (017) or TauBar (025) will do: any object with name + async decide().
    class ButtonApprover:
        name = "buttons"

        def __init__(self) -> None:
            self.shown: list[ApprovalRequest] = []

        async def decide(self, request: ApprovalRequest) -> Decision:
            self.shown.append(request)
            return Decision.APPROVED

    approver = ButtonApprover()
    gate, seen = make_gate(approver, channel="telegram")
    assert await gate.check("feed_cat", {}, tool_use_id="t1") == (True, None, "approved")
    assert approver.shown[0].channel == "telegram"
    assert seen[0].data["channel"] == "buttons"


# --- the terminal prompt -----------------------------------------------------------------------


def test_prompt_shows_tool_arguments_and_effect() -> None:
    assert format_approval_prompt(request()) == (
        "⚠️  Approval needed (tier 2)\n"
        "  Tool: move_arm\n"
        '  Arguments: {"target": {"x": 1, "y": 2}}\n'
        "  Effect: Robot kolu verilen konuma götürür.\n"
        "  Approve? [y/N] "
    )


def test_prompt_in_turkish() -> None:
    assert format_approval_prompt(request(), "tr") == (
        "⚠️  Onay gerekiyor (tier 2)\n"
        "  Araç: move_arm\n"
        '  Argümanlar: {"target": {"x": 1, "y": 2}}\n'
        "  Etki: Robot kolu verilen konuma götürür.\n"
        "  Onaylıyor musunuz? [e/H] "
    )
    assert format_approval_prompt(request(), "xx") == format_approval_prompt(request(), "en")


def test_prompt_escapes_terminal_control_characters() -> None:
    sneaky = {"note": "zararsız‮\x1b[2K\x9b31m", "şehir": "İzmir"}
    prompt = format_approval_prompt(request(arguments=sneaky, effect="Satır 1\nSatır 2"))
    assert "\x1b" not in prompt and "\x9b" not in prompt and "‮" not in prompt
    assert "\\u202e" in prompt and "\\x9b" in prompt and "\\u001b" in prompt
    assert '"şehir": "İzmir"' in prompt  # Turkish text stays readable
    assert "  Effect: Satır 1 Satır 2\n" in prompt
    assert prompt.count("\n") == 4


def test_prompt_survives_non_json_arguments() -> None:
    prompt = format_approval_prompt(request(arguments={"at": datetime(2026, 9, 29, 15, 30)}))
    assert '"at": "2026-09-29 15:30:00"' in prompt


@pytest.mark.parametrize(
    "answer", ["e", "E", "evet", "EVET", " Evet ", "e\n", "y", "Y", "yes", "YES", " Yes "]
)
async def test_terminal_approves_yes_in_both_languages(answer: str) -> None:
    prompts: list[str] = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return answer

    approver = TerminalApprover(input_func=fake_input)
    assert await approver.decide(request()) is Decision.APPROVED
    assert prompts == [format_approval_prompt(request())]


@pytest.mark.parametrize(
    "answer", ["", "h", "H", "hayır", "n", "no", "ok", "evet!", "e e", "onayla", "approve", "1"]
)
async def test_terminal_rejects_everything_else(answer: str) -> None:
    approver = TerminalApprover(input_func=lambda prompt: answer)
    assert await approver.decide(request()) is Decision.REJECTED


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
async def test_terminal_rejects_on_eof_and_interrupt(error: type[BaseException]) -> None:
    def fake_input(prompt: str) -> str:
        raise error

    approver = TerminalApprover(input_func=fake_input)
    assert await approver.decide(request()) is Decision.REJECTED
    assert approver.pending is False


async def test_terminal_asks_in_a_worker_thread_and_flags_pending() -> None:
    seen: dict[str, object] = {}

    def fake_input(prompt: str) -> str:
        seen["thread"] = threading.get_ident()
        seen["pending"] = approver.pending
        return "evet"

    approver = TerminalApprover(input_func=fake_input)
    assert await approver.decide(request()) is Decision.APPROVED
    assert seen["thread"] != threading.get_ident()  # the event loop is never blocked
    assert seen["pending"] is True and approver.pending is False


async def test_terminal_prompt_through_the_gate() -> None:
    prompts: list[str] = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return "h"

    gate, seen = make_gate(TerminalApprover(input_func=fake_input))
    result = await gate.check("move_arm", {"target": {"x": 3}}, tool_use_id="t1")
    assert result == (False, refusal_text("move_arm"), "rejected")
    assert prompts == [
        "⚠️  Approval needed (tier 2)\n"
        "  Tool: move_arm\n"
        '  Arguments: {"target": {"x": 3}}\n'
        "  Effect: Robot kolu verilen konuma götürür.\n"
        "  Approve? [y/N] "
    ]
    assert seen[0].data["channel"] == "terminal" and seen[0].data["decision"] == "rejected"


# --- the gate ----------------------------------------------------------------------------------


@pytest.mark.parametrize("tool", ["look", "save"])
async def test_tier0_and_tier1_need_no_approval(tool: str) -> None:
    consulted: list[str] = []
    approver = ScriptedApprover()
    gate, seen = make_gate(approver, exemptions=[lambda name, args: consulted.append(name)])
    assert await gate.check(tool, {"text": "x"}, tool_use_id="t1") == (True, None, None)
    assert approver.requests == [] and seen == [] and consulted == []


async def test_tier2_approved_request_and_event() -> None:
    approver = ScriptedApprover([Decision.APPROVED])
    gate, seen = make_gate(approver, session_id="s9", channel="tui")
    arguments = {"target": {"x": 1, "y": 2}}

    assert await gate.check("move_arm", arguments, tool_use_id="t7") == (True, None, "approved")

    [sent] = approver.requests
    assert len(sent.request_id) == 12 and int(sent.request_id, 16) >= 0
    assert (sent.tool, sent.tier, sent.arguments) == ("move_arm", Tier.PHYSICAL, arguments)
    assert (sent.effect, sent.session_id, sent.channel) == (
        "Robot kolu verilen konuma götürür.",
        "s9",
        "tui",
    )
    [event] = seen
    assert event.kind == "approval" and event.session_id == "s9"
    assert event.data == {
        "tool": "move_arm",
        "tier": 2,
        "arguments": arguments,
        "effect": "Robot kolu verilen konuma götürür.",
        "decision": "approved",
        "channel": "scripted",
        "request_id": sent.request_id,
    }


async def test_effect_falls_back_to_the_description() -> None:
    approver = ScriptedApprover()
    gate, _ = make_gate(approver)
    await gate.check("feed_cat", {}, tool_use_id="t1")
    assert approver.requests[0].effect == "Kedinin mama kabını doldurur."


@pytest.mark.parametrize("decision", [Decision.REJECTED, Decision.TIMEOUT])
async def test_tier2_not_approved(decision: Decision) -> None:
    gate, seen = make_gate(ScriptedApprover([decision]))
    result = await gate.check("feed_cat", {}, tool_use_id="t1")
    assert result == (False, refusal_text("feed_cat"), decision.value)
    assert seen[0].data["decision"] == decision.value


async def test_default_approver_rejects() -> None:
    gate, seen = make_gate()
    assert await gate.check("feed_cat", {}, tool_use_id="t1") == (
        False,
        refusal_text("feed_cat"),
        "rejected",
    )
    assert seen[0].data["channel"] == "auto-reject"


async def test_unknown_tool_fails_closed() -> None:
    approver = ScriptedApprover([Decision.APPROVED])
    gate, seen = make_gate(approver, exemptions=[lambda name, args: True])
    result = await gate.check("self_destruct", {}, tool_use_id="t1")
    assert result == (False, unknown_tool_text("self_destruct"), None)
    assert result[1] == "Tool 'self_destruct' is not registered; it was not run."
    assert approver.requests == []
    assert [(e.kind, e.data["where"], e.data["tool"]) for e in seen] == [
        ("error", "tier_gate", "self_destruct")
    ]


async def test_catalog_is_read_live() -> None:
    gate, _ = make_gate()
    gate.catalog.remove("look")
    assert (await gate.check("look", {}, tool_use_id="t1"))[0] is False

    @tau_tool(tier=Tier.READ)
    def fresh() -> str:
        """Yeni."""
        return "yeni"

    gate.catalog.add(fresh)
    assert await gate.check("fresh", {}, tool_use_id="t2") == (True, None, None)


async def test_tool_that_lost_its_tier_fails_closed() -> None:
    @tau_tool(tier=Tier.READ)
    def shifty() -> str:
        """Değişken."""
        return "x"

    gate, _ = make_gate()
    gate.catalog.add(shifty)
    shifty.tau_tier = None
    allowed, text, _ = await gate.check("shifty", {}, tool_use_id="t1")
    assert allowed is False and text == unknown_tool_text("shifty")


# --- failing approvers -------------------------------------------------------------------------


class RaisingApprover:
    name = "raising"

    async def decide(self, request: ApprovalRequest) -> Decision:
        raise ConnectionError("telegram unreachable")


class AnsweringApprover:
    name = "answering"

    def __init__(self, answer: object) -> None:
        self.answer = answer

    async def decide(self, request: ApprovalRequest) -> Decision:
        return self.answer  # type: ignore[return-value]


class SyncApprover:
    name = "sync"

    def decide(self, request: ApprovalRequest) -> Decision:  # not async: a programming error
        return Decision.APPROVED


async def test_raising_approver_rejects(caplog: pytest.LogCaptureFixture) -> None:
    gate, seen = make_gate(RaisingApprover())
    with caplog.at_level(logging.ERROR, logger="tau_core.approval"):
        result = await gate.check("feed_cat", {}, tool_use_id="t1")
    assert result == (False, refusal_text("feed_cat"), "rejected")
    assert "approver raising failed" in caplog.text
    assert seen[0].data["decision"] == "rejected"


@pytest.mark.parametrize("answer", [True, 1, "yes", None, "APPROVED"])
async def test_invalid_answer_rejects(answer: object) -> None:
    gate, _ = make_gate(AnsweringApprover(answer))
    assert await gate.check("feed_cat", {}, tool_use_id="t1") == (
        False,
        refusal_text("feed_cat"),
        "rejected",
    )


async def test_plain_string_decision_value_is_accepted() -> None:
    gate, _ = make_gate(AnsweringApprover("approved"))
    assert await gate.check("feed_cat", {}, tool_use_id="t1") == (True, None, "approved")


@pytest.mark.parametrize("timeout", [None, 1.0])
async def test_non_async_approver_rejects(timeout: float | None) -> None:
    gate, _ = make_gate(SyncApprover(), timeout_seconds=timeout)
    assert (await gate.check("feed_cat", {}, tool_use_id="t1"))[2] == "rejected"


# --- timeouts ----------------------------------------------------------------------------------


async def test_gate_timeout_records_timeout(caplog: pytest.LogCaptureFixture) -> None:
    approver = UnansweredApprover()
    gate, seen = make_gate(approver, timeout_seconds=0.01)
    with caplog.at_level(logging.WARNING, logger="tau_core.approval"):
        result = await gate.check("move_arm", {"target": {}}, tool_use_id="t1")
    assert result == (False, refusal_text("move_arm"), "timeout")
    assert approver.cancelled == 1  # the pending question was withdrawn
    assert seen[0].data["decision"] == "timeout"
    assert "timed out" in caplog.text


async def test_approver_timeout_attribute_applies() -> None:
    approver = UnansweredApprover(timeout_seconds=0.01)
    gate, _ = make_gate(approver)
    assert gate.effective_timeout() == 0.01
    assert (await gate.check("feed_cat", {}, tool_use_id="t1"))[2] == "timeout"


async def test_gate_timeout_overrides_approver_timeout() -> None:
    gate, _ = make_gate(UnansweredApprover(timeout_seconds=60), timeout_seconds=0.01)
    assert gate.effective_timeout() == 0.01
    assert (await asyncio.wait_for(gate.check("feed_cat", {}, tool_use_id="t1"), 5))[2] == (
        "timeout"
    )


async def test_no_timeout_waits_for_the_answer() -> None:
    class SlowApprover:
        name = "slow"

        async def decide(self, request: ApprovalRequest) -> Decision:
            await asyncio.sleep(0.05)
            return Decision.APPROVED

    gate, _ = make_gate(SlowApprover())
    assert gate.effective_timeout() is None
    assert await gate.check("feed_cat", {}, tool_use_id="t1") == (True, None, "approved")


async def test_answer_within_timeout_counts() -> None:
    gate, _ = make_gate(ScriptedApprover([Decision.APPROVED]), timeout_seconds=5)
    assert await gate.check("feed_cat", {}, tool_use_id="t1") == (True, None, "approved")


@pytest.mark.parametrize("bad", [0, -1, True, "10"])
def test_invalid_gate_timeout_is_refused(bad: object) -> None:
    with pytest.raises(ValueError):
        make_gate(timeout_seconds=bad)


def test_invalid_approver_timeout_is_ignored() -> None:
    gate, _ = make_gate(UnansweredApprover(timeout_seconds=-5))
    assert gate.effective_timeout() is None


# --- exemptions --------------------------------------------------------------------------------


async def test_exemption_skips_the_prompt() -> None:
    approver = ScriptedApprover()
    gate, seen = make_gate(approver, exemptions=[lambda name, args: name == "feed_cat"])
    assert await gate.check("feed_cat", {}, tool_use_id="t1") == (True, None, "exempt")
    assert approver.requests == [] and seen == []


async def test_exemption_must_return_true() -> None:
    approver = ScriptedApprover()
    gate, _ = make_gate(approver, exemptions=[lambda name, args: "evet"])
    assert (await gate.check("feed_cat", {}, tool_use_id="t1"))[2] == "rejected"
    assert len(approver.requests) == 1


async def test_failing_exemption_is_not_an_exemption(caplog: pytest.LogCaptureFixture) -> None:
    def broken(name: str, args: dict) -> bool:
        raise KeyError("routine")

    approver = ScriptedApprover()
    gate, _ = make_gate(approver, exemptions=[broken, lambda name, args: False])
    with caplog.at_level(logging.ERROR, logger="tau_core.approval"):
        assert (await gate.check("feed_cat", {}, tool_use_id="t1"))[2] == "rejected"
    assert len(approver.requests) == 1
    assert "treating as not exempt" in caplog.text


async def test_any_matching_exemption_is_enough() -> None:
    gate, _ = make_gate(exemptions=[lambda n, a: False, lambda n, a: a == {"target": {"x": 0}}])
    assert (await gate.check("move_arm", {"target": {"x": 0}}, tool_use_id="t1"))[2] == "exempt"
    assert (await gate.check("move_arm", {"target": {"x": 1}}, tool_use_id="t2"))[2] == "rejected"


async def test_add_exemption_at_runtime_and_remove_it() -> None:
    gate, _ = make_gate()
    remove = gate.add_exemption(lambda name, args: name == "feed_cat")
    assert (await gate.check("feed_cat", {}, tool_use_id="t1"))[2] == "exempt"
    remove()
    remove()  # idempotent
    assert (await gate.check("feed_cat", {}, tool_use_id="t2"))[2] == "rejected"


async def test_nobody_who_only_looks_can_change_the_arguments() -> None:
    class MeddlingApprover:
        name = "meddling"

        async def decide(self, request: ApprovalRequest) -> Decision:
            request.arguments["target"]["x"] = 999
            return Decision.REJECTED

    def meddling_exemption(name: str, args: dict) -> bool:
        args["target"]["y"] = -1
        return False

    arguments = {"target": {"x": 1, "y": 2}}
    gate, seen = make_gate(MeddlingApprover(), exemptions=[meddling_exemption])
    await gate.check("move_arm", arguments, tool_use_id="t1")
    assert arguments == {"target": {"x": 1, "y": 2}}
    assert seen[0].data["arguments"] == {"target": {"x": 1, "y": 2}}


# --- one prompt at a time ----------------------------------------------------------------------


async def test_parallel_calls_are_asked_one_at_a_time() -> None:
    class CountingApprover:
        name = "counting"

        def __init__(self) -> None:
            self.open = 0
            self.most = 0
            self.order: list[str] = []

        async def decide(self, request: ApprovalRequest) -> Decision:
            self.open += 1
            self.most = max(self.most, self.open)
            self.order.append(request.tool)
            await asyncio.sleep(0.01)
            self.open -= 1
            return Decision.APPROVED

    approver = CountingApprover()
    gate, _ = make_gate(approver)
    results = await asyncio.gather(
        gate.check("feed_cat", {}, tool_use_id="t1"),
        gate.check("move_arm", {"target": {}}, tool_use_id="t2"),
        gate.check("feed_cat", {}, tool_use_id="t3"),
    )
    assert [r[2] for r in results] == ["approved"] * 3
    assert approver.most == 1 and len(approver.order) == 3


def test_gate_works_across_event_loops() -> None:
    # Contention binds an asyncio.Lock to its loop; a gate reused in a new loop must not break.
    class SleepyApprover:
        name = "sleepy"

        async def decide(self, request: ApprovalRequest) -> Decision:
            await asyncio.sleep(0.001)
            return Decision.APPROVED

    gate, _ = make_gate(SleepyApprover())

    async def two_at_once() -> list[str | None]:
        results = await asyncio.gather(
            gate.check("feed_cat", {}, tool_use_id="a"), gate.check("feed_cat", {}, tool_use_id="b")
        )
        return [r[2] for r in results]

    assert asyncio.run(two_at_once()) == ["approved", "approved"]
    assert asyncio.run(two_at_once()) == ["approved", "approved"]


# --- record ------------------------------------------------------------------------------------


def record_call(gate: TierGate, tool: str, **overrides) -> None:
    values = {
        "tool_name": tool,
        "arguments": {"text": "süt"},
        "status": "ok",
        "summary": "tamam",
        "approval": None,
        "duration_ms": 3,
        "tool_use_id": "t1",
    }
    values.update(overrides)
    gate.record(**values)


def test_record_emits_tool_call_for_every_tier() -> None:
    gate, seen = make_gate()
    record_call(gate, "look")
    record_call(gate, "save")
    record_call(gate, "move_arm", approval="approved")
    record_call(gate, "ghost", status="rejected", duration_ms=None)
    assert [e.kind for e in seen] == ["tool_call"] * 4
    assert [e.data["tier"] for e in seen] == [0, 1, 2, None]
    assert seen[2].data == {
        "tool": "move_arm",
        "tier": 2,
        "arguments": {"text": "süt"},
        "status": "ok",
        "result_summary": "tamam",
        "approval": "approved",
        "duration_ms": 3,
        "tool_use_id": "t1",
    }
    assert all(e.session_id == "s1" for e in seen)


def test_record_truncates_the_summary() -> None:
    gate, seen = make_gate()
    record_call(gate, "save", summary="x" * 500)
    assert seen[0].data["result_summary"] == "x" * 200


@pytest.mark.parametrize(
    ("tool", "level"),
    [
        ("look", logging.DEBUG),
        ("save", logging.INFO),
        ("move_arm", logging.INFO),
        ("ghost", logging.WARNING),
    ],
)
def test_record_log_levels(tool: str, level: int, caplog: pytest.LogCaptureFixture) -> None:
    gate, _ = make_gate()
    with caplog.at_level(logging.DEBUG, logger="tau_core.approval"):
        record_call(gate, tool, approval="rejected", summary="onaylanmadı")
    [record] = caplog.records
    assert record.levelno == level
    message = record.getMessage()
    assert message.startswith(f"tool_call {tool} ")
    assert 'args={"text": "süt"}' in message
    assert "summary=onaylanmadı" in message and "approval=rejected" in message
