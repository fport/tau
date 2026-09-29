"""tau-tui: the Textual terminal interface for tau.

Public API::

    TauApp, build_app, resolve_resume, SessionNotFound
    TuiApprover, ApprovalScreen
    Transcript, EventLog, rasterise
"""

from importlib.metadata import PackageNotFoundError, version

import tau_tui.strings  # noqa: F401  (registers the tui.* message keys)
from tau_tui.app import SessionNotFound, TauApp, build_app, resolve_resume
from tau_tui.approval import ApprovalScreen, TuiApprover
from tau_tui.brand import rasterise
from tau_tui.events import EventLog
from tau_tui.transcript import Transcript

try:
    __version__ = version("tau-tui")
except PackageNotFoundError:
    __version__ = "0.0.0"

__all__ = [
    "ApprovalScreen",
    "EventLog",
    "SessionNotFound",
    "TauApp",
    "Transcript",
    "TuiApprover",
    "__version__",
    "build_app",
    "rasterise",
    "resolve_resume",
]
