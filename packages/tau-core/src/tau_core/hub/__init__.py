"""The ``tau hub`` daemon: a long-lived process in the hub role.

- :class:`Hub` runs the services, writes the heartbeat ``state.json`` and stops cleanly on
  SIGTERM/SIGINT; the next start turns an unclean exit into a :class:`CrashReport`.
- :class:`HubLock` keeps it to one hub per machine (:class:`AlreadyRunning` otherwise).
- :class:`ControlApi` is the local-only JSON API (``/health``, ``/status``) on 127.0.0.1; every
  other route needs a request signed with the control token and answers with a proof
  (ADR 0008).
- :class:`HubClient` calls it from another process: requests signed, proofs checked, raising
  :class:`HubUnavailable` or :class:`HubError`.
- :func:`render_plist` / :func:`render_systemd_unit` render the service definitions;
  launchd is driven through the :class:`Launchctl` protocol (:class:`FakeLaunchctl` in tests).
"""

from tau_core.hub.client import HubClient, HubError, HubUnavailable
from tau_core.hub.control import ControlApi, ControlRequest, Handler
from tau_core.hub.daemon import Hub, HubService
from tau_core.hub.launchd import (
    FakeLaunchctl,
    Launchctl,
    LaunchctlError,
    SystemLaunchctl,
    install_launch_agent,
    uninstall_launch_agent,
)
from tau_core.hub.lock import AlreadyRunning, HubLock
from tau_core.hub.state import UNCLEAN_EXIT, CrashReport, HubFiles, HubState
from tau_core.hub.units import (
    LABEL,
    PLACEHOLDER_PATHS,
    ServicePaths,
    render_plist,
    render_systemd_unit,
)

__all__ = [
    "LABEL",
    "PLACEHOLDER_PATHS",
    "UNCLEAN_EXIT",
    "AlreadyRunning",
    "ControlApi",
    "ControlRequest",
    "CrashReport",
    "FakeLaunchctl",
    "Handler",
    "Hub",
    "HubClient",
    "HubError",
    "HubFiles",
    "HubLock",
    "HubService",
    "HubState",
    "HubUnavailable",
    "Launchctl",
    "LaunchctlError",
    "ServicePaths",
    "SystemLaunchctl",
    "install_launch_agent",
    "render_plist",
    "render_systemd_unit",
    "uninstall_launch_agent",
]
