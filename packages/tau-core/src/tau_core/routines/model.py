"""The routine record, its approval hash and the checks a definition must pass.

A routine is ``{id, name, trigger, tool, arguments, enabled, created, approved_hash}`` plus
the engine's bookkeeping: ``last_slot`` (the latest scheduled time it has handled) and
``failures`` (failed firings in a row).

``approved_hash`` is the hash of ``(id, tool, canonical arguments)`` stored when the owner
approved the registration. At every firing the engine's exemption recomputes it from the call
it is about to make; a call that does not hash to it is refused by the tier gate.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from strands.types.tools import AgentTool

from tau_routines.settings import RoutineError
from tau_routines.triggers import Trigger, TriggerError, parse_trigger

__all__ = [
    "ID_RE",
    "NAME_LIMIT",
    "Routine",
    "canonical_json",
    "check_arguments",
    "parse_time",
    "routine_hash",
    "stamp",
]

ID_RE = re.compile(r"^[0-9a-f]{8}$")
NAME_LIMIT = 80
HASH_PREFIX = "sha256:"


def canonical_json(value: Any) -> str:
    """One spelling for equal JSON values: sorted keys, no spaces, UTF-8, no NaN."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def routine_hash(routine_id: str, tool: str, arguments: dict[str, Any]) -> str:
    """The approval hash of one routine's call: ``sha256`` of the canonical JSON of
    ``[id, tool, arguments]``."""
    payload = canonical_json([routine_id, tool, arguments]).encode("utf-8")
    return HASH_PREFIX + hashlib.sha256(payload).hexdigest()


def stamp(moment: datetime) -> str:
    """An aware datetime as an ISO string in UTC (what the file stores)."""
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def parse_time(value: Any, what: str) -> datetime:
    if not isinstance(value, str):
        raise RoutineError(f"{what} must be an ISO date and time, not {value!r}.")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise RoutineError(f"{what} is not an ISO date and time: {value!r}.") from None
    if moment.tzinfo is None:
        raise RoutineError(f"{what} has no time zone: {value!r}.")
    return moment


def _clean_name(name: Any) -> str:
    if not isinstance(name, str):
        raise RoutineError(f"A routine's name is text, not {name!r}.")
    cleaned = " ".join(name.split())
    if not cleaned:
        raise RoutineError("A routine's name cannot be empty.")
    if len(cleaned) > NAME_LIMIT:
        raise RoutineError(f"A routine's name has at most {NAME_LIMIT} characters.")
    if any(not ch.isprintable() for ch in cleaned):
        raise RoutineError("A routine's name cannot hold control characters.")
    return cleaned


