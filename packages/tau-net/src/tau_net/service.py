"""The ``net`` hub service: wait for mail at the spine, handle each envelope, acknowledge it
(§6.1).

A ``tau.hub_services`` component (``net = "tau_net.service:make_service"``) that runs inside
``tau hub run``. It reaches the spine outbound only, so the hub still opens no inbound port.
For each update, in order, it handles the envelope, acknowledges it and then stores the cursor,
so a crash re-handles rather than loses.

How it waits is ``[component.net] link``:

- ``auto`` (the default): it keeps the spine's WebSocket doorbell (``GET /hub/ws``,
  :mod:`tau_net.doorbell`) open and fetches with ``GET /hub/updates?timeout=0`` on every ring,
  on every (re)connect and at least every 5 minutes; otherwise it waits without any HTTP
  request. The spine's ``Mailbox`` hibernates meanwhile, which keeps a spine on the Workers
  Free plan far inside its daily Durable Object budget. When the doorbell cannot be used (a
  spine without it answers ``404``/``426``, or three attempts in a row fail) it long-polls
  instead and tries the doorbell again every 30 minutes.
- ``websocket``: the doorbell only; failures back off and retry, never falling back.
- ``poll``: the long poll of ``GET /hub/updates?timeout=25``, as before the doorbell.

- Without ``TAU_SPINE_URL``, ``TAU_SPINE_TOKEN`` or an identity it stays idle, logs one line and
  reports ``net: {configured: false}`` in ``/status``; it never fails the hub.
- On start it asks the spine for its address and publishes the card when the spine has none or
  a different one.
- Network errors back off exponentially up to 60 s; a rejected token stops polling (the token
  is read again only on a restart).
- Blocking HTTP and the doorbell run in daemon threads, so the hub loop stays responsive and
  :meth:`stop` returns at once even while a long poll or a doorbell wait is in flight.
- With a ``[component.net] universe`` host, a second task reports to that universe (ADR 0010)
  once the card is published and then every ``universe_report_minutes``, but only while the
  owner's profile says ``universe_join`` (it is read again at every interval, so ``tau net
  universe join`` and ``leave`` take effect without a restart). A universe that no longer lists
  the tau gets a fresh join. A failure only shows in ``/status`` as ``net.universe``; it never
  stops the hub or the poll loop.

The token never reaches a log line, an exception message or ``/status``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
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
from tau_net.doorbell import Doorbell, DoorbellError, DoorbellUnauthorized, DoorbellUnsupported
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
SAFETY_FETCH_SECONDS = 300.0
"""On the doorbell, fetch at least this often even when it stays quiet."""
DOORBELL_RETRY_SECONDS = 1800.0
"""``link = "auto"``: after falling back to the long poll, try the doorbell again this late."""
DOORBELL_MAX_FAILURES = 3
"""``link = "auto"``: failed doorbell attempts in a row before falling back."""
DOORBELL_STABLE_SECONDS = 60.0
"""A doorbell connection that lasted this long and then dropped is reconnected at once; one
that dropped sooner counts as a failed attempt (so a flapping link backs off)."""
FETCH_LIMIT = 50


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="seconds")


class NetService:
    """The ``net`` hub service. Tests pass ``env``, a ``transport`` (a
    :class:`tau_net.testing.FakeNetwork`), a ``model_factory``, a fast ``sleep`` (backoff),
    a ``universe_sleep`` (the report interval), a ``clock`` and a ``monotonic`` clock (the
    doorbell's retry interval).

    ``doorbell`` makes the doorbell of ``GET /hub/ws`` (a fresh or reused
    :class:`~tau_net.doorbell.Doorbell` per connection; tests pass a
    :class:`tau_net.testing.FakeDoorbell`). Without it the service uses the spine's own
    WebSocket doorbell, unless a ``transport`` was given: a fake network has no sockets, so the
    service then long-polls."""

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
        universe_sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.time,
        doorbell: Callable[[], Doorbell] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self.config = config
        self.env = env
        self.transport = transport
        self.model_factory = model_factory
        self.session_store = session_store
        self._sleep = sleep
        self._blocking = blocking
        self._universe_sleep = universe_sleep
        self.clock = clock
        self._doorbell_factory = doorbell
        self._monotonic = monotonic
        self.link: str | None = None
        """How the service waits right now: ``websocket``, ``poll`` or ``None`` before it
        starts."""
        self.doorbell_connects = 0
        self.doorbell_reconnects = 0
        self.doorbell_rings = 0
        self.doorbell_fallbacks = 0
        self.doorbell_last_error: str | None = None
        self.last_ring_at: str | None = None
        self._doorbell_retry_at = 0.0
        self.node: NetNode | None = None
        self._task: asyncio.Task[None] | None = None
        self._universe_task: asyncio.Task[None] | None = None
        self._ready: asyncio.Event | None = None
        self.state = "idle"
        self.idle_reason: str | None = None
        self.address: str | None = None
        self.card_published = False
        self.last_poll_at: str | None = None
        self.last_error: str | None = None
        self.retry_in_s: float | None = None
        self.universe_joined = False
        self.universe_last_report_at: str | None = None
        self.universe_last_error: str | None = None
        self.universe_visible_links: int | None = None
        self.universe_reports = 0

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
                clock=self.clock,
            )
        except (NetConfigError, IdentityError, NetError) as exc:
            self.idle_reason = str(exc)
            return None
        if node.identity is None:
            self.idle_reason = "no identity (run `tau net init`)"
            return None
        if self._doorbell_factory is None and self.transport is None and node.spine is not None:
            self._doorbell_factory = node.spine.doorbell
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
        self._ready = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="tau-net-poller")
        if self.node.settings.universe:
            self._universe_task = asyncio.create_task(self._universe_run(), name="tau-net-universe")

    async def stop(self) -> None:
        tasks = [self._task, self._universe_task]
        self._task = self._universe_task = None
        for task in tasks:
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
            "link": self.link,
            "last_poll_at": self.last_poll_at,
            "last_error": self.last_error,
            "retry_in_s": self.retry_in_s,
            "doorbell": self.doorbell_status(),
            **self.node.stats,
            **counts,
            "universe": self.universe_status(),
        }

    def doorbell_status(self) -> dict[str, Any]:
        """``net.doorbell`` in ``/status``: the ``link`` setting, connections (the first one
        and reconnects), rings (the hello of each connection included), fallbacks to the long
        poll, the last ring, the last doorbell error and, after a fallback, when ``auto``
        tries the doorbell again."""
        retry_at = None
        if self.link == "poll" and self._doorbell_retry_at > 0:
            remaining = max(0.0, self._doorbell_retry_at - self._monotonic())
            retry_at = _iso(self.clock() + remaining)
        return {
            "setting": self.node.settings.link if self.node is not None else None,
            "connects": self.doorbell_connects,
            "reconnects": self.doorbell_reconnects,
            "rings": self.doorbell_rings,
            "fallbacks": self.doorbell_fallbacks,
            "last_ring_at": self.last_ring_at,
            "last_error": self.doorbell_last_error,
            "retry_at": retry_at,
        }

    def universe_status(self) -> dict[str, Any]:
        """``net.universe`` in ``/status``: the host (``""`` = off), whether the profile says
        joined, the last successful report, the last error and the universe's
        ``visible_links``."""
        return {
            "universe": self.node.settings.universe if self.node is not None else "",
            "joined": self.universe_joined,
            "last_report_at": self.universe_last_report_at,
            "last_error": self.universe_last_error,
            "visible_links": self.universe_visible_links,
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
        if self._ready is not None:
            self._ready.set()
        setting = node.settings.link
        if setting != "poll" and self._doorbell_factory is None:
            logger.info("net: no doorbell in this setup; long-polling the spine")
        while True:
            if (
                setting != "poll"
                and self._doorbell_factory is not None
                and self._monotonic() >= self._doorbell_retry_at
            ):
                if await self._listen(setting) == "failed":
                    return
                self.doorbell_fallbacks += 1
                self._doorbell_retry_at = self._monotonic() + DOORBELL_RETRY_SECONDS
            retry = setting == "auto" and self._doorbell_factory is not None
            if await self._poll(self._doorbell_retry_at if retry else None) == "failed":
                return

    # -- the long poll -------------------------------------------------------------------------

    async def _poll(self, until: float | None) -> str:
        """Long-poll until the monotonic time ``until`` (``None``: for ever); ``"failed"``
        when the token was rejected, else ``"retry"``."""
        node = self.node
        assert node is not None
        self.link = "poll"
        timeout = node.settings.poll_timeout_seconds
        failures = 0
        while until is None or self._monotonic() < until:
            if failures == 0:
                self.state, self.retry_in_s = "polling", None
            try:
                await node.poll_once(timeout=timeout, blocking=self._blocking)
            except SpineError as exc:
                if exc.code in FATAL_CODES:
                    self._fail(str(exc))
                    return "failed"
                failures += 1
                await self._backoff(failures, str(exc))
                continue
            except NetNotConfigured as exc:  # pragma: no cover - checked at start
                self._fail(str(exc))
                return "failed"
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
        return "retry"

    # -- the doorbell --------------------------------------------------------------------------

    async def _listen(self, setting: str) -> str:
        """Wait on the doorbell and fetch whenever it rings, reconnecting as needed.
        Returns ``"failed"`` when the token was rejected and, with ``setting == "auto"``,
        ``"fallback"`` when the doorbell cannot be used; otherwise it never returns."""
        assert self._doorbell_factory is not None
        failures = 0
        while True:
            doorbell = self._doorbell_factory()
            try:
                await self._blocking(doorbell.connect)
            except DoorbellUnauthorized as exc:
                await self._close(doorbell)
                self._fail(str(exc))
                return "failed"
            except (DoorbellError, OSError) as exc:
                await self._close(doorbell)
                failures += 1
                self.doorbell_last_error = str(exc)
                if setting == "auto" and (
                    isinstance(exc, DoorbellUnsupported) or failures >= DOORBELL_MAX_FAILURES
                ):
                    self._fall_back(exc, failures)
                    return "fallback"
                await self._backoff(failures, f"doorbell: {exc}")
                continue
            self.doorbell_connects += 1
            if self.doorbell_connects > 1:
                self.doorbell_reconnects += 1
            if self.link != "websocket":
                logger.info("net: waiting on the doorbell of %s", self.address)
            self.link = "websocket"
            self.state, self.last_error, self.retry_in_s = "polling", None, None
            started = self._monotonic()
            try:
                token_ok = await self._ring_loop(doorbell)
            except (DoorbellError, OSError) as exc:
                await self._close(doorbell)
                self.doorbell_last_error = str(exc)
                if self._monotonic() - started >= DOORBELL_STABLE_SECONDS:
                    failures = 0
                    logger.info("net: the doorbell dropped (%s); reconnecting", exc)
                    continue
                failures += 1
                if setting == "auto" and failures >= DOORBELL_MAX_FAILURES:
                    self._fall_back(exc, failures)
                    return "fallback"
                await self._backoff(failures, f"doorbell: {exc}")
                continue
            except BaseException:  # cancelled: stop() must not wait for the closing handshake
                _close_quietly(doorbell)
                raise
            await self._close(doorbell)
            if not token_ok:
                return "failed"

    async def _close(self, doorbell: Doorbell) -> None:
        with suppress(Exception):
            await self._blocking(doorbell.close)

    async def _ring_loop(self, doorbell: Doorbell) -> bool:
        """Fetch on every ring (the hello included) and at least every
        :data:`SAFETY_FETCH_SECONDS`. ``False`` when the token was rejected; a lost doorbell
        raises."""
        while True:
            rang = await self._blocking(lambda: doorbell.wait(SAFETY_FETCH_SECONDS))
            if rang:
                self.doorbell_rings += 1
                self.last_ring_at = _now_iso()
            if not await self._fetch():
                return False

    async def _fetch(self) -> bool:
        """Take everything the spine holds, without waiting (``timeout=0``); errors back off
        and retry. ``False`` when the token was rejected."""
        node = self.node
        assert node is not None
        failures = 0
        while True:
            try:
                handled = await node.poll_once(
                    timeout=0, limit=FETCH_LIMIT, blocking=self._blocking
                )
            except SpineError as exc:
                if exc.code in FATAL_CODES:
                    self._fail(str(exc))
                    return False
                failures += 1
                await self._backoff(failures, str(exc))
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # never crash the hub
                logger.exception("net: fetch failed")
                failures += 1
                await self._backoff(failures, f"{type(exc).__name__}: {exc}")
                continue
            failures = 0
            self.state, self.last_error, self.retry_in_s = "polling", None, None
            self.last_poll_at = _now_iso()
            if len(handled) < FETCH_LIMIT:
                return True  # a full batch means more may be waiting

    def _fall_back(self, error: BaseException, failures: int) -> None:
        minutes = DOORBELL_RETRY_SECONDS / 60
        if isinstance(error, DoorbellUnsupported):
            logger.info(
                "net: the spine has no doorbell (%s); long-polling, next try in %.0f min",
                error,
                minutes,
            )
        else:
            logger.warning(
                "net: the doorbell failed %d times (%s); long-polling, next try in %.0f min",
                failures,
                error,
                minutes,
            )

    # -- the universe --------------------------------------------------------------------------

    async def _universe_run(self) -> None:
        """Report once the card is published, then every ``universe_report_minutes``."""
        node = self.node
        assert node is not None and self._ready is not None
        await self._ready.wait()
        interval = node.settings.universe_report_minutes * 60
        while True:
            await self.universe_tick()
            await self._universe_sleep(interval)

    async def universe_tick(self) -> None:
        """One report interval; never raises (a failure lands in ``net.universe``)."""
        node = self.node
        if node is None:
            return
        try:
            profile = await self._blocking(node.profile)
            self.universe_joined = profile.universe_join
            if not profile.universe_join:
                self.universe_last_error = None
                return
            sync = await self._blocking(node.universe_sync)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # never crash the hub
            self.universe_last_error = " ".join(str(exc).split()) or type(exc).__name__
            logger.warning("net: the universe report failed: %s", self.universe_last_error)
            return
        self.universe_joined = sync.joined
        self.universe_last_error = None
        if sync.joined:
            self.universe_reports += 1
            self.universe_last_report_at = _iso(self.clock())
            self.universe_visible_links = sync.visible_links
            logger.info(
                "net: reported to the universe %s%s (%s visible links)",
                node.settings.universe,
                " after joining again" if sync.rejoined else "",
                sync.visible_links,
            )


def _close_quietly(doorbell: Doorbell) -> None:
    """Close a doorbell in a daemon thread: the closing handshake may take a second, and
    :meth:`NetService.stop` must not wait for it."""

    def close() -> None:
        with suppress(Exception):
            doorbell.close()

    threading.Thread(target=close, name="tau-net-doorbell-close", daemon=True).start()


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
        if poller.get("link") == "websocket":
            return Check("net", "ok", f"on the doorbell as {poller.get('address')}")
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
