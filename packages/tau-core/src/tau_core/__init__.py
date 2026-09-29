"""tau-core: the agent core of tau.

Public API (other tau packages import only these names and ``tau_core.testing``)::

    Config, ConfigError, ConfigNotFound, MissingCredentials
    build_agent, TauAgent, TurnEvent, TextDelta, ReasoningDelta, ToolUseStarted, ToolProgress,
    ToolFinished, Throttled, Notice, TurnEnd, STOP_REASONS, to_turn_event
    SessionStore, MemorySessionStore, open_session_store, SESSION_BACKENDS,
    register_session_backend
    PROVIDERS, register_provider
    ContextSource, PersonaLoader
    HubService
    discover_tools
    EventBus, AgentEvent
    Approver, Decision, ApprovalRequest, TerminalApprover, TierGate, TierHook, Exemption
    tau_tool, Tier, ToolCatalog, UntieredToolError, tier_of, effect_of
    t, Language, LANGUAGES, SlashCommand, SLASH_COMMANDS, resolve_command, command_hint
    configure_logging, reset_logging
    CompactionError, CompactionCancelled, summarize, seed_messages, compaction_title,
    record_compaction, SessionContextMismatch
    ModelInfo, describe_model, status_lines, status_report, role_lines, stored_role

The bootstrap-config editor behind ``/settings`` is ``tau_core.settings`` (imported by name).
"""

from __future__ import annotations

from tau_core._version import __version__
from tau_core.agent import (
    STOP_REASONS,
    Notice,
    ReasoningDelta,
    SessionContextMismatch,
    TauAgent,
    TextDelta,
    Throttled,
    ToolFinished,
    ToolProgress,
    ToolUseStarted,
    TurnEnd,
    TurnEvent,
    build_agent,
    to_turn_event,
)
from tau_core.approval import (
    ApprovalRequest,
    Approver,
    Decision,
    Exemption,
    TerminalApprover,
    TierGate,
    TierHook,
)
from tau_core.commands import SLASH_COMMANDS, SlashCommand, command_hint, resolve_command
from tau_core.compaction import (
    CompactionCancelled,
    CompactionError,
    compaction_title,
    record_compaction,
    seed_messages,
    summarize,
)
from tau_core.config import Config, ConfigError, ConfigNotFound, UiConfig
from tau_core.events import AgentEvent, EventBus
from tau_core.hub.daemon import HubService
from tau_core.i18n import LANGUAGES, Language, t
from tau_core.logs import configure_logging, reset_logging
from tau_core.models import PROVIDERS, MissingCredentials
from tau_core.persona import ContextSource, PersonaLoader
from tau_core.plugins import discover_tools
from tau_core.registry import register_provider, register_session_backend
from tau_core.sessions import (
    SESSION_BACKENDS,
    MemorySessionStore,
    SessionStore,
    open_session_store,
)
from tau_core.status import (
    ModelInfo,
    describe_model,
    role_lines,
    status_lines,
    status_report,
    stored_role,
)
from tau_core.tiers import Tier, ToolCatalog, UntieredToolError, effect_of, tau_tool, tier_of

__all__ = [
    "LANGUAGES",
    "PROVIDERS",
    "SESSION_BACKENDS",
    "SLASH_COMMANDS",
    "STOP_REASONS",
    "AgentEvent",
    "ApprovalRequest",
    "Approver",
    "CompactionCancelled",
    "CompactionError",
    "Config",
    "ConfigError",
    "ConfigNotFound",
    "ContextSource",
    "Decision",
    "EventBus",
    "Exemption",
    "HubService",
    "Language",
    "MemorySessionStore",
    "MissingCredentials",
    "ModelInfo",
    "Notice",
    "PersonaLoader",
    "ReasoningDelta",
    "SessionContextMismatch",
    "SessionStore",
    "SlashCommand",
    "TauAgent",
    "TerminalApprover",
    "TextDelta",
    "Throttled",
    "Tier",
    "TierGate",
    "TierHook",
    "ToolCatalog",
    "ToolFinished",
    "ToolProgress",
    "ToolUseStarted",
    "TurnEnd",
    "TurnEvent",
    "UiConfig",
    "UntieredToolError",
    "__version__",
    "build_agent",
    "command_hint",
    "compaction_title",
    "configure_logging",
    "describe_model",
    "discover_tools",
    "effect_of",
    "open_session_store",
    "record_compaction",
    "register_provider",
    "register_session_backend",
    "reset_logging",
    "resolve_command",
    "role_lines",
    "seed_messages",
    "status_lines",
    "status_report",
    "stored_role",
    "summarize",
    "t",
    "tau_tool",
    "tier_of",
    "to_turn_event",
]
