"""Registering and changing routines: one tier-2 approval on every path.

Every path that registers a routine, or changes what one does, asks through a tier gate for
one call of the ``add_routine`` tool (tier 2): ``tau routine add`` and ``tau routine edit``
with the terminal's approver and the owner guard, a chat turn with its channel's approver,
and later the web app's form (184) with its own. The request shows the whole definition in
plain words (:func:`describe`): the trigger, the tool, its tier and the exact arguments. Only
after the approval (and the guard's step-up) is the routine stored, with its
``approved_hash``.

Changing the trigger, the tool or the arguments is a new registration of the same id
(``replaces``): it asks again, and a rejection leaves the stored routine as it was. Renaming,
pausing, resuming and removing change nothing a routine does and are free.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from strands.types.tools import AgentTool

from tau_core import Config, Tier, TierGate, UntieredToolError, effect_of, tier_of
from tau_core.agent import discovered_tools
from tau_core.routines.model import (
    NAME_LIMIT,
    Routine,
    canonical_json,
    check_arguments,
    routine_hash,
)
from tau_core.routines.settings import RoutineError, RoutineSettings
from tau_core.routines.store import RoutineStore, find_routine
from tau_core.routines.triggers import Every, Once, Trigger, parse_trigger

__all__ = [
    "ADD_TOOL",
    "OWN_TOOLS",
    "Draft",
    "Registration",
    "RoutineContext",
    "commit",
    "describe",
    "make_draft",
    "register",
    "remove",
    "rename",
    "set_enabled",
    "tool_catalog",
]

ADD_TOOL = "add_routine"
OWN_TOOLS = frozenset({"add_routine", "list_routines", "remove_routine"})
"""A routine never runs these: routines do not manage routines."""
TIER_WORDS = {
    Tier.READ: "tier 0, reads only",
    Tier.DIGITAL_WRITE: "tier 1, a digital change",
    Tier.PHYSICAL: "tier 2, a physical action",
}


def tool_catalog(config: Config, tools: Iterable[AgentTool] | None = None) -> dict[str, AgentTool]:
    """The tools a routine may run: every ``tau.tools`` tool switched on in ``[components]``
    that declares a tier, minus the routine tools themselves. ``tools`` replaces the
    discovered ones (tests, embedding code)."""
    source = discovered_tools(config) if tools is None else list(tools)
    catalog: dict[str, AgentTool] = {}
    for tool in source:
        if tool.tool_name in OWN_TOOLS:
            continue
        try:
            tier_of(tool)
        except UntieredToolError:
            continue
        catalog[tool.tool_name] = tool
    return catalog


def _arguments_words(arguments: Mapping[str, Any]) -> str:
    if not arguments:
        return "no arguments"
    return ", ".join(f"{key}={canonical_json(value)}" for key, value in arguments.items())


@dataclass(frozen=True)
class Draft:
    """A checked definition, before or while it is approved."""

    name: str
    trigger: Trigger
    tool: str
    arguments: dict[str, Any]
    tier: Tier
    effect: str
    replaces: str | None = None

    def call_arguments(self) -> dict[str, Any]:
        """The ``add_routine`` call the approval is about."""
        arguments: dict[str, Any] = {
            "trigger": self.trigger.text,
            "tool": self.tool,
            "arguments": self.arguments,
            "name": self.name,
        }
        if self.replaces:
            arguments["replaces"] = self.replaces
        return arguments


def make_draft(
    *,
    trigger: str | Trigger,
    tool: str,
    arguments: Any,
    name: str = "",
    replaces: str | None = None,
    catalog: Mapping[str, AgentTool],
    settings: RoutineSettings,
    now: datetime,
) -> Draft:
    """Check a definition; :class:`RoutineError` says what is wrong, in plain English."""
    parsed = parse_trigger(trigger) if isinstance(trigger, str) else trigger
    if isinstance(parsed, Once) and parsed.slot(settings.zone) <= now:
        raise RoutineError(f"{parsed.text} is in the past ({settings.zone_name} time).")
    if not isinstance(tool, str) or not tool.strip():
        raise RoutineError("Name the tool the routine runs.")
    tool = tool.strip()
    if tool in OWN_TOOLS:
        raise RoutineError(f"A routine cannot run {tool}: routines do not manage routines.")
    agent_tool = catalog.get(tool)
    if agent_tool is None:
        raise RoutineError(
            f"There is no tool named {tool!r} that a routine can run (see `tau components`)."
        )
    checked = check_arguments(agent_tool, arguments)
    if not isinstance(name, str):
        raise RoutineError(f"A routine's name is text, not {name!r}.")
    cleaned = " ".join(name.split()) or f"{tool}, {parsed.text}"
    if len(cleaned) > NAME_LIMIT:
        raise RoutineError(f"A routine's name has at most {NAME_LIMIT} characters.")
    if any(not ch.isprintable() for ch in cleaned):
        raise RoutineError("A routine's name cannot hold control characters.")
    return Draft(
        name=cleaned,
        trigger=parsed,
        tool=tool,
        arguments=checked,
        tier=tier_of(agent_tool),
        effect=" ".join(effect_of(agent_tool).split()),
        replaces=replaces or None,
    )


def describe(draft: Draft, settings: RoutineSettings, old: Routine | None = None) -> str:
    """The whole definition in plain words, for the approval request (fixed English).
    ``old`` is the routine a ``replaces`` draft changes, when it is known."""
    when = draft.trigger.words()
    if not isinstance(draft.trigger, Every):
        when += f", {settings.zone_name} time"
    if draft.replaces:
        was = f' ("{old.name}")' if old is not None else ""
        head = f'Changes the routine {draft.replaces}{was} into "{draft.name}"'
    else:
        head = f'Registers the routine "{draft.name}"'
    return (
        f"{head}: {when}, the hub runs {draft.tool} ({TIER_WORDS[draft.tier]}: {draft.effect}) "
        f"with exactly these arguments: {_arguments_words(draft.arguments)}. From then on it "
        "runs on that clock without asking again, without a model and while nobody is at the "
        "Mac. Pausing or removing it is free; any other change asks again."
    )


def commit(store: RoutineStore, draft: Draft, now: datetime) -> Routine:
    """Store an approved draft with its ``approved_hash``; for ``replaces``, the same id with
    the new call, its failures cleared and the clock restarted at ``now``."""
    with store.edit() as routines:
        if draft.replaces:
            index = next((i for i, r in enumerate(routines) if r.id == draft.replaces), None)
            if index is None:
                raise RoutineError(f"No routine has the id {draft.replaces!r}.")
            old = routines[index]
            changed = old.with_call(
                trigger=draft.trigger, tool=draft.tool, arguments=draft.arguments
            )  # a changed call loses its old approval here ...
            routine = changed.with_changes(  # ... and gets the one just given
                name=draft.name,
                approved_hash=routine_hash(old.id, draft.tool, draft.arguments),
                last_slot=now,
                failures=0,
            )
            routines[index] = routine
        else:
            routine_id = store.new_id(routines)
            routine = Routine(
                id=routine_id,
                name=draft.name,
                trigger=draft.trigger,
                tool=draft.tool,
                arguments=draft.arguments,
                enabled=True,
                created=now,
                approved_hash=routine_hash(routine_id, draft.tool, draft.arguments),
            )
            routines.append(routine)
    store.log("changed" if draft.replaces else "registered", routine, detail=routine.trigger.text)
    return routine


@dataclass(frozen=True)
class Registration:
    """What :func:`register` did: the stored routine, or why nothing was stored."""

    routine: Routine | None
    approval: str | None
    refusal: str | None = None


async def register(
    draft: Draft, *, gate: TierGate, store: RoutineStore, clock: Callable[[], datetime]
) -> Registration:
    """Ask ``gate`` about the ``add_routine`` call for ``draft`` (one tier-2 approval, with the
    gate's guard and step-up); store the routine only when it is allowed, at ``clock()`` after
    the approval. The gate records the call like any tool call (``tool_call`` event)."""
    arguments = draft.call_arguments()
    tool_use_id = f"routine-add-{secrets.token_hex(6)}"
    started = time.monotonic()
    allowed, refusal, approval = await gate.check(ADD_TOOL, arguments, tool_use_id=tool_use_id)

    def record(status: str, summary: str) -> None:
        gate.record(
            tool_name=ADD_TOOL,
            arguments=arguments,
            status=status,
            summary=summary,
            approval=approval,
            duration_ms=int((time.monotonic() - started) * 1000),
            tool_use_id=tool_use_id,
        )

    if not allowed:
        record("rejected", refusal or "")
        return Registration(None, approval, refusal)
    try:
        routine = commit(store, draft, clock())
    except RoutineError as exc:
        record("error", str(exc))
        raise
    record("ok", f"routine {routine.id} stored")
    return Registration(routine, approval)


# -- free changes: nothing a routine does changes ---------------------------------------------


def rename(store: RoutineStore, ref: str, name: str) -> Routine:
    cleaned = " ".join(str(name).split())
    if not cleaned or len(cleaned) > NAME_LIMIT or any(not ch.isprintable() for ch in cleaned):
        raise RoutineError(f"A routine's name is 1 to {NAME_LIMIT} printable characters.")
    with store.edit() as routines:
        routine = find_routine(routines, ref)
        renamed = routine.with_changes(name=cleaned)
        routines[routines.index(routine)] = renamed
    store.log("renamed", renamed)
    return renamed


def set_enabled(store: RoutineStore, ref: str, enabled: bool, now: datetime) -> Routine:
    """Pause or resume. Resuming clears the failure count and restarts the clock at ``now``:
    what fell due while it was paused is skipped, not missed."""
    with store.edit() as routines:
        routine = find_routine(routines, ref)
        if enabled:
            changed = routine.with_changes(enabled=True, failures=0, last_slot=now)
        else:
            changed = routine.with_changes(enabled=False)
        routines[routines.index(routine)] = changed
    store.log("resumed" if enabled else "paused", changed, detail="by the owner")
    return changed


def remove(store: RoutineStore, ref: str) -> Routine:
    with store.edit() as routines:
        routine = find_routine(routines, ref)
        routines.remove(routine)
    store.log("removed", routine)
    return routine


# -- where routines live for one caller -------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class RoutineContext:
    """Everything a registration needs: the settings, the tools a routine may run, the store
    and the clock."""

    settings: RoutineSettings
    catalog: Mapping[str, AgentTool]
    store: RoutineStore
    clock: Callable[[], datetime] = _utc_now

    @classmethod
    def from_config(
        cls,
        config: Config,
        *,
        tools: Iterable[AgentTool] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> RoutineContext:
        """:class:`~tau_core.routines.settings.RoutineConfigError` for a bad
        ``[component.routines]``."""
        return cls(
            settings=RoutineSettings.from_config(config),
            catalog=tool_catalog(config, tools),
            store=RoutineStore.for_config(config, clock=clock),
            clock=clock or _utc_now,
        )

    def now(self) -> datetime:
        return self.clock()

    def draft(self, **fields: Any) -> Draft:
        return make_draft(catalog=self.catalog, settings=self.settings, now=self.now(), **fields)

    def next_run(self, routine: Routine) -> datetime | None:
        """When an enabled routine runs next (``None`` when paused or finished)."""
        if not routine.enabled:
            return None
        after = max(routine.last_slot or routine.created, self.now())
        return routine.trigger.next_after(after, zone=self.settings.zone, anchor=routine.created)

    def local(self, moment: datetime) -> datetime:
        return moment.astimezone(self.settings.zone)

    def state(self, routine: Routine) -> str:
        """``unapproved`` (its call does not match its approval), ``active``, ``paused`` or
        ``finished`` (a ``once`` routine whose time has passed)."""
        if not routine.approved:
            return "unapproved"
        if routine.enabled:
            return "active"
        if self.next_run(routine.with_changes(enabled=True)) is None:
            return "finished"
        return "paused"
