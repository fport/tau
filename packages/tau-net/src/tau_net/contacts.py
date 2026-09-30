"""Contacts and their state machine (protocol v1, §6.3).

A contact is stored with its ``address``, ``name``, ``state``, ``sign_key``, ``box_key``,
``note`` and times; ``state`` is ``pending_in``, ``pending_out``, ``accepted`` or ``blocked``.

Incoming envelopes, after the hub verified them:

========================  ================  ==================================================
incoming                  current state     result
========================  ================  ==================================================
``contact_request``       none              ``pending_in`` with its note; the owner is told
``contact_request``       ``pending_out``   ``accepted``; a ``contact_accept`` goes back
``contact_request``       ``accepted``      a ``contact_accept`` goes back again (idempotent)
``contact_accept``        ``pending_out``   ``accepted``
``message``               ``accepted``      a network turn
anything                  ``blocked``/none  dropped and logged, never answered
========================  ================  ==================================================

Keys are pinned when a contact becomes ``accepted``; an envelope that does not verify with the
pinned key is dropped with a warning ("key changed"). The keys stored for a pending contact (from
the card fetched when it was added or when its request arrived) must match the card that signs
the next envelope, or the envelope is dropped the same way.
"""

from __future__ import annotations

import time
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from tau_net.store import NetStore

__all__ = [
    "ACCEPTED",
    "BLOCKED",
    "PENDING_IN",
    "PENDING_OUT",
    "STATES",
    "Contact",
    "ContactBook",
    "ContactError",
    "Transition",
    "clean_name",
]

PENDING_IN = "pending_in"
PENDING_OUT = "pending_out"
ACCEPTED = "accepted"
BLOCKED = "blocked"
STATES = (PENDING_IN, PENDING_OUT, ACCEPTED, BLOCKED)
NAME_LIMIT = 80
NOTE_LIMIT = 2000
HOUR = 3600


def clean_name(name: Any, limit: int = NAME_LIMIT) -> str:
    """A display name from untrusted text: one line, no control or format characters,
    at most ``limit`` characters."""
    if not isinstance(name, str):
        return ""
    kept = "".join(
        " " if unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") else ch for ch in name
    )
    return " ".join(kept.split())[:limit]


class ContactError(Exception):
    """An owner action that the contact's state does not allow; the message is English."""


@dataclass
class Contact:
    address: str
    state: str
    name: str = ""
    sign_key: str | None = None
    box_key: str | None = None
    note: str = ""
    created_at: int = 0
    updated_at: int = 0
    accepted_at: int | None = None
    auto_replies: list[int] = field(default_factory=list)
    """Send times of the auto-replies of the last hour (the hourly cap)."""

    @property
    def pinned(self) -> bool:
        """Keys are pinned once the contact is accepted."""
        return self.state == ACCEPTED and bool(self.sign_key) and bool(self.box_key)

    @property
    def label(self) -> str:
        return f"{self.name} ({self.address})" if self.name else self.address

    def keys_match(self, sign_key: str, box_key: str) -> bool:
        """``True`` when no keys are stored yet or the stored ones are these."""
        if not self.sign_key and not self.box_key:
            return True
        return self.sign_key == sign_key and self.box_key == box_key

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Contact | None:
        address, state = data.get("address"), data.get("state")
        if not isinstance(address, str) or state not in STATES:
            return None
        replies = data.get("auto_replies")
        return cls(
            address=address,
            state=state,
            name=clean_name(data.get("name")),
            sign_key=data.get("sign_key") if isinstance(data.get("sign_key"), str) else None,
            box_key=data.get("box_key") if isinstance(data.get("box_key"), str) else None,
            note=str(data.get("note") or ""),
            created_at=_int(data.get("created_at")),
            updated_at=_int(data.get("updated_at")),
            accepted_at=_int(data.get("accepted_at")) or None,
            auto_replies=[int(t) for t in replies if _is_int(t)]
            if isinstance(replies, list)
            else [],
        )


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _int(value: Any) -> int:
    return value if _is_int(value) else 0


@dataclass(frozen=True)
class Transition:
    """What the hub does after the book changed.

    ``action`` is one of ``notify`` (a new request: tell the owner), ``send_accept`` (answer
    with a ``contact_accept``), ``send_request`` (send a ``contact_request``), ``accepted``
    (nothing to send), ``turn`` (a message for a network turn) or ``drop`` (ignore; ``reason``
    says why).
    """

    action: str
    contact: Contact | None
    reason: str = ""


