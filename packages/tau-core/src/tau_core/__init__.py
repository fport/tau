"""tau-core: the agent core of tau.

Public API (other tau packages import only these names and ``tau_core.testing``)::

    Config, ConfigError, MissingCredentials
    build_agent, TauAgent, TurnEvent, TextDelta, ReasoningDelta, ToolUseStarted, ToolProgress,
    ToolFinished, Throttled, Notice, TurnEnd, STOP_REASONS, to_turn_event
    SessionStore, MemorySessionStore, open_session_store
    EventBus, AgentEvent
    Approver, Decision, ApprovalRequest, TerminalApprover, TierGate, TierHook, Exemption
    tau_tool, Tier, ToolCatalog, UntieredToolError, tier_of, effect_of
    t, Language, LANGUAGES, SlashCommand, SLASH_COMMANDS, resolve_command, command_hint
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from tau_core.agent import (
    STOP_REASONS,
    Notice,
    ReasoningDelta,
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
from tau_core.config import Config, ConfigError, UiConfig
from tau_core.events import AgentEvent, EventBus
from tau_core.i18n import LANGUAGES, Language, t
from tau_core.models import MissingCredentials
from tau_core.sessions import MemorySessionStore, SessionStore, open_session_store
from tau_core.tiers import Tier, ToolCatalog, UntieredToolError, effect_of, tau_tool, tier_of

try:
    __version__ = version("tau-core")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0"

__all__ = [
    "LANGUAGES",
    "SLASH_COMMANDS",
    "STOP_REASONS",
    "AgentEvent",
    "ApprovalRequest",
    "Approver",
    "Config",
    "ConfigError",
    "Decision",
    "EventBus",
    "Exemption",
    "Language",
    "MemorySessionStore",
    "MissingCredentials",
    "Notice",
    "ReasoningDelta",
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
    "effect_of",
    "open_session_store",
    "resolve_command",
    "t",
    "tau_tool",
    "tier_of",
    "to_turn_event",
]
