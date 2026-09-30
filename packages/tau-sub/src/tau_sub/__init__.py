"""tau-sub: sub-taus, small named specialists of a tau (ADR 0012).

A sub-tau is a named specialization of the owner's tau, not a second hub or identity: a slug
name shown as ``/name``, a persona, an about line, a model role, a tool allowlist, a
``public`` flag (a public sub-tau answers the owner's contacts over the tau network and is
listed in the universe) and its own sessions on the channel ``sub:<name>``. Definitions are the
owner's files, ``persona/subs/<name>.md``.

Public API (other packages import these names)::

    SubTau, SubRegistry, SubTauError, SubTauNotFound, SubTauExists, UnknownToolError,
    ForbiddenToolError, parse, render, validate, validate_name, template, tool_catalog,
    NAME_RE, ROLES, DEFAULT_ROLE, ABOUT_LIMIT, FORBIDDEN_TOOLS, RESERVED_NAMES,
    WEB_DAILY_DEFAULT, WEB_DAILY_RANGE, STARTERS_MAX, STARTER_LIMIT, is_valid_name
    HEADER, SubConversation, build_sub_agent, allowed_tools, persona_loader, prompt_persona,
    write_prompt, prompt_path, state_dir, last_session, remember_session
    Draft, DraftError, draft_sub, parse_draft
    DelegatedApprover, RefusingApprover, turn_approver, turn_gate
    TOOLS, CREATE_EFFECT
    PublicSub, PublicSubs, public_subs          (the ``tau.subs`` entry point for tau-net)
"""

from __future__ import annotations

from tau_sub.agent import (
    HEADER,
    SubConversation,
    allowed_tools,
    build_sub_agent,
    last_session,
    persona_loader,
    prompt_path,
    prompt_persona,
    remember_session,
    state_dir,
    write_prompt,
)
from tau_sub.approval import DelegatedApprover, RefusingApprover, turn_approver, turn_gate
from tau_sub.definition import (
    ABOUT_LIMIT,
    DEFAULT_ROLE,
    FORBIDDEN_TOOLS,
    NAME_RE,
    RESERVED_NAMES,
    ROLES,
    STARTER_LIMIT,
    STARTERS_MAX,
    WEB_DAILY_DEFAULT,
    WEB_DAILY_RANGE,
    ForbiddenToolError,
    SubRegistry,
    SubTau,
    SubTauError,
    SubTauExists,
    SubTauNotFound,
    UnknownToolError,
    is_valid_name,
    parse,
    render,
    template,
    tool_catalog,
    validate,
    validate_name,
)
from tau_sub.draft import Draft, DraftError, draft_sub, parse_draft
from tau_sub.network import PublicSub, PublicSubs, public_subs
from tau_sub.tools import CREATE_EFFECT, TOOLS

__version__ = "0.1.0"

__all__ = [
    "ABOUT_LIMIT",
    "CREATE_EFFECT",
    "DEFAULT_ROLE",
    "FORBIDDEN_TOOLS",
    "HEADER",
    "NAME_RE",
    "RESERVED_NAMES",
    "ROLES",
    "STARTERS_MAX",
    "STARTER_LIMIT",
    "TOOLS",
    "WEB_DAILY_DEFAULT",
    "WEB_DAILY_RANGE",
    "DelegatedApprover",
    "Draft",
    "DraftError",
    "ForbiddenToolError",
    "PublicSub",
    "PublicSubs",
    "RefusingApprover",
    "SubConversation",
    "SubRegistry",
    "SubTau",
    "SubTauError",
    "SubTauExists",
    "SubTauNotFound",
    "UnknownToolError",
    "__version__",
    "allowed_tools",
    "build_sub_agent",
    "draft_sub",
    "is_valid_name",
    "last_session",
    "parse",
    "parse_draft",
    "persona_loader",
    "prompt_path",
    "prompt_persona",
    "public_subs",
    "remember_session",
    "render",
    "state_dir",
    "template",
    "tool_catalog",
    "turn_approver",
    "turn_gate",
    "validate",
    "validate_name",
    "write_prompt",
]
