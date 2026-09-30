"""The ``guard`` hub service (ADR 0008 decisions 2, 3, 9, 10 and 13).

A ``tau.hub_services`` component (``guard = "tau_guard.service:make_service"``) that owns the
guard's state inside ``tau hub run``:

- **Inert when inactive.** Without the marker ``TAU_DATA_DIR/guard/enrolled`` and without
  ``[component.guard] enabled = true`` it only reports ``guard: {state: "off"}`` in ``/status``:
  no thread, no route, no cv2 or pyobjc import.
- **Active.** Every start is ``locked`` (trigger ``startup``); an unlock is never restored,
  not even after ``kill -9``. The :class:`~tau_guard.state.GuardMachine` holds the state, a
  reflex loop (a daemon thread, every 2 s) and an inline check at every admission and
  verification apply the reflex locks, and each attempt runs in its own worker subprocess
  (:mod:`tau_guard.runner`). The service registers the protected ``/guard/*`` routes of
  :mod:`tau_guard.routes` and writes ``guard/audit.jsonl``.
- **Active but broken** (a bad knob, an unsupported platform, no presence source, a start
  failure): ``state: "unavailable"`` with a reason; the routes answer ``unavailable`` and the
  ``/status`` block is never omitted.

Routes (all protected; ``ControlApi`` checks the signature and signs the answer):

- ``GET /guard/status?since=<seq>&wait=<0..25>[&attempt=<id>]``: every ``GuardStatus`` field
  plus ``enrollment``, ``screen`` (``locked``, ``unlocked`` or ``unknown``) and
  ``step_up_active``; ``attempt`` is the running attempt, or with ``attempt=<id>`` that
  attempt's record (queued, running or finished within the last 120 s), else ``null``.
- ``POST /guard/admit`` → ``{allowed, reason, enrollment, state}``, reflexes evaluated inline.
- ``POST /guard/verify`` → ``202 {attempt, seq}`` (``seq`` is just below the attempt's, so the
  first poll answers at once); refusals are ``409 {reason}`` (``locked``, ``busy``,
  ``not_enrolled``, ``unavailable``) or ``429 {reason: "cooldown", retry_after}``, never 403.
- ``POST /guard/cancel`` → ``{ok}``; ``POST /guard/lock`` → ``{state: "locked"}``
  (idempotent); ``POST /guard/enroll`` → ``202 {attempt, seq}`` (the worker answers
  ``not_enrolled`` until issue 112).

The open ``/status`` gains only ``guard: {state, enrolled, available, reason}``. ``reason``
says why the guard is unavailable, ``reflex_stalled`` when the reflex loop missed its ticks, or
``screen_unknown`` while the screen-lock state cannot be read (no GUI session).

In the hub, :class:`GuardService` implements ``tau_core.Guard`` directly (find it with
``hub.find_service("guard")`` plus an ``isinstance(Guard)`` check) and offers
:meth:`GuardService.subscribe` and :meth:`GuardService.face_fresh`. The hub log gets no
verdicts and no scores; those go to the audit log only.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import replace
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tau_core import Admission, Config, GuardProgress, GuardStatus, GuardTurn, GuardVerdict
from tau_core.guard import (
    LOCK_TRIGGERS,
    PROGRESS_STEPS,
    VERDICT_REASONS,
    config_problem,
    guard_active,
    read_enrollment,
    status_from_json,
)
from tau_core.hub import ControlApi, ControlRequest

from tau_guard.audit import AuditLog, secure_dir
from tau_guard.config import GuardSettings, SettingsError, parse_settings, stricter_policy
from tau_guard.presence import PresenceSource, PresenceUnavailable, QuartzPresence
from tau_guard.routes import SCHEMAS, BadRequest, parse_body, parse_query
from tau_guard.runner import DEFAULT_COMMAND, Progress, WorkerRun
from tau_guard.state import (
    REFLEX_STALE,
    Attempt,
    Clock,
    GuardMachine,
    Outcome,
    Reading,
    Refusal,
    SystemClock,
)

if TYPE_CHECKING:
    from tau_core.approval import ApprovalRequest
    from tau_core.hub.daemon import Hub

__all__ = ["GUARD_DIR", "REFLEX_INTERVAL", "SERVICE_NAME", "GuardService", "make_service"]

logger = logging.getLogger(__name__)

SERVICE_NAME = "guard"
GUARD_DIR = "guard"
REFLEX_INTERVAL = 2.0
STOP_WAIT = 3.0
"""How long :meth:`GuardService.stop` waits for workers to die (SIGTERM, 1 s, SIGKILL)."""
ATTEMPT_LIMIT = 120.0
SUCCESS_METHODS = ("face", "touch_id")
STATUS_FIELDS = (
    "state",
    "enrolled",
    "method",
    "since",
    "expires_at",
    "face_seen_at",
    "seq",
    "attempt",
    "last_verdict",
    "lock_trigger",
    "failures",
    "cooldown_until",
    "camera",
    "reason",
    "enrollment",
    "screen",
    "step_up_active",
)

Subscriber = Callable[[GuardStatus], None]


class GuardService:
    """The ``guard`` hub service and the in-hub ``tau_core.Guard``.

    Tests inject a ``clock``, a ``presence`` source, a ``worker_command`` (a fake worker
    script), the ``platform``, ``reflex_loop=False`` (then they call :meth:`tick`) and a short
    ``attempt_timeout``."""

    name = SERVICE_NAME

    def __init__(
        self,
        config: Config,
        *,
        clock: Clock | None = None,
        presence: PresenceSource | None = None,
        worker_command: Sequence[str] | None = None,
        worker_env: Mapping[str, str] | None = None,
        platform: str | None = None,
        reflex_interval: float = REFLEX_INTERVAL,
        reflex_loop: bool = True,
        attempt_timeout: float | None = None,
    ) -> None:
        self.config = config
        self.clock: Clock = clock or SystemClock()
        self.presence = presence
        self.worker_command = tuple(worker_command or DEFAULT_COMMAND)
        self.worker_env = dict(worker_env) if worker_env is not None else None
        self.platform = sys.platform if platform is None else platform
        self.reflex_interval = reflex_interval
        self.reflex_loop = reflex_loop
        self.attempt_timeout = attempt_timeout
        self.mode = "idle"
        """``idle`` (not started), ``off``, ``active``, ``unavailable`` or ``stopped``."""
        self.reason: str | None = None
        self.settings: GuardSettings | None = None
        self.machine: GuardMachine | None = None
        self.audit = AuditLog(self.guard_dir, now=self.clock.wall)
        self._cond = threading.Condition(threading.RLock())
        self._runs: dict[str, WorkerRun] = {}
        self._all_runs: list[WorkerRun] = []
        self._subscribers: list[Subscriber] = []
        self._listeners: set[Callable[[], None]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event = threading.Event()
        self._reflex_thread: threading.Thread | None = None
        self._routes: list[tuple[str, str]] = []
        self._presence_failed = False

    @property
    def guard_dir(self) -> Path:
        return self.config.data_dir / GUARD_DIR

    @property
    def routes(self) -> list[tuple[str, str]]:
        """The ``(method, path)`` routes this service registered."""
        return list(self._routes)

    # -- HubService --------------------------------------------------------------------------

    async def start(self, hub: Hub) -> None:
        self._loop = asyncio.get_running_loop()
        hub.add_status_source(self._status_source)
        table = self.config.component("guard")
        if not guard_active(self.config) and config_problem(table) is None:
            self.mode = "off"
            logger.info("guard: inactive (no enrollment marker, enabled is not true)")
            return
        try:
            self._activate(hub, table)
        except Exception:
            logger.exception("guard: the service failed to start; guarded channels stay locked")
            self._unavailable("error")

    def _activate(self, hub: Hub, table: dict[str, Any]) -> None:
        self.mode = "active"
        secure_dir(self.guard_dir)
        self.machine = GuardMachine(self.clock)
        try:
            self.settings = parse_settings(table)
        except SettingsError as exc:
            for problem in exc.problems:
                logger.error("guard: [component.guard] %s", problem)
            self._unavailable("config")
        else:
            limits = self.settings.limits()
            if self.attempt_timeout is not None:
                limits = replace(limits, attempt_timeout=self.attempt_timeout)
            self.machine.limits = limits
        api = hub.find_service("control-api")
        if isinstance(api, ControlApi):
            self._register(api)
        else:
            logger.error("guard: the hub has no control API; guarded channels stay locked")
            self._unavailable("no_control_api")
        if self.platform != "darwin":
            logger.error("guard: the guard works only on macOS; guarded channels stay locked")
            self._unavailable("unsupported_platform")
        if self.mode == "active" and self.presence is None:
            try:
                self.presence = QuartzPresence()
            except PresenceUnavailable as exc:
                logger.error("guard: %s; guarded channels stay locked", exc)
                self._unavailable("presence_unavailable")
        with self._transaction():
            pass  # writes the startup lock to the audit log
        if self.mode != "active":
            return
        self.tick()
        if self.reflex_loop:
            self._reflex_thread = threading.Thread(
                target=self._reflex_main, name="tau-guard-reflex", daemon=True
            )
            self._reflex_thread.start()
        logger.info("guard: active and locked")

    async def stop(self) -> None:
        if self.mode in ("idle", "off", "stopped"):
            return
        self._stop_event.set()
        if self.machine is not None:
            with self._transaction() as machine:
                machine.lock("hub_stop")
        with self._cond:
            self.mode = "stopped"
            self.reason = "stopped"
            self._cond.notify_all()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + STOP_WAIT
        thread = self._reflex_thread
        while loop.time() < deadline:
            busy = any(run.alive for run in self._all_runs)
            if not busy and (thread is None or not thread.is_alive()):
                break
            await asyncio.sleep(0.02)
        for run in self._all_runs:
            if run.alive:
                logger.error("guard: worker pid %s outlived the hub stop", run.pid)
        self._all_runs.clear()
        self._notify_listeners()

    def _unavailable(self, reason: str) -> None:
        with self._cond:
            if self.mode != "unavailable":
                self.mode = "unavailable"
                self.reason = reason
            if self.machine is not None:
                self.machine.seq += 1
            self._cond.notify_all()

    # -- the reflex loop ---------------------------------------------------------------------

    def _reflex_main(self) -> None:
        while not self._stop_event.wait(self.reflex_interval):
            self.tick()

    def tick(self) -> None:
        """One reflex tick (the loop calls it every 2 s; tests call it directly)."""
        if self.mode != "active" or self.machine is None:
            return
        try:
            reading = self._read_presence()
            with self._transaction() as machine:
                machine.observe(reading, tick=True)
        except Exception:
            logger.exception("guard: a reflex tick failed")

    def _read_presence(self) -> Reading:
        source = self.presence
        if source is None:
            return Reading(None, None)
        try:
            reading = source.read()
        except Exception:
            if not self._presence_failed:
                self._presence_failed = True
                logger.exception("guard: the presence source failed; treating it as unknown")
            return Reading(None, None)
        idle = reading.idle_seconds
        screen = reading.screen_locked
        return Reading(
            float(idle) if isinstance(idle, int | float) and not isinstance(idle, bool) else None,
            screen if isinstance(screen, bool) else None,
        )

    # -- transactions ------------------------------------------------------------------------

    @contextmanager
    def _transaction(self) -> Iterator[GuardMachine]:
        """Hold the lock, run the machine, then apply its effects (audit, kill, spawn) and
        wake every waiter when ``seq`` moved."""
        machine = self.machine
        assert machine is not None
        with self._cond:
            before = machine.seq
            try:
                yield machine
            finally:
                self._apply(machine)
                changed = machine.seq != before
                status = self._guard_status() if changed else None
                if changed:
                    self._cond.notify_all()
        if status is not None:
            self._notify(status)

    def _apply(self, machine: GuardMachine) -> None:
        while True:
            effects = machine.drain()
            if not (effects.spawn or effects.kill or effects.audit):
                return
            for entry in effects.audit:
                fields = dict(entry)
                self.audit.record(fields.pop("event"), **fields)
            for attempt_id, reason in effects.kill:
                run = self._runs.pop(attempt_id, None)
                if run is not None:
                    run.stop(reason)
            for attempt in effects.spawn:
                self._spawn(attempt)

    def _spawn(self, attempt: Attempt) -> None:
        assert self.machine is not None
        op = "enroll" if attempt.kind == "enroll" else "verify"
        settings = self.settings
        request = {
            "v": 1,
            "op": op,
            "kind": attempt.kind,
            "attempt": attempt.id,
            "data_dir": str(self.config.data_dir),
            "policy": attempt.policy,
            "settings": settings.worker() if settings is not None else {},
            "challenge_fresh": attempt.challenge_fresh,
        }
        run = WorkerRun(
            op,
            request,
            command=self.worker_command,
            log_dir=self.guard_dir,
            timeout=self.machine.limits.attempt_timeout,
            on_progress=partial(self._on_progress, attempt.id),
            on_done=partial(self._on_done, attempt.id),
            env=self.worker_env,
        )
        self._runs[attempt.id] = run
        self._all_runs = [r for r in self._all_runs if r.alive] + [run]
        run.start()

    def _on_progress(self, attempt_id: str, progress: Progress) -> None:
        with self._transaction() as machine:
            machine.progress(
                attempt_id, step=progress.step, hint=progress.hint, deadline=progress.deadline
            )

    def _on_done(self, attempt_id: str, outcome: Outcome) -> None:
        if self.machine is None:
            return
        with self._transaction() as machine:
            self._runs.pop(attempt_id, None)
            machine.finish(attempt_id, outcome)

    # -- notifications -----------------------------------------------------------------------

    def subscribe(self, callback: Subscriber) -> Callable[[], None]:
        """Call ``callback(GuardStatus)`` after every change (``seq`` moved). Callbacks run on
        the hub's event loop when the service runs in a hub, else in the thread that made the
        change; a raising callback is logged. Returns a function that unsubscribes."""
        with self._cond:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._cond:
                with suppress(ValueError):
                    self._subscribers.remove(callback)

        return unsubscribe

    def _notify(self, status: GuardStatus) -> None:
        with self._cond:
            subscribers = list(self._subscribers)
        loop = self._loop
        for callback in subscribers:
            if loop is not None and not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(_deliver, callback, status)
                    continue
                except RuntimeError:
                    pass
            _deliver(callback, status)
        self._notify_listeners()

    def _notify_listeners(self) -> None:
        with self._cond:
            listeners = list(self._listeners)
        for wake in listeners:
            wake()

    async def _wait_change(self, since: int, timeout: float) -> None:
        """Wait until ``seq`` differs from ``since``, the service stops, or ``timeout``."""
        loop = asyncio.get_running_loop()
        event = asyncio.Event()

        def wake() -> None:
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(event.set)

        with self._cond:
            self._listeners.add(wake)
        try:
            if self._seq() != since or self.mode != "active":
                return
            with suppress(TimeoutError):
                await asyncio.wait_for(event.wait(), max(0.0, timeout))
        finally:
            with self._cond:
                self._listeners.discard(wake)

    # -- status ------------------------------------------------------------------------------

    def _seq(self) -> int:
        return self.machine.seq if self.machine is not None else 0

    def _enrollment(self) -> str | None:
        return read_enrollment(self.config)

    def _payload(self, attempt_id: str | None = None, *, specific: bool = False) -> dict:
        """The ``/guard/status`` answer (hold the lock)."""
        enrollment = self._enrollment()
        payload: dict[str, Any] = dict.fromkeys(STATUS_FIELDS)
        payload.update(
            enrolled=enrollment is not None,
            enrollment=enrollment,
            seq=self._seq(),
            failures=0,
            step_up_active=False,
        )
        machine = self.machine
        if self.mode != "active" or machine is None:
            payload.update(state="unavailable", reason=self.reason or "unavailable")
            return payload
        payload.update(machine.snapshot())
        if specific:
            payload["attempt"] = machine.record(attempt_id) if attempt_id else None
        else:
            payload["attempt"] = machine.running_record()
        return payload

    def _guard_status(self) -> GuardStatus:
        return status_from_json(self._payload())

    def public_status(self) -> dict[str, Any]:
        """The ``guard`` block of the open ``/status``: ``{state, enrolled, available,
        reason}`` and nothing more (``{state: "off"}`` while inactive)."""
        if self.mode in ("idle", "off"):
            return {"state": "off"}
        enrolled = self._enrollment() is not None
        with self._cond:
            machine = self.machine
            if self.mode != "active" or machine is None:
                reason = self.reason or "unavailable"
                return {
                    "state": "unavailable",
                    "enrolled": enrolled,
                    "available": False,
                    "reason": reason,
                }
            tick = machine.last_tick
            stalled = tick is None or self.clock.monotonic() - tick > REFLEX_STALE
            reason = "reflex_stalled" if stalled else None
            if reason is None and machine.screen == "unknown":
                reason = "screen_unknown"
            return {
                "state": machine.state,
                "enrolled": enrolled,
                "available": not stalled,
                "reason": reason,
            }

    def _status_source(self) -> dict[str, Any]:
        try:
            return {"guard": self.public_status()}
        except Exception:
            logger.exception("guard: the status block failed")
            return {
                "guard": {
                    "state": "unavailable",
                    "enrolled": False,
                    "available": False,
                    "reason": "error",
                }
            }

    # -- operations (thread-safe, synchronous) -----------------------------------------------

    def _admit_sync(self, turn: GuardTurn) -> tuple[bool, str, str | None, str]:
        enrollment = self._enrollment()
        if self.mode != "active" or self.machine is None:
            return False, "unavailable", enrollment, "unavailable"
        reading = self._read_presence()
        with self._transaction() as machine:
            machine.observe(reading)
            allowed, reason = machine.admission(enrolled=enrollment is not None)
            state = machine.state
        return allowed, reason, enrollment, state

    def _request_sync(
        self,
        kind: str,
        *,
        channel: str,
        client_id: str,
        request_id: str | None = None,
        tool: str | None = None,
        policy: Mapping[str, str] | None = None,
    ) -> tuple[Attempt | Refusal, int]:
        if self.mode != "active" or self.machine is None:
            return Refusal("unavailable"), self._seq()
        if kind != "enroll" and self._enrollment() is None:
            return Refusal("not_enrolled"), self._seq()
        reading = self._read_presence() if kind != "enroll" else None
        with self._transaction() as machine:
            if reading is not None:
                machine.observe(reading)
            hub_policy = self.settings.policy() if self.settings is not None else {}
            result = machine.request(
                kind,
                channel=channel,
                client_id=client_id,
                request_id=request_id,
                tool=tool,
                policy=stricter_policy(hub_policy, policy),
            )
            seq = max(0, result.seq - 1) if isinstance(result, Attempt) else machine.seq
        return result, seq

    def _cancel_sync(self, client_id: str, attempt_id: str | None) -> bool:
        if self.mode != "active" or self.machine is None:
            return False
        with self._transaction() as machine:
            return machine.cancel(client_id, attempt_id)

    def _lock_sync(self, trigger: str, *, channel: str | None, client_id: str | None) -> None:
        if self.machine is None or self.mode not in ("active", "unavailable"):
            return
        with self._transaction() as machine:
            machine.lock(trigger, channel=channel, client_id=client_id)

    # -- routes ------------------------------------------------------------------------------

    def _register(self, api: ControlApi) -> None:
        handlers = {
            ("GET", "/guard/status"): self._route_status,
            ("POST", "/guard/admit"): self._route_admit,
            ("POST", "/guard/verify"): self._route_verify,
            ("POST", "/guard/cancel"): self._route_cancel,
            ("POST", "/guard/lock"): self._route_lock,
            ("POST", "/guard/enroll"): self._route_enroll,
        }
        assert set(handlers) == set(SCHEMAS)
        for (method, path), handler in handlers.items():
            api.add_route(method, path, self._validated((method, path), handler))
            self._routes.append((method, path))

    def _validated(
        self, route: tuple[str, str], handler: Callable[[dict[str, Any]], tuple[int, Any]]
    ) -> Callable[[ControlRequest], tuple[int, Any]]:
        def handle(request: ControlRequest) -> tuple[int, Any]:
            try:
                if route[0] == "GET":
                    parsed = parse_query(route, request.query)
                else:
                    parsed = parse_body(route, request.json())
            except (BadRequest, ValueError) as exc:
                return 400, {"reason": "error", "error": str(exc)}
            return handler(parsed)

        return handle

    def _route_status(self, query: dict[str, Any]) -> tuple[int, Any]:
        since = query.get("since")
        wait = float(query.get("wait", 0.0))
        attempt_id = query.get("attempt")
        deadline = time.monotonic() + wait
        with self._cond:
            # Wait only while nothing changed. A ``since`` above the current seq comes from a
            # hub that ran before this one (seq starts over), so it is answered at once.
            while since is not None and self._seq() == since and self.mode == "active":
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                self._cond.wait(left)
            return 200, self._payload(attempt_id, specific="attempt" in query)

    def _route_admit(self, body: dict[str, Any]) -> tuple[int, Any]:
        turn = GuardTurn(body["channel"], body.get("session_id"), body["client_id"])
        allowed, reason, enrollment, state = self._admit_sync(turn)
        return 200, {"allowed": allowed, "reason": reason, "enrollment": enrollment, "state": state}

    def _route_verify(self, body: dict[str, Any]) -> tuple[int, Any]:
        result, seq = self._request_sync(
            body["kind"],
            channel=body["channel"],
            client_id=body["client_id"],
            request_id=body.get("request_id"),
            tool=body.get("tool"),
            policy=body.get("policy"),
        )
        return _answer(result, seq)

    def _route_enroll(self, body: dict[str, Any]) -> tuple[int, Any]:
        result, seq = self._request_sync("enroll", channel="enroll", client_id=body["client_id"])
        return _answer(result, seq)

    def _route_cancel(self, body: dict[str, Any]) -> tuple[int, Any]:
        return 200, {"ok": self._cancel_sync(body["client_id"], body.get("attempt"))}

    def _route_lock(self, body: dict[str, Any]) -> tuple[int, Any]:
        trigger = body.get("trigger") or "command"
        self._lock_sync(trigger, channel=body["channel"], client_id=body["client_id"])
        return 200, {"state": "locked"}

    # -- tau_core.Guard ----------------------------------------------------------------------

    async def status(self) -> GuardStatus:
        if self.mode in ("idle", "off"):
            return GuardStatus(state="off")
        with self._cond:
            return self._guard_status()

    async def watch(self, since: int, *, wait: float = 25.0) -> GuardStatus:
        wait = max(0.0, min(float(wait), 25.0))
        if self.mode == "active":
            await self._wait_change(int(since), wait)
        elif since >= 0:
            await asyncio.sleep(wait)  # nothing changes any more: keep a watcher from spinning
        return await self.status()

    async def admit(self, turn: GuardTurn) -> Admission:
        try:
            allowed, reason, _, _ = self._admit_sync(turn)
        except Exception:
            logger.exception("guard: admission failed; refusing")
            return Admission(False, "error")
        return Admission(allowed, reason)

    async def unlock(
        self,
        *,
        channel: str,
        client_id: str,
        kind: str = "unlock",
        on_progress: Callable[[GuardProgress], None] | None = None,
    ) -> GuardVerdict:
        if kind not in ("unlock", "recheck"):
            return GuardVerdict(False, "error")
        try:
            return await self._attempt(kind, channel, client_id, on_progress)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("guard: unlock failed")
            return GuardVerdict(False, "error")

    async def step_up(
        self,
        request: ApprovalRequest,
        *,
        client_id: str,
        on_progress: Callable[[GuardProgress], None] | None = None,
    ) -> bool:
        try:
            verdict = await self._attempt(
                "step_up",
                request.channel,
                client_id,
                on_progress,
                request_id=request.request_id,
                tool=request.tool,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("guard: step-up failed")
            return False
        return verdict.ok is True

    async def cancel(self, *, client_id: str) -> None:
        try:
            self._cancel_sync(client_id, None)
        except Exception:
            logger.exception("guard: cancel failed")

    async def lock(self, *, channel: str, client_id: str, trigger: str = "command") -> None:
        try:
            self._lock_sync(
                trigger if trigger in LOCK_TRIGGERS else "command",
                channel=channel,
                client_id=client_id,
            )
        except Exception:
            logger.exception("guard: lock failed")

    def face_fresh(self, seconds: float) -> bool:
        """The guard is unlocked and the last face match is at most ``seconds`` old (the
        reflexes are evaluated first). For voice (issue 118)."""
        if self.mode != "active" or self.machine is None:
            return False
        reading = self._read_presence()
        with self._transaction() as machine:
            machine.observe(reading)
            return machine.face_fresh(seconds)

    async def _attempt(
        self,
        kind: str,
        channel: str,
        client_id: str,
        on_progress: Callable[[GuardProgress], None] | None,
        *,
        request_id: str | None = None,
        tool: str | None = None,
    ) -> GuardVerdict:
        result, _ = self._request_sync(
            kind, channel=channel, client_id=client_id, request_id=request_id, tool=tool
        )
        if isinstance(result, Refusal):
            return GuardVerdict(False, result.reason, None, result.retry_after)
        attempt_id = result.id
        loop = asyncio.get_running_loop()
        deadline = loop.time() + ATTEMPT_LIMIT
        reported: int | None = None
        try:
            while True:
                with self._cond:
                    machine = self.machine
                    record = machine.record(attempt_id) if machine is not None else None
                    state = machine.state if machine is not None else "unavailable"
                    current = self._seq()
                if record is None:
                    return GuardVerdict(False, "unavailable")
                if record["seq"] != reported and record["step"] in PROGRESS_STEPS:
                    reported = record["seq"]
                    _report(on_progress, record)
                if record["done"]:
                    return _verdict(record, state)
                left = deadline - loop.time()
                if left <= 0:
                    self._cancel_sync(client_id, attempt_id)
                    return GuardVerdict(False, "timeout")
                if self.mode != "active":
                    return GuardVerdict(False, "unavailable")
                await self._wait_change(current, min(left, 25.0))
        except asyncio.CancelledError:
            self._cancel_sync(client_id, attempt_id)
            raise


def _answer(result: Attempt | Refusal, seq: int) -> tuple[int, Any]:
    if isinstance(result, Refusal):
        payload: dict[str, Any] = {"reason": result.reason}
        if result.retry_after is not None:
            payload["retry_after"] = result.retry_after
        return (429 if result.reason == "cooldown" else 409), payload
    return 202, {"attempt": result.id, "seq": seq}


def _verdict(record: Mapping[str, Any], state: str) -> GuardVerdict:
    reason = record.get("reason")
    reason = reason if reason in VERDICT_REASONS else "error"
    retry = record.get("retry_after")
    retry_after = float(retry) if isinstance(retry, int | float) else None
    if record.get("ok") is True:
        method = record.get("method")
        if reason == "match" and method in SUCCESS_METHODS and state == "unlocked":
            return GuardVerdict(True, "match", str(method))
        return GuardVerdict(False, "error")
    return GuardVerdict(False, "error" if reason == "match" else reason, None, retry_after)


def _report(on_progress: Callable[[GuardProgress], None] | None, record: Mapping) -> None:
    if on_progress is None:
        return
    deadline = record.get("deadline")
    try:
        on_progress(
            GuardProgress(
                step=str(record["step"]),
                seq=int(record["seq"]),
                deadline=datetime.fromisoformat(deadline) if isinstance(deadline, str) else None,
                hint=record.get("hint"),
            )
        )
    except Exception:
        logger.exception("guard: a progress callback failed")


def _deliver(callback: Subscriber, status: GuardStatus) -> None:
    try:
        callback(status)
    except Exception:
        logger.exception("guard: a subscriber failed")


def make_service(config: Config) -> GuardService:
    """The ``tau.hub_services`` factory."""
    return GuardService(config)
