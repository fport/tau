"""The ``net`` hub service: long-poll the spine, handle each envelope, acknowledge it (§6.1).

A ``tau.hub_services`` component (``net = "tau_net.service:make_service"``) that runs inside
``tau hub run``. It reaches the spine outbound only, with a long poll of ``GET /hub/updates``,
so the hub still opens no inbound port. For each update, in order, it handles the envelope,
acknowledges it and then stores the cursor, so a crash re-handles rather than loses.

- Without ``TAU_SPINE_URL``, ``TAU_SPINE_TOKEN`` or an identity it stays idle, logs one line and
  reports ``net: {configured: false}`` in ``/status``; it never fails the hub.
- On start it asks the spine for its address and publishes the card when the spine has none or
  a different one.
- Network errors back off exponentially up to 60 s; a rejected token stops polling (the token
  is read again only on a restart).
- Blocking HTTP runs in daemon threads, so the hub loop stays responsive and :meth:`stop`
  returns at once even while a long poll is in flight.

The token never reaches a log line, an exception message or ``/status``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from tau_core import Config, SessionStore

from tau_net.config import (
    SPINE_TOKEN_ENV,
    SPINE_URL_ENV,
    NetConfigError,
    NetSettings,
    net_env,
    spine_from_env,
)
from tau_net.identity import IdentityError, identity_path, load_or_none
from tau_net.node import NetError, NetNode, NetNotConfigured, open_node, run_blocking
from tau_net.spine import SpineError, Transport
from tau_net.tools import set_active_node

if TYPE_CHECKING:
    from tau_core.builder import Check
    from tau_core.hub.daemon import Hub

    from tau_net.turns import ModelFactory

__all__ = ["SERVICE_NAME", "NetService", "doctor_check", "make_service"]

logger = logging.getLogger(__name__)

SERVICE_NAME = "net"
BACKOFF_START = 1.0
BACKOFF_MAX = 60.0
FATAL_CODES = frozenset({"unauthorized"})
"""Spine answers that stop polling until the hub restarts (the token is read at start)."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class NetService:
    """The ``net`` hub service. Tests pass ``env``, a ``transport`` (a
    :class:`tau_net.testing.FakeNetwork`), a ``model_factory`` and a fast ``sleep``."""

    name = SERVICE_NAME

    def __init__(
        self,
        config: Config,
        *,
        env: Mapping[str, str] | None = None,
        transport: Transport | None = None,
        model_factory: ModelFactory | None = None,
        session_store: SessionStore | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        blocking: Callable[[Callable[[], Any]], Awaitable[Any]] = run_blocking,
    ):
        self.config = config
        self.env = env
        self.transport = transport
        self.model_factory = model_factory
        self.session_store = session_store
        self._sleep = sleep
        self._blocking = blocking
        self.node: NetNode | None = None
        self._task: asyncio.Task[None] | None = None
        self.state = "idle"
        self.idle_reason: str | None = None
        self.address: str | None = None
        self.card_published = False
        self.last_poll_at: str | None = None
        self.last_error: str | None = None
        self.retry_in_s: float | None = None

    # -- HubService ----------------------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return self.node is not None

    def _open(self) -> NetNode | None:
        """The node, or ``None`` with :attr:`idle_reason` set."""
        env = net_env(self.config, self.env)
        if not (env.get(SPINE_URL_ENV) or "").strip():
            self.idle_reason = f"{SPINE_URL_ENV} is not set"
        elif not (env.get(SPINE_TOKEN_ENV) or "").strip():
            self.idle_reason = f"{SPINE_TOKEN_ENV} is not set"
        if self.idle_reason is not None:
            return None
        try:
            node = open_node(
                self.config,
                env=env,
                transport=self.transport,
                model_factory=self.model_factory,
                session_store=self.session_store,
            )
        except (NetConfigError, IdentityError, NetError) as exc:
            self.idle_reason = str(exc)
            return None
        if node.identity is None:
            self.idle_reason = "no identity (run `tau net init`)"
            return None
        return node

    async def start(self, hub: Hub) -> None:
        hub.add_status_source(lambda: {SERVICE_NAME: self.status()})
        self.node = self._open()
        if self.node is None:
            logger.info("net: %s; the network stays idle", self.idle_reason)
            return
        note = self.config.persona_dir / self.node.settings.public_note
        if not note.is_file():
            logger.info("net: %s is missing; network turns share nothing about you", note.name)
        self.state = "starting"
        set_active_node(self.node)  # the owner's tools in this hub share the node
        self._task = asyncio.create_task(self._run(), name="tau-net-poller")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        if self.node is not None:
            set_active_node(None)
            self.node.close()
            self.state = "stopped"

    def status(self) -> dict[str, Any]:
        """The ``net`` key of the hub's ``/status``: never the token or a key."""
        if self.node is None:
            return {"configured": False, "reason": self.idle_reason}
        counts = self._counts()
        return {
            "configured": True,
            "state": self.state,
            "address": self.address,
            "store": self.node.store.kind,
            "card_published": self.card_published,
            "last_poll_at": self.last_poll_at,
            "last_error": self.last_error,
            "retry_in_s": self.retry_in_s,
            **self.node.stats,
            **counts,
        }

    def _counts(self) -> dict[str, int]:
        if self.node is None or self.node.store.kind != "file":
            return {}  # a spine-backed store would cost a request per /status
        try:
            counts = self.node.contacts.counts()
        except Exception:
            return {}
        return {"contacts": counts["accepted"], "pending_in": counts["pending_in"]}

    # -- the poll loop -------------------------------------------------------------------------

    async def _backoff(self, failures: int, error: str) -> None:
        delay = min(BACKOFF_MAX, BACKOFF_START * 2 ** (failures - 1))
        self.state, self.last_error, self.retry_in_s = "retrying", error, delay
        if failures == 1:
            logger.warning("net: %s; retrying with backoff", error)
        else:
            logger.info("net: %s; retry %d in %.0f s", error, failures, delay)
        await self._sleep(delay)

    def _fail(self, error: str) -> None:
        self.state, self.last_error, self.retry_in_s = "failed", error, None
        logger.error(
            "net: the spine rejected the hub token (%s); polling stopped. Check %s in .env.",
            error,
            SPINE_TOKEN_ENV,
        )

    async def _prepare(self) -> bool:
        """The spine's address, then the card. ``False`` when the token is rejected."""
        node = self.node
        assert node is not None
        failures = 0
        while True:
            try:
                self.address = await self._blocking(lambda: node.address(refresh=True))
                published = await self._blocking(node.ensure_card)
            except SpineError as exc:
                if exc.code in FATAL_CODES:
                    self._fail(str(exc))
                    return False
                failures += 1
                await self._backoff(failures, str(exc))
                continue
            except NetError as exc:
                failures += 1
                await self._backoff(failures, str(exc))
                continue
            self.card_published = True
            self.last_error, self.retry_in_s = None, None
            if failures:
                logger.info("net: reached the spine after %d failed attempts", failures)
            if published:
                logger.info("net: published the card of %s", self.address)
            logger.info("net: polling the spine of %s", self.address)
            return True

    async def _run(self) -> None:
        node = self.node
        assert node is not None
        if not await self._prepare():
            return
        timeout = node.settings.poll_timeout_seconds
        failures = 0
        while True:
            if failures == 0:
                self.state, self.retry_in_s = "polling", None
            try:
                await node.poll_once(timeout=timeout, blocking=self._blocking)
            except SpineError as exc:
                if exc.code in FATAL_CODES:
                    self._fail(str(exc))
                    return
                failures += 1
                await self._backoff(failures, str(exc))
                continue
            except NetNotConfigured as exc:  # pragma: no cover - checked at start
                self._fail(str(exc))
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # never crash the hub
                logger.exception("net: poll failed")
                failures += 1
                await self._backoff(failures, f"{type(exc).__name__}: {exc}")
                continue
            if failures:
                logger.info("net: reconnected after %d failed polls", failures)
            failures = 0
            self.state, self.last_error, self.retry_in_s = "polling", None, None
            self.last_poll_at = _now_iso()
            if timeout == 0:
                await self._sleep(1.0)  # no long poll: do not spin


