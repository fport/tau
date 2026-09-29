"""Session stores and the backend registry.

``[sessions].backend`` in ``tau.toml`` picks a factory: ``memory`` (nothing survives the
process) and ``file`` (``Config.sessions_dir``) are the built-in seed in
:data:`SESSION_BACKENDS`; other distributions add backends through the ``tau.sessions`` entry
point group and code adds them with :func:`tau_core.registry.register_session_backend`. Issue
018 registers ``cloud``, which talks only to the tau-cloud Worker API and never holds D1
credentials.
"""

from __future__ import annotations

from collections.abc import Callable

from tau_core import registry
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
"""The built-in seed; ``tau_core.registry`` merges entry points and registrations into it."""

# Backends a later issue builds. tau.toml may name them; opening one fails with a clear message.
PLANNED_BACKENDS: dict[str, str] = {"cloud": "018"}


def open_session_store(config: Config) -> SessionStore:
    backend = config.sessions.backend
    factory = registry.session_backend_factory(backend)
    if factory is not None:
        return factory(config)
    if backend in PLANNED_BACKENDS:
        raise ConfigError(
            f"Session backend '{backend}' is not available yet (issue {PLANNED_BACKENDS[backend]})."
        )
    raise ConfigError(f"Unknown session backend: '{backend}'.")
