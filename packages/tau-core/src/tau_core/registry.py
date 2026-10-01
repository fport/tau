"""Component registries: built-in seeds plus the ``tau.*`` entry-point groups.

Every pluggable part of tau is a *component* (CONTEXT.md). This module is the one place that
merges the three ways a component can arrive:

1. the built-in seed (``tau_core.models.PROVIDERS``, ``tau_core.sessions.SESSION_BACKENDS``);
2. an entry point in one of the groups below, declared by any installed distribution;
3. an in-process call to :func:`register_provider` / :func:`register_session_backend`.

- ``tau.providers``: ``factory(RoleConfig, env) -> Model``, with an optional ``required_env``
  attribute (credential alternatives); serves a role named in ``tau.toml``.
- ``tau.sessions``: ``factory(Config) -> SessionStore``; picked by ``[sessions].backend``.
- ``tau.context``: ``factory(Config) -> ContextSource``; merged into the ``## Now`` block.
- ``tau.hub_services``: ``factory(Config) -> HubService``; started by ``tau hub run``.

``tau.tools`` and ``tau.commands`` keep their own loaders in :mod:`tau_core.plugins`; the
discipline is the same everywhere: an entry point that fails to load, or loads the wrong kind
of object, is logged with its distribution name and skipped. It never breaks the CLI.

Precedence: a seed name wins over an entry point with the same name (the duplicate is logged
and ignored, so an installed package cannot silently replace ``bedrock``); an in-process
``register_*`` call replaces anything, because it is explicit code in the process.

Name-only lookups (:func:`provider_names`, :func:`session_backend_names`) never call
``EntryPoint.load``: ``Config.load`` validates names with them, so ``tau version`` and
``tau hub status`` never import a provider's SDK.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import metadata
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from strands.models.model import Model

    from tau_core.config import Config, RoleConfig
    from tau_core.hub.daemon import HubService
    from tau_core.persona import ContextSource
    from tau_core.sessions.base import SessionStore

logger = logging.getLogger(__name__)

TOOLS_GROUP = "tau.tools"
COMMANDS_GROUP = "tau.commands"
PROVIDERS_GROUP = "tau.providers"
SESSIONS_GROUP = "tau.sessions"
CONTEXT_GROUP = "tau.context"
HUB_SERVICES_GROUP = "tau.hub_services"

GROUPS: tuple[str, ...] = (
    TOOLS_GROUP,
    COMMANDS_GROUP,
    PROVIDERS_GROUP,
    SESSIONS_GROUP,
    CONTEXT_GROUP,
    HUB_SERVICES_GROUP,
)
"""Every entry-point group tau reads, in the order ``tau components`` lists them."""

ProviderFactory = Callable[["RoleConfig", Mapping[str, str]], "Model"]
SessionFactory = Callable[["Config"], "SessionStore"]
ContextFactory = Callable[["Config"], "ContextSource"]
HubServiceFactory = Callable[["Config"], "HubService"]

_REGISTRY_DIST = "tau-core"


@dataclass(frozen=True)
class Loaded:
    """One entry point after :func:`load_group`: its object, or why it was skipped."""

    group: str
    name: str
    distribution: str
    version: str
    obj: Any = None
    error: str | None = None


# -- entry points ----------------------------------------------------------------------------


def _entry_points(group: str) -> list[metadata.EntryPoint]:
    """The entry points of ``group`` (tests monkeypatch this and call :func:`reset`)."""
    return list(metadata.entry_points(group=group))


def _dist_name(ep: metadata.EntryPoint) -> str:
    dist = getattr(ep, "dist", None)
    return dist.name if dist is not None else "?"


def _dist_version(ep: metadata.EntryPoint) -> str:
    dist = getattr(ep, "dist", None)
    return dist.version if dist is not None else "?"


def entry_point_names(group: str) -> set[str]:
    """The names declared under ``group``, without loading anything."""
    return {ep.name for ep in _entry_points(group)}


def load_entry_point(ep: metadata.EntryPoint, *, expect: Callable[[Any], str | None]) -> Loaded:
    """Load one entry point; ``expect(obj)`` returns a reason to reject it, or ``None``."""
    dist, version = _dist_name(ep), _dist_version(ep)
    try:
        obj = ep.load()
    except Exception as exc:  # a broken plugin must never break the CLI
        message = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "%s entry point %s from %s failed to load: %s", ep.group, ep.name, dist, message
        )
        return Loaded(ep.group, ep.name, dist, version, error=message)
    reason = expect(obj)
    if reason is not None:
        logger.warning("%s entry point %s from %s skipped: %s", ep.group, ep.name, dist, reason)
        return Loaded(ep.group, ep.name, dist, version, error=reason)
    return Loaded(ep.group, ep.name, dist, version, obj=obj)


def _expect_callable(obj: Any) -> str | None:
    return None if callable(obj) else f"expected a factory, got {type(obj).__name__}"


def load_group(
    group: str, *, expect: Callable[[Any], str | None] = _expect_callable
) -> list[Loaded]:
    """Every entry point of ``group``, loaded with the skip-and-log discipline (no caching)."""
    return [load_entry_point(ep, expect=expect) for ep in _entry_points(group)]


def _discover(
    group: str, expect: Callable[[Any], str | None]
) -> tuple[dict[str, Any], dict[str, Loaded]]:
    """The loadable entry points of ``group`` as ``{name: object}`` (the first name wins) and
    the ones that failed as ``{name: Loaded}`` (the first failure per name)."""
    found: dict[str, Any] = {}
    errors: dict[str, Loaded] = {}
    for item in load_group(group, expect=expect):
        if item.error is not None:
            errors.setdefault(item.name, item)
            continue
        if item.name in found:
            logger.warning(
                "%s entry point %s from %s ignored: the name is already taken",
                group,
                item.name,
                item.distribution,
            )
            continue
        found[item.name] = item.obj
    return found, errors


def discover(
    group: str, *, expect: Callable[[Any], str | None] = _expect_callable
) -> dict[str, Any]:
    """``{name: object}`` for the loadable entry points of ``group``; the first name wins."""
    return _discover(group, expect)[0]


# -- merged lookups (seed | entry points | registered), cached ---------------------------------

_registered: dict[str, dict[str, Any]] = {PROVIDERS_GROUP: {}, SESSIONS_GROUP: {}}
_required_env: dict[str, list[list[str]]] = {}
_merged: dict[str, dict[str, Any]] = {}
_errors: dict[str, dict[str, Loaded]] = {}
_names: dict[str, frozenset[str]] = {}


def reset() -> None:
    """Forget the cached lookups (and, for tests, every in-process registration)."""
    for group in _registered:
        _registered[group].clear()
    _required_env.clear()
    _invalidate()


def _invalidate() -> None:
    _merged.clear()
    _errors.clear()
    _names.clear()


def _seed(group: str) -> dict[str, Any]:
    # Imported lazily: models and sessions import this module at import time.
    if group == PROVIDERS_GROUP:
        from tau_core.models import PROVIDERS

        return dict(PROVIDERS)
    if group == SESSIONS_GROUP:
        from tau_core.sessions import SESSION_BACKENDS

        return dict(SESSION_BACKENDS)
    return {}


def _merge(group: str) -> dict[str, Any]:
    if group in _merged:
        return _merged[group]
    seed = _seed(group)
    merged = dict(seed)
    found, errors = _discover(group, _expect_callable)
    for name, obj in found.items():
        if name in seed:
            logger.warning(
                "%s entry point %s ignored: it would replace the built-in %s", group, name, name
            )
            continue
        merged[name] = obj
    merged.update(_registered.get(group, {}))
    _merged[group] = merged
    _errors[group] = errors
    return merged


def load_error(group: str, name: str) -> Loaded | None:
    """Why the entry point ``name`` of ``group`` is not in the merged lookup, or ``None``
    when it loaded (or was never declared). Lets ``resolve_model`` and ``tau doctor`` tell a
    declared-but-broken provider apart from an unknown one."""
    if name in _merge(group):
        return None
    return _errors.get(group, {}).get(name)


def _known_names(group: str) -> frozenset[str]:
    if group not in _names:
        names = set(_seed(group)) | entry_point_names(group) | set(_registered.get(group, {}))
        _names[group] = frozenset(names)
    return _names[group]


def providers() -> dict[str, ProviderFactory]:
    """Seed, entry-point and registered providers merged (loads the entry points once)."""
    return dict(_merge(PROVIDERS_GROUP))


def provider_factory(name: str) -> ProviderFactory | None:
    return _merge(PROVIDERS_GROUP).get(name)


def provider_names() -> frozenset[str]:
    """Provider names known without loading anything: seed, entry points, registered."""
    return _known_names(PROVIDERS_GROUP)


def provider_required_env(name: str) -> list[list[str]]:
    """Credential alternatives a non-seed provider declares (``[]`` = none needed).

    A registered provider uses the ``required_env`` given at registration; an entry-point
    provider may carry a ``required_env`` attribute on its factory (a list of alternative
    variable lists, each alternative fully set is enough).
    """
    if name in _required_env:
        return [list(alt) for alt in _required_env[name]]
    factory = provider_factory(name)
    raw = getattr(factory, "required_env", None) if factory is not None else None
    if raw is None:
        return []
    try:
        alternatives = [[str(v) for v in alt] for alt in raw]
    except TypeError:
        logger.warning("provider %s: required_env must be a list of variable lists; ignored", name)
        return []
    return alternatives


def register_provider(
    name: str, factory: ProviderFactory, required_env: list[list[str]] | None = None
) -> None:
    """Add (or replace) a provider in this process; ``required_env`` lists credential
    alternatives, each inner list fully set is enough (``None`` = none needed)."""
    if not callable(factory):
        raise TypeError(f"provider factory for {name!r} must be callable")
    if name in _merge(PROVIDERS_GROUP):
        logger.info("provider %s replaced by an in-process registration", name)
    _registered[PROVIDERS_GROUP][name] = factory
    _required_env[name] = [list(alt) for alt in (required_env or [])]
    _invalidate()


def session_backends() -> dict[str, SessionFactory]:
    return dict(_merge(SESSIONS_GROUP))


def session_backend_factory(name: str) -> SessionFactory | None:
    return _merge(SESSIONS_GROUP).get(name)


def session_backend_names() -> frozenset[str]:
    return _known_names(SESSIONS_GROUP)


def register_session_backend(name: str, factory: SessionFactory) -> None:
    """Add (or replace) a session backend in this process."""
    if not callable(factory):
        raise TypeError(f"session backend factory for {name!r} must be callable")
    if name in _merge(SESSIONS_GROUP):
        logger.info("session backend %s replaced by an in-process registration", name)
    _registered[SESSIONS_GROUP][name] = factory
    _invalidate()


# -- instantiated groups ---------------------------------------------------------------------


def _expect_hub_service(obj: Any) -> str | None:
    from tau_core.hub.daemon import HubService

    if isinstance(obj, HubService) and isinstance(getattr(obj, "name", None), str):
        return None
    return f"expected a HubService (name, start, stop), got {type(obj).__name__}"


def _build_all(
    group: str, config: Config, *, expect: Callable[[Any], str | None], enabled: list[str]
) -> dict[str, Any]:
    """Call every ``factory(config)`` of ``group`` and keep the objects ``expect`` accepts.

    ``enabled`` is the ``[components]`` list for the group: empty means every discovered
    component; a listed name that no distribution provides is logged and ignored.
    """
    factories = discover(group)
    wanted = list(enabled) or list(factories)
    for name in wanted:
        if name not in factories:
            logger.warning("%s: no installed component is called %s", group, name)
    built: dict[str, Any] = {}
    for name in wanted:
        factory = factories.get(name)
        if factory is None:
            continue
        if (component := config.opted_out(factory)) is not None:
            logger.debug(
                "%s component %s is off until [component.%s] enabled", group, name, component
            )
            continue
        try:
            obj = factory(config)
        except Exception as exc:
            logger.warning("%s component %s failed to build: %s", group, name, exc, exc_info=True)
            continue
        reason = expect(obj)
        if reason is not None:
            logger.warning("%s component %s skipped: %s", group, name, reason)
            continue
        built[name] = obj
    return built


def context_sources(config: Config) -> dict[str, ContextSource]:
    """``{name: source}`` for the enabled ``tau.context`` components (see ``[components]``)."""
    return _build_all(
        CONTEXT_GROUP,
        config,
        expect=lambda obj: None if callable(obj) else "a context source must be callable",
        enabled=config.components.context,
    )


def hub_services(config: Config) -> dict[str, HubService]:
    """``{name: service}`` for the enabled ``tau.hub_services`` components."""
    return _build_all(
        HUB_SERVICES_GROUP,
        config,
        expect=_expect_hub_service,
        enabled=config.components.hub_services,
    )


def seeds(group: str) -> list[Loaded]:
    """The built-in components of ``group`` as :class:`Loaded` rows (for ``tau components``)."""
    from tau_core._version import __version__

    return [
        Loaded(group, name, _REGISTRY_DIST, __version__, obj=obj)
        for name, obj in _seed(group).items()
    ]


def registered(group: str) -> list[Loaded]:
    """In-process registrations of ``group`` as :class:`Loaded` rows."""
    return [
        Loaded(group, name, "<registered in-process>", "-", obj=obj)
        for name, obj in _registered.get(group, {}).items()
    ]
