"""Static bootstrap configuration: ``tau.toml`` plus environment variables.

``Config`` is what the hub or a channel reads once at startup: which provider and model id
serve each role, the loop guard, the session backend, the hub ports and the two roots
(``TAU_HOME`` for configuration, ``TAU_DATA_DIR`` for mutable state), plus the UI language
(``[ui] language``, overridden by ``TAU_LANG``) and the component switches (``[components]``,
free ``[component.<name>]`` tables). Runtime settings that change while tau runs are a
different thing (*Settings*, a file under ``TAU_DATA_DIR``, issue 019); editing the two
bootstrap files from a channel is :mod:`tau_core.settings`.

Every ``ConfigError`` message is plain English: it is raised before any channel exists.
"""

from __future__ import annotations

import copy
import logging
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, load_dotenv

from tau_core.i18n import DEFAULT_LANGUAGE, LANGUAGES

logger = logging.getLogger(__name__)

CONFIG_FILE = "tau.toml"
DEFAULT_HOME = "~/.tau"
DEFAULT_DATA_DIR = "~/.local/share/tau"
DEFAULT_PROFILE = "home"
PROFILES = ("home", "travel", "sport")
DEFAULT_ROLE = "hub"
HOST_ROLES = ("hub", "node")

_ROLE_KEYS = {"provider", "model_id", "region", "max_tokens", "params", "fallback", "cache"}
_CACHE_STRATEGIES = ("auto", "anthropic")
_CACHE_KEYS = {"strategy", "ttl", "system_prompt_ttl", "tools_ttl"}
CONTEXT_MODES = ("sliding", "summarize")
"""``[agent] context`` values. The SDK's ``auto``/``agentic`` presets are rejected on purpose:
they register untiered SDK tools that the tier gate would refuse."""
KNOWN_TABLES = frozenset({"models", "agent", "sessions", "hub", "ui", "components", "component"})
"""Top-level ``tau.toml`` tables tau reads; any other is logged once and ignored."""
DIST_PREFIX = "dist:"
"""``[components] tools.disabled`` entries with this prefix disable a whole distribution."""

_warned_tables: set[tuple[str, str]] = set()


class ConfigError(Exception):
    """Invalid or missing configuration; the message is meant for the user."""


class ConfigNotFound(ConfigError):
    """No ``tau.toml`` in the resolved home: nothing is configured yet (``tau init`` or the
    TUI's setup screen create one). ``home`` is the directory that was looked in."""

    def __init__(self, home: Path) -> None:
        self.home = home
        super().__init__(
            f"Configuration file not found: {home / CONFIG_FILE}. "
            "Set TAU_HOME or run from the repository root."
        )


@dataclass(frozen=True)
class RoleConfig:
    """Provider and model id behind one model role (``brain``, ``fast``, ``local``)."""

    provider: str
    model_id: str
    region: str | None = None
    max_tokens: int | None = None
    params: dict[str, Any] = field(default_factory=dict)
    fallback: RoleConfig | None = None
    cache: dict[str, Any] | None = None
    """Prompt-cache settings (``strategy``, ``ttl``, ``system_prompt_ttl``, ``tools_ttl``), the
    keyword arguments of Strands' ``CacheConfig``; ``None`` leaves caching to the provider."""


@dataclass(frozen=True)
class AgentConfig:
    """``[agent]``: the loop guard, the conversation window and the optional token budget."""

    max_turns: int = 12
    context: str = "sliding"
    window_size: int = 60
    max_total_tokens: int | None = None


@dataclass(frozen=True)
class SessionsConfig:
    backend: str = "memory"


@dataclass(frozen=True)
class HubConfig:
    control_port: int = 7877
    heartbeat_seconds: int = 5


@dataclass(frozen=True)
class UiConfig:
    """Chrome language of the channels (``en`` or ``tr``); see :mod:`tau_core.i18n`."""

    language: str = DEFAULT_LANGUAGE