@dataclass(frozen=True)
class Routine:
    id: str
    name: str
    trigger: Trigger
    tool: str
    arguments: dict[str, Any]
    enabled: bool
    created: datetime
    approved_hash: str | None = None
    last_slot: datetime | None = None
    failures: int = 0
    extra: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)
    """Keys a newer tau-routines wrote; kept and written back unchanged."""

    def call_hash(self) -> str:
        return routine_hash(self.id, self.tool, self.arguments)

    @property
    def approved(self) -> bool:
        """Does the stored hash match this routine's call?"""
        return self.approved_hash is not None and self.approved_hash == self.call_hash()

    def same_call(self, other: Routine) -> bool:
        """The same trigger, tool and arguments (what an approval covers)."""
        return (
            self.trigger == other.trigger
            and self.tool == other.tool
            and canonical_json(self.arguments) == canonical_json(other.arguments)
        )

    def with_changes(self, **changes: Any) -> Routine:
        return replace(self, **changes)

    def with_call(
        self,
        *,
        trigger: Trigger | None = None,
        tool: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> Routine:
        """A copy with a new trigger, tool or arguments. When the call changes, the approval
        no longer covers it: ``approved_hash`` is cleared, and only a new approval sets it."""
        changed = replace(
            self,
            trigger=self.trigger if trigger is None else trigger,
            tool=self.tool if tool is None else tool,
            arguments=self.arguments if arguments is None else arguments,
        )
        return changed if changed.same_call(self) else replace(changed, approved_hash=None)

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.extra,
            "id": self.id,
            "name": self.name,
            "trigger": self.trigger.text,
            "tool": self.tool,
            "arguments": self.arguments,
            "enabled": self.enabled,
            "created": stamp(self.created),
            "approved_hash": self.approved_hash,
            "last_slot": stamp(self.last_slot) if self.last_slot is not None else None,
            "failures": self.failures,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Routine:
        if not isinstance(data, dict):
            raise RoutineError(f"A routine is an object, not {type(data).__name__}.")
        known = {
            "id",
            "name",
            "trigger",
            "tool",
            "arguments",
            "enabled",
            "created",
            "approved_hash",
            "last_slot",
            "failures",
        }
        routine_id = data.get("id")
        if not isinstance(routine_id, str) or not ID_RE.match(routine_id):
            raise RoutineError(f"{routine_id!r} is not a routine id (8 hex digits).")
        try:
            trigger = parse_trigger(data.get("trigger"))
        except TriggerError as exc:
            raise RoutineError(f"routine {routine_id}: {exc}") from None
        tool = data.get("tool")
        if not isinstance(tool, str) or not tool:
            raise RoutineError(f"routine {routine_id}: the tool must be a tool name.")
        arguments = data.get("arguments")
        if not isinstance(arguments, dict):
            raise RoutineError(f"routine {routine_id}: the arguments must be an object.")
        enabled = data.get("enabled")
        if not isinstance(enabled, bool):
            raise RoutineError(f"routine {routine_id}: enabled must be true or false.")
        approved_hash = data.get("approved_hash")
        if approved_hash is not None and not isinstance(approved_hash, str):
            raise RoutineError(f"routine {routine_id}: approved_hash must be text or null.")
        last_slot = data.get("last_slot")
        failures = data.get("failures", 0)
        if isinstance(failures, bool) or not isinstance(failures, int) or failures < 0:
            raise RoutineError(f"routine {routine_id}: failures must be a count.")
        return cls(
            id=routine_id,
            name=_clean_name(data.get("name")),
            trigger=trigger,
            tool=tool,
            arguments=arguments,
            enabled=enabled,
            created=parse_time(data.get("created"), f"routine {routine_id}: created"),
            approved_hash=approved_hash,
            last_slot=(
                parse_time(last_slot, f"routine {routine_id}: last_slot")
                if last_slot is not None
                else None
            ),
            failures=failures,
            extra={k: v for k, v in data.items() if k not in known},
        )


_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
    "null": (type(None),),
}


def _type_ok(value: Any, expected: Any) -> bool:
    names = expected if isinstance(expected, list) else [expected]
    for name in names:
        types = _JSON_TYPES.get(name)
        if types is None:
            return True  # a type this check does not know: leave it to the tool
        if isinstance(value, bool) and name in ("integer", "number"):
            continue
        if isinstance(value, types):
            return True
    return False


def check_arguments(tool: AgentTool, arguments: Any) -> dict[str, Any]:
    """The arguments as a JSON object the tool accepts, or :class:`RoutineError`.

    Checks what the tool's input schema says at the top level: every required argument is
    there, no unknown argument is given, and each value has the declared JSON type. The tool
    validates the rest itself when it runs.
    """
    if not isinstance(arguments, dict):
        raise RoutineError("The arguments must be an object of name → value.")
    try:
        canonical_json(arguments)
    except (TypeError, ValueError):
        raise RoutineError("The arguments must be plain JSON values.") from None
    spec = getattr(tool, "tool_spec", None) or {}
    schema = (spec.get("inputSchema") or {}).get("json") or {}
    properties = schema.get("properties")
    name = getattr(tool, "tool_name", "?")
    if not isinstance(properties, dict):
        return dict(arguments)
    missing = [key for key in schema.get("required") or () if key not in arguments]
    if missing:
        raise RoutineError(f"{name} needs the argument(s) {', '.join(missing)}.")
    if schema.get("additionalProperties") is not True:
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            known = ", ".join(properties) or "none"
            raise RoutineError(
                f"{name} has no argument(s) {', '.join(unknown)} (it takes {known})."
            )
    for key, value in arguments.items():
        prop = properties.get(key) or {}
        expected = prop.get("type")
        if value is None and "default" in prop and prop["default"] is None:
            continue  # an optional argument left at its default
        if expected is not None and not _type_ok(value, expected):
            raise RoutineError(f"{name}: {key} must be of type {expected}, not {value!r}.")
    return dict(arguments)
