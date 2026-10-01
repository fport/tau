"""tau-routines: routines on a clock, the reflex engine of ADR 0015 §4.

A routine is a trigger plus one tool call with fixed arguments, and no LLM: "lamps on at 07:00
on weekdays". Registering one, or changing what it does, is one tier-2 approval on every path
(``tau routine add``, the ``add_routine`` tool, the web app's form); its firings never ask
again. The hub service ``routines`` fires them without a model, the cloud or the owner at the
Mac, through a tier gate whose only exemption is the approved call.

Public API (other packages import these names)::

    Routine, Daily, Once, Every, Trigger, parse_trigger, routine_hash, canonical_json,
    check_arguments, RoutineError, RoutineConfigError, TriggerError, RoutineSettings,
    local_zone, COMPONENT, GRACE_DEFAULT
    RoutineStore, RoutineStoreError, RoutineNotFound, find_routine
    Draft, Registration, RoutineContext, make_draft, describe, register, commit, rename,
    set_enabled, remove, tool_catalog, ADD_TOOL, OWN_TOOLS
    RoutineEngine, Firing, RefusingApprover, approved_call, run_tool, PAUSE_AFTER, CHANNEL
    RoutinesService, make_service
    TOOLS, add_routine, list_routines, remove_routine, using, current_context
"""

from __future__ import annotations

from tau_routines.engine import (
    CHANNEL,
    PAUSE_AFTER,
    Firing,
    RefusingApprover,
    RoutineEngine,
    approved_call,
    run_tool,
)
from tau_routines.model import Routine, canonical_json, check_arguments, routine_hash
from tau_routines.registration import (
    ADD_TOOL,
    OWN_TOOLS,
    Draft,
    Registration,
    RoutineContext,
    commit,
    describe,
    make_draft,
    register,
    remove,
    rename,
    set_enabled,
    tool_catalog,
)
from tau_routines.service import RoutinesService, make_service
from tau_routines.settings import (
    COMPONENT,
    GRACE_DEFAULT,
    RoutineConfigError,
    RoutineError,
    RoutineSettings,
    local_zone,
)
from tau_routines.store import RoutineNotFound, RoutineStore, RoutineStoreError, find_routine
from tau_routines.tools import (
    TOOLS,
    add_routine,
    current_context,
    list_routines,
    remove_routine,
    using,
)
from tau_routines.triggers import Daily, Every, Once, Trigger, TriggerError, parse_trigger

__version__ = "0.1.0"

__all__ = [
    "ADD_TOOL",
    "CHANNEL",
    "COMPONENT",
    "GRACE_DEFAULT",
    "OWN_TOOLS",
    "PAUSE_AFTER",
    "TOOLS",
    "Daily",
    "Draft",
    "Every",
    "Firing",
    "Once",
    "RefusingApprover",
    "Registration",
    "Routine",
    "RoutineConfigError",
    "RoutineContext",
    "RoutineEngine",
    "RoutineError",
    "RoutineNotFound",
    "RoutineSettings",
    "RoutineStore",
    "RoutineStoreError",
    "RoutinesService",
    "Trigger",
    "TriggerError",
    "__version__",
    "add_routine",
    "approved_call",
    "canonical_json",
    "check_arguments",
    "commit",
    "current_context",
    "describe",
    "find_routine",
    "list_routines",
    "local_zone",
    "make_draft",
    "make_service",
    "parse_trigger",
    "register",
    "remove",
    "remove_routine",
    "rename",
    "routine_hash",
    "run_tool",
    "set_enabled",
    "tool_catalog",
    "using",
]
