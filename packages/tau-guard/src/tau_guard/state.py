"""The guard's state machine (ADR 0008 decisions 9, 10 and 13): pure code, no I/O, no threads.

:class:`GuardMachine` holds the state (``locked`` / ``verifying`` / ``unlocked``; ``off`` and
``unavailable`` belong to the service around it) and the orthogonal fields: ``step_up_active``,
``failures``, ``cooldown_until``, ``seq`` (grows on every change), ``face_seen_at`` and
``max_idle_since_face``. Time comes from a :class:`Clock` (tests pass a fake one); presence
comes in as :class:`Reading` values; the worker's answers come in as :class:`Outcome` values.
What the service must do next (spawn a worker, kill one, write an audit record) collects in an
outbox that :meth:`GuardMachine.drain` empties.

Rules the table in the ADR leaves to the implementation:

- ``verifying`` means an unlock attempt started from ``locked``. An attempt started while
  ``unlocked`` (a re-unlock, a recheck, a step-up) leaves the state ``unlocked`` with the
  attempt running, so other channels are not refused in the meantime and a finished step-up
  still reads ``state: "unlocked"``.
- One attempt runs at a time. An unlock joins a running unlock; a recheck joins a running
  unlock or recheck (same attempt id, same verdict). Everything else queues (at most
  :data:`MAX_QUEUE`), and a queued attempt that has not started within the attempt timeout
  finishes with ``timeout``.
- An unlock joins only when its merged policy is not stricter than the running attempt's
  (a client that asks for the challenge never gets a passive verdict); otherwise it queues.
- A step-up or a recheck while ``locked`` (or while an unlock from ``locked`` runs) is refused
  with ``locked`` and never starts a worker. Every kind is refused with ``locked`` while the
  screen is locked, so the camera never opens on a locked Mac.
- **Strict attempts.** A recheck, a step-up, an unlock started while ``unlocked`` (a re-unlock)
  and any attempt a recheck joined lock with trigger ``step_up_failed`` ("locked after a
  failed identity check") when they fail with a counted reason: any check that sees someone
  else while tau is unlocked locks. tau-core's lock triggers have no separate recheck value.
  An unlock from ``locked`` that fails goes back to ``locked``.
- **Policy.** A worker success the attempt's merged policy excludes (a Touch ID step-up when
  ``step_up`` is ``face``, Touch ID when ``unlock_fallback`` is ``none``, a face unlock without
  ``liveness: "challenge"`` when ``unlock_liveness`` is ``challenge``, a face step-up without
  the challenge outside the freshness window, a face step-up when ``step_up`` is
  ``touch_id``) finishes as ``error``. The worker enforces the policy first; this is the
  hub's second line.
- **Challenge freshness.** Only an unlock or a step-up that passed the challenge starts the
  ``challenge_fresh`` window, and every lock ends it.
- **Abandoned challenges count.** A check dropped while its record shows a head-turn prompt
  (step ``turn_left``, ``turn_right`` or ``center``) by a client's cancel, any lock (``/guard
  lock``, a screen lock, a sleep, the hub stopping) or the last client leaving ends as ``spoof``:
  it counts like a step past its deadline, and a strict attempt locks with ``step_up_failed``
  (a lock that is already happening keeps its own trigger). Otherwise someone holding up a clip
  could cancel whenever the drawn direction does not fit it and retry at once, and a step-up
  could escape its lock. A check dropped before its first prompt (camera start-up, the frontal
  match) still ends as ``cancelled`` and counts for nothing.
- An enrollment (``kind="enroll"``) runs behind LocalAuthentication; its failures do not
  count and its success resets nothing.
- A verdict with ``camera_ms`` also writes a ``camera_open`` audit record (``reason`` is the
  attempt kind, ``duration_ms`` how long the camera was on).
- Cooldown: three counted failures within :data:`FAILURE_WINDOW` start a cooldown of
  :data:`COOLDOWN_START` seconds. From then on every counted failure starts the next cooldown
  at twice the length, up to :data:`COOLDOWN_MAX`, until a match or a quiet window (no failure
  and no cooldown ending within :data:`FAILURE_WINDOW`) resets the doubling.
  :meth:`GuardMachine.failure_state` and :meth:`GuardMachine.restore_failures` carry the
  failure count and the cooldown across a hub restart (as wall times), so a restart never
  resets the rate limit.
- While the screen-lock state or the HID idle time is unknown, an unlock lasts at most
  ``idle_lock`` seconds (lock trigger ``max_age``).
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "ATTEMPT_EVENTS",
    "CHALLENGE_STEPS",
    "COUNTED_REASONS",
    "KINDS",
    "STRICTNESS",
    "Attempt",
    "Clock",
    "Effects",
    "GuardMachine",
    "Limits",
    "Outcome",
    "Reading",
    "Refusal",
    "SystemClock",
    "iso",
]

KINDS = ("unlock", "recheck", "step_up", "enroll")
ATTEMPT_EVENTS = {
    "unlock": "verify",
    "recheck": "recheck",
    "step_up": "step_up",
    "enroll": "enroll",
}
"""The audit event of each attempt kind."""
COUNTED_REASONS = frozenset({"no_match", "spoof", "multiple_faces"})
"""Verdict reasons that count as failures, for unlock, recheck and step-up alike."""
CHALLENGE_STEPS = frozenset({"turn_left", "turn_right", "center"})
"""Progress steps that show a head-turn prompt: a check dropped at one of them failed its
challenge (``spoof``)."""

FAILURE_WINDOW = 600.0
COOLDOWN_AFTER = 3
COOLDOWN_START = 30.0
COOLDOWN_MAX = 900.0
SLEEP_DRIFT = 30.0
"""A wall-minus-monotonic drift larger than this between two evaluations locks (``sleep``)."""
REFLEX_STALE = 6.0
"""Admission refuses (``unavailable``) when the reflex loop's last tick is older than this."""
RECORD_KEEP = 120.0
"""How long a finished attempt's record stays readable (the contract says at least 60 s)."""
MAX_RECORDS = 256
MAX_QUEUE = 8

