"""The routine tools (``tau.tools`` entry point ``routines``).

- ``add_routine`` (tier 2) registers a routine, or changes one (``replaces``). The turn's tier
  gate asks the channel's approver first, with the whole definition in plain words: the tool
  carries ``tau_describe`` (:func:`describe_call`), which tau-core's gate puts into the
  approval request. The body runs only after that approval and stores exactly the approved
  call.
- ``list_routines`` (tier 0) lists them.
- ``remove_routine`` (tier 1) removes one; removing changes nothing a routine does, so it is
  free like ``tau routine remove``.

The tools find where routines live at call time: the :class:`RoutineContext` a caller set with
:func:`using` (``tau routine`` does, so the description its approval shows reads the same
configuration), else :data:`context_factory` (tests), else ``Config.load()``. Everything they
return is short English for the model.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from typing import Any

from tau_core import Config, ConfigError, Tier, tau_tool
from tau_core.routines.model import canonical_json
from tau_core.routines.registration import RoutineContext, commit, describe, remove
from tau_core.routines.settings import RoutineError

__all__ = [
    "ADD_EFFECT",
    "TOOLS",
    "add_routine",
    "context_factory",
    "current_context",
    "describe_call",
    "list_routines",
    "remove_routine",
    "using",
]

logger = logging.getLogger(__name__)

ADD_EFFECT = (
    "Registers a routine: from then on the hub runs one tool call with fixed arguments on a "
    "clock, without asking again."
)
TIME_FORMAT = "%a %d.%m.%Y %H:%M"

context_factory: Callable[[], RoutineContext] | None = None
"""Replaces ``RoutineContext.from_config(Config.load())`` (tests); ``None`` = the default."""

_CONTEXT: ContextVar[RoutineContext | None] = ContextVar("tau_routines_context", default=None)


@contextlib.contextmanager
def using(context: RoutineContext) -> Iterator[RoutineContext]:
    """Make ``context`` the one the routine tools (and their approval text) use in this
    task."""
    token = _CONTEXT.set(context)
    try:
        yield context
    finally:
        _CONTEXT.reset(token)


def current_context() -> RoutineContext:
    """The context of :func:`using`, else :data:`context_factory`, else the configuration."""
    context = _CONTEXT.get()
    if context is not None:
        return context
    if context_factory is not None:
        return context_factory()
    return RoutineContext.from_config(Config.load())


def _fields(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "trigger": arguments.get("trigger"),
        "tool": arguments.get("tool"),
        "arguments": arguments.get("arguments"),
        "name": arguments.get("name") or "",
        "replaces": arguments.get("replaces") or None,
    }


def describe_call(arguments: dict[str, Any]) -> str:
    """``add_routine``'s ``tau_describe``: the definition in plain words for its approval."""
    try:
        context = current_context()
        draft = context.draft(**_fields(arguments))
        old = None
        if draft.replaces:
            old = next((r for r in context.store.load() if r.id == draft.replaces), None)
            if old is None:
                raise RoutineError(f"No routine has the id {draft.replaces!r}.")
        return describe(draft, context.settings, old)
    except (RoutineError, ConfigError) as exc:
        return (
            f"Registers a routine, but its definition is not valid: {exc} Nothing will be stored."
        )


def _when(context: RoutineContext, routine: Any) -> str:
    upcoming = context.next_run(routine)
    if upcoming is None:
        return "no next run"
    return f"next run {context.local(upcoming):{TIME_FORMAT}}"


def _state(context: RoutineContext, routine: Any) -> str:
    state = context.state(routine)
    return "not approved" if state == "unapproved" else state


@tau_tool(tier=Tier.PHYSICAL, effect=ADD_EFFECT)
def add_routine(
    trigger: str, tool: str, arguments: dict[str, Any], name: str = "", replaces: str = ""
) -> str:
    """Register a routine: one call of one of your tools, with fixed arguments, that the hub
    runs on a clock without a model and without asking again (lamps on at 07:00 on weekdays).
    The owner approves the whole definition once. To change a routine, call this again with
    its id in `replaces`; that asks again too.

    Args:
        trigger: When it runs, in the hub's local time: "daily 07:00", "daily 07:00 weekdays",
            "daily 18:30 mon,wed,fri", "once 2026-10-05 07:00" or "every 15 minutes" (at least
            5 minutes).
        tool: The name of the tool to run, from your tool list.
        arguments: The exact arguments of every call, as an object of name to value.
        name: A short name for the routine; empty for one made from the tool and the trigger.
        replaces: The id of the routine this definition replaces; empty for a new routine.
    """
    try:
        context = current_context()
        draft = context.draft(
            **_fields(
                {
                    "trigger": trigger,
                    "tool": tool,
                    "arguments": arguments,
                    "name": name,
                    "replaces": replaces,
                }
            )
        )
        routine = commit(context.store, draft, context.now())
    except (RoutineError, ConfigError) as exc:
        return f"Not registered: {exc}"
    except OSError as exc:
        return f"Not registered: the routines file could not be written ({exc.strerror or exc})."
    logger.info("routines: %s routine %s through add_routine", routine.id, routine.trigger.text)
    verb = "Changed" if draft.replaces else "Registered"
    return (
        f'{verb} the routine {routine.id} "{routine.name}": {routine.trigger.words()}, '
        f"{routine.tool}. Its {_when(context, routine)}. The owner can pause it with "
        f"`tau routine pause {routine.id}`."
    )


@tau_tool(tier=Tier.READ)
def list_routines() -> str:
    """List the owner's routines: each one's id, name, state, trigger, tool call and next run."""
    try:
        context = current_context()
        routines = context.store.load()
    except (RoutineError, ConfigError) as exc:
        return f"The routines cannot be read: {exc}"
    if not routines:
        return "The owner has no routines yet; add_routine registers one."
    lines = ["The owner's routines:"]
    for routine in routines:
        arguments = ", ".join(
            f"{key}={canonical_json(value)}" for key, value in routine.arguments.items()
        )
        when = _when(context, routine)
        lines.append(
            f'- {routine.id} "{routine.name}" ({_state(context, routine)}): '
            f"{routine.trigger.words()} runs {routine.tool}({arguments}); {when}."
        )
    return "\n".join(lines)


@tau_tool(tier=Tier.DIGITAL_WRITE)
def remove_routine(routine: str) -> str:
    """Remove one of the owner's routines, so it never runs again.

    Args:
        routine: The routine's id (8 characters, see list_routines) or its exact name.
    """
    try:
        context = current_context()
        removed = remove(context.store, routine)
    except (RoutineError, ConfigError) as exc:
        return f"Not removed: {exc}"
    except OSError as exc:
        return f"Not removed: the routines file could not be written ({exc.strerror or exc})."
    return f'Removed the routine {removed.id} "{removed.name}"; it will not run again.'


add_routine.tau_describe = describe_call  # type: ignore[attr-defined]

TOOLS = [add_routine, list_routines, remove_routine]
