"""The owner guard in ``tau chat`` (issue 113): the lock prompt, unlocking, ``/guard``.

The REPL runs in-process with a scripted ``input`` and a captured console; the guard is
``FakeGuard``, so no camera, hub or Keychain is ever touched.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from tau_core import Decision, GuardProgress, GuardVerdict, MemorySessionStore, Tier, tau_tool
from tau_core.agent import build_agent
from tau_core.builder import Check
from tau_core.channels.terminal import CLEAR_ALL, ReplState, run_repl
from tau_core.config import Config
from tau_core.guard import process_client_id
from tau_core.i18n import t
from tau_core.testing import FakeGuard, FakeModel, ScriptedApprover, ToolCall, test_config

HUB_DOWN = Check("hub", "info", "hub is not running")
MATCH = GuardVerdict(True, "match", "face")
STEPS = [
    GuardProgress("starting", 1, None),
    GuardProgress("look", 2, None, hint="too_dark"),
    GuardProgress("turn_left", 3, None),
    GuardProgress("center", 4, None),
    GuardProgress("done", 5, None),
]


@tau_tool(tier=Tier.PHYSICAL, effect="Switches the desk lamp.")
def lamp(state: str) -> str:
    """Switches the desk lamp.

    Args:
        state: "on" or "off".
    """
    return f"lamp {state}"


@pytest.fixture(autouse=True)
def _no_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tau_core.status.check_hub", lambda config: HUB_DOWN)


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return test_config(tmp_path)


class Feed:
    """An ``input`` replacement that records the prompts; ``hooks`` run before a line."""

    def __init__(self, lines: list[str], hooks: dict[int, Callable[[], None]] | None = None):
        self.lines = list(lines)
        self.hooks = hooks or {}
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        hook = self.hooks.get(len(self.prompts))
        if hook is not None:
            hook()
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)


def make_state(
    config: Config,
    guard: Any,
    *,
    model: FakeModel | None = None,
    approver: Any = None,
    tools: list | None = None,
) -> ReplState:
    approver = approver or ScriptedApprover()
    agent = build_agent(
        config=config,
        model=model or FakeModel(["Okay."]),
        tools=tools or [],
        approver=approver,
        session_store=MemorySessionStore(),
        channel="terminal",
        guard=guard,
    )
    console = Console(
        file=io.StringIO(), markup=False, emoji=False, highlight=False, soft_wrap=True, width=200
    )
    return ReplState(
        config=config,
        store=agent.store,  # type: ignore[arg-type]
        approver=approver,
        agent=agent,
        console=console,
        language=config.ui.language,
        guard=guard,
    )


def run(state: ReplState, feed: Feed) -> str:
    run_repl(state, input_func=feed)
    return state.console.file.getvalue()  # type: ignore[attr-defined]


# -- the lock prompt ---------------------------------------------------------------------------


def test_a_locked_guard_shows_the_banner_and_the_lock_prompt_first(config: Config) -> None:
    guard = FakeGuard("locked")
    guard.set_state("locked", trigger="idle")
    state = make_state(config, guard)
    feed = Feed(["/quit"])
    out = run(state, feed)
    assert out.startswith(CLEAR_ALL)  # screen and scrollback cleared before anything
    assert "tau ready." not in out  # no session id while locked
    assert "Guard: locked · locked after inactivity" in out
    assert t("guard.prompt.banner", "en") in out
    assert feed.prompts == ["locked> "]
    assert out.rstrip().endswith("Goodbye.")


def test_enter_unlocks_and_prints_every_step_before_the_notice(config: Config) -> None:
    guard = FakeGuard("locked", verdicts=[MATCH], progress=STEPS)
    model = FakeModel(["Okay."])
    state = make_state(config, guard, model=model)
    feed = Feed(["", "hello", "/quit"])
    out = run(state, feed)
    lines = out.splitlines()
    expected = [
        "  ◉ Starting the camera…",
        "  ◉ Look at the camera. It is too dark.",
        "  ◉ Turn your head left.",
        "  ◉ Look straight at the camera again.",
        "  ◉ Done.",
        "Unlocked (face). Failed attempts since the last unlock: 0.",
    ]
    start = lines.index(expected[0])
    assert lines[start : start + len(expected)] == expected
    assert lines[start + len(expected)].startswith("tau ready.")  # the banner after the unlock
    assert "tau> Okay." in out
    assert len(model.calls) == 1  # the unlock itself made no model call
    assert ("unlock", "unlock") in guard.calls
    assert feed.prompts == ["locked> ", "you> ", "you> "]


def test_failed_attempts_are_counted_in_the_unlocked_notice(config: Config) -> None:
    guard = FakeGuard(
        "locked",
        verdicts=[
            GuardVerdict(False, "no_match"),
            GuardVerdict(False, "cooldown", retry_after=30),
            MATCH,
        ],
    )
    model = FakeModel(["Okay."])
    state = make_state(config, guard, model=model)
    out = run(state, Feed(["", "", "", "/quit"]))
    assert "  ✗ The face did not match." in out
    assert "  ✗ Too many failed attempts. Wait a moment, then try again. Try again in 30 s." in out
    assert out.count(t("guard.prompt.retry", "en")) == 2
    assert "Unlocked (face). Failed attempts since the last unlock: 1." in out
    assert model.calls == []


class HangingGuard(FakeGuard):
    """An unlock that never finishes; Ctrl-C arrives while it waits (a SIGINT in the loop)."""

    def __init__(self) -> None:
        super().__init__("locked")
        self.cancelled = False

    async def unlock(self, **kwargs: Any) -> GuardVerdict:
        self.calls.append(("unlock", kwargs.get("kind")))

        def interrupt() -> None:
            raise KeyboardInterrupt

        asyncio.get_running_loop().call_soon(interrupt)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("never reached")


def test_ctrl_c_cancels_an_attempt_and_the_repl_keeps_running(config: Config) -> None:
    guard = HangingGuard()
    state = make_state(config, guard)
    feed = Feed(["", "/guard", "/quit"])
    out = run(state, feed)
    assert guard.cancelled  # the attempt's task was cancelled
    assert ("cancel", process_client_id()) in guard.calls
    assert "  ✗ The check was cancelled." in out
    assert "Guard: locked" in out.split("The check was cancelled.", 1)[1]  # /guard still ran
    assert feed.prompts == ["locked> ", "locked> ", "locked> "]
    assert out.rstrip().endswith("Goodbye.")


# -- the Touch ID fallback (issue 114) ---------------------------------------------------------

TOUCH_ID = GuardVerdict(True, "match", "touch_id")
TOUCH_STEP = [GuardProgress("touch_id", 1, None)]


def offer(mode: str = "touch_id", language: str = "en") -> str:
    how = t("guard.prompt.fallback_how", language, key="t")
    return t(f"guard.fallback.{mode}", language, how=how)


def test_the_offer_appears_after_two_face_failures_only_with_a_fallback(config: Config) -> None:
    guard = FakeGuard("locked", fallback="touch_id")
    state = make_state(config, guard)
    out = run(state, Feed(["", "", "/quit"]))  # two face checks: no_match, no_match
    assert offer() == "The face check is not working? Use Touch ID instead: type t and press Enter."
    first, second = out.split("  ✗ The face did not match.")[1:]
    assert offer() not in first and offer() in second
    assert second.index(offer()) < second.index(t("guard.prompt.retry", "en"))
    assert guard.unlock_methods == ["face", "face"]

    plain = FakeGuard("locked")  # no fallback configured: never offered, t is not sent
    state = make_state(config, plain)
    out = run(state, Feed(["", "", "t", "/quit"]))
    assert "Touch ID" not in out
    assert out.count(t("guard.prompt.not_sent", "en")) == 1
    assert plain.unlock_methods == ["face", "face"]


def test_t_is_not_a_touch_id_unlock_before_the_offer(config: Config) -> None:
    guard = FakeGuard("locked", verdicts=[TOUCH_ID], fallback="touch_id")
    state = make_state(config, guard)
    out = run(state, Feed(["t", "/quit"]))
    assert t("guard.prompt.not_sent", "en") in out
    assert guard.unlock_methods == [] and state.locked


def test_t_runs_the_touch_id_unlock_and_a_pass_unlocks_with_touch_id(config: Config) -> None:
    guard = FakeGuard(
        "locked", verdicts=[GuardVerdict(False, "camera_busy"), TOUCH_ID], fallback="touch_id"
    )
    model = FakeModel(["Okay."])
    state = make_state(config, guard, model=model)

    def touch_steps() -> None:
        guard.progress = list(TOUCH_STEP)

    feed = Feed(["", "t", "hello", "/quit"], hooks={2: touch_steps})
    out = run(state, feed)
    lines = out.splitlines()
    # a camera_* verdict offers the fallback at once, before "try again"
    busy = lines.index("  ✗ Another app is using the camera.")
    assert lines[busy + 1 : busy + 3] == [offer(), t("guard.prompt.retry", "en")]
    expected = [
        f"  ◉ {t('guard.fallback.confirm', 'en')}",
        "  ◉ Touch the Touch ID sensor.",
        "Unlocked (Touch ID). Failed attempts since the last unlock: 0.",
    ]
    start = lines.index(expected[0])
    assert lines[start : start + len(expected)] == expected
    assert lines[start + len(expected)].startswith("tau ready.")
    assert "tau> Okay." in out
    assert guard.unlock_methods == ["face", "touch_id"]
    assert guard.method == "touch_id" and guard.state == "unlocked"
    assert feed.prompts == ["locked> ", "locked> ", "you> ", "you> "]
    assert len(model.calls) == 1  # the unlock itself made no model call


def test_a_failed_touch_id_keeps_the_lock_and_says_why(config: Config) -> None:
    guard = FakeGuard(
        "locked",
        verdicts=[GuardVerdict(False, "camera_denied"), GuardVerdict(False, "touch_id_failed")],
        fallback="touch_id_or_password",
    )
    model = FakeModel(["Okay."])
    state = make_state(config, guard, model=model)
    feed = Feed(["", "T", "hello", "/quit"])
    out = run(state, feed)
    after = out.split(t("guard.fallback.confirm", "en"), 1)[1]
    assert "  ✗ Touch ID did not confirm you." in after
    assert offer("touch_id_or_password") in after  # still offered, printed again
    assert out.count(offer("touch_id_or_password")) == 2
    assert t("guard.prompt.not_sent", "en") in after  # "hello" was not sent
    assert guard.unlock_methods == ["face", "touch_id"]
    assert state.locked and guard.state == "locked"
    assert feed.prompts == ["locked> "] * 4
    assert model.calls == []


def test_the_offer_shows_under_the_banner_and_in_the_ui_language(config: Config) -> None:
    guard = FakeGuard("locked", fallback="touch_id")
    guard.camera_trouble = True  # the hub already offers it when the prompt starts
    state = make_state(config, guard)
    state.language = "tr"
    out = run(state, Feed(["/quit"]))
    banner = out.index(t("guard.prompt.banner", "tr"))
    assert out.index(offer(language="tr")) > banner
    assert "t yazıp Enter'a bas" in out


class HangingTouchId(FakeGuard):
    """A Touch ID prompt that never answers; Ctrl-C arrives while the sheet is up."""

    def __init__(self) -> None:
        super().__init__("locked", fallback="touch_id")
        self.camera_trouble = True
        self.cancelled = False

    async def unlock(self, **kwargs: Any) -> GuardVerdict:
        self.unlock_methods.append(kwargs.get("method", "face"))

        def interrupt() -> None:
            raise KeyboardInterrupt

        asyncio.get_running_loop().call_soon(interrupt)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("never reached")


def test_ctrl_c_cancels_a_touch_id_prompt(config: Config) -> None:
    guard = HangingTouchId()
    state = make_state(config, guard)
    feed = Feed(["t", "/quit"])
    out = run(state, feed)
    assert guard.cancelled and ("cancel", process_client_id()) in guard.calls
    assert guard.unlock_methods == ["touch_id"]
    assert "  ✗ The check was cancelled." in out
    assert feed.prompts == ["locked> ", "locked> "] and state.locked


def test_only_the_allowed_commands_run_while_locked(config: Config) -> None:
    guard = FakeGuard("locked")
    model = FakeModel(["Okay."])
    state = make_state(config, guard, model=model)
    lines = ["/sessions", "/status", "/compact", "/clear", "/resume", "/new", "hello"]
    out = run(state, Feed([*lines, "/help", "/lang tr", "/durum", "/quit"]))
    for name in ("sessions", "status", "compact", "clear", "resume", "new"):
        assert t("guard.cmd.refused", "en", command=name) in out
    assert t("guard.cmd.refused", "tr", command="status") in out  # after /lang tr, by alias
    assert t("guard.prompt.not_sent", "en") in out
    assert "  /guard [lock|unlock]" in out  # /help ran and lists only what works while locked
    assert "  /help" in out and "  /quit" in out and "  /lang en|tr" in out
    assert "  /sessions" not in out and "  /status" not in out and "  /tools" not in out
    assert "Profile:" not in out  # /status never ran
    assert model.calls == []
    assert state.language == "tr"


class LocksOnAdmit(FakeGuard):
    """The hub locks right before the turn's admission (the REPL read ``unlocked`` a moment
    earlier)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.armed = True

    async def admit(self, turn: Any) -> Any:
        if self.armed:
            self.armed = False
            self.set_state("locked", trigger="idle")
        return await super().admit(turn)