def make_service(config: Config) -> NetService:
    """The ``tau.hub_services`` factory."""
    return NetService(config)


def doctor_check(config: Config, env: Mapping[str, str], hub_status: Any) -> Check:
    """A ``tau doctor`` line for the network in the style of the Telegram check:
    configuration from ``env`` and, when a hub answers, the poller state from its ``/status``
    (``hub_status``; ``None`` = no hub). tau-core's doctor has no hook for components yet, so
    ``tau net status`` shows this line instead."""
    from tau_core.builder import Check

    url = (env.get(SPINE_URL_ENV) or "").strip()
    if not url:
        return Check("net", "info", f"not configured ({SPINE_URL_ENV} is not set)")
    enabled = config.components.hub_services
    if enabled and SERVICE_NAME not in enabled:
        return Check("net", "info", "switched off in [components.hub] services")
    if not (env.get(SPINE_TOKEN_ENV) or "").strip():
        return Check("net", "warn", f"{SPINE_TOKEN_ENV} is not set; the poller stays idle")
    try:
        NetSettings.from_config(config)
        spine_from_env(env)
        identity = load_or_none(identity_path(config.data_dir), env)
    except (NetConfigError, IdentityError) as exc:
        return Check("net", "fail", str(exc))
    if identity is None:
        return Check("net", "warn", "no identity; run `tau net init`")
    poller = hub_status.get(SERVICE_NAME) if isinstance(hub_status, dict) else None
    if not isinstance(poller, dict):
        if hub_status is None:
            return Check("net", "ok", "configured; polls while the hub runs")
        return Check("net", "warn", "configured, but the running hub has no net poller")
    state = poller.get("state")
    if state == "polling":
        return Check("net", "ok", f"polling as {poller.get('address')}")
    if state == "retrying":
        return Check(
            "net",
            "warn",
            f"poller retrying in {poller.get('retry_in_s')} s: {poller.get('last_error')}",
        )
    if state == "failed":
        return Check("net", "fail", f"poller stopped: {poller.get('last_error')}")
    if poller.get("configured") is False:
        return Check("net", "warn", f"the hub's poller is idle: {poller.get('reason')}")
    return Check("net", "info", f"poller {state or 'unknown'}")
