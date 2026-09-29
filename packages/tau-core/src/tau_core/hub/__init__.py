"""The ``tau hub`` daemon: a long-lived process in the hub role.

- :class:`Hub` runs the services, writes the heartbeat ``state.json`` and stops cleanly on
  SIGTERM/SIGINT; the next start turns an unclean exit into a :class:`CrashReport`.
- :class:`HubLock` keeps it to one hub per machine (:class:`AlreadyRunning` otherwise).
- :class:`ControlApi` is the local-only JSON API (``/health``, ``/status``) on 127.0.0.1.
"""

from tau_core.hub.control import ControlApi, ControlRequest, Handler
from tau_core.hub.daemon import Hub, HubService
from tau_core.hub.lock import AlreadyRunning, HubLock
from tau_core.hub.state import UNCLEAN_EXIT, CrashReport, HubFiles, HubState

__all__ = [
    "UNCLEAN_EXIT",
    "AlreadyRunning",
    "ControlApi",
    "ControlRequest",
    "CrashReport",
    "Handler",
    "Hub",
    "HubFiles",
    "HubLock",
    "HubService",
    "HubState",
]