def test_a_refused_turn_returns_to_the_lock_prompt(config: Config) -> None:
    guard = LocksOnAdmit("unlocked", verdicts=[MATCH])
    model = FakeModel(["Okay."])
    state = make_state(config, guard, model=model)
    feed = Feed(["hello", "", "again", "/quit"])
    out = run(state, feed)
    assert feed.prompts == ["you> ", "locked> ", "you> ", "you> "]
    after = out.split(CLEAR_ALL, 1)[1]
    assert t("guard.prompt.banner", "en") in after
    assert f"  ℹ {t('guard.refused.locked', 'en')}" in after  # said again under the banner
    assert len(model.calls) == 1  # only "again" reached the model


def test_a_lock_while_typing_is_seen_before_a_command_runs(config: Config) -> None:
    guard = FakeGuard("unlocked")
    state = make_state(config, guard)
    feed = Feed(["/sessions", "/quit"], hooks={1: lambda: guard.set_state("locked")})
    out = run(state, feed)
    assert CLEAR_ALL in out
    assert t("guard.cmd.refused", "en", command="sessions") in out
    assert feed.prompts == ["you> ", "locked> "]


def test_the_state_is_read_again_before_every_prompt(config: Config) -> None:
    guard = FakeGuard("unlocked")
    state = make_state(config, guard)

    def flip() -> None:
        guard.set_state("locked", trigger="screen_lock")

    feed = Feed(["/help", "/help", "/quit"], hooks={1: flip})
    out = run(state, feed)
    assert feed.prompts == ["you> ", "locked> ", "locked> "]
    assert "Guard: locked · locked with the screen" in out
    assert [name for name, _ in guard.calls].count("status") >= 3


