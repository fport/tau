"""Spend per model role, read from the LiteLLM proxy (roadmap 011, ADR 0009).

Every ``proxy`` role calls with its own virtual key, and the proxy keeps that key's spend for
the current budget period. :class:`SpendTracker` reads it with the key itself
(``GET /key/info``, no master key) and caches it; every proxied answer also carries the key's
spend in a header, which :func:`note_spend` feeds in, so the numbers stay fresh without
polling.

Three consumers read the same cache:

- the ``budget`` context source (``tau.context``) puts one line under ``## Now`` before every
  model call; it never waits on the network (a stale cache refreshes in a background thread);
- the ``spend`` hub service adds ``GET /spend`` to the control API and a ``spend`` key to
  ``GET /status``;
- ``/status`` in the channels and ``tau proxy spend``.

A role that is not behind the proxy has no key and so no spend here: direct providers are not
metered by tau (ADR 0009).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from tau_core.config import Config, RoleConfig
from tau_core.models import proxy_key_env, proxy_url

if TYPE_CHECKING:
    from tau_core.hub.control import ControlRequest
    from tau_core.hub.daemon import Hub

__all__ = [
    "RoleSpend",
    "SpendService",
    "SpendTracker",
    "context_source",
    "describe",
    "forget_trackers",
    "make_service",
    "note_spend",
    "proxy_roles",
    "tracker_for",
]

logger = logging.getLogger(__name__)

REFRESH_SECONDS = 60.0
"""How old the cache may get before a read triggers a refresh in the background."""

KeyInfoFetcher = Callable[[str, str], dict]
"""``(base_url, api_key) → the key's /key/info record``; raises ``OSError``/``ValueError``."""


def _fetch(base_url: str, api_key: str) -> dict:
    from tau_core.proxy import fetch_key_info

    return fetch_key_info(base_url, api_key)


def proxy_roles(config: Config) -> dict[str, RoleConfig]:
    """``{role: RoleConfig}`` for the roles served through the proxy, in ``tau.toml`` order."""
    return {name: role for name, role in config.roles.items() if role.provider == "proxy"}


@dataclass(frozen=True)
class RoleSpend:
    """What the proxy says about one role's key, next to what ``tau.toml`` asks for.

    ``spend``/``max_budget``/``period``/``reset_at`` come from the proxy (``None`` until read);
    ``usd``/``configured_period``/``degrade_to`` from the role's ``budget`` table. ``error`` is
    why the last read failed.
    """

    role: str
    group: str
    spend: float | None = None
    max_budget: float | None = None
    period: str | None = None
    reset_at: datetime | None = None
    usd: float | None = None
    configured_period: str | None = None
    degrade_to: str | None = None
    error: str | None = None

    @property
    def known(self) -> bool:
        return self.spend is not None

    @property
    def exhausted(self) -> bool:
        return (
            self.spend is not None and self.max_budget is not None and self.spend >= self.max_budget
        )

    @property
    def drifted(self) -> bool:
        """Does the key's cap differ from ``tau.toml`` (``tau proxy keys`` not run since)?"""
        if not self.known:
            return False
        if self.usd is None:
            return self.max_budget is not None
        return (
            self.max_budget is None
            or abs(self.max_budget - self.usd) > 1e-9
            or self.period != self.configured_period
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "spend_usd": self.spend,
            "max_budget_usd": self.max_budget,
            "period": self.period,
            "reset_at": self.reset_at.isoformat() if self.reset_at else None,
            "exhausted": self.exhausted,
            "configured": {
                "usd": self.usd,
                "period": self.configured_period,
                "degrade_to": self.degrade_to,
            },
            "error": self.error,
        }


def _blank(role: str, cfg: RoleConfig) -> RoleSpend:
    budget = cfg.budget
    return RoleSpend(
        role=role,
        group=cfg.model_id,
        usd=budget.usd if budget else None,
        configured_period=budget.period if budget else None,
        degrade_to=budget.degrade_to if budget else None,
    )


def _from_info(blank: RoleSpend, info: Mapping[str, Any]) -> RoleSpend:
    from tau_core.proxy import parse_timestamp

    def number(raw: Any) -> float | None:
        if raw is None or isinstance(raw, bool):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    period = info.get("budget_duration")
    return replace(
        blank,
        spend=number(info.get("spend")) or 0.0,
        max_budget=number(info.get("max_budget")),
        period=period if isinstance(period, str) else None,
        reset_at=parse_timestamp(info.get("budget_reset_at")),
        error=None,
    )


