"""tau-web: the hub's web app server (ADR 0015 §2).

The ``web`` hub service runs the owner's turns inside the hub on the ``web`` channel (the same
Strands agent, tools, tiers, guard and session store as the TUI) and streams them to paired
browsers with the turn protocol (``docs/reference/turn-protocol.md``). It listens on loopback
or the tailnet only; ``tau web device add <name>`` pairs a browser.

Public API (other packages import these names)::

    WebService, make_service, SERVICE_NAME
    WebSettings, WebConfigError, bind_allowed, COMPONENT, DEFAULT_PORT
    DeviceRegistry, Device, DeviceError, PAIRING_MINUTES
    Runtime, Turn, TurnError, WebApprover, OWNER_CHANNELS, CHANNEL
    create_app, COOKIE
"""

from __future__ import annotations

from tau_web.app import COOKIE, create_app
from tau_web.devices import PAIRING_MINUTES, Device, DeviceError, DeviceRegistry
from tau_web.service import SERVICE_NAME, WebService, make_service
from tau_web.settings import COMPONENT, DEFAULT_PORT, WebConfigError, WebSettings, bind_allowed
from tau_web.turns import CHANNEL, OWNER_CHANNELS, Runtime, Turn, TurnError, WebApprover

__version__ = "0.1.0"

__all__ = [
    "CHANNEL",
    "COMPONENT",
    "COOKIE",
    "DEFAULT_PORT",
    "OWNER_CHANNELS",
    "PAIRING_MINUTES",
    "SERVICE_NAME",
    "Device",
    "DeviceError",
    "DeviceRegistry",
    "Runtime",
    "Turn",
    "TurnError",
    "WebApprover",
    "WebConfigError",
    "WebService",
    "WebSettings",
    "__version__",
    "bind_allowed",
    "create_app",
    "make_service",
]
