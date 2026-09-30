"""``guard/audit.jsonl``: schema, rotation at 1 MiB with 3 files, modes 0700 and 0600."""

from __future__ import annotations

import json
import stat
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from tau_guard.audit import (
    AUDIT_FILE,
    EVENTS,
    KEEP,
    MAX_BYTES,
    OPTIONAL_KEYS,
    REQUIRED_KEYS,
    AuditLog,
)
from tau_guard.testing import FakeClock

SCHEMA = set(REQUIRED_KEYS) | set(OPTIONAL_KEYS)


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def assert_clean(entry: dict[str, Any]) -> None:
    """Only schema keys, and no value that could hold an embedding, a frame or a list."""
    assert set(entry) <= SCHEMA, set(entry) - SCHEMA
    assert set(REQUIRED_KEYS) <= set(entry)
    for key, value in entry.items():
        assert not isinstance(value, list | dict | bytes), (key, value)
        assert value is None or isinstance(value, str | int | float | bool), (key, value)
        if isinstance(value, str):
            assert len(value) <= 128


def test_records_follow_the_schema(tmp_path: Path, clock: FakeClock) -> None:
    audit = AuditLog(tmp_path / "guard", now=clock.wall)
    entry = audit.record(
        "step_up",
        channel="tui",
        client_id="c1",
        ok=False,
        reason="no_match",
        score=0.31234,
        liveness="challenge",
        duration_ms=1234,
        request_id="r1",
        tool="lamp",
    )
    assert entry == {
        "v": 1,
        "at": "2026-09-30T12:00:00+00:00",
        "event": "step_up",
        "channel": "tui",
        "client_id": "c1",
        "trigger": None,
        "ok": False,
        "reason": "no_match",
        "duration_ms": 1234,
        "score": 0.31,
        "liveness": "challenge",
        "request_id": "r1",
        "tool": "lamp",
    }
    lock = audit.record("lock", trigger="idle")
    assert set(lock) == set(REQUIRED_KEYS)  # optional keys only when set
    assert audit.read() == [entry, lock]
    for line in audit.path.read_text(encoding="utf-8").splitlines():
        assert_clean(json.loads(line))


def test_unknown_events_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        AuditLog(tmp_path).record("peek")


def test_values_are_coerced_so_nothing_else_slips_in(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path)
    entry = audit.record(
        "verify",
        channel="x" * 500,
        reason=[0.1, 0.2, 0.3],  # type: ignore[arg-type]
        ok="yes",  # type: ignore[arg-type]
        score=True,  # type: ignore[arg-type]
        duration_ms="12",  # type: ignore[arg-type]
    )
    assert_clean(entry)
    assert entry["ok"] is None and entry["duration_ms"] is None and "score" not in entry
    assert entry["reason"] is None
    assert len(entry["channel"]) == 128


def test_directory_is_0700_and_files_0600(tmp_path: Path) -> None:
    directory = tmp_path / "guard"
    directory.mkdir(mode=0o755)
    directory.chmod(0o755)
    audit = AuditLog(directory)
    audit.path.write_text("")
    audit.path.chmod(0o644)
    audit.record("lock", trigger="startup")
    assert mode(directory) == 0o700 and mode(audit.path) == 0o600


def test_rotation_keeps_three_files_of_at_most_one_mib(tmp_path: Path, clock: FakeClock) -> None:
    audit = AuditLog(tmp_path, now=clock.wall)
    written = 0
    while written < 4 * MAX_BYTES:
        entry = audit.record("verify", channel="tui", client_id="c" * 100, reason="no_match")
        written += len(json.dumps(entry)) + 1
        clock.advance(1)
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == [AUDIT_FILE, f"{AUDIT_FILE}.1", f"{AUDIT_FILE}.2"] and KEEP == 3
    for path in tmp_path.iterdir():
        assert path.stat().st_size <= MAX_BYTES
        assert mode(path) == 0o600
    entries = audit.read()
    stamps = [e["at"] for e in entries]
    assert stamps == sorted(stamps)  # oldest first across the files
    for entry in entries[:50]:
        assert_clean(entry)


def test_read_since(tmp_path: Path, clock: FakeClock) -> None:
    audit = AuditLog(tmp_path, now=clock.wall)
    audit.record("lock", trigger="startup")
    clock.advance(3600)
    audit.record("lock", trigger="command")
    later = audit.read(since=clock.wall() - timedelta(minutes=30))
    assert [e["trigger"] for e in later] == ["command"]
    (tmp_path / AUDIT_FILE).open("a").write("not json\n[1, 2]\n")
    assert len(audit.read()) == 2  # unreadable lines are skipped


def test_the_event_list_matches_the_adr() -> None:
    assert EVENTS == (
        "verify",
        "step_up",
        "recheck",
        "lock",
        "unlock",
        "enroll",
        "forget",
        "cooldown",
        "camera_open",
        "touch_id",
    )


def test_labels_never_carry_control_characters(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "guard")
    forged = "tui\x1b]0;owned\x07\r30.09.2026 12:00:00  unlocked  ok‮"
    entry = log.record("step_up", channel=forged, client_id="c\x00", tool="lamp\x1b[2K\x9b")
    for value in (entry["channel"], entry["client_id"], entry["tool"]):
        assert value.isprintable() and "\x1b" not in value and "\r" not in value
    assert entry["channel"].startswith("tui?]0;owned?")
    assert log.read()[-1]["tool"] == "lamp?[2K?"
    assert log.record("verify", channel="Zoë's café")["channel"] == "Zoë's café"  # letters stay
