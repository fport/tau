"""The network engine one tau runs: receive, verify, open, dispatch and send (§6).

:class:`NetNode` is shared by the ``net`` hub service, ``tau net`` and the owner's tools, so
``tau net poll --once`` handles an envelope exactly as the running hub would. Receiving an
envelope (:meth:`NetNode.handle`):

1. The claimed sender and kind are peeked from the unverified payload only to decide whether to
   look further: a ``blocked`` sender, or a stranger with anything but a ``contact_request``,
   is dropped at once without fetching anything.
2. The signature is verified with the contact's pinned ``sign_key``, or with a freshly fetched
   card for everyone else (a pending contact's stored keys must match that card). A pinned key
   that does not verify is dropped with a "key changed" warning.
3. ``to`` must be this tau's own address (the one ``GET /hub/health`` returns); an envelope
   already handled is dropped (the store keeps the last 1 000 ids); the box is opened.
4. The contact state machine (:mod:`tau_net.contacts`) decides; a message from an accepted
   contact becomes a network turn (:mod:`tau_net.turns`) and its reply goes back with the same
   ``thread``, ``reply_to`` = the incoming id and ``hops + 1``.

Any failure is logged and the envelope is dropped; the caller acknowledges it either way. A
reply to a given envelope always gets the same id, so an envelope handled again after a crash
cannot deliver a second reply (the recipient's spine answers ``duplicate``).

Every ``message`` handled from an accepted contact and every one delivered to a contact adds one
to the store's ``counts`` document (only when its log entry is new, so nothing is counted
twice). The card name comes from the owner's profile (:mod:`tau_net.profile`).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeVar

from tau_core import AgentEvent, Config, EventBus, SessionStore

from tau_net.config import NetSettings, net_env, spine_from_env
from tau_net.contacts import (
    ACCEPTED,
    BLOCKED,
    Contact,
    ContactBook,
    ContactError,
    clean_name,
)
from tau_net.encoding import b64u_encode, insecure_allowed, parse_address
from tau_net.envelope import (
    MAX_MESSAGE_CHARS,
    BadSignature,
    Envelope,
    EnvelopeError,
    build_envelope,
    open_box,
    open_verified,
    parse_content,
    peek_sender,
)
from tau_net.identity import Identity, identity_path, load_or_none
from tau_net.peers import CardError, Delivery, DeliveryError, PeerCard, PeerClient
from tau_net.profile import NetProfile, check_profile_changes
from tau_net.spine import SpineClient, Transport, Update
from tau_net.store import FileBackend, NetStore, SpineBackend
from tau_net.turns import NetworkTurns

if TYPE_CHECKING:
    from tau_net.turns import ModelFactory

__all__ = [
    "Handled",
    "NetError",
    "NetNode",
    "NetNotConfigured",
    "open_node",
    "reply_id",
    "run_blocking",
]

logger = logging.getLogger(__name__)

T = TypeVar("T")


class NetError(Exception):
    """An owner action that failed; the message is one plain English line."""


class NetNotConfigured(NetError):
    """The spine or the identity this action needs is not set up."""


async def run_blocking[T](func: Callable[[], T]) -> T:
    """Run a blocking call in a daemon thread and await it.

    Unlike ``asyncio.to_thread``, a long poll in flight never delays the hub's exit: awaiting
    it can be cancelled and nothing joins the thread, which ends when its request returns.
    """
    loop = asyncio.get_running_loop()
    future: asyncio.Future[T] = loop.create_future()

    def settle(result: Any, error: BaseException | None) -> None:
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)

    def work() -> None:
        try:
            result, error = func(), None
        except BaseException as exc:
            result, error = None, exc
        with suppress(RuntimeError):  # the loop closed while the call was in flight
            loop.call_soon_threadsafe(settle, result, error)

    threading.Thread(target=work, name="tau-net-io", daemon=True).start()
    return await future


def reply_id(own_address: str, sender: str, envelope_id: str) -> str:
    """The id of this tau's reply to ``envelope_id`` from ``sender``: always the same."""
    digest = hashlib.sha256(f"tau-net/1 reply|{own_address}|{sender}|{envelope_id}".encode())
    return b64u_encode(digest.digest())[:24]


