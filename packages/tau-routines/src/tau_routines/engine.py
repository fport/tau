"""The reflex engine: it fires routines on the clock with no model, no network and nobody asked.

Each firing calls the routine's tool through a :class:`~tau_core.TierGate` built for that one
call (ADR 0015 §4):

- ``guard=None``: the engine is an in-hub caller identified by its registration, which was
  approved on a trusted, guarded channel. A routine must work at 07:00 while the owner sleeps
  and the Mac is locked. This file is the engine's entry in the repo rule's allowlist.
- :class:`RefusingApprover`: nobody is asked at firing time, so every tier-2 call the
  exemption does not cover is refused.
- :func:`approved_call`: an ``Exemption`` that returns ``True`` only for the routine's own tool
  with arguments that hash, together with its id, to the stored ``approved_hash``. A routine
  whose file entry was changed behind the registration is refused by the gate and not run.

The gate consults exemptions for tier 2 only; for a tier-0 or tier-1 tool the engine applies
the same check itself before the gate.

**Missed firings.** At every tick each routine's slots since its ``last_slot`` (or its
creation) are counted. Slots at most ``grace_minutes`` old run once; older ones are logged as
``missed``. The slot is recorded before the tool runs, so a crash in the middle never repeats
a physical action. A ``once`` routine is switched off after its slot.

**Failures.** A failed or refused firing is logged and the routine stays on; after three in a
row it pauses itself and the log says so. A successful firing clears the count.

**Events.** Every outcome is an agent event ``routine`` on :attr:`RoutineEngine.events`
(``{id, name, status, tool, slot, ...}``), next to the gate's own ``tool_call`` and
``approval`` events, so channels can show it.

The engine keeps time with its injected ``clock`` and ``sleep``; tests drive :meth:`tick`
directly and never wait.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import secrets
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from strands.types.tools import AgentTool
from tau_core import (
    AgentEvent,
    ApprovalRequest,
    Decision,
    EventBus,
    Exemption,
    Tier,
    TierGate,
    ToolCatalog,
)

from tau_routines.model import Routine, routine_hash, stamp
from tau_routines.registration import OWN_TOOLS
from tau_routines.settings import RoutineError, RoutineSettings
from tau_routines.store import RoutineStore
from tau_routines.triggers import Once

__all__ = [
    "CHANNEL",
    "PAUSE_AFTER",
    "POLL_SECONDS",
    "REFUSAL_NOTE",
    "RUN_TIMEOUT",
    "Firing",
    "RefusingApprover",
    "RoutineEngine",
    "approved_call",
    "run_tool",
]

logger = logging.getLogger(__name__)

CHANNEL = "routine"
"""The channel name of a firing in events and logs."""
POLL_SECONDS = 30.0
"""The longest the engine sleeps, so it notices a changed routines file within this time."""
MIN_SLEEP = 0.5
RUN_TIMEOUT = 120.0
"""How long one firing may take before it counts as failed."""
PAUSE_AFTER = 3
"""Failed firings in a row that pause a routine."""
REFUSAL_NOTE = "A routine runs only the exact call its owner approved when registering it."
MISMATCH_TEXT = "The call does not match the routine's approval; it was not run."
SUMMARY_LIMIT = 200


class RefusingApprover:
    """The approver of a firing: it refuses every request. Nobody is asked when a routine
    fires; the registration's approval covers the routine's own call through the exemption.
    ``refusal_note`` (fixed English) is what the refusal adds."""

    name = "routine"
    timeout_seconds: float | None = None

    def __init__(self, refusal_note: str = REFUSAL_NOTE):
        self.refusal_note = refusal_note

    async def decide(self, request: ApprovalRequest) -> Decision:
        return Decision.REJECTED


def approved_call(routine: Routine) -> Exemption:
    """``True`` only for ``routine``'s tool with arguments that hash to its approval."""
    expected = routine.approved_hash

    def exempt(tool_name: str, arguments: dict[str, Any]) -> bool:
        if not expected or tool_name != routine.tool:
            return False
        return routine_hash(routine.id, tool_name, arguments) == expected

    return exempt


def _summary(result: dict[str, Any]) -> str:
    parts = [block["text"] for block in result.get("content") or [] if "text" in block]
    return " ".join(" ".join(parts).split())[:SUMMARY_LIMIT]


