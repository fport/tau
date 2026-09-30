"""The owner guard seam (ADR 0008): who may use tau's guarded surfaces right now.

tau-core owns the protocol, its value types, the closed reason lists and the route contract;
the camera, the state machine and the routes live in the hub (``tau-guard``, issue 111). No
camera library is imported here or in any channel process.

- :class:`Guard` is the protocol every guard implements. Every method fails closed: ``admit``
  refuses, ``step_up`` returns ``False``, ``unlock`` returns a failed :class:`GuardVerdict`, and
  none of them raises into its caller except ``asyncio.CancelledError``.
- :class:`LockedGuard` refuses everything (bad configuration, an unsupported platform).
- :class:`HubGuard` talks to the hub's ``/guard/*`` routes through
  :class:`~tau_core.hub.client.HubClient` and admits only a proven ``unlocked`` answer whose
  ``enrollment`` id equals the local marker's.
- :func:`resolve_guard` picks ``None`` (no guard active), a :class:`LockedGuard` or a
  :class:`HubGuard` for a configuration; ``build_agent(guard=DISCOVER)`` calls it.
- :func:`admit_turn` is the one place an admission answer is read (``TauAgent.stream``,
  ``TierGate`` and compaction use it): a raising guard, a timeout or an unknown reason refuses.

Route contract (all protected control routes, JSON; the hub side is issue 111):

- ``GET /guard/status?since=<seq>&wait=<0..25>[&attempt=<id>]`` (long poll) answers every
  :class:`GuardStatus` field plus ``enrollment``. ``attempt`` is ``null`` or
  ``{id, kind, step, seq, deadline, hint, done, ok, reason, method, retry_after}``: the running
  attempt, or, with ``attempt=<id>``, that attempt's own record whether it is queued (a step-up
  behind a running verification: ``step: "starting"``, ``done: false``), running or finished,
  and ``null`` once the id is unknown or expired. The hub keeps a finished attempt's record for
  at least 60 s. A finished attempt with ``ok: true`` has ``reason: "match"``, a ``method``,
  and comes with ``state: "unlocked"`` and the ``enrollment`` id.
- ``POST /guard/admit`` ``{channel, session_id, client_id}`` → ``{allowed, reason, enrollment}``.
- ``POST /guard/verify`` ``{channel, client_id, kind, request_id?, tool?, policy?,
  fallback?}`` → ``202 {attempt, seq}``; a refusal answers 4xx ``{reason, retry_after?}``
  (``cooldown``, ``busy``). The result is read through ``/guard/status?attempt=<id>``.
  ``policy`` holds every :data:`POLICY_KEYS` knob with the value the client uses
  (:func:`client_policy`: the strict default of :data:`POLICY_DEFAULTS` for a knob the client's
  ``tau.toml`` leaves out); the hub applies the stricter of its own value and the client's, and
  reads a knob missing from ``policy``, or a missing ``policy``, as that default, never as
  agreement with a weaker hub value.
  ``fallback: "touch_id"`` (an ``unlock`` only; ``unlock(method="touch_id")``) asks for the
  Touch ID fallback: the hub runs it only while its status offers it (``fallback``), and runs
  LocalAuthentication itself, so the sheet appears on the Mac's screen. No route accepts a
  Touch ID result either.
- ``POST /guard/cancel`` ``{client_id, attempt?}`` → ``{ok}``.
- ``POST /guard/lock`` ``{channel, client_id, trigger}`` → ``{state: "locked"}``.
- ``POST /guard/enroll`` ``{client_id}`` → ``202 {attempt, seq}``.

A route can only ask the hub to look; no route accepts a verdict, an image or an embedding.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from tau_core.config import Config
from tau_core.hub.client import HubClient, HubError, HubUnavailable
from tau_core.i18n import DEFAULT_LANGUAGE, MESSAGES, register_messages, t

if TYPE_CHECKING:
    from tau_core.approval import ApprovalRequest
    from tau_core.builder import Check

__all__ = [
    "ADMISSION_REASONS",
    "ALLOWED_WHILE_LOCKED",
    "DISCOVER",
    "ENROLLED_MARKER",
    "FACE_FAILURES",
    "FALLBACK_AFTER",
    "FALLBACK_MODES",
    "FALLBACK_NOW",
    "GUARD_CONFIG_KEYS",
    "GUARD_MESSAGES",
    "LOCKED_NOTE",
    "LOCK_TRIGGERS",
    "POLICY_DEFAULTS",
    "POLICY_KEYS",
    "PROGRESS_STEPS",
    "STEP_UP_NOTE",
    "UNLOCK_METHODS",
    "VERDICT_REASONS",
    "Admission",
    "Guard",
    "GuardLocked",
    "GuardProgress",
    "GuardState",
    "GuardStatus",
    "GuardTurn",
    "GuardVerdict",
    "HubGuard",
    "LockedGuard",
    "admission_reason",
    "admit_turn",
    "client_policy",
    "config_problem",
    "guard_active",
    "guard_doctor_check",
    "guard_status_line",
    "process_client_id",
    "read_enrollment",
    "reset_guards",
    "resolve_guard",
    "status_from_json",
]

logger = logging.getLogger(__name__)

GuardState = Literal["off", "locked", "verifying", "unlocked", "unavailable"]
GUARD_STATES: tuple[str, ...] = ("off", "locked", "verifying", "unlocked", "unavailable")

VERDICT_REASONS: tuple[str, ...] = (
    "match",
    "no_match",
    "no_face",
    "multiple_faces",
    "spoof",
    "timeout",
    "cancelled",
    "too_dark",
    "face_too_small",
    "camera_busy",
    "camera_unavailable",
    "camera_denied",
    "permission_pending",
    "not_enrolled",
    "template_invalid",
    "model_changed",
    "key_unavailable",
    "cooldown",
    "locked",
    "touch_id_unavailable",
    "touch_id_failed",
    "unsupported_platform",
    "unavailable",
    "busy",
    "error",
)
"""Every value ``GuardVerdict.reason`` (and ``GuardProgress.hint``) can carry."""

ADMISSION_REASONS: tuple[str, ...] = (
    "ok",
    "locked",
    "recheck",
    "not_enrolled",
    "cooldown",
    "unavailable",
    "unsupported_platform",
    "error",
)
"""Every value ``Admission.reason`` can carry; anything else is read as ``error``."""

LOCK_TRIGGERS: tuple[str, ...] = (
    "command",
    "idle",
    "screen_lock",
    "sleep",
    "max_age",
    "hub_stop",
    "telegram",
    "step_up_failed",
    "startup",
)
PROGRESS_STEPS: tuple[str, ...] = (
    "starting",
    "look",
    "turn_left",
    "turn_right",
    "center",
    "touch_id",
    "done",
    # enrollment poses and its "turn a little further" nudge (issue 112)
    "look_up",
    "look_down",
    "turn_more",
)
ALLOWED_WHILE_LOCKED = frozenset({"help", "lang", "quit", "guard"})
"""Slash commands a guarded channel runs while locked (issue 113)."""

ENROLLED_MARKER = "guard/enrolled"
"""The public enrollment marker, relative to ``data_dir``: JSON ``{"v": 1, "enrollment":
"<id>", "model": "<sha256>", "created": "<iso>"}``. tau-guard writes it; tau-core only reads
it. While it exists the guard is active, whatever ``[component.guard] enabled`` says."""

GUARD_CONFIG_KEYS = frozenset(
    {
        "enabled",
        "camera",
        "unlock_liveness",
        "unlock_threshold",
        "step_up_threshold",
        "verify_timeout_seconds",
        "max_unlock_hours",
        "idle_lock_minutes",
        "recheck_after_idle_minutes",
        "presence_recheck_minutes",
        "step_up_challenge_fresh_seconds",
        "unlock_fallback",
        "step_up",
    }
)
"""The keys ``[component.guard]`` may hold; any other key locks the guard for good (a typo
such as ``enable = true`` must never mean "off"). An issue that adds a knob adds it here."""

POLICY_KEYS = ("step_up", "unlock_liveness")
"""Weakening-sensitive knobs a client sends with every verification; the hub applies the
stricter of its own value and the client's."""
POLICY_DEFAULTS: dict[str, str] = {"step_up": "face", "unlock_liveness": "challenge"}
"""What a client uses for a :data:`POLICY_KEYS` knob its ``[component.guard]`` leaves out or
sets to something unknown; each default is also the knob's strictest value."""
POLICY_VALUES: dict[str, tuple[str, ...]] = {
    "step_up": ("face", "face_or_touch_id", "touch_id", "none"),
    "unlock_liveness": ("challenge", "none"),
}

