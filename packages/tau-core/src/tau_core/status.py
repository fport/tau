"""Read-only reports shared by the channels: the ``/status`` lines and the ``/model`` listing.

Both channels print the same lines (looked up through :mod:`tau_core.i18n`), so the terminal
and the TUI never drift. The hub check reuses ``tau doctor``'s probe of the control API
(:func:`check_hub`, one second timeout, reported as information, never as a failure).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from importlib import metadata

from tau_core._version import __version__
from tau_core.agent import AGENT_ID, TauAgent
from tau_core.builder import Check
from tau_core.config import Config
from tau_core.i18n import DEFAULT_LANGUAGE, t
from tau_core.sessions import SessionStore
from tau_core.spend import RoleSpend, describe, spend_report

__all__ = [
    "ModelInfo",
    "check_hub",
    "describe_model",
    "role_lines",
    "status_lines",
    "status_report",
    "stored_message_count",
    "stored_role",
    "tau_versions",
]

logger = logging.getLogger(__name__)

_PROVIDER_BY_CLASS = {
    "BedrockModel": "bedrock",
    "AnthropicModel": "anthropic",
    "OllamaModel": "ollama",
    "FakeModel": "fake",
}
"""Strands model classes of the built-in providers; anything else reports its class name."""

VERSIONED_DISTRIBUTIONS = ("tau-core", "tau-tui")


@dataclass(frozen=True)
class ModelInfo:
    """What serves a role right now: the provider, the model id and, when the role's
    ``fallback`` is in use, the primary provider it stands in for."""

    provider: str
    model_id: str
    fallback_of: str | None = None


def describe_model(agent: TauAgent) -> ModelInfo:
    """What serves the agent's role, read off the model instance, never from credentials.

    ``resolve_model`` tags the instances it builds (``tau_provider``, ``tau_fallback_of``), so
    entry-point providers report their own name; an untagged model (one a caller passed in)
    is keyed on its class, then on the role's configuration.
    """
    model = agent.agent.model
    try:
        model_id = str(model.get_config().get("model_id") or "?")
    except Exception:
        model_id = "?"
    tagged = getattr(model, "tau_provider", None)
    if isinstance(tagged, str) and tagged:
        fallback_of = getattr(model, "tau_fallback_of", None)
        return ModelInfo(tagged, model_id, fallback_of if isinstance(fallback_of, str) else None)
    provider = _PROVIDER_BY_CLASS.get(type(model).__name__)
    role_cfg = agent.config.roles.get(agent.role)
    fallback_of = None
    if role_cfg is not None:
        if provider is None:
            provider = role_cfg.provider
        elif (
            provider != role_cfg.provider
            and role_cfg.fallback is not None
            and provider == role_cfg.fallback.provider
        ):
            fallback_of = role_cfg.provider
    return ModelInfo(provider or type(model).__name__, model_id, fallback_of)


def stored_role(store: SessionStore | None, session_id: str | None, config: Config) -> str | None:
    """The ``role`` a session's metadata remembers (written by ``/model``), when ``tau.toml``
    still defines it; ``None`` otherwise, so the caller keeps its own default."""
    if store is None or session_id is None:
        return None
    try:
        role = store.read_meta(session_id).get("role")
    except Exception:
        logger.exception("could not read the metadata of session %s", session_id)
        return None
    if not isinstance(role, str) or not role:
        return None
    if role not in config.roles:
        logger.warning(
            "session %s remembers role %r, which tau.toml does not define", session_id, role
        )
        return None
    return role


def stored_message_count(store: SessionStore | None, session_id: str) -> int | None:
    """How many messages the store holds for the session (every one, not only the model's
    window); ``None`` without a store or when the session cannot be read."""
    if store is None:
        return None
    try:
        return len(store.list_messages(session_id, AGENT_ID))
    except Exception:
        logger.exception("could not count the messages of session %s", session_id)
        return None


def tau_versions() -> list[tuple[str, str]]:
    """``[(distribution, version), ...]`` for the tau distributions that are installed."""
    found = []
    for name in VERSIONED_DISTRIBUTIONS:
        try:
            found.append((name, metadata.version(name)))
        except metadata.PackageNotFoundError:
            if name == "tau-core":
                found.append((name, __version__))
    return found


def check_hub(config: Config) -> Check:
    """``tau doctor``'s probe of ``GET /health`` on the control API (one second timeout)."""
    from tau_core.builder import _check_hub

    return _check_hub(config)