def test_another_channel_unlocking_leaves_the_lock_prompt(config: Config) -> None:
    guard = FakeGuard("locked")
    state = make_state(config, guard)
    feed = Feed(["/help", "/quit"], hooks={1: lambda: guard.set_state("unlocked")})
    out = run(state, feed)
    assert feed.prompts == ["locked> ", "you> "]
    assert "Unlocked (—). Failed attempts since the last unlock: 0." in out
    assert "tau ready." in out


def test_a_recheck_runs_the_passive_check_and_resends_the_prompt(config: Config) -> None:
    guard = FakeGuard("unlocked", verdicts=[MATCH], admissions=["recheck", True])
    model = FakeModel(["Okay."])
    state = make_state(config, guard, model=model)
    feed = Feed(["hello", "/quit"])
    out = run(state, feed)
    assert ("unlock", "recheck") in guard.calls
    assert f"  ◉ {t('guard.recheck', 'en')}" in out
    assert "tau> Okay." in out
    assert len(model.calls) == 1
    assert CLEAR_ALL not in out and feed.prompts == ["you> ", "you> "]


def test_a_failed_recheck_keeps_the_prompt_while_the_guard_says_unlocked(config: Config) -> None:
    """Like the TUI: the guard still reports ``unlocked``, so there is no lock prompt (whose
    banner would say "Guard: unlocked"); the prompt was not sent and can be sent again."""
    guard = FakeGuard("unlocked", verdicts=[GuardVerdict(False, "no_face")], admissions=["recheck"])
    model = FakeModel(["Okay."])
    state = make_state(config, guard, model=model)
    feed = Feed(["hello", "hello again", "/quit"])
    out = run(state, feed)
    assert "  ✗ No face was seen." in out
    assert t("guard.recheck_not_sent", "en") in out
    assert CLEAR_ALL not in out and not state.locked
    assert feed.prompts == ["you> ", "you> ", "you> "]
    assert len(model.calls) == 1  # only the second prompt reached the model


