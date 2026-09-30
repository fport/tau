"""Touch ID in the hub (issue 114, ADR 0008 decision 15): the state machine's fallback offer,
the Touch ID unlock and recheck, the step-up modes, the service's choice of worker, and the
tier gate. Workers are the scripted fake; nothing shows a prompt or opens a camera."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from guard_helpers import TURN, guard_config, running_hub, until_async
from tau_core import Admission, GuardVerdict, HubGuard, Tier
from tau_core.approval import ApprovalRequest, Decision, TierGate
from tau_core.events import EventBus
from tau_core.hub import HubError
from tau_core.i18n import t
from tau_core.testing import ScriptedApprover
from tau_guard import worker
from tau_guard.audit import AuditLog
from tau_guard.state import (
    FAILURE_WINDOW,
    GuardMachine,
    Limits,
    Outcome,
    Reading,
    Refusal,
)
from tau_guard.testing import (
    FINGERPRINTS,
    FakeClock,
    FakeLocalAuth,
    fake_deps,
    match,
    read_requests,
)

PRESENT = Reading(idle_seconds=0.0, screen_locked=False)
MATCH = Outcome(True, "match", "face", 0.71, "challenge")
NO_FACE = Outcome(False, "no_face")
NO_MATCH = Outcome(False, "no_match", score=0.2)
TOUCH_ID = Outcome(True, "match", "touch_id", local_auth=("biometrics", "ok", 900))
TOUCH_ID_FAILED = Outcome(False, "touch_id_failed", local_auth=("biometrics", "failed", 1200))
REQUEST = ApprovalRequest("r1", "lamp", Tier.PHYSICAL, {"state": "on"}, "", "s1", "tui")


def machine(clock: FakeClock, **limits: Any) -> GuardMachine:
    m = GuardMachine(clock, Limits(**limits))
    m.observe(PRESENT, tick=True)
    m.drain()
    return m


def attempt(m: GuardMachine, kind: str = "unlock", **kwargs: Any) -> Any:
    result = m.request(kind, channel="tui", client_id=kwargs.pop("client_id", "c1"), **kwargs)
    assert not isinstance(result, Refusal), result
    return result


def fail_face(m: GuardMachine, outcome: Outcome = NO_FACE, times: int = 2) -> None:
    for _ in range(times):
        assert m.finish(attempt(m).id, outcome)


def touch_unlock(m: GuardMachine, outcome: Outcome = TOUCH_ID) -> dict:
    touch = attempt(m, method="touch_id")
    assert touch.factor == "touch_id"
    assert m.finish(touch.id, outcome)
    record = m.record(touch.id)
    assert record is not None
    return record


def audit(m: GuardMachine) -> list[dict]:
    return m.drain().audit


# -- the offer -----------------------------------------------------------------------------------


def test_the_fallback_is_offered_after_two_failed_face_unlocks(clock: FakeClock) -> None:
    m = machine(clock)
    assert m.fallback_offer() is None and m.snapshot()["fallback"] is None
    assert m.request("unlock", channel="tui", client_id="c1", method="touch_id") == Refusal(
        "touch_id_unavailable"
    )
    fail_face(m, times=1)
    assert m.fallback_offer() is None
    seq = m.seq
    fail_face(m, Outcome(False, "too_dark"), times=1)
    assert m.fallback_offer() == "touch_id" and m.snapshot()["fallback"] == "touch_id"
    assert m.seq > seq


@pytest.mark.parametrize("reason", ["camera_busy", "camera_unavailable", "camera_denied"])
def test_a_camera_verdict_offers_the_fallback_at_once(clock: FakeClock, reason: str) -> None:
    m = machine(clock, unlock_fallback="touch_id_or_password")
    fail_face(m, Outcome(False, reason), times=1)
    assert m.fallback_offer() == "touch_id_or_password"


def test_cancels_refusals_and_touch_id_failures_do_not_count(clock: FakeClock) -> None:
    m = machine(clock)
    first = attempt(m)
    m.cancel("c1", first.id)  # a cancel before any prompt
    fail_face(m, Outcome(False, "error"), times=3)
    assert m.fallback_offer() is None


def test_the_offer_ends_with_the_window_and_while_something_runs(clock: FakeClock) -> None:
    m = machine(clock)
    fail_face(m)
    assert m.fallback_offer() == "touch_id"
    running = attempt(m)  # a third face unlock runs: nothing to offer while verifying
    assert m.state == "verifying" and m.fallback_offer() is None
    m.cancel("c1", running.id)
    assert m.fallback_offer() == "touch_id"
    seq = m.seq
    clock.advance(FAILURE_WINDOW + 1)
    m.observe(PRESENT, tick=True)
    assert m.fallback_offer() is None and m.seq > seq  # the change is a status change


def test_unlock_fallback_none_never_offers(clock: FakeClock) -> None:
    m = machine(clock, unlock_fallback="none")
    fail_face(m, Outcome(False, "camera_denied"), times=3)
    assert m.fallback_offer() is None
    assert m.request("unlock", channel="tui", client_id="c1", method="touch_id") == Refusal(
        "touch_id_unavailable"
    )


def test_only_an_unlock_may_ask_for_touch_id(clock: FakeClock) -> None:
    m = machine(clock)
    fail_face(m)
    for kind in ("recheck", "step_up", "enroll"):
        assert m.request(kind, channel="tui", client_id="c1", method="touch_id") == Refusal("error")
    assert m.request("unlock", channel="tui", client_id="c1", method="password") == Refusal("error")
    m.observe(Reading(idle_seconds=0.0, screen_locked=True))
    assert m.request("unlock", channel="tui", client_id="c1", method="touch_id") == Refusal(
        "locked"
    )  # no prompt on a locked Mac


# -- the Touch ID unlock -------------------------------------------------------------------------


def test_a_passing_fallback_unlocks_with_method_touch_id(clock: FakeClock) -> None:
    m = machine(clock)
    fail_face(m)
    audit(m)
    touch = attempt(m, method="touch_id")
    assert m.state == "verifying" and m.drain().spawn == [touch]
    assert m.finish(touch.id, TOUCH_ID)
    snapshot = m.snapshot()
    assert (snapshot["state"], snapshot["method"], snapshot["fallback"]) == (
        "unlocked",
        "touch_id",
        None,
    )
    assert snapshot["face_seen_at"] is None  # Touch ID is not a face
    assert m.admission(enrolled=True) == (True, "ok")  # but it is presence: no recheck yet
    assert m.face_fresh(3600) is False  # voice still needs a face
    records = audit(m)
    [touch_record] = [r for r in records if r["event"] == "touch_id"]
    assert touch_record["policy"] == "biometrics" and touch_record["reason"] == "ok"
    assert touch_record["ok"] is True and touch_record["trigger"] == "unlock"
    assert touch_record["duration_ms"] == 900
    [verify] = [r for r in records if r["event"] == "verify"]
    assert verify["ok"] is True and verify["method"] == "touch_id"
    [unlock] = [r for r in records if r["event"] == "unlock"]
    assert unlock["method"] == "touch_id"
    m.lock("command")
    assert m.fallback_offer() is None  # the unlock cleared the offer


def test_a_failed_fallback_counts_nothing_and_stays_offered(clock: FakeClock) -> None:
    m = machine(clock)
    fail_face(m)
    failures = m.failures
    record = touch_unlock(m, TOUCH_ID_FAILED)
    assert (record["ok"], record["reason"]) == (False, "touch_id_failed")
    assert m.state == "locked" and m.failures == failures and m.cooldown_left() is None
    assert m.fallback_offer() == "touch_id"
    [verify] = [r for r in audit(m) if r["event"] == "verify" and r["ok"] is False][-1:]
    assert verify["method"] == "touch_id"


def test_touch_id_lifts_a_face_cooldown(clock: FakeClock) -> None:
    m = machine(clock)
    fail_face(m, NO_MATCH, times=3)  # counted: a cooldown starts
    assert m.cooldown_left() is not None
    assert isinstance(m.request("unlock", channel="tui", client_id="c1"), Refusal)
    record = touch_unlock(m)  # Touch ID has its own rate limit in macOS
    assert record["ok"] is True and m.state == "unlocked"
    assert m.cooldown_left() is None and m.snapshot()["cooldown_until"] is None
    assert not isinstance(m.request("step_up", channel="tui", client_id="c1"), Refusal)


def test_a_face_success_for_a_touch_id_attempt_is_an_error(clock: FakeClock) -> None:
    m = machine(clock)
    fail_face(m)
    record = touch_unlock(m, MATCH)
    assert (record["ok"], record["reason"]) == (False, "error") and m.state == "locked"


def test_a_lock_during_the_touch_id_prompt_cancels_it_without_counting(clock: FakeClock) -> None:
    m = machine(clock)
    fail_face(m)
    touch = attempt(m, method="touch_id")
    m.progress(touch.id, step="touch_id", hint=None, deadline=None)
    m.lock("command")
    record = m.record(touch.id)
    assert record is not None and record["reason"] == "cancelled"
    assert m.drain().kill == [(touch.id, "cancelled")]


def test_touch_id_unlocks_join_each_other_but_never_a_face_attempt(clock: FakeClock) -> None:
    m = machine(clock)
    fail_face(m)
    touch = attempt(m, method="touch_id")
    joined = attempt(m, method="touch_id", client_id="c2")
    assert joined is touch and touch.clients == {"c1", "c2"}
    face = attempt(m, client_id="c3")
    assert face is not touch and face in m.queue


PASSWORD = Outcome(True, "match", "touch_id", local_auth=("device_owner", "ok", 700))


def test_a_client_whose_unlock_fallback_is_none_gets_no_touch_id(clock: FakeClock) -> None:
    m = machine(clock)
    fail_face(m)
    assert m.fallback_offer() == "touch_id"  # the hub offers it
    m.drain()
    refused = m.request(
        "unlock",
        channel="tui",
        client_id="c1",
        method="touch_id",
        policy={"unlock_fallback": "none"},
    )
    assert refused == Refusal("touch_id_unavailable") and m.drain().spawn == []


@pytest.mark.parametrize(
    ("hub", "client", "outcome", "ok"),
    [
        ("touch_id", None, PASSWORD, False),  # Touch ID only: a password success is an error
        ("touch_id_or_password", None, PASSWORD, True),
        ("touch_id_or_password", "touch_id", PASSWORD, False),  # the client refuses the password
        ("touch_id_or_password", "touch_id", TOUCH_ID, True),
    ],
)
def test_a_touch_id_unlock_through_the_password_needs_the_opt_in(
    clock: FakeClock, hub: str, client: str | None, outcome: Outcome, ok: bool
) -> None:
    m = machine(clock, unlock_fallback=hub)
    fail_face(m)
    policy = {"unlock_fallback": client} if client else {}
    touch = attempt(m, method="touch_id", policy=policy)
    assert m.finish(touch.id, outcome)
    record = m.record(touch.id)
    assert record is not None
    assert (record["ok"], record["reason"]) == ((True, "match") if ok else (False, "error"))


@pytest.mark.parametrize("mode", ["touch_id", "face_or_touch_id"])
def test_a_touch_id_step_up_through_the_password_is_an_error(clock: FakeClock, mode: str) -> None:
    m = unlocked(clock)
    step_up = attempt(m, "step_up", policy={"step_up": mode})
    assert m.finish(step_up.id, PASSWORD)
    record = m.record(step_up.id)
    assert record is not None and (record["ok"], record["reason"]) == (False, "error")


def test_touch_id_only_never_joins_an_unlock_that_takes_the_password(clock: FakeClock) -> None:
    m = machine(clock, unlock_fallback="touch_id_or_password")
    fail_face(m)
    loose = attempt(m, method="touch_id", policy={"unlock_fallback": "touch_id_or_password"})
    strict = attempt(m, method="touch_id", client_id="c2", policy={"unlock_fallback": "touch_id"})
    assert strict is not loose and strict in m.queue
    again = attempt(m, method="touch_id", client_id="c3", policy={"unlock_fallback": "touch_id"})
    assert again is strict  # two Touch ID only requests share one prompt


def test_a_client_without_touch_id_rechecks_a_touch_id_session_with_the_face(
    clock: FakeClock,
) -> None:
    m = machine(clock, recheck_after_idle=180.0)
    fail_face(m)
    touch_unlock(m)
    clock.advance(200)
    m.observe(Reading(idle_seconds=200.0, screen_locked=False), tick=True)
    assert attempt(m, "recheck", policy={"unlock_fallback": "none"}).factor == "face"


# -- presence after a Touch ID unlock ------------------------------------------------------------


def test_a_touch_id_session_rechecks_with_touch_id(clock: FakeClock) -> None:
    m = machine(clock, recheck_after_idle=180.0)
    fail_face(m)
    touch_unlock(m)
    clock.advance(200)
    m.observe(Reading(idle_seconds=200.0, screen_locked=False), tick=True)
    assert m.admission(enrolled=True) == (False, "recheck")
    recheck = attempt(m, "recheck")
    assert recheck.factor == "touch_id"
    assert m.finish(
        recheck.id, Outcome(True, "match", "touch_id", local_auth=("biometrics", "ok", 1))
    )
    m.observe(PRESENT)
    assert m.admission(enrolled=True) == (True, "ok")


def test_a_face_session_rechecks_the_face(clock: FakeClock) -> None:
    m = machine(clock)
    assert m.finish(attempt(m).id, MATCH)
    assert attempt(m, "recheck").factor == "face"


# -- step-up modes -------------------------------------------------------------------------------


def unlocked(clock: FakeClock, **limits: Any) -> GuardMachine:
    m = machine(clock, **limits)
    assert m.finish(attempt(m).id, MATCH)
    m.drain()
    return m


@pytest.mark.parametrize(
    ("mode", "factor"), [("face", "face"), ("face_or_touch_id", "face"), ("touch_id", "touch_id")]
)
def test_the_step_up_runs_the_factor_of_its_mode(clock: FakeClock, mode: str, factor: str) -> None:
    m = unlocked(clock)
    step_up = attempt(m, "step_up", policy={"step_up": mode})
    assert step_up.factor == factor and m.drain().spawn == [step_up]


def test_face_or_touch_id_accepts_the_touch_id_half(clock: FakeClock) -> None:
    m = unlocked(clock)
    step_up = attempt(m, "step_up", policy={"step_up": "face_or_touch_id"})
    assert m.finish(step_up.id, TOUCH_ID)
    record = m.record(step_up.id)
    assert record is not None and (record["ok"], record["method"]) == (True, "touch_id")


def test_step_up_none_runs_no_check_and_needs_an_unlock(clock: FakeClock) -> None:
    m = unlocked(clock)
    step_up = attempt(m, "step_up", policy={"step_up": "none"})
    assert step_up.done and step_up.ok is True and step_up.method is None
    record = m.record(step_up.id)
    assert record is not None and (record["reason"], record["method"]) == ("match", None)
    effects = m.drain()
    assert effects.spawn == []
    assert [(r["event"], r["reason"]) for r in effects.audit] == [("step_up", "none")]
    assert m.face_seen_at is not None and m.step_up_active is False
    m.lock("command")
    assert m.request(
        "step_up", channel="tui", client_id="c1", policy={"step_up": "none"}
    ) == Refusal("locked")


@pytest.mark.parametrize("answer", ["failed", "changed"])
@pytest.mark.parametrize(
    ("kind", "policy"),
    [("step_up", {"step_up": "touch_id"}), ("step_up", {"step_up": "face_or_touch_id"})],
)
def test_a_refused_finger_in_a_step_up_locks_without_counting(
    clock: FakeClock, answer: str, kind: str, policy: dict
) -> None:
    m = unlocked(clock)
    step_up = attempt(m, kind, policy=policy)
    refused = Outcome(False, "touch_id_failed", local_auth=("biometrics", answer, 900))
    assert m.finish(step_up.id, refused)
    assert (m.state, m.lock_trigger) == ("locked", "step_up_failed")
    assert m.failures == 0 and m.cooldown_left() is None


def test_a_refused_finger_in_a_touch_id_recheck_locks(clock: FakeClock) -> None:
    m = machine(clock, recheck_after_idle=180.0)
    fail_face(m)
    touch_unlock(m)
    clock.advance(200)
    m.observe(Reading(idle_seconds=200.0, screen_locked=False), tick=True)
    recheck = attempt(m, "recheck")
    assert m.finish(recheck.id, TOUCH_ID_FAILED)
    assert (m.state, m.lock_trigger) == ("locked", "step_up_failed") and m.failures == 0


@pytest.mark.parametrize("answer", ["cancelled", "timeout", "unavailable"])
def test_a_touch_id_prompt_that_did_not_run_its_course_never_locks(
    clock: FakeClock, answer: str
) -> None:
    m = unlocked(clock)
    step_up = attempt(m, "step_up", policy={"step_up": "touch_id"})
    reason = "touch_id_unavailable" if answer == "unavailable" else "touch_id_failed"
    assert m.finish(step_up.id, Outcome(False, reason, local_auth=("biometrics", answer, 5)))
    assert m.state == "unlocked"


def test_a_worker_success_for_a_none_step_up_is_impossible(clock: FakeClock) -> None:
    m = unlocked(clock)
    step_up = attempt(m, "step_up", policy={"step_up": "touch_id"})
    step_up.policy["step_up"] = "none"  # as if the policy changed under a running attempt
    assert m.finish(step_up.id, TOUCH_ID)
    record = m.record(step_up.id)
    assert record is not None and (record["ok"], record["reason"]) == (False, "error")


# -- the service: which worker, which prompt text --------------------------------------------------


TOUCH_MATCH = {
    "verdict": {
        "ok": True,
        "reason": "match",
        "method": "touch_id",
        "local_auth": {"policy": "biometrics", "outcome": "ok", "ms": 800},
    }
}
NO_FACE_RUN = [{"progress": "look"}, {"verdict": {"ok": False, "reason": "no_face"}}]


async def test_the_touch_id_fallback_through_the_hub(tmp_path: Path) -> None:
    runs = [NO_FACE_RUN, NO_FACE_RUN, [{"progress": "touch_id"}, {"sleep": 0.3}, TOUCH_MATCH]]
    with running_hub(tmp_path, runs=runs) as running:
        guard = running.guard
        for _ in range(2):
            assert (await guard.unlock(channel="tui", client_id="c1")).reason == "no_face"
        status = await guard.status()
        assert status.state == "locked" and status.fallback == "touch_id"
        steps: list[str] = []
        verdict = await guard.unlock(
            channel="tui",
            client_id="c1",
            method="touch_id",
            on_progress=lambda p: steps.append(p.step),
        )
        assert verdict == GuardVerdict(True, "match", "touch_id")
        assert "touch_id" in steps
        status = await guard.status()
        assert (status.state, status.method, status.fallback) == ("unlocked", "touch_id", None)
        assert status.face_seen_at is None
        assert (await guard.admit(TURN)).allowed is True
        requests = read_requests(running.script)
        assert [r["op"] for r in requests] == ["verify", "verify", "touch_id"]
        touch = requests[-1]["request"]
        assert touch["kind"] == "unlock" and touch["settings"]["unlock_fallback"] == "touch_id"
        assert touch["reason_text"] == t("guard.cli.la.unlock", running.config.ui.language)
        entries = AuditLog(running.config.data_dir / "guard").read()
        assert any(e["event"] == "touch_id" and e["ok"] is True for e in entries)
        assert any(e["event"] == "unlock" and e.get("method") == "touch_id" for e in entries)


async def test_a_touch_id_unlock_that_is_not_offered_is_refused(tmp_path: Path) -> None:
    with running_hub(tmp_path) as running:
        body = {"channel": "tui", "client_id": "c1", "kind": "unlock", "fallback": "touch_id"}
        with pytest.raises(HubError) as caught:
            running.client.post("/guard/verify", body, timeout=10)
        assert (caught.value.status, caught.value.payload["reason"]) == (
            409,
            "touch_id_unavailable",
        )
        verdict = await running.guard.unlock(channel="tui", client_id="c1", method="touch_id")
        assert verdict == GuardVerdict(False, "touch_id_unavailable")
        assert read_requests(running.script) == []  # no worker, no prompt
        for bad in ({**body, "fallback": "face"}, {**body, "fallback": True}):
            with pytest.raises(HubError) as caught:
                running.client.post("/guard/verify", bad, timeout=10)
            assert caught.value.status == 400


async def test_a_touch_id_session_rechecks_through_the_touch_id_op(tmp_path: Path) -> None:
    runs = [NO_FACE_RUN, NO_FACE_RUN, [TOUCH_MATCH], [TOUCH_MATCH]]
    with running_hub(tmp_path, runs=runs) as running:
        guard = running.guard
        for _ in range(2):
            await guard.unlock(channel="tui", client_id="c1")
        assert (await guard.unlock(channel="tui", client_id="c1", method="touch_id")).ok
        running.presence.idle_seconds = 200.0  # past recheck_after_idle_minutes
        await asyncio.to_thread(running.advance, 200.0)
        assert await guard.admit(TURN) == Admission(False, "recheck")
        running.presence.idle_seconds = 0.0
        verdict = await guard.unlock(channel="tui", client_id="c1", kind="recheck")
        assert verdict == GuardVerdict(True, "match", "touch_id")
        last = read_requests(running.script)[-1]
        assert last["op"] == "touch_id" and last["request"]["kind"] == "recheck"
        assert last["request"]["reason_text"] == t("guard.cli.la.recheck")


@pytest.mark.parametrize(
    ("hub", "client", "op"),
    [
        ("touch_id", "face", "touch_id"),
        ("face", "touch_id", "verify"),  # same rank: the hub's value stays
        ("face_or_touch_id", "face", "verify"),
        ("none", "face", "verify"),  # the client is stricter
        ("face", "none", "verify"),  # the hub is stricter
        ("none", "none", None),  # both say none: no check at all
    ],
)
async def test_the_step_up_mode_is_the_stricter_of_hub_and_client(
    tmp_path: Path, hub: str, client: str, op: str | None
) -> None:
    config = guard_config(tmp_path, step_up=hub)
    touch = [{"progress": "touch_id"}, {"sleep": 0.3}, TOUCH_MATCH]
    second = touch if op == "touch_id" else [match()]
    with running_hub(tmp_path, config=config, runs=[[match()], second]) as running:
        guard = running.guard
        assert (await guard.unlock(channel="tui", client_id="c1")).ok
        guard.policy = {"step_up": client, "unlock_liveness": "challenge"}  # the client's toml
        steps: list[str] = []
        passed = await guard.step_up(
            REQUEST, client_id="c1", on_progress=lambda p: steps.append(p.step)
        )
        assert passed is True
        requests = read_requests(running.script)
        if op is None:
            assert len(requests) == 1  # only the unlock: nothing ran for the step-up
            return
        assert requests[-1]["op"] == op and requests[-1]["request"]["kind"] == "step_up"
        if op == "touch_id":
            text = t("guard.cli.la.step_up", tool="lamp")
            assert requests[-1]["request"]["reason_text"] == text
            assert "touch_id" in steps


@pytest.mark.parametrize(
    "client",
    [
        {"enabled": True},  # the client's tau.toml leaves step_up out: its default is face
        {"enabled": True, "step_up": "bogus"},  # an unknown value is the default too
    ],
)
async def test_a_client_that_leaves_step_up_out_never_agrees_to_none(
    tmp_path: Path, client: dict[str, Any]
) -> None:
    config = guard_config(tmp_path, step_up="none")
    with running_hub(tmp_path, config=config, runs=[[match()], [match()]]) as running:
        mine = running.config.with_overrides(component_tables={"guard": client})
        guard = HubGuard(mine)
        assert guard.policy["step_up"] == "face"
        assert (await guard.unlock(channel="tui", client_id="c1")).ok
        assert await guard.step_up(REQUEST, client_id="c1") is True
        requests = read_requests(running.script)
        assert [r["op"] for r in requests] == ["verify", "verify"]  # the step-up ran a check
        assert requests[-1]["request"]["policy"]["step_up"] == "face"


@pytest.mark.parametrize(
    ("policy", "liveness"),
    [
        ({}, "challenge"),
        ({"unlock_liveness": "none"}, "none"),  # both say none; step_up is still left out
        (None, "challenge"),
        ("absent", "challenge"),
    ],
)
async def test_a_route_caller_without_a_policy_gets_the_client_defaults(
    tmp_path: Path, policy: Any, liveness: str
) -> None:
    config = guard_config(tmp_path, step_up="none", unlock_liveness="none")
    with running_hub(tmp_path, config=config, runs=[[match()], [match()]]) as running:
        guard = running.guard  # the hub's own tau.toml: none and none
        assert (await guard.unlock(channel="tui", client_id="c1")).ok
        body: dict[str, Any] = {"channel": "tui", "client_id": "c2", "kind": "step_up"}
        if policy != "absent":
            body["policy"] = policy
        started = running.client.post("/guard/verify", body, timeout=10)
        await until_async(lambda: len(read_requests(running.script)) == 2)
        attempt = running.service.machine.attempt(started["attempt"])
        assert attempt is not None and attempt.policy["step_up"] == "face"
        assert attempt.policy["unlock_liveness"] == liveness


async def test_the_touch_id_worker_gets_the_stricter_unlock_fallback(tmp_path: Path) -> None:
    config = guard_config(tmp_path, unlock_fallback="touch_id_or_password")
    runs = [NO_FACE_RUN, NO_FACE_RUN, [TOUCH_MATCH]]
    with running_hub(tmp_path, config=config, runs=runs) as running:
        mine = running.config.with_overrides(component_tables={"guard": {"enabled": True}})
        guard = HubGuard(mine)  # the client's tau.toml leaves unlock_fallback at touch_id
        for _ in range(2):
            await guard.unlock(channel="tui", client_id="c1")
        assert (await guard.unlock(channel="tui", client_id="c1", method="touch_id")).ok
        touch = read_requests(running.script)[-1]["request"]
        assert touch["policy"]["unlock_fallback"] == "touch_id"  # Touch ID only, no password
        assert touch["settings"]["unlock_fallback"] == "touch_id_or_password"


async def test_an_in_hub_caller_follows_the_hubs_policy_alone(tmp_path: Path) -> None:
    config = guard_config(tmp_path, step_up="none")
    with running_hub(tmp_path, config=config, runs=[[match()]]) as running:
        service = running.service  # the hub's own channels: no configuration of their own
        assert (await service.unlock(channel="telegram", client_id="hub")).ok
        assert await service.step_up(REQUEST, client_id="hub") is True
        assert len(read_requests(running.script)) == 1  # the step-up spawned nothing


async def test_a_face_or_touch_id_worker_gets_time_for_the_prompt(tmp_path: Path) -> None:
    config = guard_config(tmp_path, step_up="face_or_touch_id")
    runs = [[match()], [{"hang": True}]]
    with running_hub(tmp_path, config=config, runs=runs, attempt_timeout=10.0) as running:
        guard = running.guard
        assert (await guard.unlock(channel="tui", client_id="c1")).ok
        task = asyncio.create_task(guard.step_up(REQUEST, client_id="c1"))
        await until_async(lambda: len(read_requests(running.script)) == 2)
        run = running.service._all_runs[-1]
        assert run.op == "verify" and run.timeout == 10.0 + 30.0
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# -- the tier gate: Touch ID never approves --------------------------------------------------------


class FactorGuard:
    """A guard whose step-up is the worker's real ``touch_id`` op with a passing fake factor."""

    name = "factor"

    def __init__(self, data_dir: Path, keys: Any) -> None:
        self.data_dir = data_dir
        self.keys = keys
        self.auth = FakeLocalAuth("ok")
        self.step_ups = 0

    async def admit(self, turn: Any) -> Admission:
        return Admission(True)

    async def step_up(self, request: ApprovalRequest, *, client_id: str, on_progress=None) -> bool:
        self.step_ups += 1
        answer = worker.run(
            "touch_id",
            {
                "v": 1,
                "kind": "step_up",
                "data_dir": str(self.data_dir),
                "policy": {"step_up": "touch_id"},
                "reason_text": "run lamp",
            },
            deps=fake_deps(local_auth=self.auth, keys=self.keys),
        )
        return answer.get("ok") is True


