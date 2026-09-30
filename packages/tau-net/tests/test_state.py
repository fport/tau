"""The network store (both backends) and the contact state machine (§6.3, §6.7)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from tau_net.contacts import (
    ACCEPTED,
    BLOCKED,
    PENDING_IN,
    PENDING_OUT,
    ContactBook,
    ContactError,
    clean_name,
)
from tau_net.spine import SpineClient
from tau_net.store import LOG_LIMIT, SEEN_LIMIT, FileBackend, NetStore, SpineBackend
from tau_net.testing import DEFAULT_HUB_TOKEN, FakeSpine

K1 = ("S" * 43, "B" * 43)
K2 = ("T" * 43, "C" * 43)


def file_store(tmp_path: Path) -> NetStore:
    return NetStore(FileBackend(tmp_path / "net"))


def spine_store() -> tuple[NetStore, FakeSpine]:
    spine = FakeSpine("tau.example.com", mode="cloud")
    return NetStore(SpineBackend(SpineClient(spine.url, DEFAULT_HUB_TOKEN, transport=spine))), spine


# -- the store ---------------------------------------------------------------------------------


def test_file_store_documents_and_modes(tmp_path: Path) -> None:
    store = file_store(tmp_path)
    assert store.contacts() == {} and store.sessions() == {} and store.cursor() == 0
    store.update_contacts(lambda contacts: contacts.update({"a.example": {"address": "a.example"}}))
    store.set_session("a.example", "20260930-120000-abcd")
    store.mark_seen("a.example", "x" * 20)
    store.append_log({"ts": 1, "direction": "in", "address": "a.example", "id": "x" * 20})
    store.save_cursor(7)
    root = tmp_path / "net"
    names = sorted(p.name for p in root.iterdir())
    assert names == ["contacts.json", "cursor", "log.jsonl", "seen.json", "sessions.json"]
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in root.iterdir())
    assert (root / "cursor").read_text() == "7\n"
    assert json.loads((root / "log.jsonl").read_text().splitlines()[0])["id"] == "x" * 20
    again = file_store(tmp_path)  # nothing is cached: a second process sees everything
    assert again.cursor() == 7 and again.is_seen("a.example", "x" * 20)
    assert again.sessions() == {"a.example": "20260930-120000-abcd"}


def test_log_and_seen_are_capped_and_deduplicated(tmp_path: Path) -> None:
    store = file_store(tmp_path)
    for i in range(LOG_LIMIT + 20):
        store.append_log({"ts": i, "direction": "in", "address": "a.example", "id": f"id{i:017d}"})
    entries = store.log()
    assert len(entries) == LOG_LIMIT and entries[0]["ts"] == 20
    assert store.append_log(entries[-1]) is False  # handled again after a crash: not twice
    assert len(store.log(address="a.example", limit=3)) == 3
    assert store.log(address="b.example") == []
    for i in range(SEEN_LIMIT + 5):
        store.mark_seen("a.example", f"id{i:017d}")
    assert len(store.seen()) == SEEN_LIMIT and not store.is_seen("a.example", f"id{0:017d}")


def test_unreadable_files_are_ignored(tmp_path: Path) -> None:
    store = file_store(tmp_path)
    (tmp_path / "net").mkdir()
    (tmp_path / "net" / "contacts.json").write_text("{broken")
    (tmp_path / "net" / "cursor").write_text("seven")
    (tmp_path / "net" / "log.jsonl").write_text('{"id": "a"}\nnot json\n{"id": "b"}\n')
    assert store.contacts() == {} and store.cursor() == 0
    assert [e["id"] for e in store.log()] == ["a", "b"]


def test_spine_store_uses_net_keys() -> None:
    store, spine = spine_store()
    store.update_contacts(lambda contacts: contacts.update({"a.example": {"address": "a.example"}}))
    store.set_session("a.example", "s1")
    store.mark_seen("a.example", "x" * 20)
    store.append_log({"ts": 1, "direction": "in", "address": "a.example", "id": "x" * 20})
    store.save_cursor(3)
    assert sorted(spine.state) == [
        "net.contacts",
        "net.cursor",
        "net.log",
        "net.seen",
        "net.sessions",
    ]
    assert spine.state["net.cursor"]["value"] == 3
    assert store.cursor() == 3 and store.describe() == "spine (tau.example.com)"


def test_spine_log_stays_under_the_state_limit() -> None:
    store, spine = spine_store()
    for i in range(150):
        store.append_log(
            {"ts": i, "direction": "in", "address": "a", "id": f"{i}", "text": "x" * 8000}
        )
    assert len(json.dumps(spine.state["net.log"]["value"])) < 1024 * 1024
    assert store.log()[-1]["ts"] == 149


# -- the contact state machine -----------------------------------------------------------------


@pytest.fixture
def book(tmp_path: Path) -> ContactBook:
    return ContactBook(file_store(tmp_path), clock=lambda: 1_790_000_000)


def request(book: ContactBook, keys=K1, name: str = "Bob's tau", text: str = "Hi"):
    return book.on_request("bob.example", name=name, text=text, sign_key=keys[0], box_key=keys[1])


def test_request_from_a_stranger_is_pending_and_the_owner_is_told(book: ContactBook) -> None:
    transition = request(book, text="Bob wants to plan a hike.")
    assert transition.action == "notify"
    contact = book.get("bob.example")
    assert contact is not None and contact.state == PENDING_IN and not contact.pinned
    assert contact.note == "Bob wants to plan a hike." and contact.name == "Bob's tau"
    assert request(book, text="again").action == "none"  # still one pending request
    assert book.get("bob.example").note == "again"


def test_request_while_pending_out_accepts_and_answers(book: ContactBook) -> None:
    assert book.request("bob.example", name="Bob", sign_key=K1[0], box_key=K1[1]).action == (
        "send_request"
    )
    assert book.get("bob.example").state == PENDING_OUT
    transition = request(book)
    assert transition.action == "send_accept"
    contact = book.get("bob.example")
    assert contact.state == ACCEPTED and contact.pinned and contact.sign_key == K1[0]


def test_request_from_an_accepted_contact_is_answered_again(book: ContactBook) -> None:
    request(book)
    book.accept("bob.example")
    assert request(book).action == "send_accept"
    assert book.get("bob.example").state == ACCEPTED


def test_accept_while_pending_out_pins(book: ContactBook) -> None:
    book.request("bob.example", name="Bob", sign_key=K1[0], box_key=K1[1])
    transition = book.on_accept("bob.example", name="Bob's tau", sign_key=K1[0], box_key=K1[1])
    assert transition.action == "accepted"
    assert book.get("bob.example").pinned
    again = book.on_accept("bob.example", name="Bob's tau", sign_key=K1[0], box_key=K1[1])
    assert again.action == "none"


def test_messages_only_from_accepted_contacts(book: ContactBook) -> None:
    assert book.on_message("bob.example").action == "drop"
    request(book)
    assert book.on_message("bob.example").action == "drop"  # pending_in
    book.accept("bob.example")
    assert book.on_message("bob.example").action == "turn"


def test_blocked_and_strangers_are_dropped(book: ContactBook) -> None:
    assert book.on_accept("bob.example", name="x", sign_key=K1[0], box_key=K1[1]).action == "drop"
    assert book.get("bob.example") is None
    book.block("bob.example")
    assert request(book).action == "drop"
    assert book.on_message("bob.example").action == "drop"
    assert book.on_accept("bob.example", name="x", sign_key=K1[0], box_key=K1[1]).action == "drop"
    assert book.get("bob.example").state == BLOCKED


def test_owner_actions(book: ContactBook) -> None:
    with pytest.raises(ContactError, match="no contact request"):
        book.accept("bob.example")
    request(book)
    # add while they asked already: accept at once
    assert book.request("bob.example", name="Bob", sign_key=K1[0], box_key=K1[1]).action == (
        "send_accept"
    )
    with pytest.raises(ContactError, match="already a contact"):
        book.request("bob.example", name="Bob", sign_key=K1[0], box_key=K1[1])
    with pytest.raises(ContactError, match="already a contact"):
        book.accept("bob.example")
    book.block("bob.example")
    with pytest.raises(ContactError, match="blocked"):
        book.request("bob.example", name="Bob", sign_key=K1[0], box_key=K1[1])
    assert book.remove("bob.example") is True and book.remove("bob.example") is False
    assert book.counts() == {PENDING_IN: 0, PENDING_OUT: 0, ACCEPTED: 0, BLOCKED: 0}


def test_changed_keys_of_a_pending_contact_are_refused(book: ContactBook) -> None:
    request(book, keys=K1)
    assert not book.get("bob.example").keys_match(*K2)
    with pytest.raises(ContactError, match="keys"):
        book.request("bob.example", name="Bob", sign_key=K2[0], box_key=K2[1])


def test_auto_reply_counter(book: ContactBook) -> None:
    request(book)
    book.accept("bob.example")
    for _ in range(3):
        book.record_auto_reply("bob.example")
    assert book.auto_replies_last_hour("bob.example") == 3
    book.clock = lambda: 1_790_000_000 + 3601
    assert book.auto_replies_last_hour("bob.example") == 0


def test_clean_name() -> None:
    assert clean_name("  Bob's\n\ttau ‮ evil ") == "Bob's tau evil"
    assert clean_name("x" * 200) == "x" * 80
    assert clean_name(None) == ""
