"""Model roles → Strands model instances.

Code asks for a role (``brain``, ``fast``, ``local``); ``tau.toml`` says which provider and model
id serve it. No model id ever appears in code. A new provider is one factory in
:data:`PROVIDERS` plus, when it needs credentials, one row in :data:`_DEFAULT_ENV`.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from typing import Any

from strands.models.model import Model

from tau_core.config import Config, ConfigError, RoleConfig

logger = logging.getLogger(__name__)

# Keys in ``RoleConfig.params`` that tau reads itself; they are not forwarded to the provider.
_TAU_PARAM_KEYS = frozenset({"api_key_env", "base_url"})

# Providers named in tau.toml that a later issue implements. Loading such a config works;
# resolving the role fails with a clear message.
PLANNED_PROVIDERS: dict[str, str] = {"ollama": "012"}

# Credential alternatives per provider: each inner list must be fully set.
_DEFAULT_ENV: dict[str, list[list[str]]] = {
    "bedrock": [
        ["AWS_REGION", "AWS_PROFILE"],
        ["AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
        ["AWS_REGION", "AWS_BEARER_TOKEN_BEDROCK"],
    ],
    "anthropic": [["ANTHROPIC_API_KEY"]],
    "fake": [],
}


class MissingCredentials(Exception):
    """The provider behind a role has no usable credentials. ``str(exc)`` is Turkish."""

    def __init__(self, role: str, provider: str, variables: list[str]):
        self.role = role
        self.provider = provider
        self.variables = list(variables)
        super().__init__(
            f"Model kimlik bilgileri eksik ({role} rolü, {provider}). "
            f"Şu değişkenleri .env dosyasına ekleyin: {', '.join(self.variables)}\n"
            "Örnek isimler .env.example dosyasında."
        )


def required_env(role_cfg: RoleConfig) -> list[list[str]]:
    """Credential alternatives for a role: any one inner list fully set is enough.

    ``[]`` means the provider needs no credentials. ``params.api_key_env`` renames the
    Anthropic key variable; a ``region`` in the role drops ``AWS_REGION`` from Bedrock.
    """
    _check_supported(role_cfg)
    provider = role_cfg.provider
    if provider == "anthropic" and role_cfg.params.get("api_key_env"):
        return [[str(role_cfg.params["api_key_env"])]]
    alternatives = [list(alt) for alt in _DEFAULT_ENV.get(provider, [])]
    if provider == "bedrock" and role_cfg.region:
        alternatives = [[v for v in alt if v != "AWS_REGION"] for alt in alternatives]
    return alternatives


def missing_credentials(role_cfg: RoleConfig, env: Mapping[str, str]) -> list[str]:
    """``[]`` when some alternative is satisfied, else the missing names of the closest one."""
    alternatives = required_env(role_cfg)
    if not alternatives:
        return []
    best: list[str] | None = None
    for alt in alternatives:
        missing = [name for name in alt if not env.get(name)]
        if not missing:
            return []
        if best is None or len(missing) < len(best):
            best = missing
    return best or []


def resolve_model(role: str, config: Config, *, env: Mapping[str, str] | None = None) -> Model:
    """Build the model for ``role``; fall back to ``role.fallback`` when only it has credentials."""
    env = os.environ if env is None else env
    role_cfg = config.roles.get(role)
    if role_cfg is None:
        raise ConfigError(
            f"'{role}' rolü tau.toml içinde tanımlı değil ([models.roles.{role}] ekleyin)."
        )
    missing = missing_credentials(role_cfg, env)
    if not missing:
        return _build(role_cfg, env)
    fallback = role_cfg.fallback
    if fallback is not None:
        try:
            fallback_missing = missing_credentials(fallback, env)
        except ConfigError:
            fallback_missing = ["?"]
        if not fallback_missing:
            logger.warning(
                "role %s: %s has no credentials (%s); using fallback provider %s",
                role,
                role_cfg.provider,
                ", ".join(missing),
                fallback.provider,
            )
            return _build(fallback, env)
    raise MissingCredentials(role, role_cfg.provider, missing)


def _check_supported(role_cfg: RoleConfig) -> None:
    provider = role_cfg.provider
    if provider in PROVIDERS:
        return
    if provider in PLANNED_PROVIDERS:
        raise ConfigError(
            f"'{provider}' sağlayıcısı henüz desteklenmiyor (issue {PLANNED_PROVIDERS[provider]})."
        )
    raise ConfigError(f"Bilinmeyen model sağlayıcısı: '{provider}'.")


def _build(role_cfg: RoleConfig, env: Mapping[str, str]) -> Model:
    _check_supported(role_cfg)
    return PROVIDERS[role_cfg.provider](role_cfg, env)


def _provider_params(role_cfg: RoleConfig) -> dict[str, Any]:
    return {k: v for k, v in role_cfg.params.items() if k not in _TAU_PARAM_KEYS}


def _bedrock(role_cfg: RoleConfig, env: Mapping[str, str]) -> Model:
    import boto3
    from botocore.exceptions import BotoCoreError
    from strands.models.bedrock import BedrockModel

    region = role_cfg.region or env.get("AWS_REGION")
    kwargs: dict[str, Any] = {"model_id": role_cfg.model_id, **_provider_params(role_cfg)}
    if role_cfg.max_tokens is not None:
        kwargs["max_tokens"] = role_cfg.max_tokens
    try:
        if env.get("AWS_PROFILE"):
            session = boto3.Session(profile_name=env["AWS_PROFILE"], region_name=region)
            return BedrockModel(boto_session=session, **kwargs)
        if env.get("AWS_ACCESS_KEY_ID") and env.get("AWS_SECRET_ACCESS_KEY"):
            session = boto3.Session(
                aws_access_key_id=env["AWS_ACCESS_KEY_ID"],
                aws_secret_access_key=env["AWS_SECRET_ACCESS_KEY"],
                aws_session_token=env.get("AWS_SESSION_TOKEN") or None,
                region_name=region,
            )
            return BedrockModel(boto_session=session, **kwargs)
        return BedrockModel(
            region_name=region, api_key=env.get("AWS_BEARER_TOKEN_BEDROCK") or None, **kwargs
        )
    except BotoCoreError as exc:
        raise ConfigError(f"Bedrock istemcisi kurulamadı: {exc}") from exc


def _anthropic(role_cfg: RoleConfig, env: Mapping[str, str]) -> Model:
    from strands.models.anthropic import AnthropicModel

    key_env = str(role_cfg.params.get("api_key_env") or "ANTHROPIC_API_KEY")
    client_args: dict[str, Any] = {"api_key": env.get(key_env)}
    if role_cfg.params.get("base_url"):
        client_args["base_url"] = role_cfg.params["base_url"]
    return AnthropicModel(
        client_args=client_args,
        model_id=role_cfg.model_id,
        max_tokens=role_cfg.max_tokens or 4096,
        params=_provider_params(role_cfg) or None,
    )


def _fake(role_cfg: RoleConfig, env: Mapping[str, str]) -> Model:
    """Scripted model for tests and credential-free trials.

    ``params.replies`` is a list of strings (text replies) or tool calls written as
    ``{tool = "name", input = {...}}`` (a list of those is one reply with several calls).
    """
    from tau_core.testing import FakeModel, ToolCall

    def tool_call(raw: Any) -> ToolCall:
        if not isinstance(raw, dict) or "tool" not in raw:
            raise ConfigError(f"fake sağlayıcı: geçersiz yanıt: {raw!r}")
        return ToolCall(name=str(raw["tool"]), input=dict(raw.get("input") or {}))

    def reply(raw: Any) -> Any:
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            return [tool_call(raw)]
        if isinstance(raw, list):
            return [tool_call(item) for item in raw]
        raise ConfigError(f"fake sağlayıcı: geçersiz yanıt: {raw!r}")

    replies = [reply(raw) for raw in role_cfg.params.get("replies") or []]
    default = role_cfg.params.get("default") or "Tamam efendim."
    return FakeModel(replies, default=str(default))


PROVIDERS: dict[str, Callable[[RoleConfig, Mapping[str, str]], Model]] = {
    "bedrock": _bedrock,
    "anthropic": _anthropic,
    "fake": _fake,
}