def enrolled_factor(tmp_path: Path) -> FactorGuard:
    from tau_guard.liveness import Calibration
    from tau_guard.store import MemoryKeyStore, new_key, save_enrollment, template_from
    from tau_guard.testing import OWNER

    data_dir = tmp_path / "data"
    keys = MemoryKeyStore(new_key())
    template = template_from(
        [OWNER],
        enrollment="E1",
        created="2026-09-30T12:00:00+00:00",
        model_sha="0" * 64,
        calibration=Calibration(1, 0.4, 0.4),
        domain_state=FINGERPRINTS,
    )
    save_enrollment(data_dir / "guard", template, keys.key)  # type: ignore[arg-type]
    return FactorGuard(data_dir, keys)


def gate_for(guard: Any, *decisions: Decision) -> tuple[TierGate, ScriptedApprover, list]:
    from tau_core.tiers import ToolCatalog, tau_tool

    @tau_tool(tier=Tier.PHYSICAL, effect="switches the lamp")
    def lamp(state: str) -> str:
        """Switch the lamp."""
        return state

    events: list = []
    bus = EventBus()
    bus.subscribe(events.append)
    approver = ScriptedApprover(decisions)
    gate = TierGate(ToolCatalog([lamp]), approver, bus, session_id="s1", channel="tui", guard=guard)
    return gate, approver, events