@dataclass(frozen=True)
class Handled:
    """What happened to one incoming envelope.

    ``outcome`` is ``handled``, ``dropped`` or ``duplicate``; ``reason`` says why it was
    dropped; ``replied`` is set when a network turn sent a reply.
    """

    outcome: str
    sender: str | None = None
    kind: str | None = None
    id: str | None = None
    reason: str = ""
    replied: bool = False


@dataclass
class _TurnJob:
    contact: Contact
    sender: str
    envelope_id: str
    thread: str
    hops: int
    text: str
    history: list[dict[str, Any]] = field(default_factory=list)


def _drop(reason: str, sender: str | None = None, kind: str | None = None, **kw: Any) -> Handled:
    return Handled("dropped", sender=sender, kind=kind, reason=reason, **kw)


class NetNode:
    """One tau on the network. Build it with :func:`open_node`."""

    def __init__(
        self,
        config: Config,
        *,
        settings: NetSettings,
        identity: Identity | None,
        spine: SpineClient | None,
        peers: PeerClient,
        store: NetStore,
        env: Mapping[str, str] | None = None,
        clock: Callable[[], float] = time.time,
        model_factory: ModelFactory | None = None,
        session_store: SessionStore | None = None,
        events: EventBus | None = None,
    ):
        self.config = config
        self.settings = settings
        self.identity = identity
        self.spine = spine
        self.peers = peers
        self.store = store
        self.env = dict(env or {})
        self.clock = clock
        self.contacts = ContactBook(store, clock=clock)
        self.turns = NetworkTurns(
            config, settings, store, model_factory=model_factory, session_store=session_store
        )
        self.events = events or EventBus()
        """Agent events of the network (``contact_request``); subscribe to be told."""
        self._address: str | None = None
        self.stats = {"handled": 0, "dropped": 0, "replied": 0}

    def __repr__(self) -> str:
        return f"NetNode(address={self._address!r}, store={self.store.kind!r})"

    # -- basics --------------------------------------------------------------------------------

    def require_identity(self) -> Identity:
        if self.identity is None:
            raise NetNotConfigured("no network identity yet; run `tau net init` first")
        return self.identity

    def require_spine(self) -> SpineClient:
        if self.spine is None:
            raise NetNotConfigured("TAU_SPINE_URL and TAU_SPINE_TOKEN are not both set in .env")
        return self.spine

    def address(self, *, refresh: bool = False) -> str:
        """This tau's address, as its spine reports it (cached)."""
        if self._address is None or refresh:
            health = self.require_spine().health()
            address = health.get("address")
            if not isinstance(address, str) or not address:
                raise NetError("the spine did not report its address")
            self._address = address
        return self._address

    def _now(self) -> int:
        return int(self.clock())

    # -- the owner's profile -------------------------------------------------------------------

    def profile(self) -> NetProfile:
        """The owner's profile from the store (read again every time)."""
        return NetProfile.from_json(self.store.profile())

    def update_profile(self, **changes: Any) -> NetProfile:
        """Validate ``changes`` (:class:`~tau_net.config.NetConfigError`) and write them to the
        profile; ``None`` removes a key."""
        checked = check_profile_changes(changes)
        return NetProfile.from_json(self.store.update_profile(checked))

    def display_name(self) -> str:
        """The card name: the profile's, else ``[component.net] name``, else ``tau``."""
        return self.profile().name or self.settings.name

    # -- the card ------------------------------------------------------------------------------

    def wanted_card(self) -> dict[str, str]:
        return self.require_identity().public_fields(self.display_name())

    def card_matches(self, card: Mapping[str, Any] | None) -> bool:
        if not card:
            return False
        return all(card.get(key) == value for key, value in self.wanted_card().items())

    def publish_card(self) -> dict[str, Any]:
        """``PUT /hub/card`` with the name from ``[component.net]`` and the public keys."""
        fields = self.wanted_card()
        return self.require_spine().publish_card(**fields)

    def ensure_card(self) -> bool:
        """Publish the card when the spine has none or a different one; ``True`` if it did."""
        if self.card_matches(self.require_spine().card()):
            return False
        self.publish_card()
        return True

    # -- sending -------------------------------------------------------------------------------

    def _send(
        self,
        address: str,
        box_key: str,
        kind: str,
        content: dict[str, str],
        *,
        thread: str | None = None,
        reply_to: str | None = None,
        hops: int = 0,
        envelope_id: str | None = None,
    ) -> Delivery:
        """Seal, sign and post one envelope to ``address``; log it when it was delivered."""
        envelope, payload = build_envelope(
            self.require_identity(),
            sender=self.address(),
            recipient=address,
            recipient_box_key=box_key,
            kind=kind,
            content=content,
            envelope_id=envelope_id,
            thread=thread,
            reply_to=reply_to,
            hops=hops,
            ts=self._now(),
        )
        delivery = self.peers.deliver(address, envelope)
        logged = self.store.append_log(
            {
                "ts": payload.ts,
                "direction": "out",
                "address": address,
                "kind": kind,
                "id": payload.id,
                "thread": payload.thread,
                "text": content.get("text", ""),
            }
        )
        if logged and kind == "message":
            self._count_message(address, "out")
        logger.info("net: sent %s %s to %s (%s)", kind, payload.id, address, delivery.status)
        return delivery

    def _count_message(self, address: str, direction: str) -> None:
        """One more message in the ``counts`` document; a failure is only a warning."""
        try:
            self.store.count_message(address, direction)
        except Exception as exc:
            logger.warning("net: could not count a message with %s: %s", address, exc)

    def _fetch_card(self, address: str) -> PeerCard:
        try:
            return self.peers.fetch_card(address)
        except CardError as exc:
            raise NetError(str(exc)) from None

    def _deliver_or_raise(self, what: str, send: Callable[[], Delivery]) -> Delivery:
        try:
            return send()
        except DeliveryError as exc:
            raise NetError(f"{what}, but {exc}") from None
        except EnvelopeError as exc:
            raise NetError(f"{what}, but the envelope could not be built: {exc.reason}") from None

    # -- owner actions -------------------------------------------------------------------------

    def add(self, address: str, note: str = "") -> Contact:
        """Ask ``address`` to become a contact (``tau net add``)."""
        address = parse_address(address)
        if address == self.address():
            raise ContactError("that is this tau's own address")
        self.require_identity()
        card = self._fetch_card(address)
        transition = self.contacts.request(
            address,
            name=card.name,
            sign_key=card.sign_key,
            box_key=card.box_key,
            note=note,
        )
        contact = transition.contact
        assert contact is not None
        if transition.action == "send_accept":
            self._deliver_or_raise(
                f"{address} is a contact now",
                lambda: self._send(
                    address, card.box_key, "contact_accept", {"name": self.display_name()}
                ),
            )
        else:
            self._deliver_or_raise(
                f"the request to {address} was saved",
                lambda: self._send(
                    address,
                    card.box_key,
                    "contact_request",
                    {"name": self.display_name(), "text": note},
                ),
            )
        return contact

    def accept(self, address: str) -> Contact:
        """Accept a pending request (``tau net accept``) and tell the other tau."""
        address = parse_address(address)
        self.require_identity()
        self.address()
        contact = self.contacts.accept(address)
        assert contact.box_key is not None
        self._deliver_or_raise(
            f"{address} is a contact now",
            lambda: self._send(
                address, contact.box_key or "", "contact_accept", {"name": self.display_name()}
            ),
        )
        return contact

    def block(self, address: str) -> Contact:
        return self.contacts.block(parse_address(address))

    def remove(self, address: str) -> bool:
        return self.contacts.remove(parse_address(address))

    def send(self, address: str, text: str) -> Delivery:
        """The owner's own message to an accepted contact: a new thread, ``hops`` 0."""
        address = parse_address(address)
        text = text.strip()
        if not text:
            raise NetError("the message is empty")
        if len(text) > MAX_MESSAGE_CHARS:
            raise NetError(f"the message is longer than {MAX_MESSAGE_CHARS} characters")
        contact = self.contacts.get(address)
        if contact is None or contact.state != ACCEPTED or not contact.box_key:
            state = contact.state if contact is not None else "not a contact"
            raise ContactError(f"{address} is not an accepted contact ({state})")
        box_key = contact.box_key
        return self._deliver_or_raise(
            "the message was not delivered",
            lambda: self._send(address, box_key, "message", {"text": text}),
        )

    # -- receiving -----------------------------------------------------------------------------

    def receive(self, raw: Any) -> tuple[Handled, _TurnJob | None]:
        """Steps 1–4 of the module doc, up to (not including) a network turn."""
        try:
            envelope = Envelope.from_json(raw)
            sender = peek_sender(envelope)
        except EnvelopeError as exc:
            return _drop(exc.reason), None
        contact = self.contacts.get(sender)
        if contact is not None and contact.state == BLOCKED:
            return _drop("blocked", sender), None
        card: PeerCard | None = None
        sign_key = box_key = ""  # the keys the envelope verified with, pinned on acceptance
        try:
            if contact is not None and contact.pinned:
                sign_key, box_key = contact.sign_key or "", contact.box_key or ""
                try:
                    payload = open_verified(envelope, sign_key)
                except BadSignature:
                    logger.warning(
                        "net: an envelope from %s does not verify with its pinned key "
                        "(key changed); dropped",
                        sender,
                    )
                    return _drop("key changed", sender), None
            else:
                if contact is None and _peek_kind(envelope) != "contact_request":
                    return _drop("not a contact", sender), None
                try:
                    card = self.peers.fetch_card(sender)
                except CardError as exc:
                    return _drop(f"sender card unavailable ({exc.reason})", sender), None
                sign_key, box_key = card.sign_key, card.box_key
                payload = open_verified(envelope, sign_key)
                if contact is not None and not contact.keys_match(sign_key, box_key):
                    logger.warning(
                        "net: the card of %s no longer matches the keys stored for it "
                        "(key changed); dropped",
                        sender,
                    )
                    return _drop("key changed", sender), None
        except BadSignature:
            return _drop("bad signature", sender), None
        except EnvelopeError as exc:
            return _drop(exc.reason, sender), None
        kind = payload.kind
        if payload.sender != sender:  # pragma: no cover - the same bytes were parsed twice
            return _drop("sender mismatch", sender, kind), None
        if payload.recipient != self.address():
            return _drop("wrong recipient", sender, kind, id=payload.id), None
        if self.store.is_seen(sender, payload.id):
            return Handled("duplicate", sender, kind, payload.id, "already handled"), None
        try:
            content = parse_content(
                kind, open_box(payload.box, self.require_identity(), payload.aad)
            )
        except EnvelopeError as exc:
            return _drop(exc.reason, sender, kind, id=payload.id), None

        entry = {
            "ts": payload.ts,
            "direction": "in",
            "address": sender,
            "kind": kind,
            "id": payload.id,
            "thread": payload.thread,
            "text": content.get("text", ""),
        }
        name = content.get("name") or (card.name if card is not None else "")
        job: _TurnJob | None = None
        if kind == "contact_request":
            transition = self.contacts.on_request(
                sender,
                name=name,
                text=content["text"],
                sign_key=sign_key,
                box_key=box_key,
            )
            if transition.action == "drop":
                return _drop(transition.reason, sender, kind, id=payload.id), None
            self.store.append_log(entry)
            if transition.action == "notify":
                self._notify_request(sender, clean_name(name), content["text"])
            elif transition.action == "send_accept":
                try:
                    self._send(sender, box_key, "contact_accept", {"name": self.display_name()})
                except (DeliveryError, EnvelopeError) as exc:
                    logger.warning("net: could not answer the request of %s: %s", sender, exc)
        elif kind == "contact_accept":
            transition = self.contacts.on_accept(
                sender, name=name, sign_key=sign_key, box_key=box_key
            )
            if transition.action == "drop":
                return _drop(transition.reason, sender, kind, id=payload.id), None
            self.store.append_log(entry)
            if transition.action == "accepted":
                logger.info("net: %s accepted the contact request", sender)
        else:
            transition = self.contacts.on_message(sender)
            if transition.action != "turn" or transition.contact is None:
                return _drop(transition.reason, sender, kind, id=payload.id), None
            history = [e for e in self.store.log(address=sender) if e.get("id") != payload.id]
            if self.store.append_log(entry):
                self._count_message(sender, "in")
            job = self._turn_job(transition.contact, payload.id, payload.thread, payload.hops)
            if job is not None:
                job.text = content["text"]
                job.history = history
                return Handled("handled", sender, kind, payload.id), job
        self.store.mark_seen(sender, payload.id)
        return Handled("handled", sender, kind, payload.id), None

    def _turn_job(
        self, contact: Contact, envelope_id: str, thread: str, hops: int
    ) -> _TurnJob | None:
        """A network turn when auto-replies are on and neither limit is reached."""
        if not self.settings.auto_reply:
            return None
        if hops + 1 > self.settings.max_hops:
            logger.info("net: not answering %s: hop limit %d reached", contact.address, hops + 1)
            return None
        cap = self.settings.max_auto_replies_per_hour
        if self.contacts.auto_replies_last_hour(contact.address) >= cap:
            logger.info("net: not answering %s: %d auto-replies this hour", contact.address, cap)
            return None
        return _TurnJob(contact, contact.address, envelope_id, thread, hops, "")

    def _notify_request(self, sender: str, name: str, text: str) -> None:
        logger.info(
            "net: contact request from %s%s; accept it with `tau net accept %s`",
            sender,
            f" ({name})" if name else "",
            sender,
        )
        self.events.emit(
            AgentEvent.create("contact_request", {"address": sender, "name": name, "text": text})
        )

    def finish(self, job: _TurnJob, reply: str | None) -> Handled:
        """Send the reply of a network turn, if there is one, and mark the envelope handled."""
        replied = False
        try:
            if reply:
                contact = self.contacts.get(job.sender)
                if contact is None or contact.state != ACCEPTED or not contact.box_key:
                    logger.info("net: %s is no longer a contact; the reply is dropped", job.sender)
                else:
                    self._send(
                        job.sender,
                        contact.box_key,
                        "message",
                        {"text": reply[:MAX_MESSAGE_CHARS]},
                        thread=job.thread,
                        reply_to=job.envelope_id,
                        hops=job.hops + 1,
                        envelope_id=reply_id(self.address(), job.sender, job.envelope_id),
                    )
                    self.contacts.record_auto_reply(job.sender)
                    replied = True
        except (DeliveryError, EnvelopeError) as exc:
            logger.warning("net: the reply to %s was not delivered: %s", job.sender, exc)
        finally:
            self.store.mark_seen(job.sender, job.envelope_id)
        return Handled("handled", job.sender, "message", job.envelope_id, replied=replied)

    async def handle(
        self, raw: Any, *, blocking: Callable[[Callable[[], Any]], Awaitable[Any]] = run_blocking
    ) -> Handled:
        """Handle one envelope end to end (verification, state, network turn, reply)."""
        handled, job = await blocking(lambda: self.receive(raw))
        if job is not None:
            reply = await self.turns.run(
                address=job.sender, name=job.contact.name, text=job.text, history=job.history
            )
            handled = await blocking(lambda: self.finish(job, reply))
        self._count(handled)
        return handled

    def _count(self, handled: Handled) -> None:
        if handled.outcome == "handled":
            self.stats["handled"] += 1
            self.stats["replied"] += int(handled.replied)
        else:
            self.stats["dropped"] += 1
            level = logging.INFO if handled.outcome == "duplicate" else logging.WARNING
            if handled.reason in ("blocked", "not a contact"):
                level = logging.INFO
            logger.log(
                level,
                "net: dropped a %s from %s: %s",
                handled.kind or "envelope",
                handled.sender or "an unknown sender",
                handled.reason,
            )

    async def take(
        self,
        update: Update,
        *,
        blocking: Callable[[Callable[[], Any]], Awaitable[Any]] = run_blocking,
    ) -> Handled:
        """Handle one update, then acknowledge it and move the cursor past it.

        A failure while handling drops the envelope (it is still acknowledged). A failing
        acknowledgement raises :class:`~tau_net.spine.SpineError` and leaves the cursor: the
        envelope comes again with the next poll and is then dropped as already handled.
        """
        try:
            handled = await self.handle(update.envelope, blocking=blocking)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("net: update %s failed; dropping it", update.seq)
            handled = _drop(f"internal error ({type(exc).__name__})")
            self.stats["dropped"] += 1
        spine = self.require_spine()
        await blocking(lambda: spine.ack([update.seq]))
        await blocking(lambda: self.store.save_cursor(update.seq))
        return handled

    async def poll_once(
        self,
        *,
        timeout: int = 0,
        limit: int = 50,
        blocking: Callable[[Callable[[], Any]], Awaitable[Any]] = run_blocking,
    ) -> list[Handled]:
        """Fetch what the spine holds after the cursor (waiting up to ``timeout`` s) and take
        every update in order."""
        spine = self.require_spine()
        self.require_identity()
        after = await blocking(self.store.cursor)
        updates = await blocking(lambda: spine.updates(after=after, timeout=timeout, limit=limit))
        return [await self.take(update, blocking=blocking) for update in updates]

    def close(self) -> None:
        self.turns.close()


