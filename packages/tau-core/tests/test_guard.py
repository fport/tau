"""The owner guard seam (issue 110, ADR 0008): admission, the tier gate, resolution, messages.

Everything runs offline with ``FakeGuard``; no camera, Keychain or Touch ID is ever touched.
``HubGuard`` against a fake hub is in ``test_hub_guard.py``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import tau_core
from tau_core import (
    ADMISSION_REASONS,
    LOCK_TRIGGERS,
    PROGRESS_STEPS,
    VERDICT_REASONS,
    Admission,
    Config,
    ConfigError,
    Decision,
    EventBus,
    Guard,
    GuardLocked,
    GuardProgress,
    GuardStatus,
    GuardTurn,
    GuardVerdict,
    HubGuard,
    LockedGuard,
    MemorySessionStore,
    Notice,
    Tier,
    TierGate,
    ToolCatalog,
    ToolFinished,
    TurnEnd,
    build_agent,
    resolve_guard,
    summarize,
    tau_tool,
)
from tau_core.agent import AGENT_ID, TauAgent
from tau_core.approval import ApprovalRequest, refusal_text
from tau_core.builder import Check, run_doctor
from tau_core.compaction import CompactionError
from tau_core.config import ComponentsConfig
from tau_core.guard import (
    ENROLLED_MARKER,
    GUARD_MESSAGES,
    GUARD_STATES,
    LOCKED_NOTE,
    STEP_UP_NOTE,
    admit_turn,
    guard_doctor_check,
    guard_status_line,
    process_client_id,
    reset_guards,
)
from tau_core.i18n import LANGUAGES, MESSAGES, t
from tau_core.status import status_lines, status_report
from tau_core.testing import (
    FakeGuard,
    FakeModel,
    ScriptedApprover,
    ToolCall,
    record_events,
    test_config,
)

RAN: list[str] = []


@tau_tool(tier=Tier.READ)
def clock() -> str:
    """Tells the time."""
    RAN.append("clock")
    return "15:30"


@tau_tool(tier=Tier.DIGITAL_WRITE, effect="Writes a note.")
def note(text: str) -> str:
    """Writes a note.

    Args:
        text: The note.
    """
    RAN.append("note")
    return "noted"


@tau_tool(tier=Tier.PHYSICAL, effect="Switches the desk lamp.")
def lamp(state: str) -> str:
    """Switches the desk lamp.

    Args:
        state: "on" or "off".
    """
    RAN.append("lamp")
    return f"lamp {state}"


@pytest.fixture(autouse=True)
def fresh_guards() -> Iterator[None]:
    reset_guards()
    RAN.clear()
    yield
    reset_guards()


def write_marker(config: Config, enrollment: str = "E1") -> None:
    path = config.data_dir / ENROLLED_MARKER
    path.parent.mkdir(parents=True, exist_ok=True)
    marker = {"v": 1, "enrollment": enrollment, "model": "0" * 64, "created": "2026-09-30"}
    path.write_text(json.dumps(marker), encoding="utf-8")


async def collect(agent: TauAgent, prompt: str) -> list:
    return [event async for event in agent.stream(prompt)]


# -- public API ------------------------------------------------------------------------------


def test_public_exports() -> None:
    for name in (
        "Guard",
        "GuardStatus",
        "GuardVerdict",
        "GuardProgress",
        "GuardTurn",
        "Admission",
        "GuardLocked",
        "LockedGuard",
        "HubGuard",
        "resolve_guard",
        "VERDICT_REASONS",
        "ADMISSION_REASONS",
        "LOCK_TRIGGERS",
        "PROGRESS_STEPS",
        "ALLOWED_WHILE_LOCKED",
    ):
        assert name in tau_core.__all__ and hasattr(tau_core, name), name
    import tau_core.hub as hub

    for name in ("HubClient", "HubUnavailable", "HubError"):
        assert name in hub.__all__ and hasattr(hub, name), name
    assert tau_core.ALLOWED_WHILE_LOCKED == frozenset({"help", "lang", "quit", "guard"})
    assert ADMISSION_REASONS[0] == "ok" and "error" in ADMISSION_REASONS
    assert "match" in VERDICT_REASONS and "startup" in LOCK_TRIGGERS and "done" in PROGRESS_STEPS


def test_every_guard_implementation_is_a_guard(tmp_path: Path) -> None:
    assert isinstance(FakeGuard(), Guard)
    assert isinstance(LockedGuard("error"), Guard)
    assert isinstance(HubGuard(test_config(tmp_path)), Guard)


# -- messages --------------------------------------------------------------------------------


def test_every_reason_step_trigger_and_state_has_both_languages() -> None:
    keys = (
        [f"guard.refused.{r}" for r in ADMISSION_REASONS]
        + [f"guard.verdict.{r}" for r in VERDICT_REASONS]
        + [f"guard.progress.{s}" for s in PROGRESS_STEPS]
        + [f"guard.lock_trigger.{x}" for x in LOCK_TRIGGERS]
        + [f"guard.state.{s}" for s in GUARD_STATES]
        + ["guard.step_up.start", "guard.step_up.passed", "guard.step_up.failed"]
        + ["guard.locked_during_turn", "guard.unlocked", "guard.start_hub"]
        + ["guard.not_enrolled_hint", "status.guard"]
    )
    for key in keys:
        assert key in GUARD_MESSAGES, key
        assert set(MESSAGES[key]) == set(LANGUAGES), key
        assert all(MESSAGES[key][language].strip() for language in LANGUAGES), key
    assert any(key.startswith("doctor.guard.") for key in GUARD_MESSAGES)
    assert t("guard.unlocked", "tr", method="face", failures=2).endswith("2.")


def test_guard_messages_are_registered_not_redefined() -> None:
    for key, templates in GUARD_MESSAGES.items():
        assert MESSAGES[key] == templates, key
    i18n_source = Path(tau_core.i18n.__file__).read_text(encoding="utf-8")
    assert '"guard.' not in i18n_source and '"status.guard"' not in i18n_source


# -- admit_turn: the one place an admission answer is read -----------------------------------

TURN = GuardTurn(channel="tui", session_id="s1", client_id="c1")


class OddGuard(FakeGuard):
    def __init__(self, answer: Any = None, *, raises: BaseException | None = None) -> None:
        super().__init__("unlocked")
        self.answer = answer
        self.raises = raises

    async def admit(self, turn: GuardTurn) -> Any:
        if self.raises is not None:
            raise self.raises
        return self.answer


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (Admission(True), Admission(True, "ok")),
        (Admission(True, "locked"), Admission(True, "ok")),
        (Admission(False, "recheck"), Admission(False, "recheck")),
        (Admission(False, "no_such_reason"), Admission(False, "error")),
        (Admission(False), Admission(False, "error")),  # "ok" with allowed=False
        (Admission("yes", "ok"), Admission(False, "error")),  # type: ignore[arg-type]
        (True, Admission(False, "error")),
        (None, Admission(False, "error")),
    ],
)
def test_admit_turn_reads_only_a_real_admission(answer: Any, expected: Admission) -> None:
    assert asyncio.run(admit_turn(OddGuard(answer), TURN)) == expected


def test_admit_turn_fails_closed_on_errors_and_timeouts() -> None:
    assert asyncio.run(admit_turn(OddGuard(raises=RuntimeError("boom")), TURN)) == Admission(
        False, "error"
    )

    class Silent(FakeGuard):
        async def admit(self, turn: GuardTurn) -> Admission:
            await asyncio.sleep(10)
            return Admission(True)

    result = asyncio.run(admit_turn(Silent(), TURN, timeout=0.05))
    assert result == Admission(False, "unavailable")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(admit_turn(OddGuard(raises=asyncio.CancelledError()), TURN))


def test_admit_turn_drops_a_late_answer_from_a_guard_that_swallows_cancellation() -> None:
    class Swallows(FakeGuard):
        def __init__(self, keep_going: bool) -> None:
            super().__init__("locked")
            self.keep_going = keep_going

        async def admit(self, turn: GuardTurn) -> Admission:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                if self.keep_going:
                    await asyncio.sleep(0.3)  # and ignores the cancellation for a while
            return Admission(True)  # a stale "allowed"

    async def main(guard: FakeGuard) -> tuple[Admission, float]:
        loop = asyncio.get_running_loop()
        started = loop.time()
        result = await admit_turn(guard, TURN, timeout=0.05)
        return result, loop.time() - started

    for keep_going in (False, True):
        result, took = asyncio.run(main(Swallows(keep_going)))
        assert result == Admission(False, "unavailable")
        assert took < 0.25


def test_admit_turn_refuses_a_guard_whose_admit_is_not_async() -> None:
    class Sync(FakeGuard):
        def admit(self, turn: GuardTurn) -> Admission:  # type: ignore[override]
            return Admission(True)

    assert asyncio.run(admit_turn(Sync(), TURN)) == Admission(False, "error")


# -- admission in TauAgent.stream -------------------------------------------------------------


def make_agent(config: Config, guard: Any, model: FakeModel, **kwargs: Any) -> TauAgent:
    kwargs.setdefault("tools", [clock, note, lamp])
    return build_agent(config=config, model=model, guard=guard, channel="tui", **kwargs)


def test_a_refused_turn_changes_nothing_and_the_next_needs_no_repair(config: Config) -> None:
    store = MemorySessionStore()
    guard = FakeGuard("locked")
    model = FakeModel(["Hello."])
    agent = make_agent(config, guard, model, session_store=store)
    guard_events = record_events(agent.events, "guard")
    events = asyncio.run(collect(agent, "who is there?"))
    assert events == [Notice(text=t("guard.refused.locked", "en")), TurnEnd(stop_reason="locked")]
    assert model.calls == []
    assert agent.messages == []
    assert store.list_messages(agent.session_id, AGENT_ID) == []
    assert not store.read_meta(agent.session_id).get("title")
    assert [e.data for e in guard_events] == [
        {"action": "refused", "channel": "tui", "reason": "locked"}
    ]
    assert guard.calls == [("admit", GuardTurn("tui", agent.session_id, agent.client_id))]

    guard.set_state("unlocked")
    events = asyncio.run(collect(agent, "hi"))
    assert events[-1] == TurnEnd(stop_reason="end_turn")
    assert len(model.calls) == 1
    assert [m["role"] for m in agent.messages] == ["user", "assistant"]
    assert agent.messages[0]["content"] == [{"text": "hi"}]  # no repair message was sent
    assert len(store.list_messages(agent.session_id, AGENT_ID)) == 2


@pytest.mark.parametrize(
    ("guard", "reason"),
    [
        (FakeGuard(admissions=[Admission(False, "weird")]), "error"),
        (FakeGuard(admissions=["recheck"]), "recheck"),
        (OddGuard(raises=RuntimeError("hub down")), "error"),
        (LockedGuard("unsupported_platform"), "unsupported_platform"),
    ],
)
def test_refusal_reasons_are_shown_and_unknown_ones_as_error(
    config: Config, guard: Any, reason: str
) -> None:
    agent = make_agent(config, guard, FakeModel())
    events = asyncio.run(collect(agent, "hi"))
    assert events == [Notice(text=t(f"guard.refused.{reason}", "en")), TurnEnd("locked")]


def test_the_refusal_notice_follows_the_ui_language(config: Config) -> None:
    from tau_core.config import UiConfig

    agent = make_agent(config.with_overrides(ui=UiConfig(language="tr")), FakeGuard(), FakeModel())
    events = asyncio.run(collect(agent, "merhaba"))
    assert events[0] == Notice(text=t("guard.refused.locked", "tr"))


def test_ask_raises_guard_locked(config: Config) -> None:
    agent = make_agent(config, FakeGuard(admissions=["cooldown"]), FakeModel(["Hi."]))
    with pytest.raises(GuardLocked) as caught:
        asyncio.run(agent.ask("hi"))
    assert caught.value.reason == "cooldown"
    agent.guard.set_state("unlocked")  # type: ignore[union-attr]
    assert asyncio.run(agent.ask("hi")) == "Hi."


def test_summarize_asks_the_guard_before_any_model_call(config: Config) -> None:
    guard = FakeGuard("unlocked")
    model = FakeModel(["Hi.", "The summary."])
    agent = make_agent(config, guard, model)
    asyncio.run(collect(agent, "hello"))
    guard.set_state("locked")
    calls = len(model.calls)
    with pytest.raises(GuardLocked) as caught:
        asyncio.run(summarize(agent))
    assert isinstance(caught.value, CompactionError)  # channels report it like any failure
    assert caught.value.reason == "locked"
    assert len(model.calls) == calls
    guard.set_state("unlocked")
    assert asyncio.run(summarize(agent)) == "The summary."


def test_build_agent_discovers_or_takes_the_guard(config: Config) -> None:
    agent = build_agent(config=config, model=FakeModel(), tools=[])
    assert agent.guard is None and agent.gate.guard is None  # nothing is active
    assert agent.client_id == process_client_id() == agent.gate.client_id
    guard = FakeGuard()
    agent = build_agent(config=config, model=FakeModel(), tools=[], guard=guard, client_id="c9")
    assert agent.guard is guard and agent.gate.guard is guard
    assert agent.client_id == "c9" == agent.gate.client_id
    assert agent.channel == "terminal"
    with pytest.raises(ConfigError, match="tau_core.Guard"):
        build_agent(config=config, model=FakeModel(), tools=[], guard=object())


def test_discover_finds_an_active_guard(config: Config) -> None:
    write_marker(config)
    agent = build_agent(config=config, model=FakeModel(), tools=[])
    assert agent.guard is resolve_guard(config)
    assert agent.guard is not None  # a HubGuard on macOS, a LockedGuard elsewhere


def test_a_locked_guard_refuses_a_tier_1_call_inside_an_admitted_turn(config: Config) -> None:
    guard = FakeGuard("locked", admissions=[True])  # the turn gets in, then the guard locks
    model = FakeModel([[ToolCall("note", {"text": "x"})], "I could not."])
    agent = make_agent(config, guard, model)
    events = asyncio.run(collect(agent, "write a note"))
    [finished] = [e for e in events if isinstance(e, ToolFinished)]
    assert finished.approval == "locked" and finished.status == "rejected"
    assert finished.summary.endswith(LOCKED_NOTE)
    assert RAN == []
    assert events[-1] == TurnEnd("end_turn")


# -- the tier gate ---------------------------------------------------------------------------


def make_gate(
    approver: ScriptedApprover, guard: Any, *, bus: EventBus | None = None, **kwargs: Any
) -> TierGate:
    catalog = ToolCatalog()
    catalog.extend([clock, note, lamp])
    return TierGate(
        catalog,
        approver,
        bus or EventBus(),
        session_id="s1",
        channel="tui",
        guard=guard,
        client_id="c1",
        **kwargs,
    )


def check(gate: TierGate, tool: str = "lamp") -> tuple[bool, str | None, str | None]:
    arguments = {"state": "on"} if tool == "lamp" else ({"text": "x"} if tool == "note" else {})
    return asyncio.run(gate.check(tool, arguments, tool_use_id="t1"))


STEP_RESULTS: list[Any] = [
    True,
    False,
    1,
    "yes",
    RuntimeError("camera exploded"),
    asyncio.CancelledError(),
]


@pytest.mark.parametrize("admitted", [True, False], ids=["admitted", "locked"])
@pytest.mark.parametrize("step_result", STEP_RESULTS, ids=repr)
@pytest.mark.parametrize("decision", list(Decision), ids=str)
def test_the_guard_never_produces_an_approval(
    decision: Decision, step_result: Any, admitted: bool
) -> None:
    guard = FakeGuard("unlocked" if admitted else "locked", step_ups=[step_result])
    approver = ScriptedApprover([decision])
    gate = make_gate(approver, guard)
    stepped = admitted and decision is Decision.APPROVED
    if stepped and isinstance(step_result, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            check(gate)
    else:
        allowed, text, approval = check(gate)
        expected = stepped and step_result is True
        assert allowed is expected
        assert (text is None) is expected
        if not admitted:
            assert approval == "locked" and text == refusal_text("lamp", LOCKED_NOTE)
    assert len(approver.requests) == (1 if admitted else 0)  # locked: never asked
    assert any(call[0] == "step_up" for call in guard.calls) is stepped


def test_tier_0_and_exempt_calls_never_meet_the_guard() -> None:
    guard = FakeGuard("locked")
    gate = make_gate(ScriptedApprover(), guard, exemptions=[lambda name, args: True])
    assert check(gate, "clock") == (True, None, None)
    assert check(gate, "lamp") == (True, None, "exempt")
    assert guard.calls == []


def test_tier_1_is_admitted_but_never_stepped_up() -> None:
    guard = FakeGuard("unlocked")
    bus = EventBus()
    events = record_events(bus, "guard")
    gate = make_gate(ScriptedApprover(), guard, bus=bus)
    assert check(gate, "note") == (True, None, None)
    assert guard.calls == [("admit", GuardTurn("tui", "s1", "c1"))]
    guard.set_state("locked")
    assert check(gate, "note") == (False, refusal_text("note", LOCKED_NOTE), "locked")
    assert [e.data for e in events] == [
        {"action": "refused", "channel": "tui", "reason": "locked", "tool": "note"}
    ]
    assert not any(call[0] == "step_up" for call in guard.calls)


def test_step_up_events_progress_and_the_approval_record() -> None:
    deadline = datetime(2026, 9, 30, 12, 0, 3, tzinfo=UTC)
    progress = [
        GuardProgress("look", 1, deadline),
        GuardProgress("turn_left", 2, None, "too_dark"),
    ]
    guard = FakeGuard("unlocked", step_ups=[True, False], progress=progress)
    bus = EventBus()
    events = record_events(bus, "guard", "approval")
    gate = make_gate(ScriptedApprover([Decision.APPROVED, Decision.APPROVED]), guard, bus=bus)
    assert check(gate) == (True, None, "approved")
    request_id = events[-1].data["request_id"]
    ids = {"request_id": request_id, "tool": "lamp"}
    assert [(e.kind, e.data) for e in events] == [
        ("guard", {"action": "step_up", "phase": "start", **ids}),
        (
            "guard",
            {
                "action": "challenge",
                "step": "look",
                "hint": None,
                "deadline": deadline.isoformat(),
                "request_id": request_id,
            },
        ),
        (
            "guard",
            {
                "action": "challenge",
                "step": "turn_left",
                "hint": "too_dark",
                "deadline": None,
                "request_id": request_id,
            },
        ),
        ("guard", {"action": "step_up", "phase": "end", "ok": True, **ids}),
        ("approval", {**events[-1].data, "decision": "approved", "step_up": "passed"}),
    ]
    events.clear()
    assert check(gate) == (False, refusal_text("lamp", STEP_UP_NOTE), "rejected")
    approval = events[-1]
    assert approval.kind == "approval"
    assert approval.data["decision"] == "rejected" and approval.data["step_up"] == "failed"


class LocksWhileAsking(ScriptedApprover):
    """The owner walks away with the approval dialog open, the guard locks, someone clicks."""

    def __init__(self, guard: FakeGuard) -> None:
        super().__init__([Decision.APPROVED])
        self.guard = guard

    async def decide(self, request: ApprovalRequest) -> Decision:
        self.guard.set_state("locked", trigger="idle")
        return await super().decide(request)


def test_a_lock_while_the_dialog_is_open_refuses_before_the_step_up() -> None:
    guard = FakeGuard("unlocked", step_ups=[True])  # a guard whose step-up ignores the lock
    bus = EventBus()
    events = record_events(bus, "guard", "approval")
    gate = make_gate(LocksWhileAsking(guard), guard, bus=bus)
    assert check(gate) == (False, refusal_text("lamp", LOCKED_NOTE), "locked")
    assert [call[0] for call in guard.calls] == ["admit", "admit"]  # never stepped up
    assert [(e.kind, e.data.get("action"), e.data.get("reason")) for e in events] == [
        ("guard", "refused", "locked"),
        ("approval", None, None),
    ]
    assert events[-1].data["decision"] == "rejected" and "step_up" not in events[-1].data


def test_a_recheck_after_the_approval_goes_on_to_the_step_up() -> None:
    guard = FakeGuard("unlocked", admissions=[True, "recheck"], step_ups=[True])
    gate = make_gate(ScriptedApprover([Decision.APPROVED]), guard)
    assert check(gate) == (True, None, "approved")
    assert [call[0] for call in guard.calls] == ["admit", "admit", "step_up"]
    guard = FakeGuard("unlocked", admissions=[True, "cooldown"], step_ups=[True])
    gate = make_gate(ScriptedApprover([Decision.APPROVED]), guard)
    assert check(gate) == (False, refusal_text("lamp", LOCKED_NOTE), "locked")


def test_without_a_guard_the_approval_record_has_no_step_up() -> None:
    bus = EventBus()
    events = record_events(bus, "approval")
    gate = make_gate(ScriptedApprover([Decision.APPROVED]), None, bus=bus)
    assert check(gate) == (True, None, "approved")
    assert "step_up" not in events[0].data


def test_a_cancelled_step_up_is_recorded_as_failed_and_propagates() -> None:
    guard = FakeGuard("unlocked", step_ups=[asyncio.CancelledError()])
    bus = EventBus()
    events = record_events(bus, "guard", "approval")
    gate = make_gate(ScriptedApprover([Decision.APPROVED]), guard, bus=bus)
    with pytest.raises(asyncio.CancelledError):
        check(gate)
    assert events[-2].data["phase"] == "end" and events[-2].data["ok"] is False
    assert events[-1].kind == "approval"
    assert events[-1].data["decision"] == "rejected" and events[-1].data["step_up"] == "failed"


def test_a_failed_step_up_reaches_the_model_as_the_fixed_note(config: Config) -> None:
    guard = FakeGuard("unlocked", step_ups=[False])
    approver = ScriptedApprover([Decision.APPROVED])
    model = FakeModel([[ToolCall("lamp", {"state": "on"})], "Not done."])
    agent = make_agent(config, guard, model, approver=approver)
    events = asyncio.run(collect(agent, "lamp on"))
    [finished] = [e for e in events if isinstance(e, ToolFinished)]
    assert finished.approval == "rejected" and finished.status == "rejected"
    assert finished.summary == refusal_text("lamp", STEP_UP_NOTE)
    assert RAN == []
    result = model.calls[-1].messages[-1]["content"][0]["toolResult"]
    assert STEP_UP_NOTE in json.dumps(result)


# -- FakeGuard -------------------------------------------------------------------------------


def test_fake_guard_replays_progress_and_never_approves() -> None:
    steps: list[GuardProgress] = []
    progress = [GuardProgress("look", 1, None), GuardProgress("done", 2, None)]
    guard = FakeGuard(verdicts=[GuardVerdict(True, "match", "face")], progress=progress)
    request = ApprovalRequest("r1", "lamp", Tier.PHYSICAL, {}, "", "s1", "tui")

    async def main() -> None:
        assert (await guard.unlock(channel="tui", client_id="c1", on_progress=steps.append)).ok
        assert (await guard.status()).state == "unlocked"
        assert await guard.step_up(request, client_id="c1") is False  # exhausted script
        verdict = await guard.unlock(channel="tui", client_id="c1")
        assert verdict == GuardVerdict(False, "no_match")
        seq = guard.seq
        waiter = asyncio.create_task(guard.watch(seq, wait=5))
        await asyncio.sleep(0.02)
        await guard.lock(channel="tui", client_id="c1", trigger="telegram")
        status = await waiter
        assert status.state == "locked" and status.lock_trigger == "telegram"
        assert status.seq == seq + 1

    asyncio.run(main())
    assert [s.step for s in steps] == ["look", "done"]


def test_fake_guard_takes_the_documented_signature() -> None:
    verdict = GuardVerdict(True, "match", "face")
    guard = FakeGuard("locked", [verdict], [True], (), ["recheck"])
    assert (guard.verdicts, guard.step_ups, guard.admissions) == ([verdict], [True], ["recheck"])


def test_every_guard_message_is_a_literal_in_the_table() -> None:
    """Turkish UI text lives only in the ``tr`` column: no constant or f-string built elsewhere
    in the module feeds the table (CLAUDE.md)."""
    import ast

    import tau_core.guard as guard_module

    tree = ast.parse(Path(guard_module.__file__).read_text(encoding="utf-8"))
    [table] = [
        node.value
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "GUARD_MESSAGES"
    ]
    assert isinstance(table, ast.Dict)
    for row in table.values:
        assert isinstance(row, ast.Dict)
        for text in row.values:
            assert isinstance(text, ast.Constant) and isinstance(text.value, str), ast.unparse(text)


# -- LockedGuard -----------------------------------------------------------------------------


def test_locked_guard_refuses_everything() -> None:
    guard = LockedGuard("unsupported_platform", detail="macOS only")
    request = ApprovalRequest("r1", "lamp", Tier.PHYSICAL, {}, "", "s1", "tui")

    async def main() -> None:
        assert await guard.status() == GuardStatus("unavailable", reason="unsupported_platform")
        assert await guard.admit(TURN) == Admission(False, "unsupported_platform")
        verdict = await guard.unlock(channel="tui", client_id="c1")
        assert verdict == GuardVerdict(False, "unsupported_platform")
        assert await guard.step_up(request, client_id="c1") is False
        await guard.lock(channel="tui", client_id="c1")
        await guard.cancel(client_id="c1")
        assert (await guard.watch(-1)).state == "unavailable"

    asyncio.run(main())
    assert asyncio.run(LockedGuard("weird").admit(TURN)) == Admission(False, "error")


# -- resolve_guard ---------------------------------------------------------------------------


def guarded_config(tmp_path: Path, table: dict[str, Any] | None = None) -> Config:
    config = test_config(tmp_path)
    return config.with_overrides(component_tables={"guard": table} if table is not None else {})


def test_resolve_guard_is_none_without_marker_or_enabled(tmp_path: Path) -> None:
    assert resolve_guard(guarded_config(tmp_path), platform="darwin") is None
    assert resolve_guard(guarded_config(tmp_path / "b", {"enabled": False})) is None
    assert resolve_guard(guarded_config(tmp_path / "c", {"camera": "builtin"})) is None
    assert resolve_guard(guarded_config(tmp_path / "d"), platform="linux") is None


@pytest.mark.parametrize("table", [None, {"enabled": False}, {"enabled": True, "step_up": "face"}])
def test_resolve_guard_with_the_marker_is_a_hub_guard(tmp_path: Path, table: Any) -> None:
    config = guarded_config(tmp_path, table)
    write_marker(config)
    guard = resolve_guard(config, platform="darwin")
    assert isinstance(guard, HubGuard)
    assert resolve_guard(config, platform="darwin") is guard  # memoized per (home, data_dir)
    reset_guards()
    assert resolve_guard(config, platform="darwin") is not guard


def test_no_guard_is_never_memoized(tmp_path: Path) -> None:
    config = guarded_config(tmp_path)
    assert resolve_guard(config, platform="darwin") is None
    write_marker(config)  # `tau guard setup` in another terminal
    guard = resolve_guard(config, platform="darwin")
    assert isinstance(guard, HubGuard)
    assert resolve_guard(config, platform="darwin") is guard
    other = guarded_config(tmp_path / "other")
    assert resolve_guard(other, platform="darwin") is None
    enabled = other.with_overrides(component_tables={"guard": {"enabled": True}})
    assert isinstance(resolve_guard(enabled, platform="darwin"), HubGuard)  # same home, data


def test_a_process_started_before_enrollment_is_guarded_at_its_next_build(
    config: Config,
) -> None:
    model = FakeModel(["one", "never sent"])
    first = build_agent(config=config, model=model, tools=[])
    assert first.guard is None
    assert asyncio.run(first.ask("hi")) == "one"
    write_marker(config)  # the owner runs `tau guard setup` while this window stays open
    again = build_agent(config=config, model=model, tools=[])  # /new, /resume, /model
    assert again.guard is not None and again.gate.guard is again.guard
    events = asyncio.run(collect(again, "hi"))
    assert events[-1] == TurnEnd("locked")  # no hub (or not macOS): refused, not unguarded
    assert len(model.calls) == 1


def test_enabled_true_without_a_marker_is_a_hub_guard(tmp_path: Path) -> None:
    guard = resolve_guard(guarded_config(tmp_path, {"enabled": True}), platform="darwin")
    assert isinstance(guard, HubGuard)
    assert asyncio.run(guard.admit(TURN)) == Admission(False, "unavailable")  # no token, no hub


@pytest.mark.parametrize(
    "table",
    [{"enabled": "true"}, {"enabled": 1}, {"enable": True}, {"enabled": True, "stepup": "none"}],
    ids=["string", "int", "typo", "unknown-key"],
)
def test_a_broken_guard_table_locks_for_good(tmp_path: Path, table: dict[str, Any]) -> None:
    guard = resolve_guard(guarded_config(tmp_path, table), platform="darwin")
    assert isinstance(guard, LockedGuard)
    assert guard.reason == "error" and guard.detail
    assert asyncio.run(guard.admit(TURN)) == Admission(False, "error")


def test_other_platforms_lock_an_active_guard(tmp_path: Path) -> None:
    config = guarded_config(tmp_path)
    write_marker(config)
    guard = resolve_guard(config, platform="linux")
    assert isinstance(guard, LockedGuard) and guard.reason == "unsupported_platform"
    assert asyncio.run(guard.admit(TURN)) == Admission(False, "unsupported_platform")


# -- /status and tau doctor ------------------------------------------------------------------


def test_guard_status_line() -> None:
    assert guard_status_line(GuardStatus("unlocked", method="face")) == "Guard: unlocked · face"
    locked = GuardStatus("locked", lock_trigger="idle")
    assert guard_status_line(locked, "tr") == "Koruma: kilitli · hareketsizlik nedeniyle kilitlendi"
    no_hub = guard_status_line(GuardStatus("unavailable", reason="no_hub"))
    assert no_hub == f"Guard: unavailable · {t('guard.start_hub', 'en')}"
    assert guard_status_line(GuardStatus("unavailable", reason="guard_off")).endswith("guard_off")


def test_status_shows_the_guard_only_when_one_is_active(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("tau_core.status.check_hub", lambda config: Check("hub", "info", "off"))
    plain = build_agent(config=config, model=FakeModel(), tools=[])
    assert not any(line.startswith("Guard:") for line in asyncio.run(status_report(plain)))
    guarded = build_agent(config=config, model=FakeModel(), tools=[], guard=FakeGuard("unlocked"))
    lines = asyncio.run(status_report(guarded))
    assert lines[-1] == "Guard: unlocked"
    assert status_lines(guarded)[-1] != "Guard: unlocked"  # only with a status passed in


def active_config(tmp_path: Path, table: dict[str, Any] | None = None, **kw: Any) -> Config:
    config = guarded_config(tmp_path, table)
    write_marker(config)
    return config.with_overrides(**kw) if kw else config


def test_doctor_check_off_and_broken(tmp_path: Path) -> None:
    check_off = guard_doctor_check(guarded_config(tmp_path), None, platform="darwin")
    assert check_off.status == "info" and check_off.detail.startswith("off")
    broken = guard_doctor_check(guarded_config(tmp_path / "b", {"enable": True}), None)
    assert broken.status == "fail" and "enable" in broken.detail
    linux = guard_doctor_check(active_config(tmp_path / "c"), None, platform="linux")
    assert linux.status == "fail" and "macOS" in linux.detail


@pytest.mark.parametrize(
    ("hub_status", "status", "phrase"),
    [
        (None, "warn", "no hub runs"),
        ({"pid": 1}, "warn", "no guard service"),
        ({"guard": {"state": "off"}}, "warn", "reports the guard off"),
        ({"guard": {"state": "locked", "enrolled": True}}, "ok", "reports it locked"),
        (
            {"guard": {"state": "unavailable", "available": False, "reason": "config"}},
            "fail",
            "reports it unavailable (config)",
        ),
        (
            {"guard": {"state": "unavailable", "reason": "\x1b[2Jforged"}},
            "fail",
            "unavailable (unknown)",
        ),
        (
            {"guard": {"state": "locked", "available": False, "reason": "reflex_stalled"}},
            "warn",
            "cannot check it right now (reflex_stalled)",
        ),
        (
            {"guard": {"state": "unlocked", "available": True, "reason": "screen_unknown"}},
            "warn",
            "cannot read the screen lock",
        ),
    ],
)
def test_doctor_check_against_the_hub(
    tmp_path: Path, hub_status: Any, status: str, phrase: str
) -> None:
    result = guard_doctor_check(active_config(tmp_path), hub_status, platform="darwin")
    assert (result.name, result.status) == ("guard", status)
    assert phrase in result.detail


def test_doctor_check_notes_ignored_enabled_false_and_pinned_services(tmp_path: Path) -> None:
    ignored = guard_doctor_check(
        active_config(tmp_path, {"enabled": False}),
        {"guard": {"state": "unlocked"}},
        platform="darwin",
    )
    assert ignored.status == "ok" and "enabled = false is ignored" in ignored.detail
    pinned = active_config(
        tmp_path / "b", components=ComponentsConfig(hub_services=("telegram", "spend"))
    )
    result = guard_doctor_check(pinned, {"guard": {"state": "locked"}}, platform="darwin")
    assert result.status == "fail" and "does not list guard" in result.detail


def test_tau_doctor_shows_the_guard_line(config: Config) -> None:
    import socket

    with socket.socket() as probe:  # a port nothing listens on: never the live hub
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {"TAU_HUB_PORT": str(port), "TAU_DATA_DIR": str(config.data_dir)}
    checks = run_doctor(config.home, env=env)
    [guard] = [c for c in checks if c.name == "guard"]
    assert guard.status == "info" and guard.detail.startswith("off")