@pytest.mark.parametrize("decision", [Decision.REJECTED, Decision.TIMEOUT])
async def test_a_passing_touch_id_never_turns_a_refusal_into_an_approval(
    tmp_path: Path, decision: Decision
) -> None:
    guard = enrolled_factor(tmp_path)
    gate, approver, _ = gate_for(guard, decision)
    allowed, _, approval = await gate.check("lamp", {"state": "on"}, tool_use_id="t1")
    assert allowed is False and approval == decision.value
    assert guard.step_ups == 0 and guard.auth.calls == []  # the factor was never asked


async def test_an_unanswered_approval_never_reaches_touch_id(tmp_path: Path) -> None:
    guard = enrolled_factor(tmp_path)

    class Silent:
        name = "silent"
        timeout_seconds = 0.05

        async def decide(self, request: ApprovalRequest) -> Decision:
            await asyncio.sleep(10)
            return Decision.APPROVED

    gate, _, _ = gate_for(guard)
    gate.approver = Silent()
    allowed, _, approval = await gate.check("lamp", {"state": "on"}, tool_use_id="t1")
    assert allowed is False and approval == "timeout" and guard.step_ups == 0


async def test_touch_id_only_ever_follows_a_human_approval(tmp_path: Path) -> None:
    guard = enrolled_factor(tmp_path)
    gate, approver, _ = gate_for(guard, Decision.APPROVED)
    allowed, _, approval = await gate.check("lamp", {"state": "on"}, tool_use_id="t1")
    assert allowed is True and approval == "approved" and len(approver.requests) == 1
    assert guard.step_ups == 1 and guard.auth.calls == [("biometrics", "run lamp")]
    guard.auth = FakeLocalAuth("failed")
    gate, _, _ = gate_for(guard, Decision.APPROVED)
    allowed, _, approval = await gate.check("lamp", {"state": "on"}, tool_use_id="t2")
    assert allowed is False and approval == "rejected"  # a failed Touch ID narrows