class SpendTracker:
    """The cached spend of every proxy role of one configuration.

    :meth:`snapshot` never blocks: it returns the cache and, when it is older than ``ttl``,
    starts one background refresh. :meth:`refresh` reads every key now (for the CLI and the
    control API, which may wait a few seconds).
    """

    def __init__(
        self,
        config: Config,
        env: Mapping[str, str] | None = None,
        *,
        ttl: float = REFRESH_SECONDS,
        fetch: KeyInfoFetcher | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._env = os.environ if env is None else env
        self._roles = proxy_roles(config)
        first = next(iter(self._roles.values()), None)
        self.url = proxy_url(first, self._env)
        self._ttl = ttl
        self._fetch = fetch or _fetch
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[str, RoleSpend] = {
            name: _blank(name, cfg) for name, cfg in self._roles.items()
        }
        self._fetched_at: float | None = None
        self._refreshing = False

    @property
    def roles(self) -> list[str]:
        return list(self._roles)

    def snapshot(self) -> dict[str, RoleSpend]:
        """The cached values; a stale cache refreshes in the background, never inline."""
        with self._lock:
            stale = self._fetched_at is None or self._clock() - self._fetched_at >= self._ttl
            start = bool(self._roles) and stale and not self._refreshing
            if start:
                self._refreshing = True
            cache = dict(self._cache)
        if start:
            threading.Thread(target=self._refresh_quietly, name="tau-spend", daemon=True).start()
        return cache

    def refresh(self) -> dict[str, RoleSpend]:
        """Read every role's key from the proxy now and return the new values."""
        fresh: dict[str, RoleSpend] = {}
        for name, cfg in self._roles.items():
            blank = _blank(name, cfg)
            key = self._env.get(proxy_key_env(cfg))
            if not key:
                fresh[name] = replace(blank, error=f"{proxy_key_env(cfg)} is not set")
                continue
            try:
                info = self._fetch(proxy_url(cfg, self._env), key)
            except (OSError, ValueError) as exc:
                fresh[name] = replace(blank, error=str(exc) or type(exc).__name__)
                continue
            fresh[name] = _from_info(blank, info)
        with self._lock:
            for name, value in fresh.items():
                if value.error is not None and self._cache[name].known:
                    # Keep the last good numbers; only record why this read failed.
                    value = replace(self._cache[name], error=value.error)
                self._cache[name] = value
            self._fetched_at = self._clock()
            return dict(self._cache)

    def note(self, group: str, spend: float) -> None:
        """A proxied answer reported ``spend`` for model group ``group``'s key."""
        with self._lock:
            for name, cfg in self._roles.items():
                if cfg.model_id == group and self._cache[name].known:
                    self._cache[name] = replace(self._cache[name], spend=spend)

    def _refresh_quietly(self) -> None:
        try:
            self.refresh()
        except Exception:
            logger.exception("reading the proxy spend failed")
        finally:
            with self._lock:
                self._refreshing = False


_trackers: dict[tuple, SpendTracker] = {}
_trackers_lock = threading.Lock()


def _tracker_key(config: Config, env: Mapping[str, str]) -> tuple:
    roles = proxy_roles(config)
    return tuple(
        (name, cfg.model_id, proxy_url(cfg, env), proxy_key_env(cfg), cfg.budget)
        for name, cfg in roles.items()
    )


def tracker_for(config: Config, env: Mapping[str, str] | None = None) -> SpendTracker:
    """The process-wide tracker of this configuration's proxy roles (one per distinct set of
    roles, URLs and key names), so every channel and the hub read one cache."""
    env = os.environ if env is None else env
    key = _tracker_key(config, env)
    with _trackers_lock:
        tracker = _trackers.get(key)
        if tracker is None:
            tracker = _trackers[key] = SpendTracker(config, env)
        return tracker


def forget_trackers() -> None:
    """Drop every shared tracker (tests; a process that reloads its configuration)."""
    with _trackers_lock:
        _trackers.clear()


def note_spend(url: str, group: str, spend: float) -> None:
    """Feed a key's spend from a proxy response header into every tracker for ``url``."""
    with _trackers_lock:
        trackers = list(_trackers.values())
    for tracker in trackers:
        if tracker.url == url.rstrip("/"):
            tracker.note(group, spend)


def _reset_text(reset_at: datetime | None) -> str:
    if reset_at is None:
        return "?"
    from tau_core.persona import TIMEZONE

    return f"{reset_at.astimezone(TIMEZONE):%d.%m.%Y %H:%M}"


def describe(spends: Mapping[str, RoleSpend]) -> str | None:
    """One English line for the model and the logs, ``None`` when nothing is known yet:
    ``brain $0.42 of $15.00 per 1mo (resets 01.10.2026 03:00); fast $1.00 of $1.00 per 1d,
    spent, degrades to local (resets ...)``."""
    parts = []
    for spend in spends.values():
        if not spend.known:
            continue
        text = f"{spend.role} ${spend.spend:.2f}"
        if spend.max_budget is not None:
            text += f" of ${spend.max_budget:.2f}"
            if spend.period:
                text += f" per {spend.period}"
        else:
            text += " (no cap)"
        if spend.exhausted:
            text += ", spent"
            if spend.degrade_to:
                text += f", {spend.degrade_to} answers instead"
        if spend.max_budget is not None:
            text += f" (resets {_reset_text(spend.reset_at)})"
        parts.append(text)
    return "; ".join(parts) or None


def context_source(config: Config) -> Callable[[], dict[str, Any]]:
    """The ``tau.context`` factory: ``{"budget": describe(...)}`` from the cached spend."""
    if not proxy_roles(config):
        return lambda: {}
    tracker = tracker_for(config)

    def source() -> dict[str, Any]:
        return {"budget": describe(tracker.snapshot())}

    return source


class SpendService:
    """``tau.hub_services`` component: ``GET /spend`` and a ``spend`` key in ``GET /status``."""

    name = "spend"

    def __init__(self, config: Config) -> None:
        self.config = config
        self.tracker = tracker_for(config)

    def payload(self, spends: Mapping[str, RoleSpend]) -> dict[str, Any]:
        return {
            "proxy": self.tracker.url if self.tracker.roles else None,
            "roles": {name: spend.to_json() for name, spend in spends.items()},
        }

    def status(self) -> dict[str, Any]:
        return {self.name: self.payload(self.tracker.snapshot())}

    def handle_spend(self, request: ControlRequest) -> tuple[int, Any]:
        return 200, self.payload(self.tracker.refresh())

    async def start(self, hub: Hub) -> None:
        hub.add_status_source(self.status)
        api = hub.find_service("control-api")
        if api is not None:
            api.add_route("GET", "/spend", self.handle_spend)  # type: ignore[attr-defined]
        self.tracker.snapshot()  # first read in the background

    async def stop(self) -> None:
        return None


def make_service(config: Config) -> SpendService:
    """The ``tau.hub_services`` factory."""
    return SpendService(config)