LOCKED_NOTE = "tau was locked before the user answered."
"""Fixed English note the model reads when a tier-1 or tier-2 call met a locked guard."""
STEP_UP_NOTE = "The guard could not confirm the user's identity."
"""Fixed English note the model reads when the tier-2 step-up did not pass."""

ADMIT_TIMEOUT = 3.0
"""How long ``HubGuard.admit`` waits for the hub before it refuses."""
ADMIT_LIMIT = 5.0
"""How long :func:`admit_turn` waits for any guard's ``admit`` before it refuses."""
REQUEST_TIMEOUT = 5.0
LONG_POLL = 25.0
ATTEMPT_LIMIT = 120.0
"""Upper bound on one unlock or step-up attempt seen from the client."""
SUCCESS_METHODS = ("face", "touch_id")

# -- the Touch ID fallback (ADR 0008 decision 15, issue 114) --------------------------------------

UNLOCK_METHODS = ("face", "touch_id")
"""What ``Guard.unlock(method=...)`` may ask for; ``touch_id`` only while it is offered."""
FALLBACK_MODES = ("touch_id", "touch_id_or_password")
"""``[component.guard] unlock_fallback`` values that offer Touch ID (``none`` offers nothing);
``touch_id_or_password`` also takes the Mac password (the opt-in for a closed lid)."""
FALLBACK_AFTER = 2
"""Failed face unlocks in one attempt window before the lock screen offers the fallback."""
FALLBACK_NOW = frozenset({"camera_busy", "camera_unavailable", "camera_denied"})
"""Verdicts after which the fallback is offered at once (the face check cannot work)."""
FACE_FAILURES = frozenset(
    {"no_match", "no_face", "multiple_faces", "spoof", "timeout", "too_dark", "face_too_small"}
)
"""Verdicts of a face check that ran and failed; :data:`FALLBACK_AFTER` of them offer the
fallback. Refusals (``cooldown``, ``locked``, ``busy``) and ``cancelled`` do not count."""


# -- value types -------------------------------------------------------------------------------


@dataclass(frozen=True)
class GuardProgress:
    """One step of a running attempt, for the challenge prompts ("turn left")."""

    step: str
    """One of :data:`PROGRESS_STEPS`."""
    seq: int
    """Grows with every change of the attempt."""
    deadline: datetime | None
    """UTC; when the current step times out."""
    hint: str | None = None
    """A :data:`VERDICT_REASONS` value used as a live hint (``too_dark``)."""


@dataclass(frozen=True)
class GuardVerdict:
    """The outcome of an unlock, a recheck or a step-up."""

    ok: bool
    reason: str
    """One of :data:`VERDICT_REASONS`."""
    method: str | None = None
    """``face`` or ``touch_id`` when ``ok``."""
    retry_after: float | None = None
    """Seconds, with ``cooldown``."""


@dataclass(frozen=True)
class GuardTurn:
    """What a channel asks admission for."""

    channel: str
    session_id: str | None
    client_id: str
    """Random per process; an audit label and the key for later per-client grants (117),
    never a claim."""


@dataclass(frozen=True)
class Admission:
    allowed: bool
    reason: str = "ok"
    """One of :data:`ADMISSION_REASONS`; an unknown value is treated as ``error``."""


@dataclass(frozen=True)
class GuardStatus:
    state: GuardState
    enrolled: bool = False
    method: str | None = None
    since: datetime | None = None
    expires_at: datetime | None = None
    face_seen_at: datetime | None = None
    seq: int = 0
    attempt: GuardProgress | None = None
    """The running attempt, while ``verifying``."""
    last_verdict: str | None = None
    lock_trigger: str | None = None
    """One of :data:`LOCK_TRIGGERS`, after a lock."""
    failures: int = 0
    """Failed attempts since the last unlock."""
    cooldown_until: datetime | None = None
    camera: str | None = None
    """``ok``, ``denied``, ``not_determined`` or ``unavailable``."""
    reason: str | None = None
    """Why ``unavailable``."""
    fallback: str | None = None
    """While ``locked``: the Touch ID fallback the lock screen may offer now (one of
    :data:`FALLBACK_MODES`), after :data:`FALLBACK_AFTER` failed face unlocks or a
    :data:`FALLBACK_NOW` verdict; ``None`` otherwise. ``unlock(method="touch_id")`` runs it."""


class GuardLocked(Exception):
    """The guard refused the turn; ``reason`` is one of :data:`ADMISSION_REASONS`.

    ``TauAgent.ask()`` raises it (``tau ask`` exits 2 with the guard notice, 073)."""

    def __init__(self, reason: str) -> None:
        self.reason = reason if reason in ADMISSION_REASONS else "error"
        super().__init__(f"tau is locked by the guard ({self.reason}).")


