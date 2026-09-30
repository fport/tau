"""tau-sub: sub-taus, small named specialists of a tau (ADR 0012).

A sub-tau is a named specialization of the owner's tau, not a second hub or identity: a slug
name shown as ``/name``, a persona, an about line, a model role, a tool allowlist, a
``public`` flag (network behaviour comes with issue 150) and its own sessions on the channel
``sub:<name>``. Definitions are the owner's files, ``persona/subs/<name>.md``.

Public API (other packages import these names)::

    SubTau, SubRegistry, SubTauError, SubTauNotFound, SubTauExists, UnknownToolError,
    ForbiddenToolError, parse, render, validate, validate_name, template, tool_catalog,
    NAME_RE, ROLES, DEFAULT_ROLE, ABOUT_LIMIT, FORBIDDEN_TOOLS
"""

from __future__ import annotations

from tau_sub.definition import (
    ABOUT_LIMIT,
    DEFAULT_ROLE,
    FORBIDDEN_TOOLS,
    NAME_RE,
    ROLES,
    ForbiddenToolError,
    SubRegistry,
    SubTau,
    SubTauError,
    SubTauExists,
    SubTauNotFound,
    UnknownToolError,
    parse,
    render,
    template,
    tool_catalog,
    validate,
    validate_name,
)

__version__ = "0.1.0"

__all__ = [
    "ABOUT_LIMIT",
    "DEFAULT_ROLE",
    "FORBIDDEN_TOOLS",
    "NAME_RE",
    "ROLES",
    "ForbiddenToolError",
    "SubRegistry",
    "SubTau",
    "SubTauError",
    "SubTauExists",
    "SubTauNotFound",
    "UnknownToolError",
    "__version__",
    "parse",
    "render",
    "template",
    "tool_catalog",
    "validate",
    "validate_name",
]