async def run_tool(
    tool: AgentTool, arguments: dict[str, Any], tool_use_id: str
) -> tuple[bool, str]:
    """Run ``tool`` once, without an agent: ``(succeeded, summary)``.

    ``AgentTool.stream`` is what the Strands executor calls: it validates the input against
    the tool's schema, runs a sync function in a worker thread, and yields events whose last
    one carries the tool result. A tool that needs an agent (a ``ToolContext``) fails here.
    """
    tool_use = {"toolUseId": tool_use_id, "name": tool.tool_name, "input": copy.deepcopy(arguments)}
    result: dict[str, Any] | None = None
    async for event in tool.stream(tool_use, {}):  # type: ignore[arg-type]
        candidate = event.get("tool_result") if isinstance(event, dict) else None
        if isinstance(candidate, dict):
            result = candidate
    if result is None:
        return False, "The tool gave no result."
    return result.get("status") == "success", _summary(result)


@dataclass(frozen=True)
class Firing:
    """One outcome of a tick: ``ok``, ``failed``, ``refused``, ``missed`` or ``paused``."""

    routine_id: str
    name: str
    status: str
    slot: datetime | None
    detail: str = ""
    count: int = 1
    """How many slots this covers: the slots of one run, or of one ``missed`` entry."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RoutineEngine:
    """Fires the routines of one store. Build it, then call :meth:`tick` (tests) or await
    :meth:`run` (the hub service)."""

    def __init__(
        self,
        store: RoutineStore,
        settings: RoutineSettings,
        *,
        tools: Iterable[AgentTool],
        events: EventBus | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        run_timeout: float = RUN_TIMEOUT,
    ):
        self.store = store
        self.settings = settings
        self.events = events or EventBus()
        self.catalog = ToolCatalog()
        for tool in tools:
            if tool.tool_name in OWN_TOOLS:
                continue
            try:
                self.catalog.add(tool)
            except Exception as exc:
                logger.warning("routines: tool %s cannot run in a routine: %s", tool, exc)
        self._clock = clock or _utc_now
        self._sleep = sleep or asyncio.sleep
        self.run_timeout = run_timeout
        self._routines: list[Routine] = []
        self._stamp: tuple[int, int, int] | None | bool = False  # False = never read
        self._trouble = False
        """The last tick hit an error: wait :data:`POLL_SECONDS` before the next one."""

    # -- reading the file ----------------------------------------------------------------

    @property
    def routines(self) -> list[Routine]:
        return list(self._routines)

    def refresh(self) -> list[Routine]:
        """Re-read ``routines.json`` when it changed since the last read."""
        current = self.store.stamp()
        if current != self._stamp:
            try:
                self._routines = self.store.load()
            except RoutineError as exc:
                logger.error("routines: %s; keeping the routines read before", exc)
            else:
                logger.info("routines: %d routine(s) loaded", len(self._routines))
            self._stamp = current
        return self.routines

    # -- the clock -----------------------------------------------------------------------

    def _start(self, routine: Routine) -> datetime:
        return routine.last_slot or routine.created

    def next_due(self) -> datetime | None:
        """The earliest pending slot of an enabled routine (it may lie in the past)."""
        due: list[datetime] = []
        for routine in self._routines:
            if not routine.enabled:
                continue
            slot = routine.trigger.next_after(
                self._start(routine), zone=self.settings.zone, anchor=routine.created
            )
            if slot is not None:
                due.append(slot)
        return min(due) if due else None

    def delay(self) -> float:
        """Seconds until the next tick: the next slot, at most :data:`POLL_SECONDS`."""
        upcoming = self.next_due()
        if upcoming is None or self._trouble:
            return POLL_SECONDS
        seconds = (upcoming - self._clock()).total_seconds()
        return min(POLL_SECONDS, max(MIN_SLEEP, seconds))

    async def run(self) -> None:
        """Tick, sleep until the next slot (or :data:`POLL_SECONDS`), forever."""
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._trouble = True
                logger.exception("routines: a tick failed; trying again")
            await self._sleep(self.delay())

    async def tick(self) -> list[Firing]:
        """Handle every slot that fell due up to now."""
        self.refresh()
        now = self._clock()
        firings: list[Firing] = []
        self._trouble = False
        for routine in self.routines:
            if not routine.enabled:
                continue
            try:
                firings += await self._handle(routine, now)
            except (RoutineError, OSError) as exc:
                self._trouble = True
                logger.error("routines: routine %s could not be handled: %s", routine.id, exc)
        if firings:
            self.refresh()
        return firings

    # -- one routine ---------------------------------------------------------------------

    def _emit(self, firing: Firing, routine: Routine) -> None:
        data: dict[str, Any] = {
            "id": firing.routine_id,
            "name": firing.name,
            "status": firing.status,
            "tool": routine.tool,
            "slot": stamp(firing.slot) if firing.slot is not None else None,
            "detail": firing.detail,
            "count": firing.count,
        }
        self.events.emit(AgentEvent.create("routine", data, clock=self._clock))

    def _record(self, routine: Routine, firing: Firing) -> Firing:
        self.store.log(
            firing.status,
            routine,
            at=stamp(self._clock()),
            slot=stamp(firing.slot) if firing.slot is not None else None,
            detail=firing.detail or None,
            count=firing.count if firing.count != 1 else None,
        )
        self._emit(firing, routine)
        return firing

    async def _handle(self, routine: Routine, now: datetime) -> list[Firing]:
        zone, anchor = self.settings.zone, routine.created
        start = self._start(routine)
        count, latest = routine.trigger.between(start, now, zone=zone, anchor=anchor)
        if not count or latest is None:
            return []
        cutoff = now - timedelta(minutes=self.settings.grace_minutes)
        old, last_old = routine.trigger.between(
            start, cutoff - timedelta(microseconds=1), zone=zone, anchor=anchor
        )
        recent = count - old

        # Record the slot before anything runs: a crash never repeats a physical action, and a
        # routine changed meanwhile waits for the next tick.
        with self.store.edit() as routines:
            index = next((i for i, r in enumerate(routines) if r.id == routine.id), None)
            if index is None:
                return []
            current = routines[index]
            if (
                not current.enabled
                or not current.same_call(routine)
                or current.last_slot != routine.last_slot
            ):
                return []
            routines[index] = current.with_changes(
                last_slot=latest,
                enabled=False if isinstance(routine.trigger, Once) else current.enabled,
            )

        firings: list[Firing] = []
        if old:
            detail = f"{old} firing(s) more than {self.settings.grace_minutes} minutes late"
            firings.append(
                self._record(
                    routine,
                    Firing(routine.id, routine.name, "missed", last_old, detail, count=old),
                )
            )
        if recent:
            firings += await self._fire(routine, latest, recent)
        return firings

    async def _fire(self, routine: Routine, slot: datetime, covers: int) -> list[Firing]:
        tool_use_id = f"routine-{routine.id}-{secrets.token_hex(4)}"
        arguments = copy.deepcopy(routine.arguments)
        exemption = approved_call(routine)
        gate = TierGate(
            self.catalog,
            RefusingApprover(),
            self.events,
            session_id=None,
            channel=CHANNEL,
            exemptions=[exemption],
            guard=None,  # the reflex engine (ADR 0015 §4): bounded by the approved registration
        )
        started = time.monotonic()
        tier = self.catalog.tier(routine.tool)
        approval: str | None = None
        if (
            tier is not None
            and tier < Tier.PHYSICAL
            and exemption(routine.tool, arguments) is not True
        ):
            allowed, refusal = False, MISMATCH_TEXT  # the gate checks exemptions for tier 2 only
        else:
            try:
                allowed, refusal, approval = await gate.check(
                    routine.tool, arguments, tool_use_id=tool_use_id
                )
            except Exception:
                logger.exception("routines: the tier gate failed for %s; refusing", routine.id)
                allowed, refusal = False, MISMATCH_TEXT

        tool = self.catalog.get(routine.tool)
        if allowed and tool is not None:
            try:
                ok, summary = await asyncio.wait_for(
                    run_tool(tool, arguments, tool_use_id), self.run_timeout
                )
            except TimeoutError:
                ok, summary = False, f"The tool did not finish within {self.run_timeout:g} s."
            except Exception as exc:
                ok, summary = False, f"{type(exc).__name__}: {exc}"[:SUMMARY_LIMIT]
            status, gate_status = ("ok", "ok") if ok else ("failed", "error")
        else:
            status, gate_status, summary = "refused", "rejected", refusal or MISMATCH_TEXT
        gate.record(
            tool_name=routine.tool,
            arguments=arguments,
            status=gate_status,
            summary=summary,
            approval=approval,
            duration_ms=int((time.monotonic() - started) * 1000),
            tool_use_id=tool_use_id,
        )

        paused = False
        failures = 0
        with self.store.edit() as routines:
            index = next((i for i, r in enumerate(routines) if r.id == routine.id), None)
            if index is not None and routines[index].same_call(routine):
                current = routines[index]
                failures = 0 if status == "ok" else current.failures + 1
                paused = current.enabled and failures >= PAUSE_AFTER
                routines[index] = current.with_changes(
                    failures=failures, enabled=current.enabled and not paused
                )

        firings = [
            self._record(
                routine, Firing(routine.id, routine.name, status, slot, summary, count=covers)
            )
        ]
        if paused:
            detail = f"paused after {failures} failed firings in a row"
            firings.append(
                self._record(routine, Firing(routine.id, routine.name, "paused", slot, detail))
            )
            logger.warning("routines: routine %s (%s) %s", routine.id, routine.name, detail)
        return firings
