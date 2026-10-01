"""Simulated devices, stand-ins for hardware that is not on hand (ADR 0015 §5): a built-in,
opt-in component of tau-core (``[component.sim] enabled = true``).

The first one is a lamp. tau drives it with the tools and tiers a real lamp will have:
``lamp_list`` (tier 0) and ``lamp_set`` (tier 2, every call asks the owner). Its state lives in
``TAU_DATA_DIR/sim/lamps.json``, the lamps are named in ``[component.sim] lamps`` (default
``["desk"]``), and every answer, card and status line says it is simulated. The ``sim`` hub
service implements tau-core's ``DeviceSource``, so the web app lists the lamps and sees every
change. Nothing here talks to hardware.

Public API (other packages import these names)::

    Lamp, LampStore, SimSettings, SimConfigError, UnknownLamp, device_id, normalize_name,
    COMPONENT, DEFAULT_LAMPS, KIND, NAME_RE
    TOOLS, SET_EFFECT, SIMULATED_NOTE
    SimService, make_service, SERVICE_NAME, POLL_SECONDS
"""

from __future__ import annotations

from tau_core.sim.lamps import (
    COMPONENT,
    DEFAULT_LAMPS,
    KIND,
    NAME_RE,
    Lamp,
    LampStore,
    SimConfigError,
    SimSettings,
    UnknownLamp,
    device_id,
    normalize_name,
)
from tau_core.sim.service import POLL_SECONDS, SERVICE_NAME, SimService, make_service
from tau_core.sim.tools import SET_EFFECT, SIMULATED_NOTE, TOOLS

__all__ = [
    "COMPONENT",
    "DEFAULT_LAMPS",
    "KIND",
    "NAME_RE",
    "POLL_SECONDS",
    "SERVICE_NAME",
    "SET_EFFECT",
    "SIMULATED_NOTE",
    "TOOLS",
    "Lamp",
    "LampStore",
    "SimConfigError",
    "SimService",
    "SimSettings",
    "UnknownLamp",
    "device_id",
    "make_service",
    "normalize_name",
]
