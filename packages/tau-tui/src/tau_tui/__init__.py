"""tau-tui: the Textual terminal interface for tau.

Public API::

    TauApp, build_app, resolve_resume, SessionNotFound
    ChatPane, EventPane
    ApprovalScreen, TuiApprover
"""

from importlib.metadata import PackageNotFoundError, version

from tau_tui.app import SessionNotFound, TauApp, build_app, resolve_resume
from tau_tui.approval import ApprovalScreen, TuiApprover
from tau_tui.panes import ChatPane, EventPane

try:
    __version__ = version("tau-tui")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "ApprovalScreen",
    "ChatPane",
    "EventPane",
    "SessionNotFound",
    "TauApp",
    "TuiApprover",
    "__version__",
    "build_app",
    "resolve_resume",
]