@dataclass(frozen=True)
class ComponentsConfig:
    """``[components]``: which discovered components are switched on or off.

    ``tools_disabled`` (``tools.disabled`` in the file) holds tool names or ``dist:<name>``
    for every tool of a distribution; ``context`` and ``hub_services`` (``hub.services``)
    list the enabled component names of their groups, empty meaning every discovered one.
    """

    tools_disabled: tuple[str, ...] = ()
    context: tuple[str, ...] = ()
    hub_services: tuple[str, ...] = ()

    def tool_disabled(self, name: str, distribution: str | None = None) -> bool:
        """Is this tool switched off, by its name or by its distribution?"""
        if name in self.tools_disabled:
            return True
        return distribution is not None and f"{DIST_PREFIX}{distribution}" in self.tools_disabled


@dataclass(frozen=True)
class Config:
    """Everything tau needs to start. Build it with :meth:`Config.load`."""

    home: Path
    data_dir: Path
    profile: str
    role: str
    roles: dict[str, RoleConfig]
    agent: AgentConfig
    sessions: SessionsConfig
    hub: HubConfig
    ui: UiConfig = field(default_factory=UiConfig)
    components: ComponentsConfig = field(default_factory=ComponentsConfig)
    component_tables: dict[str, dict[str, Any]] = field(default_factory=dict)
    """The free ``[component.<name>]`` tables, read through :meth:`component`."""

    def component(self, name: str) -> dict[str, Any]:
        """The ``[component.<name>]`` table as a fresh dict (``{}`` when there is none)."""
        return copy.deepcopy(self.component_tables.get(name, {}))

    @property
    def persona_dir(self) -> Path:
        return self.home / "persona"

    @property
    def tools_dir(self) -> Path:
        return self.home / "tools"

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def hub_dir(self) -> Path:
        return self.data_dir / "hub"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @classmethod
    def load(
        cls, home: Path | str | None = None, *, env: Mapping[str, str] | None = None
    ) -> Config:
        """Load ``<home>/tau.toml`` and the environment.

        ``home`` wins over ``TAU_HOME``; without either, the current directory is used when it
        holds a ``tau.toml``, else ``~/.tau``. ``<home>/.env`` is read with python-dotenv and
        never overrides variables that are already set. With ``env=None`` the process
        environment is used (and ``.env`` is loaded into it, so provider SDKs see the same
        credentials); with an explicit mapping nothing global is touched.
        """
        base_env: Mapping[str, str] = os.environ if env is None else env
        root = _resolve_home(home, base_env)
        dotenv_path = root / ".env"
        if env is None:
            if dotenv_path.is_file():
                load_dotenv(dotenv_path, override=False)
            merged: Mapping[str, str] = os.environ
        else:
            file_values = dotenv_values(dotenv_path) if dotenv_path.is_file() else {}
            merged = {k: v for k, v in file_values.items() if v is not None} | dict(env)

        config_path = root / CONFIG_FILE
        if not config_path.is_file():
            raise ConfigNotFound(root)
        try:
            raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(
                f"Configuration file could not be read: {config_path}: {exc}"
            ) from exc

        _warn_unknown_tables(config_path, raw)
        roles = _parse_roles(raw.get("models", {}).get("roles", {}))
        agent = _parse_agent(raw.get("agent", {}))
        sessions = _parse_sessions(raw.get("sessions", {}))
        hub = _parse_hub(raw.get("hub", {}), merged)
        ui = _parse_ui(raw.get("ui", {}), merged)
        components = _parse_components(raw.get("components", {}))
        component_tables = _parse_component_tables(raw.get("component", {}))

        data_dir = Path(merged.get("TAU_DATA_DIR") or DEFAULT_DATA_DIR).expanduser()
        profile = merged.get("TAU_PROFILE") or DEFAULT_PROFILE
        host_role = merged.get("TAU_ROLE") or DEFAULT_ROLE
        if host_role not in HOST_ROLES:
            raise ConfigError(f"Invalid TAU_ROLE: '{host_role}'. Valid values: hub, node.")

        config = cls(
            home=root,
            data_dir=data_dir.resolve(),
            profile=profile,
            role=host_role,
            roles=roles,
            agent=agent,
            sessions=sessions,
            hub=hub,
            ui=ui,
            components=components,
            component_tables=component_tables,
        )
        _validate_names(config)
        return config

    def with_overrides(self, **kw: Any) -> Config:
        """Return a copy with the given fields replaced (``dataclasses.replace``)."""
        return replace(self, **kw)


