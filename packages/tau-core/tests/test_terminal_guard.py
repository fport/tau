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
    assert "  /guard [lock|unlock]" in out  # /help ran
    assert "Profile:" not in out  # /status never ran
    assert model.calls == []
    assert state.language == "tr"


def test_a_refused_turn_returns_to_the_lock_prompt(config: Config) -> None:
    guard = FakeGuard("unlocked", verdicts=[MATCH], admissions=["locked"])
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


def test_a_failed_recheck_returns_to_the_lock_prompt(config: Config) -> None:
    guard = FakeGuard("unlocked", verdicts=[GuardVerdict(False, "no_face")], admissions=["recheck"])
    model = FakeModel(["Okay."])
    state = make_state(config, guard, model=model)
    feed = Feed(["hello", "/quit"])
    out = run(state, feed)
    assert "  ✗ No face was seen." in out
    assert feed.prompts == ["you> ", "locked> "]
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
