"""Static bootstrap configuration: ``tau.toml`` plus environment variables.

``Config`` is what the hub or a channel reads once at startup: which provider and model id
serve each role, the loop guard, the session backend, the hub ports and the two roots
(``TAU_HOME`` for configuration, ``TAU_DATA_DIR`` for mutable state). Runtime settings that
change while tau runs are a different thing (*Settings*, stored in D1, issue 019).
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from dotenv import dotenv_values, load_dotenv

CONFIG_FILE = "tau.toml"
DEFAULT_HOME = "~/.tau"
DEFAULT_DATA_DIR = "~/.local/share/tau"
DEFAULT_PROFILE = "ev"
DEFAULT_ROLE = "hub"
HOST_ROLES = ("hub", "node")

_ROLE_KEYS = {"provider", "model_id", "region", "max_tokens", "params", "fallback"}


class ConfigError(Exception):
    """Invalid or missing configuration. The message is Turkish and meant for the user."""


@dataclass(frozen=True)
class RoleConfig:
    """Provider and model id behind one model role (``brain``, ``fast``, ``local``)."""

    provider: str
    model_id: str
    region: str | None = None
    max_tokens: int | None = None
    params: dict[str, Any] = field(default_factory=dict)
    fallback: RoleConfig | None = None


@dataclass(frozen=True)
class AgentConfig:
    max_turns: int = 12


@dataclass(frozen=True)
class SessionsConfig:
    backend: str = "memory"


@dataclass(frozen=True)
class HubConfig:
    control_port: int = 7877
    heartbeat_seconds: int = 5


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
            raise ConfigError(
                f"Yapılandırma dosyası bulunamadı: {config_path}. "
                "TAU_HOME değişkenini ayarlayın veya repo kökünde çalıştırın."
            )
        try:
            raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"Yapılandırma dosyası okunamadı: {config_path}: {exc}") from exc

        roles = _parse_roles(raw.get("models", {}).get("roles", {}))
        agent = _parse_agent(raw.get("agent", {}))
        sessions = _parse_sessions(raw.get("sessions", {}))
        hub = _parse_hub(raw.get("hub", {}), merged)

        data_dir = Path(merged.get("TAU_DATA_DIR") or DEFAULT_DATA_DIR).expanduser()
        profile = merged.get("TAU_PROFILE") or DEFAULT_PROFILE
        host_role = merged.get("TAU_ROLE") or DEFAULT_ROLE
        if host_role not in HOST_ROLES:
            raise ConfigError(f"TAU_ROLE geçersiz: '{host_role}'. Geçerli değerler: hub, node.")

        config = cls(
            home=root,
            data_dir=data_dir.resolve(),
            profile=profile,
            role=host_role,
            roles=roles,
            agent=agent,
            sessions=sessions,
            hub=hub,
        )
        _validate_names(config)
        return config

    def with_overrides(self, **kw: Any) -> Config:
        """Return a copy with the given fields replaced (``dataclasses.replace``)."""
        return replace(self, **kw)


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
        raise ConfigError("tau.toml: [models.roles] bir tablo olmalı.")
    return {name: _parse_role(name, value) for name, value in raw.items()}


def _parse_role(name: str, raw: Any, *, allow_fallback: bool = True) -> RoleConfig:
    where = f"[models.roles.{name}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"tau.toml: {where} bir tablo olmalı.")
    unknown = sorted(set(raw) - _ROLE_KEYS)
    if unknown:
        raise ConfigError(f"tau.toml: {where} içinde bilinmeyen anahtar: {', '.join(unknown)}.")
    provider = raw.get("provider")
    model_id = raw.get("model_id")
    if not isinstance(provider, str) or not provider:
        raise ConfigError(f"tau.toml: {where} için 'provider' gerekli.")
    if not isinstance(model_id, str) or not model_id:
        raise ConfigError(f"tau.toml: {where} için 'model_id' gerekli.")
    region = raw.get("region")
    if region is not None and not isinstance(region, str):
        raise ConfigError(f"tau.toml: {where} 'region' metin olmalı.")
    max_tokens = raw.get("max_tokens")
    if max_tokens is not None and (not isinstance(max_tokens, int) or max_tokens <= 0):
        raise ConfigError(f"tau.toml: {where} 'max_tokens' pozitif bir tam sayı olmalı.")
    params = raw.get("params", {})
    if not isinstance(params, dict):
        raise ConfigError(f"tau.toml: {where} 'params' bir tablo olmalı.")
    fallback = None
    if "fallback" in raw:
        if not allow_fallback:
            raise ConfigError(f"tau.toml: {where} içinde iç içe 'fallback' desteklenmiyor.")
        fallback = _parse_role(f"{name}.fallback", raw["fallback"], allow_fallback=False)
    return RoleConfig(
        provider=provider,
        model_id=model_id,
        region=region,
        max_tokens=max_tokens,
        params=dict(params),
        fallback=fallback,
    )


def _parse_agent(raw: Any) -> AgentConfig:
    if not isinstance(raw, dict):
        raise ConfigError("tau.toml: [agent] bir tablo olmalı.")
    max_turns = raw.get("max_turns", AgentConfig.max_turns)
    if not isinstance(max_turns, int) or max_turns < 1:
        raise ConfigError("tau.toml: [agent] 'max_turns' 1 veya daha büyük bir tam sayı olmalı.")
    return AgentConfig(max_turns=max_turns)


def _parse_sessions(raw: Any) -> SessionsConfig:
    if not isinstance(raw, dict):
        raise ConfigError("tau.toml: [sessions] bir tablo olmalı.")
    backend = raw.get("backend", SessionsConfig.backend)
    if not isinstance(backend, str) or not backend:
        raise ConfigError("tau.toml: [sessions] 'backend' metin olmalı.")
    return SessionsConfig(backend=backend)


def _parse_hub(raw: Any, env: Mapping[str, str]) -> HubConfig:
    if not isinstance(raw, dict):
        raise ConfigError("tau.toml: [hub] bir tablo olmalı.")
    port = raw.get("control_port", HubConfig.control_port)
    heartbeat = raw.get("heartbeat_seconds", HubConfig.heartbeat_seconds)
    if env.get("TAU_HUB_PORT"):
        try:
            port = int(env["TAU_HUB_PORT"])
        except ValueError as exc:
            raise ConfigError(
                f"TAU_HUB_PORT geçersiz: '{env['TAU_HUB_PORT']}'. Bir port numarası girin."
            ) from exc
    if not isinstance(port, int) or not 0 < port < 65536:
        raise ConfigError("tau.toml: [hub] 'control_port' 1-65535 arasında olmalı.")
    if not isinstance(heartbeat, int) or heartbeat < 1:
        raise ConfigError("tau.toml: [hub] 'heartbeat_seconds' pozitif bir tam sayı olmalı.")
    return HubConfig(control_port=port, heartbeat_seconds=heartbeat)


def _validate_names(config: Config) -> None:
    """Reject providers and session backends nobody knows about.

    The registries live next to their implementations (``tau_core.models.PROVIDERS``,
    ``tau_core.sessions.SESSION_BACKENDS``) so new providers or backends never touch this file.
    Names that are planned but not built yet pass here and fail with a clear message when used.
    """
    from tau_core.models import PLANNED_PROVIDERS, PROVIDERS
    from tau_core.sessions import PLANNED_BACKENDS, SESSION_BACKENDS

    known_providers = set(PROVIDERS) | set(PLANNED_PROVIDERS)
    for name, role in config.roles.items():
        for cfg in (role, role.fallback):
            if cfg is not None and cfg.provider not in known_providers:
                raise ConfigError(
                    f"tau.toml: '{name}' rolü için bilinmeyen sağlayıcı: '{cfg.provider}'. "
                    f"Geçerli değerler: {', '.join(sorted(known_providers))}."
                )
    known_backends = set(SESSION_BACKENDS) | set(PLANNED_BACKENDS)
    if config.sessions.backend not in known_backends:
        raise ConfigError(
            f"tau.toml: bilinmeyen oturum deposu: '{config.sessions.backend}'. "
            f"Geçerli değerler: {', '.join(sorted(known_backends))}."
        )
