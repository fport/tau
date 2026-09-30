"""Model roles → Strands model instances.

Code asks for a role (``brain``, ``fast``, ``local``); ``tau.toml`` says which provider and model
id serve it. No model id ever appears in code. :data:`PROVIDERS` is the built-in seed; other
distributions add providers through the ``tau.providers`` entry point group and code adds them
with :func:`tau_core.registry.register_provider` (see :mod:`tau_core.registry`). A provider that
needs credentials declares them in :data:`_DEFAULT_ENV` (built-in) or through ``required_env``.

Providers are called directly (ADR 0011): ``anthropic``, ``openai``, ``gemini``, ``ollama`` (a
local model), the optional ``bedrock`` and the scripted ``fake``. A role with a ``budget`` or a
``failover`` is wrapped in :class:`tau_core.budget.RoleModel`, which prices every answer,
enforces the budget (answering with ``budget.degrade_to`` or raising :class:`BudgetExhausted`)
and hands an unreachable model's call to ``failover``. Channels show a :class:`ModelNotice` as
one sentence, never a trace. Never ``litellm``: its PyPI releases were compromised in 2026.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from strands.models.model import Model

from tau_core import registry
from tau_core.config import Config, ConfigError, RoleConfig
from tau_core.i18n import DEFAULT_LANGUAGE, t

logger = logging.getLogger(__name__)

# Keys in ``RoleConfig.params`` that tau reads itself; they are not forwarded to the provider.
_TAU_PARAM_KEYS = frozenset({"api_key_env", "base_url", "workspace_id"})

# An Anthropic key that is not scoped to a workspace must name the workspace on every
# request; the API rejects it otherwise (400, "not scoped to a workspace").
ANTHROPIC_WORKSPACE_HEADER = "anthropic-workspace-id"
ANTHROPIC_WORKSPACE_ENV = "ANTHROPIC_WORKSPACE_ID"

# Ollama for the `local` role: on this machine by default, or the Mac over the tailnet.
OLLAMA_URL_ENV = "TAU_OLLAMA_URL"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_CONNECT_TIMEOUT = 3.0
"""Seconds to reach Ollama before the call counts as unreachable (a sleeping Mac)."""

# Providers named in tau.toml that a later issue implements. Loading such a config works;
# resolving the role fails with a clear message.
PLANNED_PROVIDERS: dict[str, str] = {}

# Credential alternatives per provider: each inner list must be fully set.
_DEFAULT_ENV: dict[str, list[list[str]]] = {
    "bedrock": [
        ["AWS_REGION", "AWS_PROFILE"],
        ["AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
        ["AWS_REGION", "AWS_BEARER_TOKEN_BEDROCK"],
    ],
    "anthropic": [["ANTHROPIC_API_KEY"]],
    "openai": [["OPENAI_API_KEY"]],
    "gemini": [["GEMINI_API_KEY"], ["GOOGLE_API_KEY"]],
    "ollama": [],
    "fake": [],
}


class ProviderNotSupported(ConfigError):
    """A role names a provider that is planned but not built yet (:data:`PLANNED_PROVIDERS`).

    ``str(exc)`` is the sentence the user sees; ``issue`` is the roadmap issue that adds the
    provider. A channel that can edit the config catches this at start-up and opens its
    settings on the Model roles section instead of exiting.
    """

    def __init__(self, provider: str, issue: str) -> None:
        self.provider = provider
        self.issue = issue
        super().__init__(f"Provider '{provider}' is not supported yet (issue {issue}).")


class ModelNotice(Exception):
    """A model failure the user reads as one sentence in the UI language, not as a trace.

    ``TauAgent`` shows :meth:`notice` instead of the generic model-error text; ``str(exc)``
    stays plain English for the log.
    """

    def notice(self, language: str = DEFAULT_LANGUAGE) -> str:
        raise NotImplementedError


def _format_reset(reset_at: datetime | None, language: str) -> str:
    if reset_at is None:
        return t("budget.reset_unknown", language)
    from tau_core.persona import TIMEZONE

    return f"{reset_at.astimezone(TIMEZONE):%d.%m.%Y %H:%M}"


def _usd(value: float | None) -> str:
    """Dollars with cents; a sub-cent amount (a test cap) keeps its significant digits."""
    if value is None:
        return "?"
    if 0 < abs(value) < 0.01:
        return f"{value:.8f}".rstrip("0")
    return f"{value:.2f}"


class BudgetExhausted(ModelNotice):
    """A role's budget is spent for its period, and nothing may stand in.

    ``also`` is set when the role's ``degrade_to`` was tried and is spent as well.
    """

    def __init__(
        self,
        role: str,
        *,
        spend: float | None = None,
        max_budget: float | None = None,
        reset_at: datetime | None = None,
        also: BudgetExhausted | None = None,
    ) -> None:
        self.role = role
        self.spend = spend
        self.max_budget = max_budget
        self.reset_at = reset_at
        self.also = also
        detail = f"budget of role '{role}' is spent (${_usd(spend)} of ${_usd(max_budget)})"
        if also is not None:
            detail += f"; its degrade role '{also.role}' is spent too"
        super().__init__(detail)

    def notice(self, language: str = DEFAULT_LANGUAGE) -> str:
        if self.also is not None:
            return t(
                "notice.budget_exhausted_also",
                language,
                role=self.role,
                reset=_format_reset(self.reset_at, language),
                degrade=self.also.role,
                degrade_reset=_format_reset(self.also.reset_at, language),
            )
        return t(
            "notice.budget_exhausted",
            language,
            role=self.role,
            spend=_usd(self.spend),
            cap=_usd(self.max_budget),
            reset=_format_reset(self.reset_at, language),
        )


@dataclass(frozen=True)
class BudgetDegraded:
    """A model call a spent role handed to its ``degrade_to`` role; the channel shows it."""

    role: str
    degrade_to: str
    reset_at: datetime | None = None
    reason = "budget"

    def notice(self, language: str = DEFAULT_LANGUAGE) -> str:
        return t(
            "notice.budget_degraded",
            language,
            role=self.role,
            degrade=self.degrade_to,
            reset=_format_reset(self.reset_at, language),
        )


@dataclass(frozen=True)
class FailedOver:
    """A model call an unreachable role handed to its ``failover`` role; the channel shows it."""

    role: str
    failover: str
    reason = "failover"

    def notice(self, language: str = DEFAULT_LANGUAGE) -> str:
        return t("notice.failover", language, role=self.role, failover=self.failover)


class MissingCredentials(Exception):
    """The provider behind a role has no usable credentials; ``str(exc)`` names the variables."""

    def __init__(self, role: str, provider: str, variables: list[str]):
        self.role = role
        self.provider = provider
        self.variables = list(variables)
        super().__init__(
            f"Missing model credentials for role '{role}' ({provider}). "
            f"Add these variables to .env: {', '.join(self.variables)}\n"
            "Example names are in .env.example."
        )


def required_env(role_cfg: RoleConfig) -> list[list[str]]:
    """Credential alternatives for a role: any one inner list fully set is enough.

    ``[]`` means the provider needs no credentials. ``params.api_key_env`` renames the
    Anthropic key variable; a ``region`` in the role drops ``AWS_REGION`` from Bedrock.
    """
    _check_supported(role_cfg)
    provider = role_cfg.provider
    if provider in ("anthropic", "openai", "gemini") and role_cfg.params.get("api_key_env"):
        return [[str(role_cfg.params["api_key_env"])]]
    if provider in _DEFAULT_ENV:
        alternatives = [list(alt) for alt in _DEFAULT_ENV[provider]]
    else:
        alternatives = registry.provider_required_env(provider)
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
        raise ConfigError(f"Role '{role}' is not defined in tau.toml (add [models.roles.{role}]).")
    missing = missing_credentials(role_cfg, env)
    if not missing:
        model = _wrap(_build(role_cfg, env), role, role_cfg, role_cfg, config, env)
        return _tag(model, role_cfg.provider, None, role)
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
            model = _wrap(_build(fallback, env), role, role_cfg, fallback, config, env)
            return _tag(model, fallback.provider, role_cfg.provider, role)
    raise MissingCredentials(role, role_cfg.provider, missing)


def _wrap(
    model: Model,
    role: str,
    role_cfg: RoleConfig,
    serving: RoleConfig,
    config: Config,
    env: Mapping[str, str],
) -> Model:
    """Put a role with a ``budget`` or a ``failover`` inside :class:`tau_core.budget.RoleModel`
    (``serving`` is the table that built ``model``: the role's or its credential fallback's).
    The stand-in roles are resolved lazily, on their first use."""
    if role_cfg.budget is None and role_cfg.failover is None:
        return model
    from tau_core.budget import RoleModel

    def stand_in(name: str | None) -> Callable[[], Model] | None:
        return None if name is None else (lambda: resolve_model(name, config, env=env))

    return RoleModel(
        model,
        role=role,
        provider=serving.provider,
        model_id=serving.model_id,
        config=config,
        budget=role_cfg.budget,
        degrade=(role_cfg.budget.degrade_to if role_cfg.budget else None),
        degrade_factory=stand_in(role_cfg.budget.degrade_to if role_cfg.budget else None),
        failover=role_cfg.failover,
        failover_factory=stand_in(role_cfg.failover),
    )


def _tag(model: Model, provider: str, fallback_of: str | None, role: str) -> Model:
    """Mark the instance with the provider that built it (``tau_provider``), the role it
    serves (``tau_role``) and, when it is a role's fallback, the primary it stands in for
    (``tau_fallback_of``), so ``/status`` can say what serves a role without guessing from the
    class name (entry-point providers have any class). An object that refuses attributes is
    left untagged."""
    tags = (("tau_provider", provider), ("tau_fallback_of", fallback_of), ("tau_role", role))
    for name, value in tags:
        try:
            setattr(model, name, value)
        except (AttributeError, TypeError):
            logger.debug("model %r refused the %s tag", type(model).__name__, name)
    return model


def _check_supported(role_cfg: RoleConfig) -> None:
    provider = role_cfg.provider
    if registry.provider_factory(provider) is not None:
        return
    if provider in PLANNED_PROVIDERS:
        raise ProviderNotSupported(provider, PLANNED_PROVIDERS[provider])
    broken = registry.load_error(registry.PROVIDERS_GROUP, provider)
    if broken is not None:
        raise ConfigError(provider_load_failure(provider, broken))
    raise ConfigError(f"Unknown model provider: '{provider}'.")


def provider_load_failure(provider: str, broken: registry.Loaded) -> str:
    """The one sentence ``resolve_model`` and ``tau doctor`` use for a ``tau.providers`` entry
    point that is declared but does not load (``tau components`` shows the same error)."""
    origin = f" from {broken.distribution}" if broken.distribution != "?" else ""
    return f"Model provider '{provider}'{origin} failed to load: {broken.error}"


def _build(role_cfg: RoleConfig, env: Mapping[str, str]) -> Model:
    _check_supported(role_cfg)
    factory = registry.provider_factory(role_cfg.provider)
    assert factory is not None  # _check_supported raised otherwise
    return factory(role_cfg, env)


def _provider_params(role_cfg: RoleConfig) -> dict[str, Any]:
    return {k: v for k, v in role_cfg.params.items() if k not in _TAU_PARAM_KEYS}


def _cache_kwargs(role_cfg: RoleConfig) -> dict[str, Any]:
    """``{"cache_config": CacheConfig(...)}`` when the role has a ``cache`` table, else ``{}``.

    Bedrock and Anthropic honour it (a cache point after the system prompt and, with
    ``tools_ttl``, after the tool definitions); the fake provider ignores it.
    """
    if not role_cfg.cache:
        return {}
    from strands.models import CacheConfig

    return {"cache_config": CacheConfig(**role_cfg.cache)}


def _bedrock(role_cfg: RoleConfig, env: Mapping[str, str]) -> Model:
    import boto3
    from botocore.exceptions import BotoCoreError
    from strands.models.bedrock import BedrockModel

    region = role_cfg.region or env.get("AWS_REGION")
    kwargs: dict[str, Any] = {
        "model_id": role_cfg.model_id,
        **_provider_params(role_cfg),
        **_cache_kwargs(role_cfg),
    }
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
        raise ConfigError(f"Bedrock client could not be created: {exc}") from exc


def _anthropic(role_cfg: RoleConfig, env: Mapping[str, str]) -> Model:
    from strands.models.anthropic import AnthropicModel

    key_env = str(role_cfg.params.get("api_key_env") or "ANTHROPIC_API_KEY")
    client_args: dict[str, Any] = {"api_key": env.get(key_env)}
    if role_cfg.params.get("base_url"):
        client_args["base_url"] = role_cfg.params["base_url"]
    workspace_id = role_cfg.params.get("workspace_id") or env.get(ANTHROPIC_WORKSPACE_ENV)
    if workspace_id:
        client_args["default_headers"] = {ANTHROPIC_WORKSPACE_HEADER: str(workspace_id)}
    return AnthropicModel(
        client_args=client_args,
        model_id=role_cfg.model_id,
        max_tokens=role_cfg.max_tokens or 4096,
        params=_provider_params(role_cfg) or None,
        **_cache_kwargs(role_cfg),
    )


def _api_key(role_cfg: RoleConfig, env: Mapping[str, str], *names: str) -> str | None:
    """The key from ``params.api_key_env`` if the role names one, else the first set name."""
    explicit = role_cfg.params.get("api_key_env")
    for name in (str(explicit),) if explicit else names:
        if env.get(name):
            return env[name]
    return None


def _openai(role_cfg: RoleConfig, env: Mapping[str, str]) -> Model:
    """OpenAI (or any OpenAI-compatible API through ``params.base_url``)."""
    from strands.models.openai import OpenAIModel

    client_args: dict[str, Any] = {"api_key": _api_key(role_cfg, env, "OPENAI_API_KEY")}
    if role_cfg.params.get("base_url"):
        client_args["base_url"] = role_cfg.params["base_url"]
    return OpenAIModel(
        client_args=client_args,
        model_id=role_cfg.model_id,
        # Current OpenAI models take max_completion_tokens; max_tokens is refused by some.
        params={"max_completion_tokens": role_cfg.max_tokens or 4096, **_provider_params(role_cfg)},
    )


def _gemini(role_cfg: RoleConfig, env: Mapping[str, str]) -> Model:
    """Google Gemini through Strands' ``GeminiModel`` (the ``google-genai`` SDK)."""
    from strands.models.gemini import GeminiModel

    key = _api_key(role_cfg, env, "GEMINI_API_KEY", "GOOGLE_API_KEY")
    return GeminiModel(
        client_args={"api_key": key},
        model_id=role_cfg.model_id,
        params={"max_output_tokens": role_cfg.max_tokens or 4096, **_provider_params(role_cfg)},
    )