def status_lines(
    agent: TauAgent,
    *,
    language: str = DEFAULT_LANGUAGE,
    hub: Check | None = None,
    spends: dict[str, RoleSpend] | None = None,
) -> list[str]:
    """The ``/status`` report, one line per fact, in ``language``. ``hub`` is the control-API
    check and ``spends`` the roles' spend when the caller read it (see :func:`status_report`);
    without ``spends`` the ledger is read here (a local SQLite query)."""
    config = agent.config
    store = agent.store
    session_id = agent.session_id
    title = ""
    if store is not None:
        try:
            title = str(store.read_meta(session_id).get("title") or "")
        except Exception:
            logger.exception("could not read the title of session %s", session_id)
    stored = stored_message_count(store, session_id)
    info = describe_model(agent)
    tools = agent.catalog.tools()
    approval = sum(1 for tool in tools if agent.catalog.tier(tool.tool_name) == 2)
    lines = [
        t("status.profile", language, profile=config.profile),
        t(
            "status.session",
            language,
            session=session_id,
            title=title or t("session.untitled", language),
            n=stored if stored is not None else len(agent.messages),
            role=agent.role,
        ),
    ]
    if info.fallback_of is not None:
        lines.append(
            t(
                "status.model_fallback",
                language,
                role=agent.role,
                provider=info.provider,
                primary=info.fallback_of,
                model_id=info.model_id,
            )
        )
    else:
        lines.append(
            t(
                "status.model",
                language,
                role=agent.role,
                provider=info.provider,
                model_id=info.model_id,
            )
        )
    lines += [
        t(
            "status.context",
            language,
            mode=config.agent.context,
            window=config.agent.window_size,
            n=len(agent.messages),
        ),
        t("status.tools", language, n=len(tools), approval=approval),
        t("status.language", language, language=language),
        t(
            "status.versions",
            language,
            versions=" · ".join(f"{name} {version}" for name, version in tau_versions()),
        ),
    ]
    if hub is not None:
        lines.append(t("status.hub", language, detail=hub.detail))
    if any(role.budget for role in config.roles.values()):
        if spends is None:
            spends = spend_report(config)
        detail = describe(spends)
        if detail:
            lines.append(t("status.budget", language, detail=detail))
    return lines


async def status_report(agent: TauAgent, *, language: str = DEFAULT_LANGUAGE) -> list[str]:
    """:func:`status_lines` with the hub probed and the ledger read in threads, so a UI loop
    never blocks on either."""
    hub = await asyncio.to_thread(check_hub, agent.config)
    spends = await asyncio.to_thread(spend_report, agent.config)
    return status_lines(agent, language=language, hub=hub, spends=spends)


def role_lines(agent: TauAgent, language: str = DEFAULT_LANGUAGE) -> list[str]:
    """The ``/model`` listing: the role in use, then every role in ``tau.toml`` with its
    provider (and fallback), the current one marked."""
    info = describe_model(agent)
    lines = [
        t("model.current", language, role=agent.role, provider=info.provider),
        t("model.roles_header", language),
    ]
    roles = agent.config.roles
    width = max((len(name) for name in roles), default=0)
    for name, role_cfg in roles.items():
        line = f"  {name:<{width}}  {role_cfg.provider}"
        if role_cfg.fallback is not None:
            line += f" ({t('model.fallback_note', language, provider=role_cfg.fallback.provider)})"
        if name == agent.role:
            line += f" · {t('model.current_mark', language)}"
        lines.append(line)
    return lines