class LocksOnFailedRecheck(FakeGuard):
    """A recheck that fails and locks the guard (the hub's cooldown after counted failures)."""

    async def unlock(self, **kwargs: Any) -> GuardVerdict:
        verdict = await super().unlock(**kwargs)
        if not verdict.ok:
            self.set_state("locked", trigger="idle")
        return verdict


def test_a_failed_recheck_that_locks_the_guard_returns_to_the_lock_prompt(config: Config) -> None:
    guard = LocksOnFailedRecheck("unlocked", admissions=["recheck"])
    model = FakeModel(["Okay."])
    state = make_state(config, guard, model=model)
    feed = Feed(["hello", "/quit"])
    out = run(state, feed)
    assert "  ✗ The face did not match." in out
    after = out.split(CLEAR_ALL, 1)[1]
    assert "Guard: locked · locked after inactivity" in after
    assert f"  ℹ {t('guard.refused.recheck', 'en')}" in after
    assert feed.prompts == ["you> ", "locked> "]
    assert model.calls == []


def test_ctrl_c_during_a_recheck_keeps_the_prompt_unsent(config: Config) -> None:
    class HangingRecheck(FakeGuard):
        async def unlock(self, **kwargs: Any) -> GuardVerdict:
            self.calls.append(("unlock", kwargs.get("kind")))

            def interrupt() -> None:
                raise KeyboardInterrupt

            asyncio.get_running_loop().call_soon(interrupt)
            await asyncio.Event().wait()
            raise AssertionError("never reached")

    guard = HangingRecheck("unlocked", admissions=["recheck"])
    model = FakeModel(["Okay."])
    state = make_state(config, guard, model=model)
    feed = Feed(["hello", "/quit"])
    out = run(state, feed)
    assert ("cancel", process_client_id()) in guard.calls
    assert "  ✗ The check was cancelled." in out
    assert t("guard.recheck_not_sent", "en") in out
    assert feed.prompts == ["you> ", "you> "]
    assert model.calls == []