def _ollama(role_cfg: RoleConfig, env: Mapping[str, str]) -> Model:
    """Ollama's OpenAI-compatible endpoint: ``params.base_url``, else ``TAU_OLLAMA_URL``, else
    this machine. It fails fast (a short connect timeout, no retries), so a role's
    ``failover`` answers within seconds while the Mac is asleep or away."""
    import httpx
    from strands.models.openai import OpenAIModel

    base = str(
        role_cfg.params.get("base_url") or env.get(OLLAMA_URL_ENV) or DEFAULT_OLLAMA_URL
    ).rstrip("/")
    return OpenAIModel(
        client_args={
            "base_url": f"{base}/v1",
            "api_key": "ollama",
            "timeout": httpx.Timeout(120.0, connect=OLLAMA_CONNECT_TIMEOUT),
            "max_retries": 0,
        },
        model_id=role_cfg.model_id,
        params={"max_tokens": role_cfg.max_tokens or 4096, **_provider_params(role_cfg)},
    )


def _fake(role_cfg: RoleConfig, env: Mapping[str, str]) -> Model:
    """Scripted model for tests and credential-free trials.

    ``params.replies`` is a list of strings (text replies) or tool calls written as
    ``{tool = "name", input = {...}}`` (a list of those is one reply with several calls).
    """
    from tau_core.testing import FakeModel, ToolCall

    def tool_call(raw: Any) -> ToolCall:
        if not isinstance(raw, dict) or "tool" not in raw:
            raise ConfigError(f"fake provider: invalid reply: {raw!r}")
        return ToolCall(name=str(raw["tool"]), input=dict(raw.get("input") or {}))

    def reply(raw: Any) -> Any:
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            return [tool_call(raw)]
        if isinstance(raw, list):
            return [tool_call(item) for item in raw]
        raise ConfigError(f"fake provider: invalid reply: {raw!r}")

    replies = [reply(raw) for raw in role_cfg.params.get("replies") or []]
    default = role_cfg.params.get("default") or "Okay."
    return FakeModel(replies, default=str(default))


PROVIDERS: dict[str, Callable[[RoleConfig, Mapping[str, str]], Model]] = {
    "anthropic": _anthropic,
    "openai": _openai,
    "gemini": _gemini,
    "ollama": _ollama,
    "bedrock": _bedrock,
    "fake": _fake,
}
"""The built-in seed. Do not add to it at runtime: use ``tau_core.registry.register_provider``
or a ``tau.providers`` entry point, which the merged lookup and ``tau components`` both see."""