def resolve_home(home: Path | str | None = None, env: Mapping[str, str] | None = None) -> Path:
    """The configuration root ``Config.load`` would use: ``home``, else ``TAU_HOME``, else the
    current directory when it holds a ``tau.toml``, else ``~/.tau``."""
    return _resolve_home(home, os.environ if env is None else env)


def _resolve_home(home: Path | str | None, env: Mapping[str, str]) -> Path:
    if home is not None:
        return Path(home).expanduser().resolve()
    if env.get("TAU_HOME"):
        return Path(env["TAU_HOME"]).expanduser().resolve()
    cwd = Path.cwd()
    if (cwd / CONFIG_FILE).is_file():
        return cwd.resolve()
    return Path(DEFAULT_HOME).expanduser().resolve()


def _parse_roles(raw: Any) -> dict[str, RoleConfig]:
    if not isinstance(raw, dict):
        raise ConfigError("tau.toml: [models.roles] must be a table.")
    return {name: _parse_role(name, value) for name, value in raw.items()}


def _parse_role(name: str, raw: Any, *, allow_fallback: bool = True) -> RoleConfig:
    where = f"[models.roles.{name}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"tau.toml: {where} must be a table.")
    unknown = sorted(set(raw) - _ROLE_KEYS)
    if unknown:
        raise ConfigError(f"tau.toml: {where} has unknown keys: {', '.join(unknown)}.")
    provider = raw.get("provider")
    model_id = raw.get("model_id")
    if not isinstance(provider, str) or not provider:
        raise ConfigError(f"tau.toml: {where} needs a 'provider'.")
    if not isinstance(model_id, str) or not model_id:
        raise ConfigError(f"tau.toml: {where} needs a 'model_id'.")
    region = raw.get("region")
    if region is not None and not isinstance(region, str):
        raise ConfigError(f"tau.toml: {where} 'region' must be a string.")
    max_tokens = raw.get("max_tokens")
    if max_tokens is not None and (not isinstance(max_tokens, int) or max_tokens <= 0):
        raise ConfigError(f"tau.toml: {where} 'max_tokens' must be a positive integer.")
    params = raw.get("params", {})
    if not isinstance(params, dict):
        raise ConfigError(f"tau.toml: {where} 'params' must be a table.")
    fallback = None
    if "fallback" in raw:
        if not allow_fallback:
            raise ConfigError(f"tau.toml: {where} cannot nest another 'fallback'.")
        fallback = _parse_role(f"{name}.fallback", raw["fallback"], allow_fallback=False)
    cache = _parse_cache(where, raw.get("cache"))
    return RoleConfig(
        provider=provider,
        model_id=model_id,
        region=region,
        max_tokens=max_tokens,
        params=dict(params),
        fallback=fallback,
        cache=cache,
    )