class ContactBook:
    """The contact state machine over a :class:`~tau_net.store.NetStore`."""

    def __init__(self, store: NetStore, *, clock: Callable[[], float] = time.time):
        self.store = store
        self.clock = clock

    def _now(self) -> int:
        return int(self.clock())

    # -- reading -------------------------------------------------------------------------------

    def get(self, address: str) -> Contact | None:
        data = self.store.contacts().get(address)
        return Contact.from_json(data) if data is not None else None

    def all(self) -> list[Contact]:
        order = {state: i for i, state in enumerate(STATES)}
        contacts = [c for c in map(Contact.from_json, self.store.contacts().values()) if c]
        return sorted(contacts, key=lambda c: (order[c.state], c.address))

    def counts(self) -> dict[str, int]:
        counts = dict.fromkeys(STATES, 0)
        for contact in self.all():
            counts[contact.state] += 1
        return counts

    def _change(self, address: str, edit: Callable[[Contact | None], Any]) -> Any:
        """Run ``edit`` on the current record under the store lock; it returns
        ``(contact_or_None_to_delete, result)`` and the record is written back."""

        def change(contacts: dict[str, dict[str, Any]]) -> Any:
            data = contacts.get(address)
            current = Contact.from_json(data) if data is not None else None
            contact, result = edit(current)
            if contact is None:
                contacts.pop(address, None)
            else:
                contact.updated_at = self._now()
                contacts[address] = contact.to_json()
            return result

        return self.store.update_contacts(change)

    def _new(self, address: str, state: str, **fields: Any) -> Contact:
        now = self._now()
        return Contact(address=address, state=state, created_at=now, updated_at=now, **fields)

    # -- incoming (after the envelope verified) ------------------------------------------------

    def on_request(
        self, address: str, *, name: str, text: str, sign_key: str, box_key: str
    ) -> Transition:
        def edit(current: Contact | None) -> Any:
            if current is None:
                contact = self._new(
                    address,
                    PENDING_IN,
                    name=clean_name(name),
                    sign_key=sign_key,
                    box_key=box_key,
                    note=text[:NOTE_LIMIT],
                )
                return contact, Transition("notify", contact)
            if current.state == BLOCKED:
                return current, Transition("drop", current, "blocked")
            if current.state == PENDING_OUT:
                self._pin(current, name, sign_key, box_key)
                return current, Transition("send_accept", current)
            if current.state == ACCEPTED:
                return current, Transition("send_accept", current)
            # pending_in again: keep one request, with the latest note
            current.name = clean_name(name) or current.name
            current.note = text[:NOTE_LIMIT]
            return current, Transition("none", current, "already pending")

        return self._change(address, edit)

    def on_accept(self, address: str, *, name: str, sign_key: str, box_key: str) -> Transition:
        def edit(current: Contact | None) -> Any:
            if current is None:
                return None, Transition("drop", None, "not a contact")
            if current.state == PENDING_OUT:
                self._pin(current, name, sign_key, box_key)
                return current, Transition("accepted", current)
            if current.state == ACCEPTED:
                return current, Transition("none", current, "already accepted")
            return current, Transition("drop", current, current.state)

        return self._change(address, edit)

    def on_message(self, address: str) -> Transition:
        contact = self.get(address)
        if contact is None:
            return Transition("drop", None, "not a contact")
        if contact.state != ACCEPTED:
            return Transition("drop", contact, contact.state)
        return Transition("turn", contact)

    def _pin(self, contact: Contact, name: str, sign_key: str, box_key: str) -> None:
        contact.state = ACCEPTED
        contact.name = clean_name(name) or contact.name
        contact.sign_key, contact.box_key = sign_key, box_key
        contact.accepted_at = self._now()

    # -- owner actions -------------------------------------------------------------------------

    def request(
        self, address: str, *, name: str, sign_key: str, box_key: str, note: str = ""
    ) -> Transition:
        """``tau net add``: ask ``address`` to become a contact.

        None → ``pending_out`` (``send_request``); ``pending_out`` → sent again; ``pending_in``
        → accepted at once (``send_accept``); ``accepted`` or ``blocked`` → :class:`ContactError`.
        A pending contact whose stored keys differ from the card is refused ("key changed").
        """

        def edit(current: Contact | None) -> Any:
            if current is None:
                contact = self._new(
                    address,
                    PENDING_OUT,
                    name=clean_name(name),
                    sign_key=sign_key,
                    box_key=box_key,
                    note=note[:NOTE_LIMIT],
                )
                return contact, Transition("send_request", contact)
            if current.state == ACCEPTED:
                raise ContactError(f"{address} is already a contact")
            if current.state == BLOCKED:
                raise ContactError(f"{address} is blocked; remove it first")
            if not current.keys_match(sign_key, box_key):
                raise ContactError(
                    f"the keys of {address} changed since its request; remove it and add it again"
                )
            if current.state == PENDING_IN:
                self._pin(current, name or current.name, sign_key, box_key)
                return current, Transition("send_accept", current)
            current.name = clean_name(name) or current.name
            current.sign_key, current.box_key = sign_key, box_key
            if note:
                current.note = note[:NOTE_LIMIT]
            return current, Transition("send_request", current)

        return self._change(address, edit)

    def accept(self, address: str) -> Contact:
        """``tau net accept``: ``pending_in`` → ``accepted`` with the keys of its request."""

        def edit(current: Contact | None) -> Any:
            if current is None:
                raise ContactError(f"no contact request from {address}")
            if current.state == ACCEPTED:
                raise ContactError(f"{address} is already a contact")
            if current.state != PENDING_IN:
                raise ContactError(f"{address} has not asked to be a contact ({current.state})")
            if not current.sign_key or not current.box_key:
                raise ContactError(f"the request from {address} carries no keys")
            self._pin(current, current.name, current.sign_key, current.box_key)
            return current, current

        return self._change(address, edit)

    def block(self, address: str) -> Contact:
        """``tau net block``: every state (or none) → ``blocked``; nothing from it is read."""

        def edit(current: Contact | None) -> Any:
            contact = current or self._new(address, BLOCKED)
            contact.state = BLOCKED
            return contact, contact

        return self._change(address, edit)

    def remove(self, address: str) -> bool:
        """``tau net remove``: forget the contact (its log and session stay)."""

        def edit(current: Contact | None) -> Any:
            return None, current is not None

        return self._change(address, edit)

    # -- the hourly auto-reply cap -------------------------------------------------------------

    def auto_replies_last_hour(self, address: str) -> int:
        contact = self.get(address)
        if contact is None:
            return 0
        since = self._now() - HOUR
        return sum(1 for t in contact.auto_replies if t > since)

    def record_auto_reply(self, address: str) -> None:
        def edit(current: Contact | None) -> Any:
            if current is None:
                return None, None
            now = self._now()
            current.auto_replies = [t for t in current.auto_replies if t > now - HOUR] + [now]
            return current, None

        self._change(address, edit)
