"""tau-guard: the owner guard in the hub (ADR 0008).

Public API::

    GuardService, make_service                 the ``guard`` hub service (tau.hub_services)
    GuardMachine, Limits, Reading, Outcome     the pure state machine (tau_guard.state)
    Clock, SystemClock                         time for the state machine
    PresenceSource, QuartzPresence             presence signals (tau_guard.presence)
    GuardSettings, parse_settings              ``[component.guard]`` (tau_guard.config)
    AuditLog                                   ``guard/audit.jsonl`` (tau_guard.audit)
    WorkerRun                                  one worker subprocess (tau_guard.runner)
    FrameSource, AVFoundationCamera            the camera (tau_guard.camera)
    FaceEngine, OpenCvFaceEngine, Face         YuNet and SFace (tau_guard.engine)
    Calibration                                the head-turn calibration (tau_guard.liveness)
    KeyStore, KeychainKeyStore, MemoryKeyStore the template key (tau_guard.store)
    LocalAuthFactor                            LocalAuthentication (tau_guard.localauth)

Test helpers live in :mod:`tau_guard.testing`; the worker itself is ``python -m
tau_guard.worker``. Names load lazily, so importing the package (which the worker does at every
start) pulls in neither tau-core nor any camera or pyobjc module.
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import Any

try:
    __version__ = version("tau-guard")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0"

_EXPORTS = {
    "AVFoundationCamera": "tau_guard.camera",
    "AuditLog": "tau_guard.audit",
    "Calibration": "tau_guard.liveness",
    "Face": "tau_guard.engine",
    "FaceEngine": "tau_guard.engine",
    "FrameSource": "tau_guard.camera",
    "KeyStore": "tau_guard.store",
    "KeychainKeyStore": "tau_guard.store",
    "LocalAuthFactor": "tau_guard.localauth",
    "MemoryKeyStore": "tau_guard.store",
    "OpenCvFaceEngine": "tau_guard.engine",
    "Clock": "tau_guard.state",
    "GuardMachine": "tau_guard.state",
    "GuardService": "tau_guard.service",
    "GuardSettings": "tau_guard.config",
    "Limits": "tau_guard.state",
    "Outcome": "tau_guard.state",
    "PresenceSource": "tau_guard.presence",
    "QuartzPresence": "tau_guard.presence",
    "Reading": "tau_guard.state",
    "SystemClock": "tau_guard.state",
    "WorkerRun": "tau_guard.runner",
    "make_service": "tau_guard.service",
    "parse_settings": "tau_guard.config",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module 'tau_guard' has no attribute {name!r}")
    return getattr(import_module(module), name)


def __dir__() -> list[str]:
    return sorted([*globals(), *_EXPORTS])