@runtime_checkable
class Guard(Protocol):
    """The owner guard as a channel sees it. Every method fails closed and never raises
    except ``asyncio.CancelledError``. ``kind`` is ``unlock`` (the full policy) or ``recheck``
    (a passive quick check). ``method`` is ``face`` or ``touch_id``: the Touch ID fallback of
    an ``unlock``, which the hub runs (on the Mac's screen) only while
    :attr:`GuardStatus.fallback` offers it."""

    name: str

    async def status(self) -> GuardStatus: ...

    async def watch(self, since: int, *, wait: float = 25.0) -> GuardStatus: ...

    async def admit(self, turn: GuardTurn) -> Admission: ...

    async def unlock(
        self,
        *,
        channel: str,
        client_id: str,
        kind: str = "unlock",
        on_progress: Callable[[GuardProgress], None] | None = None,
        method: str = "face",
    ) -> GuardVerdict: ...

    async def cancel(self, *, client_id: str) -> None: ...

    async def lock(self, *, channel: str, client_id: str, trigger: str = "command") -> None: ...

    async def step_up(
        self,
        request: ApprovalRequest,
        *,
        client_id: str,
        on_progress: Callable[[GuardProgress], None] | None = None,
    ) -> bool: ...


class _Discover:
    """The ``build_agent(guard=...)`` default: resolve the guard from the configuration."""

    def __repr__(self) -> str:
        return "DISCOVER"


DISCOVER: Any = _Discover()

_PROCESS_CLIENT_ID = secrets.token_hex(8)


def process_client_id() -> str:
    """This process's client id (random, fixed for the life of the process)."""
    return _PROCESS_CLIENT_ID


def admission_reason(reason: object) -> str:
    """``reason`` when it is a refusal reason of :data:`ADMISSION_REASONS`, else ``error``."""
    if isinstance(reason, str) and reason in ADMISSION_REASONS and reason != "ok":
        return reason
    return "error"


async def admit_turn(guard: Guard, turn: GuardTurn, *, timeout: float | None = None) -> Admission:
    """Ask ``guard`` to admit ``turn``, failing closed.

    Only an :class:`Admission` with ``allowed is True`` admits. A guard that raises refuses
    with ``error``, one that does not answer within ``timeout`` (default
    :data:`ADMIT_LIMIT`) with ``unavailable``, and an unknown reason reads as ``error``.
    ``asyncio.CancelledError`` propagates.

    The bound is hard: ``admit`` runs as its own task, and when the time is up the task is
    cancelled and whatever it answers later is dropped. (``asyncio.wait_for`` hands back a
    late result when the coroutine swallows the cancellation, which would admit a turn after
    the limit.)
    """
    limit = ADMIT_LIMIT if timeout is None else timeout
    try:
        task = asyncio.ensure_future(guard.admit(turn))
    except Exception:
        logger.exception("guard %s failed to answer admission; refusing", _name(guard))
        return Admission(False, "error")
    try:
        done, _ = await asyncio.wait({task}, timeout=limit)
    except asyncio.CancelledError:
        task.cancel()
        task.add_done_callback(_drop_result)
        raise
    if not done:
        task.cancel()
        task.add_done_callback(_drop_result)
        logger.warning("guard %s did not answer admission within %ss", _name(guard), limit)
        return Admission(False, "unavailable")
    try:
        answer = task.result()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("guard %s failed to answer admission; refusing", _name(guard))
        return Admission(False, "error")
    if isinstance(answer, Admission) and answer.allowed is True:
        return Admission(True, "ok")
    return Admission(False, admission_reason(getattr(answer, "reason", None)))


def _drop_result(task: asyncio.Future[Any]) -> None:
    """Retrieve a late admission task's outcome so nothing is logged as never retrieved."""
    if not task.cancelled():
        task.exception()


def _name(guard: object) -> str:
    return str(getattr(guard, "name", type(guard).__name__))


# -- LockedGuard -------------------------------------------------------------------------------


class LockedGuard:
    """A guard that refuses everything: a broken ``[component.guard]`` table or a platform the
    guard does not support. ``detail`` is plain English for the log and ``tau doctor``."""

    name = "locked"

    def __init__(self, reason: str, *, detail: str | None = None) -> None:
        self.reason = reason
        self.detail = detail

    async def status(self) -> GuardStatus:
        return GuardStatus(state="unavailable", reason=self.reason)

    async def watch(self, since: int, *, wait: float = 25.0) -> GuardStatus:
        if since >= 0:
            await asyncio.sleep(max(0.0, min(float(wait), LONG_POLL)))  # nothing ever changes
        return await self.status()

    async def admit(self, turn: GuardTurn) -> Admission:
        return Admission(False, admission_reason(self.reason))

    async def unlock(
        self,
        *,
        channel: str,
        client_id: str,
        kind: str = "unlock",
        on_progress: Callable[[GuardProgress], None] | None = None,
        method: str = "face",
    ) -> GuardVerdict:
        return GuardVerdict(False, self.reason if self.reason in VERDICT_REASONS else "error")

    async def cancel(self, *, client_id: str) -> None:
        return None

    async def lock(self, *, channel: str, client_id: str, trigger: str = "command") -> None:
        return None

    async def step_up(
        self,
        request: ApprovalRequest,
        *,
        client_id: str,
        on_progress: Callable[[GuardProgress], None] | None = None,
    ) -> bool:
        return False


# -- HubGuard ----------------------------------------------------------------------------------


def _deliver(future: asyncio.Future[Any], value: Any, error: BaseException | None) -> None:
    if future.done():
        return
    if error is not None:
        future.set_exception(error)
    else:
        future.set_result(value)


