"""Session stores and the backend registry.

``[sessions].backend`` in ``tau.toml`` picks a factory from :data:`SESSION_BACKENDS`: ``memory``
(nothing survives the process) and ``file`` (``Config.sessions_dir``). Issue 018 registers
``cloud``, which talks only to the tau-cloud Worker API and never holds D1 credentials.
"""

from __future__ import annotations

from collections.abc import Callable

from tau_core.config import Config, ConfigError
from tau_core.sessions.base import SessionStore, SessionSummary, new_session_id
from tau_core.sessions.file import FileSessionStore, InvalidSessionId
from tau_core.sessions.memory import MemorySessionStore

__all__ = [
    "PLANNED_BACKENDS",
    "SESSION_BACKENDS",
    "FileSessionStore",
    "InvalidSessionId",
    "MemorySessionStore",
    "SessionStore",
    "SessionSummary",
    "new_session_id",
    "open_session_store",
]

SESSION_BACKENDS: dict[str, Callable[[Config], SessionStore]] = {
    "memory": lambda config: MemorySessionStore(),
    "file": lambda config: FileSessionStore(config.sessions_dir),
}

# Backends a later issue builds. tau.toml may name them; opening one fails with a clear message.
PLANNED_BACKENDS: dict[str, str] = {"cloud": "018"}


def open_session_store(config: Config) -> SessionStore:
    backend = config.sessions.backend
    factory = SESSION_BACKENDS.get(backend)
    if factory is not None:
        return factory(config)
    if backend in PLANNED_BACKENDS:
        raise ConfigError(
            f"Session backend '{backend}' is not available yet (issue {PLANNED_BACKENDS[backend]})."
        )
    raise ConfigError(f"Unknown session backend: '{backend}'.")
