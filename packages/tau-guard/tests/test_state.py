"""The pure state machine (``tau_guard.state``) with a fake clock: every row of ADR 0008's
decision 9 table, the reflex locks of decision 10 and the cooldown of decision 13."""

from __future__ import annotations

import pytest
from tau_guard.state import (
    COOLDOWN_MAX,
    GuardMachine,
    Limits,
    Outcome,
    Reading,
    Refusal,
)
from tau_guard.testing import FakeClock

MATCH = Outcome(True, "match", "face", 0.71, "challenge")
NO_MATCH = Outcome(False, "no_match", score=0.21)
PRESENT = Reading(idle_seconds=0.0, screen_locked=False)


def machine(clock: FakeClock, **limits: float) -> GuardMachine:
    m = GuardMachine(clock, Limits(**limits))
    m.observe(PRESENT, tick=True)
    m.drain()
    return m


def unlocked(clock: FakeClock, **limits: float) -> GuardMachine:
    m = machine(clock, **limits)
    attempt = m.request("unlock", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    assert m.finish(attempt.id, MATCH)
    m.drain()
    assert m.state == "unlocked"
    return m


def events(m: GuardMachine) -> list[tuple[str, object]]:
    return [(e["event"], e.get("trigger") or e.get("reason")) for e in m.drain().audit]


# -- decision 9: the table -----------------------------------------------------------------------


def test_start_is_locked_with_trigger_startup(clock: FakeClock) -> None:
    m = GuardMachine(clock)
    assert (m.state, m.lock_trigger) == ("locked", "startup")
    assert m.since is None and m.expires_at is None and m.face_seen_at is None
    assert events(m) == [("lock", "startup")]


def test_unlock_request_from_locked_starts_verifying_and_spawns_one_worker(
    clock: FakeClock,
) -> None:
    m = machine(clock)
    seq = m.seq
    attempt = m.request("unlock", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    assert m.state == "verifying" and m.running is attempt and m.seq > seq
    effects = m.drain()
    assert [a.id for a in effects.spawn] == [attempt.id]
    assert attempt.record() == {
        "id": attempt.id,
        "kind": "unlock",
        "step": "starting",
        "seq": attempt.seq,
        "deadline": None,
        "hint": None,
        "done": False,
        "ok": None,
        "reason": None,
        "method": None,
        "retry_after": None,
    }


def test_unlock_request_from_unlocked_runs_while_staying_unlocked(clock: FakeClock) -> None:
    m = unlocked(clock)
    since = m.since
    clock.advance(60)
    attempt = m.request("unlock", channel="chat", client_id="c2")
    assert not isinstance(attempt, Refusal)
    assert m.running is attempt and m.state == "unlocked"  # other channels keep working
    assert m.finish(attempt.id, MATCH)
    assert m.state == "unlocked" and m.since is not None and since is not None
    assert m.since > since  # a re-unlock refreshes since and expires_at


def test_concurrent_unlocks_share_one_attempt_and_one_verdict(clock: FakeClock) -> None:
    m = machine(clock)
    first = m.request("unlock", channel="tui", client_id="c1")
    second = m.request("unlock", channel="chat", client_id="c2")
    recheck = m.request("recheck", channel="tui", client_id="c3")
    assert first is second
    assert isinstance(recheck, Refusal) and recheck.reason == "locked"
    assert len(m.drain().spawn) == 1  # one worker for both
    assert not isinstance(first, Refusal)
    assert first.clients == {"c1", "c2"}
    m.finish(first.id, MATCH)
    record = m.record(first.id)
    assert record is not None and record["ok"] is True and record["reason"] == "match"


def test_unlock_ok_sets_since_expiry_face_and_reports_failures(clock: FakeClock) -> None:
    m = machine(clock, max_unlock=3600)
    for _ in range(2):
        attempt = m.request("unlock", channel="tui", client_id="c1")
        assert not isinstance(attempt, Refusal)
        m.finish(attempt.id, NO_MATCH)
    assert m.failures == 2 and m.snapshot()["failures"] == 2
    attempt = m.request("unlock", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    m.finish(attempt.id, MATCH)
    now = clock.wall()
    assert m.state == "unlocked" and m.method == "face"
    assert m.since == now and m.face_seen_at == now
    assert m.expires_at is not None and (m.expires_at - now).total_seconds() == 3600
    snapshot = m.snapshot()
    assert snapshot["failures"] == 2  # shown once, on the unlock that follows them
    assert m.failures == 0 and snapshot["lock_trigger"] is None
    assert ("unlock", "match") in events(m)


def test_unlock_fail_goes_back_to_the_previous_state(clock: FakeClock) -> None:
    m = machine(clock)
    attempt = m.request("unlock", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    m.finish(attempt.id, Outcome(False, "no_face"))
    assert m.state == "locked" and m.failures == 0  # no_face does not count
    m.finish(attempt.id, NO_MATCH)  # a verdict for a finished attempt changes nothing
    attempt = m.request("unlock", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    m.finish(attempt.id, NO_MATCH)
    assert (m.state, m.lock_trigger, m.failures) == ("locked", "startup", 1)
    m2 = unlocked(FakeClock())
    attempt = m2.request("unlock", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    m2.finish(attempt.id, Outcome(False, "no_face"))
    assert m2.state == "unlocked"  # an uncounted failure of a re-unlock stays unlocked


def test_a_re_unlock_that_sees_someone_else_locks(clock: FakeClock) -> None:
    """A channel that asks for ``unlock`` instead of the due ``recheck`` gets no free tries."""
    m = unlocked(clock)
    attempt = m.request("unlock", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal) and attempt.strict
    m.finish(attempt.id, NO_MATCH)
    assert (m.state, m.lock_trigger, m.failures) == ("locked", "step_up_failed", 1)


def test_a_recheck_that_joins_a_re_unlock_locks_on_a_counted_failure(clock: FakeClock) -> None:
    m = unlocked(clock)
    unlock = m.request("unlock", channel="desktop", client_id="d1")
    recheck = m.request("recheck", channel="tui", client_id="t1")
    assert not isinstance(unlock, Refusal) and recheck is unlock and unlock.strict
    m.finish(unlock.id, NO_MATCH)
    assert (m.state, m.lock_trigger) == ("locked", "step_up_failed")
    record = m.record(unlock.id)
    assert record is not None and record["reason"] == "no_match"


def test_a_recheck_joined_to_a_queued_unlock_makes_it_strict(clock: FakeClock) -> None:
    m = unlocked(clock)
    step_up = m.request("step_up", channel="tui", client_id="s1")
    unlock = m.request("unlock", channel="desktop", client_id="d1")
    recheck = m.request("recheck", channel="tui", client_id="t1")
    assert not isinstance(step_up, Refusal) and not isinstance(unlock, Refusal)
    assert recheck is unlock and unlock in m.queue and unlock.strict
    m.finish(step_up.id, MATCH)
    assert m.running is unlock
    m.finish(unlock.id, Outcome(False, "spoof"))
    assert (m.state, m.lock_trigger) == ("locked", "step_up_failed")


def test_step_up_while_unlocked_stays_unlocked_and_queues_behind_a_running_check(
    clock: FakeClock,
) -> None:
    m = unlocked(clock)
    recheck = m.request("recheck", channel="tui", client_id="c1")
    step_up = m.request("step_up", channel="tui", client_id="c1", request_id="r1", tool="lamp")
    assert not isinstance(recheck, Refusal) and not isinstance(step_up, Refusal)
    assert m.running is recheck and m.queue == [step_up]
    assert [a.id for a in m.drain().spawn] == [recheck.id]  # the step-up waits
    record = m.record(step_up.id)
    assert record is not None and record["step"] == "starting" and record["done"] is False
    m.finish(recheck.id, MATCH)
    assert m.running is step_up and m.step_up_active and m.state == "unlocked"
    assert [a.id for a in m.drain().spawn] == [step_up.id]


def test_queued_step_up_is_bounded_by_the_attempt_timeout(clock: FakeClock) -> None:
    m = unlocked(clock, attempt_timeout=30)
    running = m.request("unlock", channel="tui", client_id="c1")
    step_up = m.request("step_up", channel="tui", client_id="c1")
    assert not isinstance(running, Refusal) and not isinstance(step_up, Refusal)
    clock.advance(31)
    m.observe(PRESENT, tick=True)
    record = m.record(step_up.id)
    assert record is not None and record["done"] and record["reason"] == "timeout"


@pytest.mark.parametrize("state", ["locked", "verifying"])
def test_step_up_while_locked_returns_locked_without_a_worker(clock: FakeClock, state: str) -> None:
    m = machine(clock)
    if state == "verifying":
        m.request("unlock", channel="tui", client_id="c1")
        m.drain()
    assert m.state == state
    refusal = m.request("step_up", channel="tui", client_id="c1", request_id="r1")
    assert refusal == Refusal("locked")
    assert m.drain().spawn == []  # the camera never opens


def test_step_up_ok_refreshes_the_face_only(clock: FakeClock) -> None:
    m = unlocked(clock)
    since, expires = m.since, m.expires_at
    clock.advance(120)
    attempt = m.request("step_up", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    m.finish(attempt.id, MATCH)
    assert m.face_seen_at == clock.wall() and m.max_idle_since_face == 0
    assert (m.since, m.expires_at) == (since, expires)
    assert not m.step_up_active


@pytest.mark.parametrize("reason", ["no_match", "spoof", "multiple_faces"])
def test_failed_step_up_with_a_counted_reason_locks(clock: FakeClock, reason: str) -> None:
    m = unlocked(clock)
    attempt = m.request("step_up", channel="tui", client_id="c1", request_id="r1", tool="lamp")
    assert not isinstance(attempt, Refusal)
    m.finish(attempt.id, Outcome(False, reason))
    assert (m.state, m.lock_trigger) == ("locked", "step_up_failed")
    assert m.failures == 1
    audit = m.drain().audit
    assert audit[-2]["event"] == "step_up" and audit[-2]["reason"] == reason
    assert audit[-2]["request_id"] == "r1" and audit[-2]["tool"] == "lamp"
    assert audit[-1]["event"] == "lock" and audit[-1]["trigger"] == "step_up_failed"


def test_failed_step_up_without_a_counted_reason_stays_unlocked(clock: FakeClock) -> None:
    m = unlocked(clock)
    attempt = m.request("step_up", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    m.finish(attempt.id, Outcome(False, "timeout"))
    assert m.state == "unlocked" and m.failures == 0


def test_any_lock_trigger_cancels_the_running_attempt(clock: FakeClock) -> None:
    m = machine(clock)
    attempt = m.request("unlock", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    m.drain()
    assert m.lock("telegram", channel="telegram", client_id="t1")
    assert (m.state, m.lock_trigger) == ("locked", "telegram")
    assert m.running is None
    effects = m.drain()
    assert effects.kill == [(attempt.id, "cancelled")]  # the camera is released
    record = m.record(attempt.id)
    assert record is not None and record["done"] and record["reason"] == "cancelled"
    assert record["ok"] is False
    assert m.finish(attempt.id, MATCH) is False  # a late verdict changes nothing
    assert m.state == "locked"


def test_lock_from_unlocked_cancels_a_step_up_and_queued_attempts(clock: FakeClock) -> None:
    m = unlocked(clock)
    step_up = m.request("step_up", channel="tui", client_id="c1")
    queued = m.request("step_up", channel="chat", client_id="c2")
    assert not isinstance(step_up, Refusal) and not isinstance(queued, Refusal)
    m.drain()
    assert m.lock("idle")
    assert m.state == "locked" and not m.step_up_active and m.method is None
    assert m.drain().kill == [(step_up.id, "cancelled")]
    for attempt in (step_up, queued):
        record = m.record(attempt.id)
        assert record is not None and record["reason"] == "cancelled"


def test_lock_is_idempotent(clock: FakeClock) -> None:
    m = machine(clock)
    seq = m.seq
    assert m.lock("command") is False  # already locked, nothing running
    assert m.seq == seq and m.lock_trigger == "startup"
    assert m.drain().audit == []


def test_recheck_ok_refreshes_the_face_and_the_idle_since_the_face(clock: FakeClock) -> None:
    m = unlocked(clock)
    clock.advance(100)
    m.observe(Reading(idle_seconds=90, screen_locked=False), tick=True)
    assert m.max_idle_since_face == 90
    attempt = m.request("recheck", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    m.finish(attempt.id, Outcome(True, "match", "face", 0.8, "passive"))
    assert m.face_seen_at == clock.wall() and m.max_idle_since_face == 0
    assert m.state == "unlocked"


def test_recheck_that_sees_another_face_locks(clock: FakeClock) -> None:
    m = unlocked(clock)
    attempt = m.request("recheck", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    m.finish(attempt.id, NO_MATCH)
    assert (m.state, m.lock_trigger) == ("locked", "step_up_failed")


def test_cancel_withdraws_one_client_and_cancels_an_attempt_nobody_waits_for(
    clock: FakeClock,
) -> None:
    m = machine(clock)
    attempt = m.request("unlock", channel="tui", client_id="c1")
    m.request("unlock", channel="chat", client_id="c2")
    assert not isinstance(attempt, Refusal)
    m.drain()
    assert m.cancel("c1")
    assert m.running is attempt and m.drain().kill == []  # c2 still waits
    assert not m.cancel("c1")
    assert m.cancel("c2", attempt.id)
    assert m.running is None and m.state == "locked"
    assert m.drain().kill == [(attempt.id, "cancelled")]


def test_records_stay_readable_for_at_least_60_seconds(clock: FakeClock) -> None:
    m = machine(clock)
    attempt = m.request("unlock", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    m.finish(attempt.id, NO_MATCH)
    clock.advance(60)
    assert m.record(attempt.id) is not None
    clock.advance(61)
    assert m.record(attempt.id) is None  # unknown or expired: null
    assert m.record("never-issued") is None


# -- decision 10: reflex locks -------------------------------------------------------------------


def test_max_age_locks_on_the_wall_clock(clock: FakeClock) -> None:
    m = unlocked(clock, max_unlock=3600)
    clock.advance(3599)
    m.observe(PRESENT, tick=True)
    assert m.state == "unlocked"
    clock.advance(1)
    m.observe(PRESENT, tick=True)
    assert (m.state, m.lock_trigger) == ("locked", "max_age")


def test_sleep_drift_locks(clock: FakeClock) -> None:
    m = unlocked(clock)
    clock.advance(2)
    m.observe(PRESENT, tick=True)
    clock.sleep(29)
    m.observe(PRESENT, tick=True)
    assert m.state == "unlocked"  # under 30 s of drift
    clock.sleep(31)
    m.observe(PRESENT, tick=True)
    assert (m.state, m.lock_trigger) == ("locked", "sleep")


def test_sleep_drift_is_caught_inline_too(clock: FakeClock) -> None:
    m = unlocked(clock)
    clock.sleep(8 * 3600)  # the lid was closed overnight; monotonic time barely moved
    m.observe(PRESENT)  # an admission, before any tick
    assert (m.state, m.lock_trigger) == ("locked", "sleep")


def test_idle_locks(clock: FakeClock) -> None:
    m = unlocked(clock, idle_lock=600)
    clock.advance(600)
    m.observe(Reading(599, False), tick=True)
    assert m.state == "unlocked"
    m.observe(Reading(600, False), tick=True)
    assert (m.state, m.lock_trigger) == ("locked", "idle")


def test_screen_lock_locks_even_during_a_check(clock: FakeClock) -> None:
    m = machine(clock)
    attempt = m.request("unlock", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    m.drain()
    m.observe(Reading(0, True))
    assert (m.state, m.lock_trigger) == ("locked", "screen_lock")
    assert m.drain().kill == [(attempt.id, "cancelled")]


@pytest.mark.parametrize(
    "reading", [Reading(0.0, None), Reading(None, False), Reading(None, None)], ids=str
)
def test_unknown_presence_caps_the_unlock_at_idle_lock(clock: FakeClock, reading: Reading) -> None:
    m = unlocked(clock, idle_lock=600, max_unlock=8 * 3600)
    clock.advance(599)
    m.observe(reading, tick=True)
    assert m.state == "unlocked"
    if reading.screen_locked is None:
        assert m.snapshot()["screen"] == "unknown"
    clock.advance(1)
    m.observe(reading, tick=True)
    assert (m.state, m.lock_trigger) == ("locked", "max_age")


def test_admission_refuses_when_the_reflex_loop_is_stale(clock: FakeClock) -> None:
    m = unlocked(clock)
    assert m.admission(enrolled=True) == (True, "ok")
    clock.advance(6)
    m.observe(PRESENT)  # an inline evaluation is not a tick
    assert m.admission(enrolled=True) == (True, "ok")
    clock.advance(0.5)
    assert m.admission(enrolled=True) == (False, "unavailable")
    m.observe(PRESENT, tick=True)
    assert m.admission(enrolled=True) == (True, "ok")


def test_admission_reasons(clock: FakeClock) -> None:
    m = machine(clock)
    assert m.admission(enrolled=False) == (False, "not_enrolled")
    assert m.admission(enrolled=True) == (False, "locked")
    fresh = GuardMachine(clock)  # never ticked
    assert fresh.admission(enrolled=True) == (False, "unavailable")


def test_admission_asks_for_a_recheck_after_idle_since_the_face(clock: FakeClock) -> None:
    m = unlocked(clock, recheck_after_idle=180, idle_lock=600)
    clock.advance(179)
    m.observe(Reading(179, False), tick=True)
    assert m.admission(enrolled=True) == (True, "ok")
    clock.advance(1)
    m.observe(Reading(180, False), tick=True)
    assert m.admission(enrolled=True) == (False, "recheck")
    # someone typed since: HID idle is back to 0, but the idle since the face stays
    clock.advance(2)
    m.observe(Reading(0, False), tick=True)
    assert m.admission(enrolled=True) == (False, "recheck")


def test_idle_before_the_face_match_does_not_count(clock: FakeClock) -> None:
    m = machine(clock, recheck_after_idle=180)
    clock.advance(1)
    m.observe(Reading(500, False), tick=True)  # nobody touched the Mac before the unlock
    attempt = m.request("unlock", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    m.finish(attempt.id, MATCH)
    clock.advance(10)
    m.observe(Reading(510, False), tick=True)
    assert m.max_idle_since_face == 10
    assert m.admission(enrolled=True) == (True, "ok")


def test_admission_asks_for_a_recheck_after_presence_recheck_minutes(clock: FakeClock) -> None:
    m = unlocked(clock, presence_recheck=1800)
    for _ in range(899):
        clock.advance(2)
        m.observe(PRESENT, tick=True)
    assert m.admission(enrolled=True) == (True, "ok")
    clock.advance(2)
    m.observe(PRESENT, tick=True)
    assert m.admission(enrolled=True) == (False, "recheck")


def test_face_fresh_follows_face_seen_at(clock: FakeClock) -> None:
    m = machine(clock)
    assert not m.face_fresh(30)
    m = unlocked(clock)
    assert m.face_fresh(30)
    clock.advance(31)
    assert not m.face_fresh(30) and m.face_fresh(60)


# -- decision 13: failures and cooldown ----------------------------------------------------------


def fail(m: GuardMachine, reason: str = "no_match") -> Refusal | None:
    attempt = m.request("unlock", channel="tui", client_id="c1")
    if isinstance(attempt, Refusal):
        return attempt
    m.finish(attempt.id, Outcome(False, reason))
    return None


def test_three_counted_failures_in_ten_minutes_start_a_cooldown(clock: FakeClock) -> None:
    m = machine(clock)
    assert fail(m) is None
    clock.advance(200)
    m.observe(PRESENT, tick=True)
    assert fail(m, "spoof") is None
    clock.advance(200)
    m.observe(PRESENT, tick=True)
    assert m.cooldown_left() is None
    assert fail(m, "multiple_faces") is None
    assert m.cooldown_left() == 30
    assert m.snapshot()["cooldown_until"] is not None
    assert fail(m) == Refusal("cooldown", 30)
    assert m.admission(enrolled=True) == (False, "cooldown")
    step_up_audit = [e for e in m.drain().audit if e["event"] == "cooldown"]
    assert step_up_audit == [
        {"event": "cooldown", "ok": False, "reason": "cooldown", "duration_ms": 30000}
    ]
    clock.advance(10)
    refusal = fail(m)
    assert refusal is not None and refusal.retry_after == 20


def test_failures_outside_the_window_do_not_add_up(clock: FakeClock) -> None:
    m = machine(clock)
    fail(m)
    fail(m)
    clock.advance(601)
    fail(m)
    assert m.cooldown_left() is None


def test_uncounted_failures_never_start_a_cooldown(clock: FakeClock) -> None:
    m = machine(clock)
    for reason in ("no_face", "timeout", "too_dark", "camera_busy", "cancelled"):
        fail(m, reason)
    assert m.cooldown_left() is None and m.failures == 0


def test_cooldown_doubles_up_to_fifteen_minutes(clock: FakeClock) -> None:
    m = machine(clock)
    fail(m)
    fail(m)
    lengths = []
    for _ in range(8):
        assert fail(m) is None
        left = m.cooldown_left()
        assert left is not None
        lengths.append(left)
        clock.advance(left)
        m.observe(PRESENT, tick=True)
    assert lengths == [30, 60, 120, 240, 480, COOLDOWN_MAX, COOLDOWN_MAX, COOLDOWN_MAX]


def test_a_match_resets_the_doubling(clock: FakeClock) -> None:
    m = machine(clock)
    for _ in range(3):
        fail(m)
    clock.advance(30)
    attempt = m.request("unlock", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    m.finish(attempt.id, MATCH)
    m.lock("command")
    for _ in range(3):
        fail(m)
    assert m.cooldown_left() == 30


def test_step_up_failures_count_toward_the_cooldown(clock: FakeClock) -> None:
    m = unlocked(clock)
    attempt = m.request("step_up", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    m.finish(attempt.id, NO_MATCH)
    assert m.state == "locked" and m.failures == 1
    fail(m)
    assert m.cooldown_left() is None
    fail(m)
    assert m.cooldown_left() == 30


def test_enrollment_ignores_the_cooldown_and_the_lock(clock: FakeClock) -> None:
    m = machine(clock)
    for _ in range(3):
        fail(m)
    attempt = m.request("enroll", channel="enroll", client_id="c1")
    assert not isinstance(attempt, Refusal) and attempt.kind == "enroll"


def test_the_queue_is_bounded(clock: FakeClock) -> None:
    m = unlocked(clock)
    m.request("step_up", channel="tui", client_id="c0")
    for index in range(8):
        assert not isinstance(m.request("step_up", channel="tui", client_id=f"q{index}"), Refusal)
    assert m.request("step_up", channel="tui", client_id="late") == Refusal("busy")


def test_seq_grows_on_every_change(clock: FakeClock) -> None:
    m = machine(clock)
    seen = [m.seq]
    attempt = m.request("unlock", channel="tui", client_id="c1")
    assert not isinstance(attempt, Refusal)
    seen.append(m.seq)
    m.progress(attempt.id, step="look", hint=None, deadline=None)
    seen.append(m.seq)
    m.progress(attempt.id, step="turn_left", hint="too_dark", deadline=clock.wall())
    seen.append(m.seq)
    m.finish(attempt.id, MATCH)
    seen.append(m.seq)
    m.lock("command")
    seen.append(m.seq)
    assert seen == sorted(set(seen))
    record = m.record(attempt.id)
    assert record is not None and record["seq"] <= m.seq