async def _in_daemon_thread[T](fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run blocking ``fn`` in a fresh daemon thread and await its result.

    Never ``asyncio.to_thread``: its executor is joined at shutdown, so a hung request would
    keep a channel from exiting. A cancelled caller stops waiting; the thread finishes alone
    and its result is dropped.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[T] = loop.create_future()

    def run() -> None:
        value: Any = None
        error: BaseException | None = None
        try:
            value = fn(*args, **kwargs)
        except BaseException as exc:  # handed to the awaiting task
            error = exc
        try:
            loop.call_soon_threadsafe(_deliver, future, value, error)
        except RuntimeError:
            pass  # the loop is closed: nobody waits any more

    threading.Thread(target=run, name="tau-guard-http", daemon=True).start()
    return await future


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _int(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _progress(attempt: object) -> GuardProgress | None:
    if not isinstance(attempt, dict):
        return None
    step = attempt.get("step")
    if step not in PROGRESS_STEPS:
        return None
    hint = attempt.get("hint")
    return GuardProgress(
        step=str(step),
        seq=_int(attempt.get("seq")),
        deadline=_parse_time(attempt.get("deadline")),
        hint=hint if hint in VERDICT_REASONS else None,
    )


def status_from_json(payload: Mapping[str, Any]) -> GuardStatus:
    """A :class:`GuardStatus` from the JSON of ``GET /guard/status`` (not yet checked against
    the local enrollment; :class:`HubGuard` does that)."""
    state = payload.get("state")
    attempt = payload.get("attempt")
    running = isinstance(attempt, dict) and attempt.get("done") is not True
    trigger = payload.get("lock_trigger")
    fallback = payload.get("fallback")
    return GuardStatus(
        state=state if state in GUARD_STATES else "unavailable",  # type: ignore[arg-type]
        enrolled=payload.get("enrolled") is True,
        method=_str(payload.get("method")),
        since=_parse_time(payload.get("since")),
        expires_at=_parse_time(payload.get("expires_at")),
        face_seen_at=_parse_time(payload.get("face_seen_at")),
        seq=_int(payload.get("seq")),
        attempt=_progress(attempt) if running else None,
        last_verdict=_str(payload.get("last_verdict")),
        lock_trigger=trigger if trigger in LOCK_TRIGGERS else None,
        failures=_int(payload.get("failures")),
        cooldown_until=_parse_time(payload.get("cooldown_until")),
        camera=_str(payload.get("camera")),
        reason=_str(payload.get("reason")),
        fallback=fallback if fallback in FALLBACK_MODES and state == "locked" else None,
    )


def read_enrollment(config: Config) -> str | None:
    """The ``enrollment`` id of the local marker, ``None`` without a readable one."""
    try:
        raw = json.loads((config.data_dir / ENROLLED_MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return _str(raw.get("enrollment")) if isinstance(raw, dict) else None


def client_policy(table: Mapping[str, Any]) -> dict[str, str]:
    """The weakening-sensitive knobs of ``[component.guard]`` this client sends the hub: every
    :data:`POLICY_KEYS` knob with the value this client uses, so a knob it leaves out (or sets
    to an unknown value) goes as its strict default (:data:`POLICY_DEFAULTS`), never as a
    silence the hub could read as agreeing with a weaker value of its own."""
    policy: dict[str, str] = {}
    for key in POLICY_KEYS:
        value = table.get(key)
        policy[key] = value if value in POLICY_VALUES[key] else POLICY_DEFAULTS[key]
    return policy


class HubGuard:
    """:class:`Guard` over the hub's ``/guard/*`` routes (``HubClient``: token, nonce, proof).

    The mapping is strict: only a proven answer that says ``unlocked`` (``allowed: true`` from
    ``/guard/admit``) with an ``enrollment`` id equal to the local marker's admits. ``off``, a
    404, a 403 after one token re-read, a 5xx, a timeout, bad JSON, a missing or wrong proof
    and an enrollment mismatch all mean locked (``unavailable``); a 403 is never signed, so its
    body never picks a verdict. ``unlock`` and ``step_up`` follow their own attempt by id
    (``/guard/status?attempt=<id>``), so a step-up queued behind another client's attempt keeps
    waiting, bounded by :data:`ATTEMPT_LIMIT`. Blocking HTTP runs in daemon threads; a
    cancelled ``unlock`` or ``step_up`` posts ``/guard/cancel`` and re-raises.
    """

    name = "hub"

    def __init__(self, config: Config, *, client: HubClient | None = None) -> None:
        self.config = config
        self.client = client or HubClient(config)
        self.policy = client_policy(config.component("guard"))

    # -- helpers --------------------------------------------------------------------------

    def _enrollment_ok(self, enrollment: object) -> bool:
        local = read_enrollment(self.config)
        return local is not None and enrollment == local

    def _checked(self, payload: object) -> GuardStatus:
        if not isinstance(payload, dict):
            return GuardStatus(state="unavailable", reason="bad_response")
        status = status_from_json(payload)
        if status.state == "off":
            return GuardStatus(state="unavailable", reason="guard_off")
        if status.state == "unlocked" and not self._enrollment_ok(payload.get("enrollment")):
            return GuardStatus(state="unavailable", enrolled=status.enrolled, reason="enrollment")
        return status

    async def _get_status(self, query: dict[str, str] | None, timeout: float) -> GuardStatus:
        try:
            payload = await _in_daemon_thread(
                self.client.get, "/guard/status", timeout=timeout, query=query
            )
        except HubUnavailable as exc:
            return GuardStatus(state="unavailable", reason=exc.reason)
        except HubError as exc:
            reason = "guard_off" if exc.status == 404 else "hub_error"
            return GuardStatus(state="unavailable", reason=reason)
        except Exception:
            logger.exception("guard status request failed")
            return GuardStatus(state="unavailable", reason="error")
        return self._checked(payload)

    def _post_later(self, path: str, body: dict[str, Any]) -> None:
        """Fire and forget (a cancelled attempt must not wait for the hub)."""

        def run() -> None:
            try:
                self.client.post(path, body, timeout=REQUEST_TIMEOUT)
            except Exception as exc:
                logger.warning("guard %s failed: %s", path, exc)

        threading.Thread(target=run, name="tau-guard-http", daemon=True).start()

    # -- Guard ----------------------------------------------------------------------------

    async def status(self) -> GuardStatus:
        return await self._get_status(None, REQUEST_TIMEOUT)

    async def watch(self, since: int, *, wait: float = 25.0) -> GuardStatus:
        wait = max(0.0, min(float(wait), LONG_POLL))
        query = {"since": str(int(since)), "wait": f"{wait:g}"}
        loop = asyncio.get_running_loop()
        started = loop.time()
        status = await self._get_status(query, wait + REQUEST_TIMEOUT)
        if status.state == "unavailable":
            # No hub (or a broken answer) comes back at once: keep a watcher from spinning.
            await asyncio.sleep(max(0.0, min(wait, 2.0) - (loop.time() - started)))
        return status

    async def admit(self, turn: GuardTurn) -> Admission:
        try:
            return await asyncio.wait_for(self._admit(turn), ADMIT_TIMEOUT)
        except TimeoutError:
            logger.warning("the hub did not answer admission within %ss", ADMIT_TIMEOUT)
            return Admission(False, "unavailable")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("admission request failed")
            return Admission(False, "error")

    async def _admit(self, turn: GuardTurn) -> Admission:
        body = {"channel": turn.channel, "session_id": turn.session_id, "client_id": turn.client_id}
        try:
            payload = await _in_daemon_thread(
                self.client.post, "/guard/admit", body, timeout=ADMIT_TIMEOUT
            )
        except (HubUnavailable, HubError) as exc:
            logger.info("admission refused: %s", exc)
            return Admission(False, "unavailable")
        if not isinstance(payload, dict) or payload.get("state") == "off":
            return Admission(False, "unavailable")
        if payload.get("allowed") is True:
            if self._enrollment_ok(payload.get("enrollment")):
                return Admission(True, "ok")
            logger.warning("the hub admitted a turn for another enrollment; refusing")
            return Admission(False, "unavailable")
        return Admission(False, admission_reason(payload.get("reason")))

    async def unlock(
        self,
        *,
        channel: str,
        client_id: str,
        kind: str = "unlock",
        on_progress: Callable[[GuardProgress], None] | None = None,
        method: str = "face",
    ) -> GuardVerdict:
        if kind not in ("unlock", "recheck") or method not in UNLOCK_METHODS:
            return GuardVerdict(False, "error")
        if method == "touch_id" and kind != "unlock":
            return GuardVerdict(False, "error")  # the hub picks a recheck's method itself
        body = {"channel": channel, "client_id": client_id, "kind": kind, "policy": self.policy}
        if method == "touch_id":
            body["fallback"] = "touch_id"  # the hub decides whether it is offered, and runs it
        try:
            return await self._attempt(body, client_id, on_progress)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("guard unlock failed")
            return GuardVerdict(False, "error")

    async def step_up(
        self,
        request: ApprovalRequest,
        *,
        client_id: str,
        on_progress: Callable[[GuardProgress], None] | None = None,
    ) -> bool:
        body = {
            "channel": request.channel,
            "client_id": client_id,
            "kind": "step_up",
            "request_id": request.request_id,
            "tool": request.tool,
            "policy": self.policy,
        }
        try:
            verdict = await self._attempt(body, client_id, on_progress)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("guard step-up failed")
            return False
        return verdict.ok is True

    async def cancel(self, *, client_id: str) -> None:
        try:
            await _in_daemon_thread(
                self.client.post, "/guard/cancel", {"client_id": client_id}, timeout=REQUEST_TIMEOUT
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("guard cancel failed: %s", exc)

    async def lock(self, *, channel: str, client_id: str, trigger: str = "command") -> None:
        """Ask the hub to lock. It never raises; a lock the hub did not confirm is logged as an
        error, and a channel that must know re-reads :meth:`status` afterwards (113)."""
        body = {
            "channel": channel,
            "client_id": client_id,
            "trigger": trigger if trigger in LOCK_TRIGGERS else "command",
        }
        try:
            answer = await _in_daemon_thread(
                self.client.post, "/guard/lock", body, timeout=REQUEST_TIMEOUT
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("the guard lock did not reach the hub: %s", exc)
            return
        if not isinstance(answer, dict) or answer.get("state") != "locked":
            logger.error("the hub did not confirm the guard lock: %r", answer)

    # -- one attempt ----------------------------------------------------------------------

    async def _attempt(
        self,
        body: dict[str, Any],
        client_id: str,
        on_progress: Callable[[GuardProgress], None] | None,
    ) -> GuardVerdict:
        try:
            started = await _in_daemon_thread(
                self.client.post, "/guard/verify", body, timeout=REQUEST_TIMEOUT
            )
        except asyncio.CancelledError:
            self._post_later("/guard/cancel", {"client_id": client_id})  # no attempt id yet
            raise
        except HubUnavailable:
            return GuardVerdict(False, "unavailable")
        except HubError as exc:
            if exc.status == 403:
                return GuardVerdict(False, "unavailable")  # never signed: any listener's words
            return _refused_verdict(exc.payload)  # HubClient checked this answer's proof
        if not isinstance(started, dict):
            return GuardVerdict(False, "error")
        attempt_id = _str(started.get("attempt"))
        seq = _int(started.get("seq"), -1)
        if attempt_id is None or seq < 0:
            return GuardVerdict(False, "error")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + ATTEMPT_LIMIT
        reported: int | None = None
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    self._post_later(
                        "/guard/cancel", {"client_id": client_id, "attempt": attempt_id}
                    )
                    return GuardVerdict(False, "timeout")
                wait = min(LONG_POLL, remaining)
                query = {"since": str(seq), "wait": f"{wait:g}", "attempt": attempt_id}
                try:
                    payload = await _in_daemon_thread(
                        self.client.get,
                        "/guard/status",
                        timeout=wait + REQUEST_TIMEOUT,
                        query=query,
                    )
                except (HubUnavailable, HubError):
                    return GuardVerdict(False, "unavailable")
                if not isinstance(payload, dict):
                    return GuardVerdict(False, "unavailable")
                attempt = payload.get("attempt")
                if not isinstance(attempt, dict) or attempt.get("id") != attempt_id:
                    # unknown or expired (null), or a hub that ignored ``attempt=<id>``
                    return GuardVerdict(False, "unavailable")
                seq = max(seq, _int(payload.get("seq"), seq))
                progress = _progress(attempt)
                if progress is not None and progress.seq != reported:
                    reported = progress.seq
                    _report(on_progress, progress)
                if attempt.get("done") is True:
                    return self._verdict(payload, attempt)
        except asyncio.CancelledError:
            self._post_later("/guard/cancel", {"client_id": client_id, "attempt": attempt_id})
            raise

    def _verdict(self, payload: dict[str, Any], attempt: dict[str, Any]) -> GuardVerdict:
        reason = attempt.get("reason")
        reason = reason if reason in VERDICT_REASONS else "error"
        method = attempt.get("method")
        method = method if method in SUCCESS_METHODS else None
        retry = attempt.get("retry_after")
        retry_after = float(retry) if isinstance(retry, int | float) and retry >= 0 else None
        if attempt.get("ok") is not True:
            return GuardVerdict(False, "error" if reason == "match" else reason, None, retry_after)
        if reason != "match" or payload.get("state") != "unlocked":
            return GuardVerdict(False, "error")
        if not self._enrollment_ok(payload.get("enrollment")):
            logger.warning("the hub verified another enrollment; refusing")
            return GuardVerdict(False, "unavailable")
        return GuardVerdict(True, "match", method)


def _refused_verdict(payload: object) -> GuardVerdict:
    """A verify request the hub refused with a proven non-403 answer (``cooldown``, ``busy``):
    never ``ok``."""
    if isinstance(payload, dict):
        reason = payload.get("reason")
        if reason in VERDICT_REASONS and reason != "match":
            retry = payload.get("retry_after")
            retry_after = float(retry) if isinstance(retry, int | float) and retry >= 0 else None
            return GuardVerdict(False, str(reason), None, retry_after)
    return GuardVerdict(False, "unavailable")


def _report(on_progress: Callable[[GuardProgress], None] | None, progress: GuardProgress) -> None:
    if on_progress is None:
        return
    try:
        on_progress(progress)
    except Exception:
        logger.exception("guard progress callback failed")


# -- resolution --------------------------------------------------------------------------------

_GUARDS: dict[tuple[str, str, str], Guard] = {}
_GUARDS_LOCK = threading.Lock()


def config_problem(table: Mapping[str, Any]) -> tuple[str, dict[str, str]] | None:
    """``(message key, kwargs)`` when ``[component.guard]`` must lock the guard for good."""
    if "enabled" in table and not isinstance(table["enabled"], bool):
        return "doctor.guard.bad_enabled", {"value": repr(table["enabled"])}
    unknown = sorted(set(table) - GUARD_CONFIG_KEYS)
    if unknown:
        return "doctor.guard.unknown_keys", {"keys": ", ".join(unknown)}
    return None


def guard_active(config: Config) -> bool:
    """The marker exists or ``[component.guard] enabled = true`` (the literal bool)."""
    return (config.data_dir / ENROLLED_MARKER).exists() or (
        config.component("guard").get("enabled") is True
    )


def _resolve(config: Config, platform: str) -> Guard | None:
    problem = config_problem(config.component("guard"))
    if problem is not None:
        key, kwargs = problem
        detail = t(key, DEFAULT_LANGUAGE, **kwargs)
        logger.error("the guard is locked for good: %s", detail)
        return LockedGuard("error", detail=detail)
    if not guard_active(config):
        return None
    if platform != "darwin":
        detail = t("doctor.guard.unsupported_platform", DEFAULT_LANGUAGE)
        logger.error("the guard is locked for good: %s", detail)
        return LockedGuard("unsupported_platform", detail=detail)
    return HubGuard(config)


def resolve_guard(config: Config, *, platform: str | None = None) -> Guard | None:
    """The guard for ``config``; a found guard is memoized per ``(home, data_dir)`` (and
    platform), so every build in a process gets the same object.

    ``None`` when neither the marker nor ``[component.guard] enabled = true`` is present; a
    :class:`LockedGuard` for a non-bool ``enabled``, an unknown key in ``[component.guard]``
    or any platform but darwin; otherwise a :class:`HubGuard`, even when ``enabled = false``
    as long as the marker exists. ``platform`` defaults to ``sys.platform`` (tests pass it).

    ``None`` is never memoized: it would fail open for the life of the process. A ``tau
    chat`` or ``tau tui`` started before ``tau guard setup`` wrote the marker (or before
    ``enabled = true``) therefore finds the guard at its next build, for the cost of a stat.
    """
    platform = sys.platform if platform is None else platform
    key = (str(config.home), str(config.data_dir), platform)
    with _GUARDS_LOCK:
        guard = _GUARDS.get(key)
        if guard is None:
            guard = _resolve(config, platform)
            if guard is not None:
                _GUARDS[key] = guard
        return guard


def reset_guards() -> None:
    """Forget every memoized guard (tests)."""
    with _GUARDS_LOCK:
        _GUARDS.clear()


# -- reports -----------------------------------------------------------------------------------


def guard_status_line(status: GuardStatus, language: str = DEFAULT_LANGUAGE) -> str:
    """The ``/status`` line for an active guard."""
    parts = [t(f"guard.state.{status.state}", language)]
    if status.state == "unlocked" and status.method in SUCCESS_METHODS:
        parts.append(str(status.method))
    if status.state == "locked" and status.lock_trigger in LOCK_TRIGGERS:
        parts.append(t(f"guard.lock_trigger.{status.lock_trigger}", language))
    if status.state == "unavailable":
        if status.reason == "no_hub":
            parts.append(t("guard.start_hub", language))
        elif status.reason in VERDICT_REASONS:
            parts.append(t(f"guard.verdict.{status.reason}", language))
        elif status.reason:
            parts.append(status.reason)
    return t("status.guard", language, detail=" · ".join(parts))


def guard_doctor_check(
    config: Config,
    hub_status: Mapping[str, Any] | None,
    language: str = DEFAULT_LANGUAGE,
    *,
    platform: str | None = None,
) -> Check:
    """``tau doctor``'s ``guard`` line. ``hub_status`` is the running hub's ``/status``
    (``None`` = no hub answers). English by default, like every doctor line; ``platform``
    defaults to ``sys.platform`` (tests pass it)."""
    from tau_core.builder import Check

    platform = sys.platform if platform is None else platform
    table = config.component("guard")
    problem = config_problem(table)
    if problem is not None:
        key, kwargs = problem
        detail = t(key, language, **kwargs)
        return Check("guard", "fail", t("doctor.guard.locked", language, detail=detail))
    if not guard_active(config):
        return Check("guard", "info", t("doctor.guard.off", language))
    if platform != "darwin":
        detail = t("doctor.guard.unsupported_platform", language)
        return Check("guard", "fail", t("doctor.guard.locked", language, detail=detail))
    note = ""
    if table.get("enabled") is False:
        note = " " + t("doctor.guard.enabled_ignored", language)
    pinned = config.components.hub_services
    if pinned and "guard" not in pinned:
        return Check("guard", "fail", t("doctor.guard.not_in_services", language) + note)
    if hub_status is None:
        text = t("doctor.guard.no_hub", language, hint=t("guard.start_hub", language))
        return Check("guard", "warn", text + note)
    block = hub_status.get("guard")
    if not isinstance(block, dict):
        return Check("guard", "warn", t("doctor.guard.no_service", language) + note)
    state = block.get("state")
    if state == "off" or state not in GUARD_STATES:
        return Check("guard", "warn", t("doctor.guard.hub_off", language) + note)
    raw_reason = block.get("reason")
    reason = raw_reason if isinstance(raw_reason, str) and _REASON.match(raw_reason) else None
    if state == "unavailable":
        text = t("doctor.guard.unavailable", language, reason=reason or "unknown")
        return Check("guard", "fail", text + note)
    if block.get("available") is False:
        text = t("doctor.guard.not_available", language, reason=reason or "unknown")
        return Check("guard", "warn", text + note)
    text = t("doctor.guard.ok", language, state=t(f"guard.state.{state}", language))
    if reason == "screen_unknown":
        return Check("guard", "warn", f"{text} {t('doctor.guard.screen_unknown', language)}{note}")
    return Check("guard", "ok", text + note)


_REASON = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
"""What a ``/status`` guard reason may look like before a doctor line shows it (the open
``/status`` is unauthenticated: no control characters reach the terminal)."""


# -- messages ----------------------------------------------------------------------------------

GUARD_MESSAGES: dict[str, dict[str, str]] = {
    # admission refusals (a Notice, then TurnEnd("locked"))
    "guard.refused.ok": {"en": "tau is unlocked.", "tr": "tau'nun kilidi açık."},
    "guard.refused.locked": {
        "en": "tau is locked. Unlock it at the Mac to continue.",
        "tr": "tau kilitli. Devam etmek için Mac'in başında kilidi aç.",
    },
    "guard.refused.recheck": {
        "en": "tau needs to see you again before it continues.",
        "tr": "tau devam etmeden önce seni yeniden görmeli.",
    },
    "guard.refused.not_enrolled": {
        "en": "The guard is on, but no face is enrolled. Run `tau guard setup` at the Mac.",
        "tr": "Koruma açık ama kayıtlı bir yüz yok. Mac'in başında `tau guard setup` çalıştır.",
    },
    "guard.refused.cooldown": {
        "en": "Too many failed attempts. tau stays locked for a while.",
        "tr": "Çok fazla başarısız deneme. tau bir süre kilitli kalacak.",
    },
    "guard.refused.unavailable": {
        "en": "tau is locked: the guard cannot be reached. Start the hub (TauBar → Run the "
        "hub, or `tau hub run`).",
        "tr": "tau kilitli: korumaya ulaşılamıyor. Hub'ı başlat (TauBar → Run the hub ya da "
        "`tau hub run`).",
    },
    "guard.refused.unsupported_platform": {
        "en": "tau is locked: the guard works only on macOS.",
        "tr": "tau kilitli: koruma yalnızca macOS'ta çalışır.",
    },
    "guard.refused.error": {
        "en": "tau is locked: the guard reported an error. Details are in the log.",
        "tr": "tau kilitli: koruma bir hata bildirdi. Ayrıntı günlükte.",
    },
    # states
    "guard.state.off": {"en": "off", "tr": "kapalı"},
    "guard.state.locked": {"en": "locked", "tr": "kilitli"},
    "guard.state.verifying": {"en": "verifying", "tr": "doğrulanıyor"},
    "guard.state.unlocked": {"en": "unlocked", "tr": "açık"},
    "guard.state.unavailable": {"en": "unavailable", "tr": "ulaşılamıyor"},
    # verdicts
    "guard.verdict.match": {"en": "Verified.", "tr": "Doğrulandı."},
    "guard.verdict.no_match": {"en": "The face did not match.", "tr": "Yüz eşleşmedi."},
    "guard.verdict.no_face": {"en": "No face was seen.", "tr": "Yüz görülmedi."},
    "guard.verdict.multiple_faces": {
        "en": "More than one face was seen.",
        "tr": "Birden fazla yüz görüldü.",
    },
    "guard.verdict.spoof": {
        "en": "The liveness check failed.",
        "tr": "Canlılık kontrolü başarısız oldu.",
    },
    "guard.verdict.timeout": {
        "en": "The check timed out.",
        "tr": "Kontrol zaman aşımına uğradı.",
    },
    "guard.verdict.cancelled": {"en": "The check was cancelled.", "tr": "Kontrol iptal edildi."},
    "guard.verdict.too_dark": {"en": "It is too dark.", "tr": "Ortam çok karanlık."},
    "guard.verdict.face_too_small": {"en": "Move closer to the camera.", "tr": "Kameraya yaklaş."},
    "guard.verdict.camera_busy": {
        "en": "Another app is using the camera.",
        "tr": "Kamerayı başka bir uygulama kullanıyor.",
    },
    "guard.verdict.camera_unavailable": {
        "en": "The camera is not available.",
        "tr": "Kamera kullanılamıyor.",
    },
    "guard.verdict.camera_denied": {
        "en": "Camera access is denied. Allow it in System Settings → Privacy & Security → Camera.",
        "tr": "Kamera erişimi reddedildi. Sistem Ayarları → Gizlilik ve Güvenlik → Kamera'dan "
        "izin ver.",
    },
    "guard.verdict.permission_pending": {
        "en": "Waiting for camera permission. Answer the macOS prompt, then try again.",
        "tr": "Kamera izni bekleniyor. macOS isteğini yanıtla, sonra yeniden dene.",
    },
    "guard.verdict.not_enrolled": {
        "en": "No face is enrolled. Run `tau guard setup`.",
        "tr": "Kayıtlı yüz yok. `tau guard setup` çalıştır.",
    },
    "guard.verdict.template_invalid": {
        "en": "The face template cannot be read. Enroll again with `tau guard enroll`.",
        "tr": "Yüz şablonu okunamıyor. `tau guard enroll` ile yeniden kaydol.",
    },
    "guard.verdict.model_changed": {
        "en": "The face model changed. Enroll again with `tau guard enroll`.",
        "tr": "Yüz modeli değişti. `tau guard enroll` ile yeniden kaydol.",
    },
    "guard.verdict.key_unavailable": {
        "en": "The template key could not be read from the Keychain.",
        "tr": "Şablon anahtarı Anahtar Zinciri'nden okunamadı.",
    },
    "guard.verdict.cooldown": {
        "en": "Too many failed attempts. Wait a moment, then try again.",
        "tr": "Çok fazla başarısız deneme. Biraz bekle, sonra yeniden dene.",
    },
    "guard.verdict.locked": {"en": "tau is locked.", "tr": "tau kilitli."},
    "guard.verdict.touch_id_unavailable": {
        "en": "Touch ID is not available.",
        "tr": "Touch ID kullanılamıyor.",
    },
    "guard.verdict.touch_id_failed": {
        "en": "Touch ID did not confirm you.",
        "tr": "Touch ID seni doğrulamadı.",
    },
    "guard.verdict.unsupported_platform": {
        "en": "The guard works only on macOS.",
        "tr": "Koruma yalnızca macOS'ta çalışır.",
    },
    "guard.verdict.unavailable": {
        "en": "The guard cannot be reached. Start the hub (TauBar → Run the hub, or "
        "`tau hub run`).",
        "tr": "Korumaya ulaşılamıyor. Hub'ı başlat (TauBar → Run the hub ya da `tau hub run`).",
    },
    "guard.verdict.busy": {"en": "Another check is running.", "tr": "Başka bir kontrol sürüyor."},
    "guard.verdict.error": {
        "en": "The check failed. Details are in the log.",
        "tr": "Kontrol başarısız oldu. Ayrıntı günlükte.",
    },
    # challenge steps
    "guard.progress.starting": {"en": "Starting the camera…", "tr": "Kamera açılıyor…"},
    "guard.progress.look": {"en": "Look at the camera.", "tr": "Kameraya bak."},
    "guard.progress.turn_left": {"en": "Turn your head left.", "tr": "Başını sola çevir."},
    "guard.progress.turn_right": {"en": "Turn your head right.", "tr": "Başını sağa çevir."},
    "guard.progress.center": {
        "en": "Look straight at the camera again.",
        "tr": "Yeniden kameraya düz bak.",
    },
    "guard.progress.touch_id": {
        "en": "Touch the Touch ID sensor.",
        "tr": "Touch ID sensörüne dokun.",
    },
    "guard.progress.done": {"en": "Done.", "tr": "Tamam."},
    "guard.progress.look_up": {
        "en": "Tilt your head up a little.",
        "tr": "Başını biraz yukarı kaldır.",
    },
    "guard.progress.look_down": {
        "en": "Tilt your head down a little.",
        "tr": "Başını biraz aşağı indir.",
    },
    "guard.progress.turn_more": {"en": "Turn a little further.", "tr": "Biraz daha çevir."},
    # lock triggers
    "guard.lock_trigger.command": {"en": "locked by command", "tr": "komutla kilitlendi"},
    "guard.lock_trigger.idle": {
        "en": "locked after inactivity",
        "tr": "hareketsizlik nedeniyle kilitlendi",
    },
    "guard.lock_trigger.screen_lock": {
        "en": "locked with the screen",
        "tr": "ekranla birlikte kilitlendi",
    },
    "guard.lock_trigger.sleep": {
        "en": "locked when the Mac slept",
        "tr": "Mac uyuyunca kilitlendi",
    },
    "guard.lock_trigger.max_age": {
        "en": "locked after the longest unlock time",
        "tr": "en uzun açık kalma süresi dolunca kilitlendi",
    },
    "guard.lock_trigger.hub_stop": {
        "en": "locked when the hub stopped",
        "tr": "hub durunca kilitlendi",
    },
    "guard.lock_trigger.telegram": {"en": "locked from Telegram", "tr": "Telegram'dan kilitlendi"},
    "guard.lock_trigger.step_up_failed": {
        "en": "locked after a failed identity check",
        "tr": "başarısız bir kimlik kontrolünden sonra kilitlendi",
    },
    "guard.lock_trigger.startup": {"en": "locked at start", "tr": "başlangıçta kilitli"},
    # step-up, unlock, hints
    "guard.step_up.start": {
        "en": "Confirm it is you: look at the camera.",
        "tr": "Sen olduğunu doğrula: kameraya bak.",
    },
    "guard.step_up.passed": {"en": "Identity confirmed.", "tr": "Kimlik doğrulandı."},
    "guard.step_up.failed": {
        "en": "The guard could not confirm it is you; the action was not run.",
        "tr": "Koruma senin olduğunu doğrulayamadı; işlem çalıştırılmadı.",
    },
    "guard.locked_during_turn": {
        "en": "tau locked; the turn was stopped.",
        "tr": "tau kilitlendi; tur durduruldu.",
    },
    "guard.unlocked": {
        "en": "Unlocked ({method}). Failed attempts since the last unlock: {failures}.",
        "tr": "Kilit açıldı ({method}). Son açılıştan beri başarısız deneme: {failures}.",
    },
    "guard.start_hub": {
        "en": "Start the hub: TauBar → Run the hub, or `tau hub run`.",
        "tr": "Hub'ı başlat: TauBar → Run the hub ya da `tau hub run`.",
    },
    "guard.not_enrolled_hint": {
        "en": "No face is enrolled yet. Run `tau guard setup` at the Mac.",
        "tr": "Henüz kayıtlı yüz yok. Mac'in başında `tau guard setup` çalıştır.",
    },
    # the Touch ID fallback on the lock screen and the terminal lock prompt (issue 114);
    # {how} is the channel's own key hint ("type t and press Enter")
    "guard.fallback.touch_id": {
        "en": "The face check is not working? Use Touch ID instead: {how}.",
        "tr": "Yüz kontrolü çalışmıyor mu? Onun yerine Touch ID kullan: {how}.",
    },
    "guard.fallback.touch_id_or_password": {
        "en": "The face check is not working? Use Touch ID or your Mac password instead: {how}.",
        "tr": "Yüz kontrolü çalışmıyor mu? Onun yerine Touch ID ya da Mac parolanı kullan: {how}.",
    },
    "guard.fallback.confirm": {
        "en": "Confirm in the macOS prompt on the Mac's screen.",
        "tr": "Mac'in ekranındaki macOS isteminde onayla.",
    },
    # /status and tau doctor
    "status.guard": {"en": "Guard: {detail}", "tr": "Koruma: {detail}"},
    "doctor.guard.off": {
        "en": "off (no enrollment marker, and [component.guard] enabled is not true)",
        "tr": "kapalı (kayıt işareti yok ve [component.guard] enabled true değil)",
    },
    "doctor.guard.locked": {
        "en": "active and locked for good: {detail}",
        "tr": "etkin ve kalıcı olarak kilitli: {detail}",
    },
    "doctor.guard.bad_enabled": {
        "en": "[component.guard] enabled must be true or false, not {value}",
        "tr": "[component.guard] enabled true ya da false olmalı, {value} değil",
    },
    "doctor.guard.unknown_keys": {
        "en": "unknown keys in [component.guard]: {keys}",
        "tr": "[component.guard] içinde bilinmeyen anahtarlar: {keys}",
    },
    "doctor.guard.unsupported_platform": {
        "en": "the guard works only on macOS; guarded channels stay locked",
        "tr": "koruma yalnızca macOS'ta çalışır; korunan kanallar kilitli kalır",
    },
    "doctor.guard.enabled_ignored": {
        "en": "([component.guard] enabled = false is ignored while the enrollment marker "
        "exists; `tau guard forget` turns the guard off.)",
        "tr": "(Kayıt işareti varken [component.guard] enabled = false yok sayılır; korumayı "
        "`tau guard forget` kapatır.)",
    },
    "doctor.guard.not_in_services": {
        "en": "active, but [components.hub] services does not list guard; guarded channels "
        "stay locked",
        "tr": "etkin ama [components.hub] services guard içermiyor; korunan kanallar kilitli kalır",
    },
    "doctor.guard.no_hub": {
        "en": "active; no hub runs, so guarded channels stay locked. {hint}",
        "tr": "etkin; çalışan hub yok, bu yüzden korunan kanallar kilitli kalır. {hint}",
    },
    "doctor.guard.no_service": {
        "en": "active, but the running hub has no guard service; guarded channels stay locked "
        "(install tau-guard and restart the hub)",
        "tr": "etkin ama çalışan hub'da koruma servisi yok; korunan kanallar kilitli kalır "
        "(tau-guard kur ve hub'ı yeniden başlat)",
    },
    "doctor.guard.hub_off": {
        "en": "active here, but the running hub reports the guard off; restart the hub",
        "tr": "burada etkin ama çalışan hub korumayı kapalı bildiriyor; hub'ı yeniden başlat",
    },
    "doctor.guard.ok": {
        "en": "active; the hub reports it {state}",
        "tr": "etkin; hub durumunu {state} olarak bildiriyor",
    },
    "doctor.guard.unavailable": {
        "en": "active, but the hub reports it unavailable ({reason}); guarded channels stay "
        "locked. The hub log has the details.",
        "tr": "etkin ama hub onu kullanılamaz bildiriyor ({reason}); korunan kanallar kilitli "
        "kalır. Ayrıntılar hub günlüğünde.",
    },
    "doctor.guard.not_available": {
        "en": "active, but the hub cannot check it right now ({reason}); guarded channels are "
        "refused until it can",
        "tr": "etkin ama hub şu an onu denetleyemiyor ({reason}); denetleyene kadar korunan "
        "kanallar reddedilir",
    },
    "doctor.guard.screen_unknown": {
        "en": "(The hub cannot read the screen lock, as when it runs outside a GUI session; an "
        "unlock then lasts at most idle_lock_minutes.)",
        "tr": "(Hub ekran kilidini okuyamıyor, örneğin grafik oturumun dışında çalışırken; bir "
        "açılış o zaman en fazla idle_lock_minutes sürer.)",
    },
}

_collisions = set(GUARD_MESSAGES) & set(MESSAGES)
assert not _collisions, f"guard message keys collide with tau-core: {sorted(_collisions)}"
register_messages(GUARD_MESSAGES)