def test_step_up_challenge_steps_print_from_the_event_bus(config: Config) -> None:
    progress = [GuardProgress("look", 1, None), GuardProgress("turn_right", 2, None)]
    guard = FakeGuard("unlocked", step_ups=[True], progress=progress)
    model = FakeModel([[ToolCall("lamp", {"state": "on"})], "Lamp is on."])
    approver = ScriptedApprover([Decision.APPROVED])
    state = make_state(config, guard, model=model, approver=approver, tools=[lamp])
    out = run(state, Feed(["lamp on", "/quit"]))
    lines = out.splitlines()
    expected = [
        f"  ◉ {t('guard.step_up.start', 'en')}",
        "  ◉ Look at the camera.",
        "  ◉ Turn your head right.",
        f"  ✓ {t('guard.step_up.passed', 'en')}",
    ]
    start = lines.index(expected[0])
    assert lines[start : start + 4] == expected
    assert "tau> Lamp is on." in out


def test_a_failed_step_up_prints_the_failure(config: Config) -> None:
    guard = FakeGuard("unlocked", step_ups=[False])
    model = FakeModel([[ToolCall("lamp", {"state": "on"})], "Not done."])
    approver = ScriptedApprover([Decision.APPROVED])
    state = make_state(config, guard, model=model, approver=approver, tools=[lamp])
    out = run(state, Feed(["lamp on", "/quit"]))
    assert f"  ✗ {t('guard.step_up.failed', 'en')}" in out


# -- /guard ----------------------------------------------------------------------------------


def test_guard_without_a_guard_says_it_is_off(config: Config) -> None:
    state = make_state(config, None)
    out = run(state, Feed(["/guard", "/guard lock", "/koruma unlock", "/quit"]))
    assert out.count(t("guard.cmd.off", "en")) == 3
    assert CLEAR_ALL not in out


def test_guard_shows_the_state_locks_and_answers_unlock(config: Config) -> None:
    guard = FakeGuard("unlocked", verdicts=[MATCH])
    state = make_state(config, guard)
    feed = Feed(["/guard", "/guard unlock", "/guard nope", "/guard lock", "/guard unlock", "/quit"])
    out = run(state, feed)
    assert "Guard: unlocked" in out
    assert t("guard.cmd.already_unlocked", "en") in out
    assert t("guard.cmd.usage", "en") in out
    assert ("lock", "command") in guard.calls
    assert "Guard: locked · locked by command" in out.split(CLEAR_ALL, 1)[1]
    assert "Unlocked (face)." in out  # /guard unlock at the lock prompt is an attempt
    assert feed.prompts == ["you> ", "you> ", "you> ", "you> ", "locked> ", "you> "]


