"""tau-core: the agent core of tau.

Public API (other tau packages import only these names and ``tau_core.testing``)::

    Config, ConfigError, ConfigNotFound, MissingCredentials, ProviderNotSupported
    build_agent, TauAgent, TurnEvent, TextDelta, ReasoningDelta, ToolUseStarted, ToolInput,
    ToolProgress, ToolFinished, Throttled, Notice, TurnEnd, STOP_REASONS, to_turn_event,
    tool_inputs_of
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
    DeviceState, DeviceSource, device_to_json
    Guard, GuardState, GuardStatus, GuardVerdict, GuardProgress, GuardTurn, Admission,
    GuardLocked, LockedGuard, HubGuard, resolve_guard, VERDICT_REASONS, ADMISSION_REASONS,
    LOCK_TRIGGERS, PROGRESS_STEPS, ALLOWED_WHILE_LOCKED

The owner guard's helpers (``admit_turn``, ``guard_status_line``, ``guard_doctor_check``,
``DISCOVER``, ``ENROLLED_MARKER``) are in ``tau_core.guard``; ``HubClient``, ``HubUnavailable``
and ``HubError`` in ``tau_core.hub``.

The bootstrap-config editor behind ``/settings`` is ``tau_core.settings`` (imported by name).
The turn protocol for the web app (ADR 0015), event bodies and history blocks, is
``tau_core.turn_protocol`` (imported by name).
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
    ToolInput,
    ToolProgress,
    ToolUseStarted,
    TurnEnd,
    TurnEvent,
    build_agent,
    to_turn_event,
    tool_inputs_of,
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
from tau_core.devices import DeviceSource, DeviceState
from tau_core.devices import to_json as device_to_json
from tau_core.events import AgentEvent, EventBus
from tau_core.guard import (
    ADMISSION_REASONS,
    ALLOWED_WHILE_LOCKED,
    LOCK_TRIGGERS,
    PROGRESS_STEPS,
    VERDICT_REASONS,
    Admission,
    Guard,
    GuardLocked,
    GuardProgress,
    GuardState,
    GuardStatus,
    GuardTurn,
    GuardVerdict,
    HubGuard,
    LockedGuard,
    resolve_guard,
)
from tau_core.hub.daemon import HubService
from tau_core.i18n import LANGUAGES, Language, t
from tau_core.logs import configure_logging, reset_logging
from tau_core.models import PROVIDERS, MissingCredentials, ProviderNotSupported
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
    "ADMISSION_REASONS",
    "ALLOWED_WHILE_LOCKED",
    "LANGUAGES",
    "LOCK_TRIGGERS",
    "PROGRESS_STEPS",
    "PROVIDERS",
    "SESSION_BACKENDS",
    "SLASH_COMMANDS",
    "STOP_REASONS",
    "VERDICT_REASONS",
    "Admission",
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
    "DeviceSource",
    "DeviceState",
    "EventBus",
    "Exemption",
    "Guard",
    "GuardLocked",
    "GuardProgress",
    "GuardState",
    "GuardStatus",
    "GuardTurn",
    "GuardVerdict",
    "HubGuard",
    "HubService",
    "Language",
    "LockedGuard",
    "MemorySessionStore",
    "MissingCredentials",
    "ModelInfo",
    "Notice",
    "PersonaLoader",
    "ProviderNotSupported",
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
    "ToolInput",
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
    "device_to_json",
    "discover_tools",
    "effect_of",
    "open_session_store",
    "record_compaction",
    "register_provider",
    "register_session_backend",
    "reset_logging",
    "resolve_command",
    "resolve_guard",
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
    "tool_inputs_of",
]