def _peek_kind(envelope: Envelope) -> str | None:
    """The claimed kind of an unverified envelope (only to drop early)."""
    try:
        data = json.loads(envelope.payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    kind = data.get("kind") if isinstance(data, dict) else None
    return kind if isinstance(kind, str) else None


def open_node(
    config: Config,
    *,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
    identity: Identity | None = None,
    model_factory: ModelFactory | None = None,
    session_store: SessionStore | None = None,
    clock: Callable[[], float] = time.time,
) -> NetNode:
    """A :class:`NetNode` for ``config``: settings from ``[component.net]``, variables from
    ``env`` (default: the process environment over ``<home>/.env``), the identity from
    ``TAU_NET_IDENTITY`` or the identity file, the spine from ``TAU_SPINE_URL`` and
    ``TAU_SPINE_TOKEN``. Missing pieces stay ``None`` (actions that need them raise
    :class:`NetNotConfigured`); a ``store = "spine"`` without a spine raises it at once.
    ``NetConfigError`` and ``IdentityError`` report a broken configuration."""
    merged = net_env(config, env)
    settings = NetSettings.from_config(config)
    if identity is None:
        identity = load_or_none(identity_path(config.data_dir), merged)
    spine = spine_from_env(merged, transport=transport)
    peers = PeerClient(transport, allow_insecure=insecure_allowed(merged))
    if settings.store == "spine":
        if spine is None:
            raise NetNotConfigured(
                '[component.net] store = "spine" needs TAU_SPINE_URL and TAU_SPINE_TOKEN'
            )
        store = NetStore(SpineBackend(spine))
    else:
        store = NetStore(FileBackend(config.data_dir / "net"))
    return NetNode(
        config,
        settings=settings,
        identity=identity,
        spine=spine,
        peers=peers,
        store=store,
        env=merged,
        clock=clock,
        model_factory=model_factory,
        session_store=session_store,
    )