class DeafGuard(FakeGuard):
    """A guard whose lock never reaches the hub (``HubGuard`` only logs that)."""

    async def lock(self, *, channel: str, client_id: str, trigger: str = "command") -> None:
        self.calls.append(("lock", trigger))


def test_a_lock_that_did_not_take_says_so(config: Config) -> None:
    guard = DeafGuard("unlocked")
    state = make_state(config, guard)
    out = run(state, Feed(["/guard lock", "/quit"]))
    assert t("guard.cmd.lock_failed", "en") in out
    assert CLEAR_ALL not in out


def test_every_build_gets_the_same_guard(config: Config) -> None:
    guard = FakeGuard("unlocked")
    state = make_state(config, guard)
    first = state.agent
    run(state, Feed(["/new", "/model fast", "/quit"]))
    assert state.agent is not first
    assert state.agent.guard is guard and state.agent.gate.guard is guard


def test_a_guard_set_up_after_the_start_is_found_before_the_next_prompt(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    guard = FakeGuard("locked")
    found: list[Any] = [None]
    monkeypatch.setattr("tau_core.channels.terminal.resolve_guard", lambda config: found[0])
    state = make_state(config, None)

    def enroll() -> None:
        found[0] = guard

    feed = Feed(["/help", "/new", "/quit"], hooks={1: enroll})
    out = run(state, feed)
    assert state.guard is guard
    assert feed.prompts == ["you> ", "locked> ", "locked> "]
    assert t("guard.cmd.refused", "en", command="new") in out


# -- a guard that appears while the REPL runs ------------------------------------------------


@pytest.fixture
def builds_with(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[Any]]:
    """Every rebuild (``_switch_to``) gets the test's model and tools; returns the guards it
    passed to ``build_agent``."""

    def install(model: FakeModel, tools: list) -> list[Any]:
        seen: list[Any] = []

        def building(**kwargs: Any) -> Any:
            seen.append(kwargs.get("guard"))
            return build_agent(**{**kwargs, "model": model, "tools": tools})

        monkeypatch.setattr("tau_core.channels.terminal.build_agent", building)
        return seen

    return install


def test_a_guard_found_while_unlocked_rebuilds_the_agent_before_the_next_turn(
    config: Config, monkeypatch: pytest.MonkeyPatch, builds_with: Callable[..., list[Any]]
) -> None:
    """``tau guard setup`` ran in another window and left the guard unlocked: no lock prompt,
    but the next turn is admitted and its tier-2 call stepped up (a failed step-up refuses)."""
    ran: list[str] = []

    @tau_tool(tier=Tier.PHYSICAL, effect="Moves the arm.")
    def arm(direction: str) -> str:
        """Moves the arm.

        Args:
            direction: where to.
        """
        ran.append(direction)
        return f"moved {direction}"

    guard = FakeGuard("unlocked", step_ups=[False])
    found: list[Any] = [None]
    monkeypatch.setattr("tau_core.channels.terminal.resolve_guard", lambda config: found[0])
    model = FakeModel([[ToolCall("arm", {"direction": "left"})], "Not moved."])
    approver = ScriptedApprover([Decision.APPROVED])
    state = make_state(config, None, model=model, approver=approver, tools=[arm])
    session = state.agent.session_id
    seen = builds_with(model, [arm])
    feed = Feed(["move the arm", "/quit"], hooks={1: lambda: found.__setitem__(0, guard)})
    out = run(state, feed)
    assert state.agent.guard is guard and state.agent.gate.guard is guard
    assert state.agent.session_id == session and seen == [guard]  # same session, one rebuild
    assert any(name == "admit" for name, _ in guard.calls)
    assert any(name == "step_up" for name, _ in guard.calls)
    assert ran == []  # the step-up failed: the arm never moved
    assert f"  ✗ {t('guard.step_up.failed', 'en')}" in out


def test_a_guard_found_locked_rebuilds_the_agent_at_the_unlock(
    config: Config, monkeypatch: pytest.MonkeyPatch, builds_with: Callable[..., list[Any]]
) -> None:
    guard = FakeGuard("locked", verdicts=[MATCH], step_ups=[False])
    found: list[Any] = [None]
    monkeypatch.setattr("tau_core.channels.terminal.resolve_guard", lambda config: found[0])
    model = FakeModel([[ToolCall("lamp", {"state": "on"})], "Not done."])
    approver = ScriptedApprover([Decision.APPROVED])
    state = make_state(config, None, model=model, approver=approver, tools=[lamp])
    seen = builds_with(model, [lamp])
    feed = Feed(["/help", "", "lamp on", "/quit"], hooks={1: lambda: found.__setitem__(0, guard)})
    out = run(state, feed)
    assert feed.prompts == ["you> ", "locked> ", "you> ", "you> "]
    assert seen == [guard]  # rebuilt at the unlock, before the turn
    assert state.agent.guard is guard
    assert any(name == "step_up" for name, _ in guard.calls)
    assert f"  ✗ {t('guard.step_up.failed', 'en')}" in out
    assert "tau> Not done." in out


def test_a_failed_rebuild_under_a_new_guard_sends_nothing(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tau_core.models import MissingCredentials

    guard = FakeGuard("unlocked")
    found: list[Any] = [None]
    monkeypatch.setattr("tau_core.channels.terminal.resolve_guard", lambda config: found[0])

    def broken(**kwargs: Any) -> Any:
        raise MissingCredentials("brain", "fake", ["SOME_KEY"])

    monkeypatch.setattr("tau_core.channels.terminal.build_agent", broken)
    model = FakeModel(["Okay."])
    state = make_state(config, None, model=model)
    feed = Feed(["hello", "/compact", "/quit"], hooks={1: lambda: found.__setitem__(0, guard)})
    out = run(state, feed)
    assert out.count(t("guard.rearm_failed", "en")) == 2  # the turn and /compact
    assert state.agent.guard is None and model.calls == []


class FakeReadline:
    """``sys.modules["readline"]`` for the test: a list with readline's history calls."""

    def __init__(self, items: list[str]) -> None:
        self.items = list(items)

    def get_current_history_length(self) -> int:
        return len(self.items)

    def get_history_item(self, index: int) -> str | None:
        return self.items[index - 1] if 1 <= index <= len(self.items) else None

    def clear_history(self) -> None:
        self.items.clear()

    def add_history(self, line: str) -> None:
        self.items.append(line)


def test_the_lock_prompt_hides_the_line_history_until_the_unlock(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    readline = FakeReadline(["my secret plan", "/sessions"])
    monkeypatch.setitem(sys.modules, "readline", readline)
    guard = FakeGuard("unlocked", verdicts=[MATCH])
    state = make_state(config, guard)
    seen: list[list[str]] = []

    def at_lock_prompt() -> None:
        seen.append(list(readline.items))  # what the Up arrow could recall at locked>
        readline.add_history("/help")  # input() records what is typed at the lock prompt

    feed = Feed(["/guard lock", "/help", "", "/quit"], hooks={2: at_lock_prompt})
    run(state, feed)
    assert feed.prompts == ["you> ", "locked> ", "locked> ", "you> "]
    assert seen == [[]]
    assert readline.items == ["my secret plan", "/sessions"]  # back after the unlock
    assert state.hidden_history is None


class OldReadline:
    """A readline build without ``clear_history``: items are removed one by one."""

    def __init__(self, items: list[str]) -> None:
        self.items = list(items)

    def get_current_history_length(self) -> int:
        return len(self.items)

    def get_history_item(self, index: int) -> str | None:
        return self.items[index - 1] if 1 <= index <= len(self.items) else None

    def remove_history_item(self, position: int) -> None:
        del self.items[position]

    def add_history(self, line: str) -> None:
        self.items.append(line)


def test_the_line_history_is_hidden_without_clear_history(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    readline = OldReadline(["first", "second"])
    monkeypatch.setitem(sys.modules, "readline", readline)
    guard = FakeGuard("locked", verdicts=[MATCH])
    state = make_state(config, guard)
    seen: list[list[str]] = []
    run(state, Feed(["", "/quit"], hooks={1: lambda: seen.append(list(readline.items))}))
    assert seen == [[]] and readline.items == ["first", "second"]
