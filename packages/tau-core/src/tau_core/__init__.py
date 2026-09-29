"""tau-core: the agent core of tau.

Public API (other tau packages import only these names and ``tau_core.testing``)::

    Config, ConfigError, MissingCredentials
    build_agent, TauAgent, TurnEvent, TextDelta, ToolUseStarted, ToolFinished, Notice, TurnEnd
    SessionStore, MemorySessionStore, open_session_store
    EventBus, AgentEvent
    Approver, Decision, ApprovalRequest
    tau_tool, Tier, ToolCatalog
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from tau_core.agent import (
    Notice,
    TauAgent,
    TextDelta,
    ToolFinished,
    ToolUseStarted,
    TurnEnd,
    TurnEvent,
    build_agent,
)
from tau_core.approval import ApprovalRequest, Approver, Decision
from tau_core.config import Config, ConfigError
from tau_core.events import AgentEvent, EventBus
from tau_core.models import MissingCredentials
from tau_core.sessions import MemorySessionStore, SessionStore, open_session_store
from tau_core.tiers import Tier, ToolCatalog, tau_tool

try:
    __version__ = version("tau-core")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0"

__all__ = [
    "AgentEvent",
    "ApprovalRequest",
    "Approver",
    "Config",
    "ConfigError",
    "Decision",
    "EventBus",
    "MemorySessionStore",
    "MissingCredentials",
    "Notice",
    "SessionStore",
    "TauAgent",
    "TextDelta",
    "Tier",
    "ToolCatalog",
    "ToolFinished",
    "ToolUseStarted",
    "TurnEnd",
    "TurnEvent",
    "__version__",
    "build_agent",
    "open_session_store",
    "tau_tool",
]
