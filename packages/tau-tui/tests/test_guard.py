"""The owner guard in the TUI (issue 113): the lock screen, live locks, step-ups, ``/guard``.

Every test runs offline against ``FakeGuard`` (or a subclass that waits); no camera, hub,
Keychain or Touch ID is ever touched, and approvals are always a key press.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from helpers import (
    SESSION_ID,
    arm_tool,
    finish,
    fixed_clock,
    make_app,
    send,
    steady,
    wait_until,
)
from tau_core import (
    ApprovalRequest,
    Config,
    Decision,
    GuardProgress,
    GuardStatus,
    GuardVerdict,
    MemorySessionStore,
    Tier,
    command_hint,
    registry,
    tau_tool,
)
from tau_core.guard import process_client_id
from tau_core.i18n import t
from tau_core.testing import FakeGuard, FakeModel, ToolCall, record_events, test_config
from tau_tui import ApprovalScreen, SettingsScreen, build_app
from tau_tui.composer import Composer, PromptArea
from tau_tui.guard import GuardScreen
from tau_tui.sessions import SessionPicker
from tau_tui.settings import SettingsOutcome
from tau_tui.transcript import NoticeRow
from textual.pilot import Pilot
from textual.widgets import Input

MATCH = GuardVerdict(True, "match", "face")
STEPS = [
    GuardProgress("starting", 1, None),
    GuardProgress("look", 2, None, hint="face_too_small"),
    GuardProgress("turn_right", 3, None),
    GuardProgress("center", 4, None),
    GuardProgress("done", 5, None),
]
STEP_TEXTS = [
    "Starting the camera…",
    "Look at the camera. Move closer to the camera.",
    "Turn your head right.",
    "Look straight at the camera again.",
    "Done.",
]


def notices(app) -> list[str]:
    return [row.content.plain for row in app.transcript.query(NoticeRow)]


def guard_app(tmp_path: Path, guard: Any, replies: list | None = None, **kw) -> Any:
    kw.setdefault("session_store", MemorySessionStore())
    return make_app(tmp_path, replies or ["Okay."], guard=guard, **kw)


async def lock_screen(pilot: Pilot) -> GuardScreen:
    await wait_until(pilot, lambda: isinstance(pilot.app.screen, GuardScreen))
    await pilot.pause()
    return pilot.app.screen  # type: ignore[return-value]


async def unlocked(pilot: Pilot) -> None:
    app = pilot.app
    await wait_until(pilot, lambda: not app.locked and app.agent is not None)
    await wait_until(pilot, lambda: not isinstance(app.screen, GuardScreen))
    await pilot.pause()


async def type_entry(pilot: Pilot, text: str) -> None:
    """Type into the lock screen's field and press Enter."""
    pilot.app.screen.query_one("#entry", Input).value = text
    await pilot.press("enter")
    await pilot.pause()


class WaitingGuard(FakeGuard):
    """An unlock that waits until the test releases it (or it is cancelled)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.release = asyncio.Event()
        self.cancelled = False

    async def unlock(self, *, on_progress: Any = None, **kwargs: Any) -> GuardVerdict:
        self.calls.append(("unlock", kwargs.get("kind", "unlock")))
        if on_progress is not None:
            on_progress(GuardProgress("look", 1, None))
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return await super().unlock(channel="tui", client_id="c", kind="unlock")


class SlowStepUpGuard(FakeGuard):
    """A step-up that shows two challenge steps and waits until the test releases it."""

    def __init__(self) -> None:
        super().__init__("unlocked")
        self.release = asyncio.Event()

    async def step_up(self, request: ApprovalRequest, *, client_id: str, on_progress=None):
        self.calls.append(("step_up", request.request_id))
        if on_progress is not None:
            on_progress(GuardProgress("look", 1, None))
            on_progress(GuardProgress("turn_left", 2, None, hint="too_dark"))
        await self.release.wait()
        return True


class LocksOnAdmit(FakeGuard):
    """The hub locks right before the turn's admission (the watcher is a moment behind)."""

    async def admit(self, turn: Any) -> Any:
        self.set_state("locked", trigger="idle")
        return await super().admit(turn)


class DeafGuard(FakeGuard):
    """A lock that never takes (``HubGuard`` only logs that)."""

    async def lock(self, *, channel: str, client_id: str, trigger: str = "command") -> None:
        self.calls.append(("lock", trigger))


# -- the lock comes first --------------------------------------------------------------------