_JOINS = {"unlock": frozenset({"unlock"}), "recheck": frozenset({"unlock", "recheck"})}
"""Which running kind an incoming kind joins."""
STRICTNESS: dict[str, dict[str, int]] = {
    "step_up": {"none": 0, "face_or_touch_id": 1, "face": 2, "touch_id": 2},
    "unlock_liveness": {"none": 0, "challenge": 1},
}
"""Higher is stricter; two different values of the same rank keep the hub's."""
_STEP_UP_METHODS = {
    "face": frozenset({"face"}),
    "touch_id": frozenset({"touch_id"}),
    "face_or_touch_id": frozenset({"face", "touch_id"}),
    "none": frozenset({"face", "touch_id"}),
}
"""The success methods each ``step_up`` policy accepts (an unknown value: face only)."""
MAX_SAVED_FAILURES = 32
MAX_SAVED_LEVEL = 16
_CAMERA = {
    "camera_denied": "denied",
    "camera_unavailable": "unavailable",
    "camera_busy": "unavailable",
    "permission_pending": "not_determined",
}
_CAMERA_OK = frozenset(
    {"match", "no_match", "no_face", "multiple_faces", "spoof", "too_dark", "face_too_small"}
)


@runtime_checkable
class Clock(Protocol):
    """Wall time (UTC, aware) and monotonic seconds."""

    def wall(self) -> datetime: ...

    def monotonic(self) -> float: ...