def _parse_cache(where: str, raw: Any) -> dict[str, Any] | None:
    """``cache = { strategy = "auto", ttl = "1h", ... }`` → ``CacheConfig`` keyword arguments."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"tau.toml: {where} 'cache' must be a table.")
    unknown = sorted(set(raw) - _CACHE_KEYS)
    if unknown:
        raise ConfigError(f"tau.toml: {where} 'cache' has unknown keys: {', '.join(unknown)}.")
    cache = dict(raw)
    strategy = cache.get("strategy", "auto")
    if strategy not in _CACHE_STRATEGIES:
        raise ConfigError(
            f"tau.toml: {where} 'cache.strategy' must be one of {', '.join(_CACHE_STRATEGIES)}."
        )
    cache["strategy"] = strategy
    if "ttl" in cache and not isinstance(cache["ttl"], str):
        raise ConfigError(f"tau.toml: {where} 'cache.ttl' must be a string like \"1h\".")
    for key in ("system_prompt_ttl", "tools_ttl"):
        if key in cache and not isinstance(cache[key], bool | str):
            raise ConfigError(f"tau.toml: {where} 'cache.{key}' must be a boolean or a string.")
    return cache


def _positive_int(raw: Any, table: str, key: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ConfigError(f"tau.toml: [{table}] '{key}' must be an integer of 1 or more.")
    return raw


def _parse_agent(raw: Any) -> AgentConfig:
    if not isinstance(raw, dict):
        raise ConfigError("tau.toml: [agent] must be a table.")
    max_turns = _positive_int(raw.get("max_turns", AgentConfig.max_turns), "agent", "max_turns")
    context = raw.get("context", AgentConfig.context)
    if not isinstance(context, str) or context not in CONTEXT_MODES:
        raise ConfigError(
            f"tau.toml: [agent] 'context' must be one of {', '.join(CONTEXT_MODES)}, "
            f"not {context!r}."
        )
    window_size = _positive_int(
        raw.get("window_size", AgentConfig.window_size), "agent", "window_size"
    )
    max_total_tokens = raw.get("max_total_tokens")
    if max_total_tokens is not None:
        max_total_tokens = _positive_int(max_total_tokens, "agent", "max_total_tokens")
    return AgentConfig(
        max_turns=max_turns,
        context=context,
        window_size=window_size,
        max_total_tokens=max_total_tokens,
    )


def _parse_sessions(raw: Any) -> SessionsConfig:
    if not isinstance(raw, dict):
        raise ConfigError("tau.toml: [sessions] must be a table.")
    backend = raw.get("backend", SessionsConfig.backend)
    if not isinstance(backend, str) or not backend:
        raise ConfigError("tau.toml: [sessions] 'backend' must be a string.")
    return SessionsConfig(backend=backend)


def _parse_hub(raw: Any, env: Mapping[str, str]) -> HubConfig:
    if not isinstance(raw, dict):
        raise ConfigError("tau.toml: [hub] must be a table.")
    port = raw.get("control_port", HubConfig.control_port)
    heartbeat = raw.get("heartbeat_seconds", HubConfig.heartbeat_seconds)
    if env.get("TAU_HUB_PORT"):
        try:
            port = int(env["TAU_HUB_PORT"])
        except ValueError as exc:
            raise ConfigError(
                f"Invalid TAU_HUB_PORT: '{env['TAU_HUB_PORT']}'. Enter a port number."
            ) from exc
    if not isinstance(port, int) or not 0 < port < 65536:
        raise ConfigError("tau.toml: [hub] 'control_port' must be between 1 and 65535.")
    if not isinstance(heartbeat, int) or heartbeat < 1:
        raise ConfigError("tau.toml: [hub] 'heartbeat_seconds' must be a positive integer.")
    return HubConfig(control_port=port, heartbeat_seconds=heartbeat)


def _parse_ui(raw: Any, env: Mapping[str, str]) -> UiConfig:
    """``[ui] language`` from the file, overridden by ``TAU_LANG``; both must be known languages."""
    if not isinstance(raw, dict):
        raise ConfigError("tau.toml: [ui] must be a table.")
    language = raw.get("language", UiConfig.language)
    source = "tau.toml: [ui] 'language'"
    if env.get("TAU_LANG"):
        language = env["TAU_LANG"]
        source = "TAU_LANG"
    if not isinstance(language, str) or language not in LANGUAGES:
        raise ConfigError(f"{source} must be one of {', '.join(LANGUAGES)}, not {language!r}.")
    return UiConfig(language=language)


def _string_list(raw: Any, where: str, key: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
        raise ConfigError(f"tau.toml: {where} '{key}' must be a list of non-empty strings.")
    return tuple(raw)


def _sub_table(raw: Mapping[str, Any], name: str, keys: set[str]) -> dict[str, Any]:
    """``[components.<name>]``: a table whose keys are all in ``keys`` (a typo such as
    ``disable`` must not silently leave a tool switched on)."""
    table = raw.get(name, {})
    if not isinstance(table, dict):
        raise ConfigError(f"tau.toml: [components.{name}] must be a table.")
    unknown = sorted(set(table) - keys)
    if unknown:
        raise ConfigError(f"tau.toml: [components.{name}] has unknown keys: {', '.join(unknown)}.")
    return table


def _parse_components(raw: Any) -> ComponentsConfig:
    """``[components]``: ``tools.disabled``, ``context`` and ``hub.services`` lists."""
    if not isinstance(raw, dict):
        raise ConfigError("tau.toml: [components] must be a table.")
    unknown = sorted(set(raw) - {"tools", "context", "hub"})
    if unknown:
        raise ConfigError(f"tau.toml: [components] has unknown keys: {', '.join(unknown)}.")
    tools = _sub_table(raw, "tools", {"disabled"})
    hub = _sub_table(raw, "hub", {"services"})
    return ComponentsConfig(
        tools_disabled=_string_list(tools.get("disabled"), "[components.tools]", "disabled"),
        context=_string_list(raw.get("context"), "[components]", "context"),
        hub_services=_string_list(hub.get("services"), "[components.hub]", "services"),
    )


def _parse_component_tables(raw: Any) -> dict[str, dict[str, Any]]:
    """Free ``[component.<name>]`` tables, kept as they are for :meth:`Config.component`."""
    if not isinstance(raw, dict):
        raise ConfigError("tau.toml: [component] must hold [component.<name>] tables.")
    tables: dict[str, dict[str, Any]] = {}
    for name, value in raw.items():
        if not isinstance(value, dict):
            raise ConfigError(f"tau.toml: [component.{name}] must be a table.")
        tables[name] = copy.deepcopy(value)
    return tables


def _warn_unknown_tables(config_path: Path, raw: Mapping[str, Any]) -> None:
    """Log every top-level table tau does not read, once per file and table, never fail.

    A typo (``[model]``) or a table meant for a plugin that is not installed must not stop
    tau from starting; ``tau doctor`` and the log point it out.
    """
    for name in raw:
        if name in KNOWN_TABLES:
            continue
        key = (str(config_path), name)
        if key in _warned_tables:
            continue
        _warned_tables.add(key)
        logger.warning(
            "%s: unknown top-level table [%s] is ignored (known: %s)",
            config_path,
            name,
            ", ".join(sorted(KNOWN_TABLES)),
        )


def _validate_names(config: Config) -> None:
    """Reject providers and session backends nobody knows about, by name only.

    The names come from :mod:`tau_core.registry` (the built-in seed, the entry-point names of
    ``tau.providers`` / ``tau.sessions`` and in-process registrations), cached after the first
    call and never loading an entry point, so ``tau version`` stays fast and no provider SDK is
    imported here. Names that are planned but not built yet pass and fail with a clear message
    when used.
    """
    from tau_core import registry
    from tau_core.models import PLANNED_PROVIDERS
    from tau_core.sessions import PLANNED_BACKENDS

    known_providers = registry.provider_names() | set(PLANNED_PROVIDERS)
    for name, role in config.roles.items():
        for cfg in (role, role.fallback):
            if cfg is not None and cfg.provider not in known_providers:
                raise ConfigError(
                    f"tau.toml: unknown provider for role '{name}': '{cfg.provider}'. "
                    f"Valid values: {', '.join(sorted(known_providers))}."
                )
    known_backends = registry.session_backend_names() | set(PLANNED_BACKENDS)
    if config.sessions.backend not in known_backends:
        raise ConfigError(
            f"tau.toml: unknown session backend: '{config.sessions.backend}'. "
            f"Valid values: {', '.join(sorted(known_backends))}."
        )