async def test_the_lock_screen_is_the_first_screen_and_the_agent_waits(tmp_path: Path) -> None:
    guard = FakeGuard("locked")
    model = FakeModel(["Okay."])
    app = guard_app(tmp_path, guard, model=model)
    assert app.agent is None  # nothing is built before the first unlock
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await lock_screen(pilot)
        assert [type(s).__name__ for s in app.screen_stack] == ["TauScreen", "GuardScreen"]
        assert app.agent is None and app.locked
        assert "tau is locked" in screen.text and "Guard: locked" in screen.text
        assert app.header.text.endswith("⚿ brain · en")  # the lock glyph: a guard is active
        assert SESSION_ID not in app.header.text
    assert model.calls == []


async def test_missing_credentials_open_the_settings_only_after_the_unlock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEEDY_KEY", raising=False)
    registry.reset()
    registry.register_provider("needy", lambda role_cfg, env: FakeModel(["Hi."]), [["NEEDY_KEY"]])
    try:
        config = test_config(tmp_path)
        (config.home / "tau.toml").write_text(
            '[models.roles.brain]\nprovider = "needy"\nmodel_id = "n"\n', encoding="utf-8"
        )
        config = Config.load(config.home, env={"TAU_DATA_DIR": str(tmp_path / "data")})
        guard = FakeGuard("locked", verdicts=[MATCH])
        app = build_app(
            config, tools=[], guard=guard, clock=fixed_clock, motion=False, show_paths=False
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await lock_screen(pilot)
            await pilot.pause(0.2)
            assert not any(isinstance(s, SettingsScreen) for s in app.screen_stack)
            await pilot.press("f10")  # refused while locked
            await type_entry(pilot, "/settings")
            app.open_settings()  # and refused inside, whoever calls it
            assert not any(isinstance(s, SettingsScreen) for s in app.screen_stack)
            await pilot.press("enter")  # unlock
            await wait_until(pilot, lambda: isinstance(app.screen, SettingsScreen))
            assert app.missing_credentials is not None and app.agent is None
    finally:
        registry.reset()


class NoHubGuard(FakeGuard):
    """``HubGuard`` when no hub answers: unavailable, reason ``no_hub``."""

    def _status(self) -> GuardStatus:
        return GuardStatus(state="unavailable", reason="no_hub", seq=self.seq)

    async def unlock(self, **kwargs: Any) -> GuardVerdict:
        self.calls.append(("unlock", kwargs.get("kind")))
        return GuardVerdict(False, "unavailable")


async def test_without_a_hub_the_lock_screen_says_how_to_start_one(tmp_path: Path) -> None:
    app = guard_app(tmp_path, NoHubGuard("locked"))
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await lock_screen(pilot)
        await wait_until(pilot, lambda: app.guard_status is not None)
        assert t("guard.start_hub", "en") in screen.text
        await pilot.press("enter")
        await wait_until(pilot, lambda: bool(screen.message_lines))
        assert screen.message_lines[0] == t("guard.verdict.unavailable", "en")
        assert app.locked and app.agent is None


async def test_every_action_but_the_lock_screens_own_is_refused(tmp_path: Path) -> None:
    guard = FakeGuard("locked")
    app = guard_app(tmp_path, guard)
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        await lock_screen(pilot)
        for key in ("ctrl+r", "ctrl+n", "ctrl+t", "ctrl+e", "ctrl+o", "f1", "f2", "f10"):
            await pilot.press(key)
        await pilot.press("ctrl+l", "pageup", "f9")
        await pilot.pause()
        assert [type(s).__name__ for s in app.screen_stack] == ["TauScreen", "GuardScreen"]
        for action in ("pick_session", "new_session", "settings", "help", "lock", "show_tools"):
            assert app.check_action(action, ()) is False
        assert app.check_action("quit", ()) is True
        assert not any(isinstance(s, SessionPicker) for s in app.screen_stack)
        assert guard.calls.count(("lock", "command")) == 0  # ctrl+l did nothing while locked


async def test_only_the_allowed_commands_run_on_the_lock_screen(tmp_path: Path) -> None:
    guard = FakeGuard("locked")
    app = guard_app(tmp_path, guard)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await lock_screen(pilot)
        for command in ("/status", "/sessions", "/compact", "/clear", "/resume", "/new"):
            await type_entry(pilot, command)
            name = command[1:]
            assert screen.message_lines == [t("guard.cmd.refused", "en", command=name)]
        await type_entry(pilot, "/help")
        assert screen.message_lines[0] == "Commands:"
        assert any(line.startswith("  /guard [lock|unlock]") for line in screen.message_lines)
        assert not any("/status" in line for line in screen.message_lines)
        await type_entry(pilot, "/guard")
        assert screen.message_lines == ["Guard: locked"]
        await type_entry(pilot, "/hlep")  # answered here, not in the hidden transcript
        unknown = t("chat.unknown_command", "en", name="hlep", hint=command_hint("en"))
        assert screen.message_lines == [unknown]
        assert unknown not in app.transcript.text
        await type_entry(pilot, "hello")
        assert screen.message_lines == [t("guard.prompt.not_sent", "en")]
        assert screen.query_one("#entry", Input).value == "hello"  # not sent, kept
        await type_entry(pilot, "/lang tr")
        assert app.language == "tr" and "tau kilitli" in screen.text
        await type_entry(pilot, "/lang xx")
        assert screen.message_lines == [t("lang.unknown", "tr", language="xx", choices="en|tr")]
        assert app.agent is None


# -- unlocking -------------------------------------------------------------------------------


async def test_enter_unlocks_every_step_shows_and_the_notice_counts_failures(
    tmp_path: Path,
) -> None:
    guard = FakeGuard("locked", verdicts=[GuardVerdict(False, "no_match"), MATCH], progress=STEPS)
    model = FakeModel(["Okay."])
    app = guard_app(tmp_path, guard, model=model)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await lock_screen(pilot)
        await pilot.press("enter")
        await wait_until(pilot, lambda: "The face did not match." in screen.message_lines)
        assert screen.shown[: len(STEP_TEXTS)] == STEP_TEXTS  # every step before the verdict
        assert screen.shown[len(STEP_TEXTS)] == "The face did not match."
        await pilot.press("enter")
        await unlocked(pilot)
        assert screen.shown[-len(STEP_TEXTS) :] == STEP_TEXTS
        assert notices(app)[-1] == "▸ Unlocked (face). Failed attempts since the last unlock: 1."
        assert app.agent is not None and app.agent.guard is guard
        assert app.header.text.endswith("⚿ brain · en")
        assert SESSION_ID in app.header.text
    assert model.calls == []  # the unlock made no model call
    assert [call for call in guard.calls if call[0] == "unlock"] == [("unlock", "unlock")] * 2


async def test_esc_cancels_a_running_attempt(tmp_path: Path) -> None:
    guard = WaitingGuard("locked")
    app = guard_app(tmp_path, guard)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await lock_screen(pilot)
        await pilot.press("enter")
        await wait_until(pilot, lambda: app.attempt_running and screen.progress_line != "")
        assert screen.progress_line == "Look at the camera."
        assert "◉ tau is locked" in screen.text  # the camera is on
        await pilot.press("escape")
        await wait_until(pilot, lambda: ("cancel", process_client_id()) in guard.calls)
        await wait_until(pilot, lambda: not app.attempt_running)
        assert guard.cancelled
        assert screen.message_lines[0] == t("guard.verdict.cancelled", "en")
        assert isinstance(app.screen, GuardScreen) and app.locked


async def test_another_channel_unlocking_closes_the_lock_screen(tmp_path: Path) -> None:
    guard = FakeGuard("locked")
    app = guard_app(tmp_path, guard)
    async with app.run_test(size=(80, 24)) as pilot:
        await lock_screen(pilot)
        guard.set_state("unlocked")
        await unlocked(pilot)
        assert notices(app)[-1] == "▸ Unlocked (—). Failed attempts since the last unlock: 0."


async def test_a_prompt_kept_from_before_the_lock_is_not_sent_after_the_unlock(
    tmp_path: Path,
) -> None:
    guard = FakeGuard("unlocked", verdicts=[MATCH])
    model = FakeModel(["Okay."])
    app = guard_app(tmp_path, guard, model=model)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        app.query_one(PromptArea).load_text("draft to keep")
        guard.set_state("locked", trigger="idle")
        await lock_screen(pilot)
        await pilot.press("enter")
        await unlocked(pilot)
        assert app.composer.text == "draft to keep"
        assert model.calls == []


# -- live lock propagation -------------------------------------------------------------------


async def test_an_external_lock_cancels_the_turn_and_rejects_the_approval(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    guard = FakeGuard("unlocked")
    model = FakeModel([[ToolCall("move_arm", {"direction": "left"})], "Moved."])
    app = guard_app(tmp_path, guard, model=model, tools=[arm_tool(calls)], approve_delay=0)
    approvals = record_events(app.bus, "approval")
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        await steady(pilot)
        await send(pilot, "move the arm")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        started = asyncio.get_running_loop().time()
        guard.set_state("locked", trigger="telegram")
        await wait_until(pilot, lambda: isinstance(app.screen, GuardScreen), timeout=2.0)
        assert asyncio.get_running_loop().time() - started < 2.0
        assert not any(isinstance(s, ApprovalScreen) for s in app.screen_stack)
        await wait_until(pilot, lambda: not app.busy)
        assert [e.data["decision"] for e in approvals] == ["rejected"]
        assert calls == []  # the arm never moved
        assert t("guard.locked_during_turn", "en") in app.transcript.text
        assert "Guard: locked · locked from Telegram" in app.screen.text
        assert app.approver is not None and app.approver.pending is None


async def test_an_external_lock_cancels_a_running_compaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tau_core import CompactionCancelled

    async def slow_summarize(agent, *, focus=None, cancel_signal=None):
        while not (cancel_signal is not None and cancel_signal.is_set()):
            await asyncio.sleep(0.01)
        raise CompactionCancelled("compaction was cancelled.")

    monkeypatch.setattr("tau_tui.app.summarize", slow_summarize)
    guard = FakeGuard("unlocked")
    app = guard_app(tmp_path, guard, ["Buyurun."])
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        await send(pilot, "Merhaba")
        await finish(pilot)
        agent = app.agent
        await send(pilot, "/compact")
        await wait_until(pilot, lambda: app.busy)
        guard.set_state("locked")
        await lock_screen(pilot)
        await wait_until(pilot, lambda: not app.busy)
        assert "▸ Compaction cancelled; the session continues." in notices(app)
        assert app.agent is agent


async def test_the_approver_rejects_at_once_while_locked(tmp_path: Path) -> None:
    guard = FakeGuard("locked")
    app = guard_app(tmp_path, guard)
    request = ApprovalRequest("r1", "move_arm", Tier.PHYSICAL, {}, "", SESSION_ID, "tui")
    async with app.run_test(size=(80, 24)) as pilot:
        await lock_screen(pilot)
        assert app.approver is not None
        decision = await asyncio.wait_for(app.approver.decide(request), 2.0)
        assert decision == Decision.REJECTED
        await pilot.pause()
        assert not any(isinstance(s, ApprovalScreen) for s in app.screen_stack)


# -- the composer and the recheck ------------------------------------------------------------


async def test_a_prompt_submitted_while_locked_stays_in_the_composer(tmp_path: Path) -> None:
    guard = FakeGuard("unlocked")
    model = FakeModel(["Okay."])
    app = guard_app(tmp_path, guard, model=model)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        guard.set_state("locked")
        await lock_screen(pilot)
        app.query_one(PromptArea).load_text("hello")
        admits = [c for c in guard.calls if c[0] == "admit"]
        await app.on_composer_submitted(Composer.Submitted("hello"))
        await pilot.pause()
        assert app.composer.text == "hello" and not app.busy
        assert [c for c in guard.calls if c[0] == "admit"] == admits  # no turn was started
    assert model.calls == []


async def test_a_refused_turn_puts_the_prompt_back_and_shows_the_lock(tmp_path: Path) -> None:
    guard = LocksOnAdmit("unlocked")
    model = FakeModel(["Okay."])
    app = guard_app(tmp_path, guard, model=model)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        await send(pilot, "hello")  # the watcher has not seen the lock yet: the turn is refused
        await lock_screen(pilot)
        await wait_until(pilot, lambda: not app.busy)
        assert app.composer.text == "hello"
        assert t("guard.refused.locked", "en") in app.transcript.text
        assert "Locked" in app.transcript.text  # the turn footer (tui.turn.stop.locked)
    assert model.calls == []


async def test_a_recheck_runs_the_passive_check_and_resends(tmp_path: Path) -> None:
    guard = FakeGuard("unlocked", verdicts=[MATCH], admissions=["recheck", True])
    model = FakeModel(["Okay."])
    app = guard_app(tmp_path, guard, model=model)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        await send(pilot, "hello")
        await finish(pilot)
        assert ("unlock", "recheck") in guard.calls
        assert "Okay." in app.transcript.text
        assert app.composer.text == "" and not isinstance(app.screen, GuardScreen)
    assert len(model.calls) == 1


# -- step-up ---------------------------------------------------------------------------------


async def test_step_up_steps_show_in_the_busy_line_with_a_bell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    guard = SlowStepUpGuard()
    model = FakeModel([[ToolCall("move_arm", {"direction": "left"})], "Moved."])
    app = guard_app(tmp_path, guard, model=model, tools=[arm_tool(calls)], approve_delay=0)
    bells: list[bool] = []
    monkeypatch.setattr(app, "bell", lambda: bells.append(True))
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        await send(pilot, "move the arm")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.press("y")
        busy = "✻ Identity check: Turn your head left. It is too dark."
        await wait_until(pilot, lambda: busy in app.transcript.text)
        assert app.attempt_running and "⚿ ◉ brain" in app.header.text
        assert len(bells) >= 4  # the approval, the start and both steps
        guard.release.set()
        await finish(pilot)
        assert calls == [{"direction": "left"}]
        assert not app.attempt_running and "◉" not in app.header.text


# -- /guard, ctrl+l, the header --------------------------------------------------------------


async def test_guard_command_without_a_guard_says_off(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        await send(pilot, "/guard")
        await pilot.pause()
        assert notices(app)[-1] == f"▸ {t('guard.cmd.off', 'en')}"
        await pilot.press("ctrl+l")
        await pilot.pause()
        assert any(t("guard.cmd.off", "en") in str(n.message) for n in app._notifications)
        assert "⚿" not in app.header.text and not app.locked


async def test_guard_command_ctrl_l_and_a_lock_that_did_not_take(tmp_path: Path) -> None:
    guard = FakeGuard("unlocked")
    app = guard_app(tmp_path, guard)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        await send(pilot, "/guard")
        await pilot.pause()
        assert notices(app)[-1] == "▸ Guard: unlocked"
        await send(pilot, "/guard unlock")
        await pilot.pause()
        assert notices(app)[-1] == f"▸ {t('guard.cmd.already_unlocked', 'en')}"
        await send(pilot, "/guard nope")
        await pilot.pause()
        assert notices(app)[-1] == f"▸ {t('guard.cmd.usage', 'en')}"
        await pilot.press("ctrl+l")
        screen = await lock_screen(pilot)
        assert ("lock", "command") in guard.calls
        assert "Guard: locked · locked by command" in screen.text

    deaf = DeafGuard("unlocked")
    app = guard_app(tmp_path / "deaf", deaf)
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        await unlocked(pilot)
        await send(pilot, "/guard lock")
        await wait_until(pilot, lambda: bool(app._notifications))
        assert any(t("guard.cmd.lock_failed", "en") in str(n.message) for n in app._notifications)
        assert not app.locked


async def test_guard_unlock_on_the_lock_screen_is_an_attempt(tmp_path: Path) -> None:
    guard = FakeGuard("locked", verdicts=[MATCH])
    app = guard_app(tmp_path, guard)
    async with app.run_test(size=(80, 24)) as pilot:
        await lock_screen(pilot)
        await type_entry(pilot, "/guard unlock")
        await unlocked(pilot)
        assert ("unlock", "unlock") in guard.calls


# -- one guard for every build ---------------------------------------------------------------


@pytest.fixture
def recorded_builds(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Any]]:
    import tau_tui.app as app_module

    seen: list[Any] = []
    original = app_module.build_agent

    def recording(**kwargs: Any) -> Any:
        seen.append(kwargs.get("guard"))
        return original(**kwargs)

    monkeypatch.setattr(app_module, "build_agent", recording)
    yield seen


async def test_the_same_guard_goes_to_every_build(
    tmp_path: Path, recorded_builds: list[Any]
) -> None:
    guard = FakeGuard("unlocked")
    store = MemorySessionStore()
    app = guard_app(tmp_path, guard, ["one", "two"], session_store=store)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        await send(pilot, "hello")
        await finish(pilot)
        await send(pilot, "/new")
        await wait_until(pilot, lambda: app.agent.session_id != SESSION_ID)
        await send(pilot, f"/resume {SESSION_ID}")
        await wait_until(pilot, lambda: app.agent.session_id == SESSION_ID)
        await send(pilot, "/model fast")
        await wait_until(pilot, lambda: app.role == "fast")
        outcome = SettingsOutcome(config=app.config, language="en", reload=True)
        await app.apply_settings(outcome)
        await pilot.pause()
    assert len(recorded_builds) == 5  # first unlock, /new, /resume, /model, settings save
    assert all(seen is guard for seen in recorded_builds)
    assert app.agent.guard is guard and app.agent.gate.guard is guard


async def test_without_a_guard_the_header_has_no_lock_and_the_app_starts_at_once(
    tmp_path: Path, recorded_builds: list[Any]
) -> None:
    app = make_app(tmp_path, [])
    assert app.agent is not None and app.guard is None and not app.locked
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.header.text.endswith("  brain · en") and "⚿" not in app.header.text
        assert not any(isinstance(s, GuardScreen) for s in app.screen_stack)


async def test_a_guard_set_up_while_the_app_runs_locks_it_and_keeps_the_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = FakeGuard("locked")
    found: list[Any] = [None]
    monkeypatch.setattr("tau_tui.app.resolve_guard", lambda config: found[0])
    model = FakeModel(["Okay."])
    app = make_app(tmp_path, [], model=model)
    async with app.run_test(size=(80, 24)) as pilot:
        assert app.guard is None
        found[0] = guard
        await send(pilot, "hello")
        await lock_screen(pilot)
        assert app.guard is guard and app.locked
        assert app.composer.text == "hello"
        assert app.header.text.endswith("⚿ brain · en")
    assert model.calls == []


async def test_the_lock_screen_has_an_ascii_twin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TAU_TUI_ASCII", "1")
    guard = FakeGuard("unlocked")
    app = guard_app(tmp_path, guard)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        assert app.header.text.endswith("K brain · en")
        guard.set_state("locked")
        screen = await lock_screen(pilot)
        assert screen.has_class("-ascii") and screen.text.startswith("K tau is locked")
        assert screen.query_one("#dialog").styles.border_top[0] == "ascii"


# -- races: a screen dismissed before it mounted ---------------------------------------------


async def test_a_lock_in_the_same_tick_as_the_approval_dialog_does_not_crash(
    tmp_path: Path,
) -> None:
    guard = FakeGuard("unlocked")
    app = guard_app(tmp_path, guard)
    request = ApprovalRequest("r1", "move_arm", Tier.PHYSICAL, {}, "", SESSION_ID, "tui")
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        assert app.approver is not None
        task = asyncio.create_task(app.approver.decide(request))
        await asyncio.sleep(0)  # decide pushed the dialog and waits for it
        assert isinstance(app.screen, ApprovalScreen) and not app.screen.is_mounted
        await app.enter_lock(GuardStatus("locked", seq=5))  # before the dialog mounted
        assert await asyncio.wait_for(task, 2.0) == Decision.REJECTED
        await pilot.pause(0.2)
        assert app.is_running and isinstance(app.screen, GuardScreen)
        assert not any(isinstance(s, ApprovalScreen) for s in app.screen_stack)


async def test_a_lock_and_an_unlock_in_the_same_tick_do_not_crash(tmp_path: Path) -> None:
    guard = FakeGuard("unlocked")
    app = guard_app(tmp_path, guard)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        await app.enter_lock(GuardStatus("locked", seq=5))
        assert app.guard_screen is not None and not app.guard_screen.is_mounted
        await app.leave_lock("face")  # before the lock screen mounted
        await pilot.pause(0.2)
        assert app.is_running and not app.locked
        assert not any(isinstance(s, GuardScreen) for s in app.screen_stack)


# -- a guard that appears while the app runs -------------------------------------------------


@pytest.fixture
def found_guard(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """What ``resolve_guard`` finds: ``None`` until the test puts a guard in slot 0."""
    found: list[Any] = [None]
    monkeypatch.setattr("tau_tui.app.resolve_guard", lambda config: found[0])
    return found


async def test_a_guard_found_mid_session_rebuilds_the_agent_at_the_unlock(
    tmp_path: Path, found_guard: list[Any]
) -> None:
    """The agent built before ``tau guard setup`` gets the guard at the unlock: its turns are
    admitted and a tier-2 call is stepped up (and refused when the step-up fails)."""
    calls: list[dict[str, Any]] = []
    guard = FakeGuard("locked", verdicts=[MATCH], step_ups=[False])
    model = FakeModel([[ToolCall("move_arm", {"direction": "left"})], "Not moved."])
    app = make_app(tmp_path, [], model=model, tools=[arm_tool(calls)], approve_delay=0)
    async with app.run_test(size=(80, 24)) as pilot:
        first = app.agent
        assert first is not None and first.guard is None
        found_guard[0] = guard
        await send(pilot, "move the arm")  # the guard is found on the submit
        await lock_screen(pilot)
        assert app.agent is first and app.composer.text == "move the arm"
        await pilot.press("enter")
        await unlocked(pilot)
        await wait_until(pilot, lambda: app.agent is not first)
        agent = app.agent
        assert agent.guard is guard and agent.gate.guard is guard
        assert agent.session_id == first.session_id
        await send(pilot, "move the arm")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.press("y")
        await finish(pilot)
        assert t("guard.step_up.failed", "en") in app.transcript.text
    assert [name for name, _ in guard.calls].count("step_up") == 1
    assert any(name == "admit" for name, _ in guard.calls)
    assert calls == []  # the step-up failed: the arm never moved


async def test_a_guard_found_unlocked_rebuilds_the_agent_when_the_lock_leaves(
    tmp_path: Path, found_guard: list[Any]
) -> None:
    calls: list[dict[str, Any]] = []
    guard = FakeGuard("unlocked", step_ups=[False])
    model = FakeModel([[ToolCall("move_arm", {"direction": "left"})], "Not moved."])
    app = make_app(tmp_path, [], model=model, tools=[arm_tool(calls)], approve_delay=0)
    async with app.run_test(size=(80, 24)) as pilot:
        first = app.agent
        found_guard[0] = guard
        await send(pilot, "move the arm")  # locks, then the watcher reads unlocked
        await wait_until(pilot, lambda: app.guard is guard and not app.locked)
        await wait_until(
            pilot, lambda: not any(isinstance(s, GuardScreen) for s in app.screen_stack)
        )
        assert app.agent is not first and app.agent.guard is guard
        assert app.composer.text == "move the arm"  # kept, not sent
        await send(pilot, "move the arm")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.press("y")
        await finish(pilot)
    assert any(name == "step_up" for name, _ in guard.calls)
    assert calls == []


async def test_a_guard_found_during_a_turn_cancels_it(
    tmp_path: Path, found_guard: list[Any]
) -> None:
    release = threading.Event()

    @tau_tool(tier=Tier.READ)
    def slow_read() -> str:
        """Reads slowly."""
        release.wait(5)
        return "read"

    guard = FakeGuard("locked")
    model = FakeModel([[ToolCall("slow_read", {})], "Done reading."])
    app = make_app(tmp_path, [], model=model, tools=[slow_read])
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "read slowly")
        await wait_until(pilot, lambda: app.busy and "slow_read" in app.transcript.text)
        found_guard[0] = guard
        await send(pilot, "one more thing")  # busy: the submit finds the guard
        await lock_screen(pilot)
        release.set()
        await wait_until(pilot, lambda: not app.busy)
        assert t("guard.locked_during_turn", "en") in app.transcript.text
        assert app.composer.text == "one more thing"
    assert len(model.calls) == 1  # the reply after the tool was never asked for


async def test_a_guard_found_with_the_approval_dialog_open_rejects_it(
    tmp_path: Path, found_guard: list[Any]
) -> None:
    calls: list[dict[str, Any]] = []
    guard = FakeGuard("unlocked")
    model = FakeModel([[ToolCall("move_arm", {"direction": "left"})], "Moved."])
    app = make_app(tmp_path, [], model=model, tools=[arm_tool(calls)], approve_delay=0)
    approvals = record_events(app.bus, "approval")
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "move the arm")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        found_guard[0] = guard
        await pilot.press("ctrl+l")  # finds the guard, then locks it
        await lock_screen(pilot)
        await wait_until(pilot, lambda: not app.busy)
        assert not any(isinstance(s, ApprovalScreen) for s in app.screen_stack)
        assert [e.data["decision"] for e in approvals] == ["rejected"]
        assert t("guard.locked_during_turn", "en") in app.transcript.text
    assert calls == []


# -- the order of states, the watcher ---------------------------------------------------------


class SlowStatusGuard(FakeGuard):
    """``status()`` answers what it saw when asked, after the test releases it."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.hold: asyncio.Event | None = None

    async def status(self) -> GuardStatus:
        snapshot = self._status()
        self.calls.append(("status", None))
        if self.hold is not None:
            await self.hold.wait()
        return snapshot


async def test_a_stale_unlocked_answer_does_not_leave_the_lock(tmp_path: Path) -> None:
    guard = SlowStatusGuard("unlocked")
    app = guard_app(tmp_path, guard)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        guard.hold = asyncio.Event()
        asking = asyncio.create_task(app.guard_command(""))  # /guard, answered late
        await wait_until(pilot, lambda: ("status", None) in guard.calls)
        guard.set_state("locked", trigger="telegram")
        screen = await lock_screen(pilot)
        guard.hold.set()
        await asyncio.wait_for(asking, 2.0)
        await pilot.pause(0.1)
        assert app.locked and app.screen is screen
        assert screen.message_lines == ["Guard: locked · locked from Telegram"]


async def test_the_watcher_survives_a_state_it_could_not_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = FakeGuard("unlocked")
    app = guard_app(tmp_path, guard)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        original = app.apply_guard_status
        failing = [True]

        async def flaky(status: GuardStatus) -> None:
            if failing and failing.pop():
                raise RuntimeError("boom")
            await original(status)

        monkeypatch.setattr(app, "apply_guard_status", flaky)
        guard.set_state("locked")
        await lock_screen(pilot)  # failed closed
        assert app.locked
        guard.set_state("unlocked")  # the watcher still runs
        await unlocked(pilot)


# -- the recheck and the step-up under Esc and a lock ------------------------------------------


async def test_esc_during_a_recheck_cancels_it_and_sends_nothing(tmp_path: Path) -> None:
    guard = WaitingGuard("unlocked", verdicts=[MATCH], admissions=["recheck"])
    model = FakeModel(["Okay."])
    app = guard_app(tmp_path, guard, model=model)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        await send(pilot, "hello")
        await wait_until(pilot, lambda: app.attempt_running and app.busy)
        await pilot.press("escape")
        await wait_until(pilot, lambda: not app.busy)
        assert guard.cancelled
        assert ("cancel", process_client_id()) in guard.calls
        assert app.composer.text == "hello"  # not sent, back in the composer
        assert not app.attempt_running and not app._cancelling
        assert "Cancelled" in app.transcript.text
    assert model.calls == []


async def test_a_lock_during_a_recheck_cancels_it_and_the_lock_screen_works(
    tmp_path: Path,
) -> None:
    guard = WaitingGuard("unlocked", admissions=["recheck"])
    model = FakeModel(["Okay."])
    app = guard_app(tmp_path, guard, model=model)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        await send(pilot, "hello")
        await wait_until(pilot, lambda: app.attempt_running and app.busy)
        guard.set_state("locked", trigger="idle")
        await lock_screen(pilot)
        await wait_until(pilot, lambda: not app.busy and not app.attempt_running)
        assert guard.cancelled and app.composer.text == "hello"
        await pilot.press("enter")  # the lock screen's own attempt can start now
        await wait_until(pilot, lambda: guard.calls.count(("unlock", "unlock")) == 1)
    assert model.calls == []


async def test_a_lock_during_a_step_up_stops_the_camera_and_the_call(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    guard = SlowStepUpGuard()
    model = FakeModel([[ToolCall("move_arm", {"direction": "left"})], "Stopped."])
    app = guard_app(tmp_path, guard, model=model, tools=[arm_tool(calls)], approve_delay=0)
    async with app.run_test(size=(80, 24)) as pilot:
        await unlocked(pilot)
        await send(pilot, "move the arm")
        await wait_until(pilot, lambda: isinstance(app.screen, ApprovalScreen))
        await pilot.press("y")
        await wait_until(pilot, lambda: app.attempt_running)
        guard.set_state("locked", trigger="screen_lock")
        await lock_screen(pilot)
        await wait_until(pilot, lambda: ("cancel", process_client_id()) in guard.calls)
        guard.release.set()  # this fake's step-up passes anyway; the gate asks once more
        await wait_until(pilot, lambda: not app.busy)
    assert calls == []  # the arm never moved under the lock


async def test_the_unlock_method_is_translated(tmp_path: Path) -> None:
    guard = FakeGuard("locked", verdicts=[MATCH])
    app = guard_app(tmp_path, guard)
    async with app.run_test(size=(80, 24)) as pilot:
        await lock_screen(pilot)
        await type_entry(pilot, "/lang tr")
        await pilot.press("enter")
        await unlocked(pilot)
        assert notices(app)[-1] == "▸ Kilit açıldı (yüz). Son açılıştan beri başarısız deneme: 0."
