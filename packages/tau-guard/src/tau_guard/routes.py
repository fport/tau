"""The ``/guard/*`` route schemas (ADR 0008 decision 3) and their strict validation.

Every route is a protected control route (``ControlApi`` checks the signature and signs the
answer before and after the handler runs). A route can only ask the hub to look: no field of
any schema takes a verdict, a score, an image or an embedding. A body or query with an unknown
key, a missing required key or a value of the wrong type is refused with 400
``{"reason": "error", "error": "..."}``. The ``channel`` fields are audit labels only.

:data:`SCHEMAS` maps ``(method, path)`` to its fields; tests enumerate it against the routes
the service registers.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tau_core.guard import LOCK_TRIGGERS

from tau_guard.config import CHOICES

__all__ = ["MAX_WAIT", "SCHEMAS", "BadRequest", "FieldSpec", "parse_body", "parse_query"]

MAX_TEXT = 128
MAX_WAIT = 25.0


class BadRequest(ValueError):
    """A request that does not fit its route's schema."""


@dataclass(frozen=True)
class FieldSpec:
    kind: str
    """``text``, ``bool``, ``choice``, ``int``, ``number`` or ``policy``."""
    required: bool = False
    nullable: bool = False
    choices: tuple[str, ...] = ()
    low: float | None = None
    high: float | None = None


TEXT = FieldSpec("text", required=True)
OPTIONAL_TEXT = FieldSpec("text", nullable=True)
POLICY_FIELDS: dict[str, FieldSpec] = {
    "step_up": FieldSpec("choice", choices=CHOICES["step_up"]),
    "unlock_liveness": FieldSpec("choice", choices=CHOICES["unlock_liveness"]),
}
"""The only knobs a client may send; each can only make the check stricter."""
VERIFY_KINDS = ("unlock", "recheck", "step_up")

SCHEMAS: dict[tuple[str, str], dict[str, FieldSpec]] = {
    ("GET", "/guard/status"): {
        "since": FieldSpec("int"),
        "wait": FieldSpec("number", low=0, high=MAX_WAIT),
        "attempt": FieldSpec("text"),
    },
    ("POST", "/guard/admit"): {
        "channel": TEXT,
        "session_id": OPTIONAL_TEXT,
        "client_id": TEXT,
    },
    ("POST", "/guard/verify"): {
        "channel": TEXT,
        "client_id": TEXT,
        "kind": FieldSpec("choice", required=True, choices=VERIFY_KINDS),
        "request_id": OPTIONAL_TEXT,
        "tool": OPTIONAL_TEXT,
        "policy": FieldSpec("policy", nullable=True),
    },
    ("POST", "/guard/cancel"): {
        "client_id": TEXT,
        "attempt": OPTIONAL_TEXT,
    },
    ("POST", "/guard/lock"): {
        "channel": TEXT,
        "client_id": TEXT,
        "trigger": FieldSpec("choice", choices=LOCK_TRIGGERS),
    },
    ("POST", "/guard/enroll"): {
        "client_id": TEXT,
        "add": FieldSpec("bool"),
    },
}


def _check(name: str, spec: FieldSpec, value: Any) -> Any:
    if value is None:
        if spec.nullable:
            return None
        raise BadRequest(f"{name} must not be null")
    if spec.kind == "text":
        if not isinstance(value, str) or not value or len(value) > MAX_TEXT:
            raise BadRequest(f"{name} must be a string of 1 to {MAX_TEXT} characters")
        return value
    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise BadRequest(f"{name} must be true or false")
        return value
    if spec.kind == "choice":
        if value not in spec.choices:
            raise BadRequest(f"{name} must be one of {', '.join(spec.choices)}")
        return value
    if spec.kind in ("int", "number"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise BadRequest(f"{name} must be a number")
        if spec.kind == "int" and not isinstance(value, int):
            raise BadRequest(f"{name} must be an integer")
        if not math.isfinite(value):
            raise BadRequest(f"{name} must be finite")
        if spec.low is not None and value < spec.low:
            raise BadRequest(f"{name} must be at least {spec.low:g}")
        if spec.high is not None and value > spec.high:
            raise BadRequest(f"{name} must be at most {spec.high:g}")
        return value
    if spec.kind == "policy":
        if not isinstance(value, dict):
            raise BadRequest(f"{name} must be an object")
        return _fields(value, POLICY_FIELDS, prefix=f"{name}.")
    raise BadRequest(f"{name} has an unknown kind")  # pragma: no cover


def _fields(
    payload: Mapping[str, Any], schema: Mapping[str, FieldSpec], *, prefix: str = ""
) -> dict:
    unknown = sorted(set(payload) - set(schema))
    if unknown:
        raise BadRequest(f"unknown field {prefix}{unknown[0]}")
    parsed: dict[str, Any] = {}
    for name, spec in schema.items():
        if name not in payload:
            if spec.required:
                raise BadRequest(f"{prefix}{name} is required")
            continue
        parsed[name] = _check(prefix + name, spec, payload[name])
    return parsed


def parse_body(route: tuple[str, str], payload: Any) -> dict[str, Any]:
    """The validated JSON body of ``route``; raises :class:`BadRequest`."""
    if not isinstance(payload, dict):
        raise BadRequest("the body must be a JSON object")
    return _fields(payload, SCHEMAS[route])


def parse_query(route: tuple[str, str], query: Mapping[str, list[str]]) -> dict[str, Any]:
    """The validated query string of ``route`` (last value of each key)."""
    schema = SCHEMAS[route]
    raw: dict[str, Any] = {}
    for name, values in query.items():
        if name not in schema:
            raise BadRequest(f"unknown parameter {name}")
        value = values[-1] if values else ""
        spec = schema[name]
        if spec.kind in ("int", "number"):
            try:
                raw[name] = int(value) if spec.kind == "int" else float(value)
            except ValueError as exc:
                raise BadRequest(f"{name} must be a number") from exc
        else:
            raw[name] = value
    return _fields(raw, schema)