class SystemClock:
    def wall(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


def iso(moment: datetime | None) -> str | None:
    """``moment`` as ISO 8601 UTC with seconds, ``None`` stays ``None``."""
    if moment is None:
        return None
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _stamp(moment: datetime | None) -> str | None:
    """``moment`` as ISO 8601 UTC with microseconds (for :meth:`GuardMachine.failure_state`)."""
    return None if moment is None else moment.astimezone(UTC).isoformat()


def _moment(value: object) -> datetime | None:
    """An aware ISO time, else ``None``."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _rank(key: str, policy: Mapping[str, str]) -> int:
    """How strict ``policy[key]`` is (a missing or unknown value counts as the strictest)."""
    ranks = STRICTNESS[key]
    value = policy.get(key)
    return ranks[value] if value in ranks else max(ranks.values())


@dataclass(frozen=True)
class Limits:
    """The reflex and attempt knobs in seconds, and the hub's Touch ID fallback
    (``[component.guard]``, validated)."""

    max_unlock: float = 8 * 3600.0
    idle_lock: float = 10 * 60.0
    recheck_after_idle: float = 3 * 60.0
    presence_recheck: float = 30 * 60.0
    attempt_timeout: float = 30.0
    challenge_fresh: float = 120.0
    unlock_fallback: str = "touch_id"


@dataclass(frozen=True)
class Reading:
    """One presence sample. ``None`` means unknown (no GUI session, no idle source)."""

    idle_seconds: float | None
    screen_locked: bool | None


@dataclass(frozen=True)
class Outcome:
    """A validated worker verdict (or one the service decided: ``cancelled``, ``timeout``)."""

    ok: bool
    reason: str
    method: str | None = None
    score: float | None = None
    liveness: str | None = None
    camera_ms: int | None = None
    """How long the worker had the camera on (the audit's ``camera_open``)."""
    local_auth: tuple[str, str, int] | None = None
    """``(policy, outcome, ms)`` of a LocalAuthentication prompt (the audit's ``touch_id``)."""


@dataclass(frozen=True)
class Refusal:
    """A request the machine turned down; ``reason`` is a verdict reason."""

    reason: str
    retry_after: float | None = None


@dataclass
class Attempt:
    id: str
    kind: str
    channel: str
    client_id: str
    request_id: str | None = None
    tool: str | None = None
    policy: dict[str, str] = field(default_factory=dict)
    clients: set[str] = field(default_factory=set)
    created: float = 0.0
    started: float | None = None
    finished: float | None = None
    step: str = "starting"
    hint: str | None = None
    deadline: datetime | None = None
    seq: int = 0
    done: bool = False
    ok: bool | None = None
    reason: str | None = None
    method: str | None = None
    retry_after: float | None = None
    score: float | None = None
    liveness: str | None = None
    challenge_fresh: bool = False
    """A step-up within ``challenge_fresh`` seconds of a passed challenge (a passive match
    is enough, decision 12)."""
    strict: bool = False
    """A counted failure locks (``step_up_failed``): a recheck, a step-up, a re-unlock started
    while ``unlocked``, or an attempt a recheck joined."""
    add: bool = False
    """An enrollment that adds samples to the existing template (``tau guard enroll --add``)."""

    def record(self) -> dict[str, Any]:
        """The wire shape tau-core's ``HubGuard`` reads."""
        return {
            "id": self.id,
            "kind": self.kind,
            "step": self.step,
            "seq": self.seq,
            "deadline": iso(self.deadline),
            "hint": self.hint,
            "done": self.done,
            "ok": self.ok,
            "reason": self.reason,
            "method": self.method,
            "retry_after": self.retry_after,
        }


@dataclass
class Effects:
    """What the service must do after a transition."""

    spawn: list[Attempt] = field(default_factory=list)
    kill: list[tuple[str, str]] = field(default_factory=list)
    """``(attempt id, reason)`` of workers to stop."""
    audit: list[dict[str, Any]] = field(default_factory=list)
    """Keyword arguments for :meth:`tau_guard.audit.AuditLog.record`."""


class GuardMachine:
    """The guard's state. Construction is the ``start`` event: ``locked``, trigger
    ``startup``; an unlock is never restored."""

    def __init__(self, clock: Clock, limits: Limits | None = None) -> None:
        self.clock = clock
        self.limits = limits or Limits()
        self.state = "locked"
        self.lock_trigger: str | None = "startup"
        self.seq = 1
        self.method: str | None = None
        self.since: datetime | None = None
        self.expires_at: datetime | None = None
        self.face_seen_at: datetime | None = None
        self.max_idle_since_face = 0.0
        self.failures = 0
        """Counted failures since the last unlock."""
        self.reported_failures = 0
        """The count the last successful unlock reported (shown while unlocked)."""
        self.cooldown_until: datetime | None = None
        self._cooldown_until_mono: float | None = None
        self._cooldown_level = 0
        self._cooldown_end: float | None = None
        self._cooldown_end_wall: datetime | None = None
        self._last_failure: float | None = None
        self._last_failure_wall: datetime | None = None
        self._failure_times: list[tuple[float, datetime]] = []
        """``(monotonic, wall)`` of each counted failure within the window."""
        self.step_up_active = False
        self.last_verdict: str | None = None
        self.camera: str | None = None
        self.screen = "unknown"
        """``locked``, ``unlocked`` or ``unknown`` (the last presence reading)."""
        self.idle_known = False
        self.running: Attempt | None = None
        self.queue: list[Attempt] = []
        self._records: dict[str, Attempt] = {}
        self._offset: float | None = None
        self.last_tick: float | None = None
        self._challenge_passed: float | None = None
        self._outbox = Effects()
        self._audit("lock", trigger="startup")

    # -- queries ---------------------------------------------------------------------------

    def drain(self) -> Effects:
        """Take the pending effects."""
        effects, self._outbox = self._outbox, Effects()
        return effects

    def cooldown_left(self) -> float | None:
        """Seconds of cooldown left, ``None`` without one."""
        if self._cooldown_until_mono is None:
            return None
        left = self._cooldown_until_mono - self.clock.monotonic()
        return round(left, 1) if left > 0 else None

    def recheck_due(self) -> bool:
        if self.face_seen_at is None:
            return True
        if self.max_idle_since_face >= self.limits.recheck_after_idle:
            return True
        age = (self.clock.wall() - self.face_seen_at).total_seconds()
        return age >= self.limits.presence_recheck

    def admission(self, *, enrolled: bool) -> tuple[bool, str]:
        """``(allowed, reason)`` for a turn; evaluate the reflexes (:meth:`observe`) first."""
        if not enrolled:
            return False, "not_enrolled"
        tick = self.last_tick
        if tick is None or self.clock.monotonic() - tick > REFLEX_STALE:
            return False, "unavailable"
        if self.state == "unlocked":
            if self.recheck_due():
                return False, "recheck"
            return True, "ok"
        if self.cooldown_left() is not None:
            return False, "cooldown"
        return False, "locked"

    def face_fresh(self, seconds: float) -> bool:
        """Unlocked, and the last face match is at most ``seconds`` old."""
        if self.state != "unlocked" or self.face_seen_at is None:
            return False
        return (self.clock.wall() - self.face_seen_at).total_seconds() <= seconds

    def snapshot(self) -> dict[str, Any]:
        """Every ``GuardStatus`` field this machine knows (the service adds ``enrolled``,
        ``enrollment``, ``attempt`` and ``reason``)."""
        unlocked = self.state == "unlocked"
        cooldown = self.cooldown_until if self.cooldown_left() is not None else None
        return {
            "state": self.state,
            "method": self.method if unlocked else None,
            "since": iso(self.since) if unlocked else None,
            "expires_at": iso(self.expires_at) if unlocked else None,
            "face_seen_at": iso(self.face_seen_at),
            "seq": self.seq,
            "last_verdict": self.last_verdict,
            "lock_trigger": None if unlocked else self.lock_trigger,
            "failures": self.reported_failures if unlocked else self.failures,
            "cooldown_until": iso(cooldown),
            "camera": self.camera,
            "screen": self.screen,
            "step_up_active": self.step_up_active,
        }

    def record(self, attempt_id: str) -> dict[str, Any] | None:
        """The record of a queued, running or recently finished attempt."""
        self._prune_records()
        attempt = self._find(attempt_id)
        return attempt.record() if attempt is not None else None

    def running_record(self) -> dict[str, Any] | None:
        return self.running.record() if self.running is not None else None

    def attempt(self, attempt_id: str) -> Attempt | None:
        return self._find(attempt_id)

    def failure_state(self) -> dict[str, Any]:
        """The failure count and the cooldown with wall times, so a hub restart keeps them
        (the service stores this in ``guard/failures.json``)."""
        return {
            "v": 1,
            "failures": self.failures,
            "failure_times": [
                _stamp(wall) for _, wall in self._failure_times[-MAX_SAVED_FAILURES:]
            ],
            "level": self._cooldown_level,
            "last_failure": _stamp(self._last_failure_wall),
            "cooldown_end": _stamp(self._cooldown_end_wall),
            "cooldown_until": _stamp(self.cooldown_until),
        }

    def restore_failures(self, data: object) -> bool:
        """Take back a :meth:`failure_state` from before a restart: wall times become
        monotonic ones. A malformed value restores nothing (``False``). A time in the future
        counts as now, and a cooldown never comes back longer than :data:`COOLDOWN_MAX`."""
        parsed = _parse_failure_state(data)
        if parsed is None:
            return False
        failures, times, level, last_failure, cooldown_end, cooldown_until = parsed
        now, wall = self.clock.monotonic(), self.clock.wall()

        def back(moment: datetime, most: float = 0.0) -> tuple[float, datetime]:
            delta = min((moment - wall).total_seconds(), most)
            return now + delta, wall + timedelta(seconds=delta)

        self.failures = failures
        self._failure_times = [back(moment) for moment in times]
        self._cooldown_level = level
        self._last_failure, self._last_failure_wall = (
            back(last_failure) if last_failure is not None else (None, None)
        )
        self._cooldown_end, self._cooldown_end_wall = (
            back(cooldown_end, COOLDOWN_MAX) if cooldown_end is not None else (None, None)
        )
        if cooldown_until is not None:
            until_mono, until_wall = back(cooldown_until, COOLDOWN_MAX)
            if until_mono > now:
                self._cooldown_until_mono, self.cooldown_until = until_mono, until_wall
        self._prune()
        self._bump()
        return True

    # -- requests --------------------------------------------------------------------------

    def request(
        self,
        kind: str,
        *,
        channel: str,
        client_id: str,
        request_id: str | None = None,
        tool: str | None = None,
        policy: Mapping[str, str] | None = None,
        add: bool = False,
    ) -> Attempt | Refusal:
        """Ask for an attempt: a new one, a joined one, a queued one, or a refusal. ``add``
        only applies to an enrollment."""
        if kind not in KINDS:
            raise ValueError(f"unknown attempt kind {kind!r}")
        self._prune()
        if self.screen == "locked":
            return Refusal("locked")  # the camera never opens on a locked Mac
        if kind != "enroll":
            left = self.cooldown_left()
            if left is not None:
                return Refusal("cooldown", left)
        if kind in ("step_up", "recheck") and self.state != "unlocked":
            return Refusal("locked")
        merged = dict(policy or {})
        joins = _JOINS.get(kind, frozenset())
        for candidate in [self.running, *self.queue]:
            if candidate is None or candidate.done or candidate.kind not in joins:
                continue
            if kind == "unlock" and _rank("unlock_liveness", merged) > _rank(
                "unlock_liveness", candidate.policy
            ):
                continue  # a stricter unlock never takes a weaker verdict: it queues
            candidate.clients.add(client_id)
            if kind == "recheck":
                candidate.strict = True
            return candidate
        if self.running is not None and len(self.queue) >= MAX_QUEUE:
            return Refusal("busy")
        attempt = Attempt(
            id=secrets.token_hex(8),
            kind=kind,
            channel=channel,
            client_id=client_id,
            request_id=request_id,
            tool=tool,
            policy=merged,
            clients={client_id},
            created=self.clock.monotonic(),
            strict=kind in ("recheck", "step_up"),
            add=add and kind == "enroll",
        )
        if self.running is None:
            self._start(attempt)
        else:
            self.queue.append(attempt)
            attempt.seq = self._bump()
        return attempt

    def progress(
        self, attempt_id: str, *, step: str, hint: str | None, deadline: datetime | None
    ) -> bool:
        """A progress event of the running attempt."""
        attempt = self.running
        if attempt is None or attempt.id != attempt_id or attempt.done:
            return False
        attempt.step, attempt.hint, attempt.deadline = step, hint, deadline
        attempt.seq = self._bump()
        return True

    def finish(self, attempt_id: str, outcome: Outcome) -> bool:
        """The running attempt's verdict; ignored for an attempt that is no longer running."""
        attempt = self.running
        if attempt is None or attempt.id != attempt_id or attempt.done:
            return False
        if outcome.ok and not self._policy_allows(attempt, outcome):
            outcome = Outcome(False, "error", score=outcome.score, liveness=outcome.liveness)
        self._conclude(attempt, outcome)
        self._start_next()
        return True

    def cancel(self, client_id: str, attempt_id: str | None = None) -> bool:
        """Withdraw ``client_id`` from its attempts (or from ``attempt_id``); an attempt no
        client waits for any more is cancelled."""
        changed = False
        for attempt in [self.running, *self.queue]:
            if attempt is None or attempt.done or client_id not in attempt.clients:
                continue
            if attempt_id is not None and attempt.id != attempt_id:
                continue
            attempt.clients.discard(client_id)
            changed = True
            if not attempt.clients:
                self._drop(attempt, "cancelled")
        if changed:
            self._start_next()
        return changed

    def lock(
        self, trigger: str, *, channel: str | None = None, client_id: str | None = None
    ) -> bool:
        """Any lock trigger: ``locked``, running and queued attempts cancelled. ``False`` when
        nothing changed (already locked with nothing running): locking is idempotent."""
        busy = self.running is not None or bool(self.queue)
        if self.state == "locked" and not busy:
            return False
        for attempt in [self.running, *self.queue]:
            if attempt is not None and not attempt.done:
                self._drop(attempt, "cancelled", locking=True)
        self.state = "locked"
        self.lock_trigger = trigger
        self.method = None
        self.since = None
        self.expires_at = None
        self.step_up_active = False
        self._challenge_passed = None  # freshness lives inside one unlocked session
        self._bump()
        self._audit("lock", channel=channel, client_id=client_id, trigger=trigger)
        return True

    # -- reflexes ----------------------------------------------------------------------------

    def observe(self, reading: Reading, *, tick: bool = False) -> None:
        """Evaluate the reflex locks against one presence reading (inline at admission and
        step-up, and from the reflex loop with ``tick=True``)."""
        now = self.clock.monotonic()
        wall = self.clock.wall()
        offset = wall.timestamp() - now
        drifted = self._offset is not None and abs(offset - self._offset) > SLEEP_DRIFT
        self._offset = offset
        screen = (
            "unknown"
            if reading.screen_locked is None
            else ("locked" if reading.screen_locked else "unlocked")
        )
        idle_known = reading.idle_seconds is not None
        if screen != self.screen or idle_known != self.idle_known:
            self.screen, self.idle_known = screen, idle_known
            self._bump()
        if drifted:
            self.lock("sleep")
        if screen == "locked":
            self.lock("screen_lock")
        if self.state == "unlocked":
            self._unlocked_reflexes(reading, wall)
        if tick:
            self.last_tick = now
        self._prune()
        self._expire_queue(now)

    def _unlocked_reflexes(self, reading: Reading, wall: datetime) -> None:
        limits = self.limits
        if self.expires_at is not None and wall >= self.expires_at:
            self.lock("max_age")
            return
        unknown = reading.idle_seconds is None or reading.screen_locked is None
        if unknown and self.since is not None:
            if (wall - self.since).total_seconds() >= limits.idle_lock:
                self.lock("max_age")
                return
        idle = reading.idle_seconds
        if idle is None:
            return
        if idle >= limits.idle_lock:
            self.lock("idle")
            return
        if self.face_seen_at is not None:
            since_face = max(0.0, (wall - self.face_seen_at).total_seconds())
            observed = min(max(0.0, idle), since_face)
            if observed > self.max_idle_since_face:
                self.max_idle_since_face = observed

    # -- internals ---------------------------------------------------------------------------

    def _bump(self) -> int:
        self.seq += 1
        return self.seq

    def _audit(self, event: str, **fields: Any) -> None:
        self._outbox.audit.append({"event": event, **fields})

    def _find(self, attempt_id: str) -> Attempt | None:
        if self.running is not None and self.running.id == attempt_id:
            return self.running
        for attempt in self.queue:
            if attempt.id == attempt_id:
                return attempt
        return self._records.get(attempt_id)

    def _start(self, attempt: Attempt) -> None:
        now = self.clock.monotonic()
        attempt.started = now
        self.running = attempt
        if attempt.kind == "unlock":
            if self.state == "locked":
                self.state = "verifying"
            elif self.state == "unlocked":
                attempt.strict = True  # a re-unlock that sees someone else locks
        if attempt.kind == "step_up":
            self.step_up_active = True
            fresh = self._challenge_passed
            attempt.challenge_fresh = (
                fresh is not None and now - fresh <= self.limits.challenge_fresh
            )
        attempt.seq = self._bump()
        self._outbox.spawn.append(attempt)

    def _start_next(self) -> None:
        while self.running is None and self.queue:
            attempt = self.queue.pop(0)
            if attempt.kind in ("step_up", "recheck") and self.state != "unlocked":
                self._finish_unstarted(attempt, Outcome(False, "locked"))
                continue
            left = self.cooldown_left() if attempt.kind != "enroll" else None
            if left is not None:
                attempt.retry_after = left
                self._finish_unstarted(attempt, Outcome(False, "cooldown"))
                continue
            self._start(attempt)

    def _drop(self, attempt: Attempt, reason: str, *, locking: bool = False) -> None:
        """End a running or queued attempt the service decided about (no worker verdict). A
        check dropped at a head-turn prompt failed its challenge (``spoof``, counted); with
        ``locking`` a lock is already under way, so a strict attempt does not lock again."""
        if attempt is self.running:
            self._outbox.kill.append((attempt.id, reason))
            outcome = Outcome(False, reason)
            if attempt.kind != "enroll" and attempt.step in CHALLENGE_STEPS:
                outcome = Outcome(False, "spoof")
            self._conclude(attempt, outcome, relock=not locking)
        else:
            if attempt in self.queue:
                self.queue.remove(attempt)
            self._finish_unstarted(attempt, Outcome(False, reason))

    def _finish_unstarted(self, attempt: Attempt, outcome: Outcome) -> None:
        self._mark_done(attempt, outcome)
        self._audit(
            ATTEMPT_EVENTS[attempt.kind],
            channel=attempt.channel,
            client_id=attempt.client_id,
            ok=False,
            reason=outcome.reason,
            duration_ms=0,
            request_id=attempt.request_id,
            tool=attempt.tool,
        )

    def _mark_done(self, attempt: Attempt, outcome: Outcome) -> None:
        attempt.done = True
        attempt.ok = outcome.ok
        attempt.reason = outcome.reason
        attempt.method = outcome.method if outcome.ok else None
        attempt.score = outcome.score
        attempt.liveness = outcome.liveness
        attempt.finished = self.clock.monotonic()
        attempt.hint = None
        attempt.deadline = None
        attempt.step = "done"
        self._records[attempt.id] = attempt
        attempt.seq = self._bump()

    def _conclude(self, attempt: Attempt, outcome: Outcome, *, relock: bool = True) -> None:
        """Apply a verdict of the running attempt (decision 9's table); ``relock=False``
        when the caller locks anyway."""
        self.running = None
        wall = self.clock.wall()
        now = self.clock.monotonic()
        checks = attempt.kind != "enroll"  # an enrollment neither counts nor resets failures
        counted = checks and not outcome.ok and outcome.reason in COUNTED_REASONS
        self.last_verdict = outcome.reason
        if outcome.reason in _CAMERA:
            self.camera = _CAMERA[outcome.reason]
        elif outcome.reason in _CAMERA_OK:
            self.camera = "ok"
        lock_after: str | None = None
        unlocked_now = False
        if attempt.kind == "unlock":
            if outcome.ok:
                unlocked_now = self.state != "unlocked"
                self.state = "unlocked"
                self.lock_trigger = None
                self.method = outcome.method
                self.since = wall
                self.expires_at = wall + timedelta(seconds=self.limits.max_unlock)
                self._face_seen(wall)
                self.reported_failures = self.failures
                self.failures = 0
            elif self.state == "verifying":
                self.state = "locked"
        elif attempt.kind in ("recheck", "step_up"):
            if attempt.kind == "step_up":
                self.step_up_active = False
            if outcome.ok:
                self._face_seen(wall)
        if counted and attempt.strict:
            lock_after = "step_up_failed"
        if outcome.ok and checks:
            self._failure_times.clear()
            self._cooldown_level = 0
            self._last_failure = self._last_failure_wall = None
            self._cooldown_end = self._cooldown_end_wall = None
            if outcome.liveness == "challenge" and attempt.kind in ("unlock", "step_up"):
                self._challenge_passed = now
        duration = None if attempt.started is None else int((now - attempt.started) * 1000)
        if outcome.camera_ms is not None:
            self._audit(
                "camera_open",
                channel=attempt.channel,
                client_id=attempt.client_id,
                ok=True,
                reason=attempt.kind,
                duration_ms=outcome.camera_ms,
            )
        self._mark_done(attempt, outcome)
        self._audit(
            ATTEMPT_EVENTS[attempt.kind],
            channel=attempt.channel,
            client_id=attempt.client_id,
            ok=outcome.ok,
            reason=outcome.reason,
            score=outcome.score,
            liveness=outcome.liveness,
            duration_ms=duration,
            request_id=attempt.request_id,
            tool=attempt.tool,
        )
        if unlocked_now:
            self._audit(
                "unlock",
                channel=attempt.channel,
                client_id=attempt.client_id,
                ok=True,
                reason=outcome.reason,
            )
        if counted:
            self._count_failure(now, wall)
        if lock_after is not None and relock:
            self.lock(lock_after, channel=attempt.channel, client_id=attempt.client_id)

    def _face_seen(self, wall: datetime) -> None:
        self.face_seen_at = wall
        self.max_idle_since_face = 0.0

    def _policy_allows(self, attempt: Attempt, outcome: Outcome) -> bool:
        """Whether a worker success fits the attempt's merged policy (the worker checks it
        first; this is the hub's second line)."""
        method, liveness, policy = outcome.method, outcome.liveness, attempt.policy
        if attempt.kind == "enroll":
            return True
        if attempt.kind == "step_up":
            mode = policy.get("step_up", "face")
            if method not in _STEP_UP_METHODS.get(mode, _STEP_UP_METHODS["face"]):
                return False
            if method == "face" and mode != "none":
                return liveness == "challenge" or (
                    attempt.challenge_fresh and liveness == "passive"
                )
            return True
        if method == "touch_id":
            return self.limits.unlock_fallback != "none"
        if attempt.kind == "unlock" and _rank("unlock_liveness", policy) > 0:
            return liveness == "challenge"
        return True

    def _count_failure(self, now: float, wall: datetime) -> None:
        self.failures += 1
        self._prune_failures(now)
        self._failure_times.append((now, wall))
        self._last_failure, self._last_failure_wall = now, wall
        if self._cooldown_level == 0 and len(self._failure_times) < COOLDOWN_AFTER:
            return
        seconds = min(COOLDOWN_MAX, COOLDOWN_START * 2**self._cooldown_level)
        self._cooldown_level += 1
        self._cooldown_until_mono = now + seconds
        self._cooldown_end = now + seconds
        self.cooldown_until = wall + timedelta(seconds=seconds)
        self._cooldown_end_wall = self.cooldown_until
        self._bump()
        self._audit("cooldown", ok=False, reason="cooldown", duration_ms=int(seconds * 1000))

    def _prune_failures(self, now: float) -> None:
        """Forget failures older than the window; after a quiet window (no failure and no
        cooldown ending in it) the doubling starts over."""
        self._failure_times = [
            (mono, wall) for mono, wall in self._failure_times if now - mono < FAILURE_WINDOW
        ]
        anchors = [t for t in (self._last_failure, self._cooldown_end) if t is not None]
        if not anchors or now - max(anchors) >= FAILURE_WINDOW:
            self._cooldown_level = 0

    def _prune(self) -> None:
        now = self.clock.monotonic()
        self._prune_failures(now)
        if self._cooldown_until_mono is not None and now >= self._cooldown_until_mono:
            self._cooldown_until_mono = None
            self.cooldown_until = None
            self._bump()
        self._prune_records()

    def _prune_records(self) -> None:
        now = self.clock.monotonic()
        expired = [
            key
            for key, attempt in self._records.items()
            if attempt.finished is not None and now - attempt.finished > RECORD_KEEP
        ]
        for key in expired:
            del self._records[key]
        while len(self._records) > MAX_RECORDS:
            del self._records[next(iter(self._records))]

    def _expire_queue(self, now: float) -> None:
        limit = self.limits.attempt_timeout
        for attempt in list(self.queue):
            if now - attempt.created > limit:
                self.queue.remove(attempt)
                self._finish_unstarted(attempt, Outcome(False, "timeout"))


def _parse_failure_state(
    data: object,
) -> tuple[int, list[datetime], int, datetime | None, datetime | None, datetime | None] | None:
    """Validate a :meth:`GuardMachine.failure_state` read back from disk; ``None`` when any
    field is off."""
    if not isinstance(data, dict) or data.get("v") != 1:
        return None
    failures, level = _count(data.get("failures")), _count(data.get("level"))
    times = data.get("failure_times")
    if failures is None or level is None:
        return None
    if not isinstance(times, list) or len(times) > MAX_SAVED_FAILURES:
        return None
    moments = [_moment(text) for text in times]
    if any(moment is None for moment in moments):
        return None
    optional: list[datetime | None] = []
    for key in ("last_failure", "cooldown_end", "cooldown_until"):
        value = data.get(key)
        moment = _moment(value)
        if value is not None and moment is None:
            return None
        optional.append(moment)
    return (
        min(failures, 10**6),
        [moment for moment in moments if moment is not None],
        min(level, MAX_SAVED_LEVEL),
        optional[0],
        optional[1],
        optional[2],
    )


def _count(value: object) -> int | None:
    """A non-negative int (not a bool), else ``None``."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None
