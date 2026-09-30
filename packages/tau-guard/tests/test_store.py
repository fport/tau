"""The template store: format, AAD, modes, tampering, model changes, keys, forget. Only the
in-memory key store and a fake keyring backend are used; the real Keychain is never touched."""

from __future__ import annotations

import json
import os
import shutil
import stat
import threading
import time
from pathlib import Path

import pytest
from tau_core.guard import read_enrollment
from tau_core.testing import test_config
from tau_guard.engine import SFACE_SHA256
from tau_guard.liveness import Calibration
from tau_guard.store import (
    KEY_ACCOUNT,
    KEY_SERVICE,
    MAGIC,
    MARKER_FILE,
    TEMPLATE_FILE,
    KeychainKeyStore,
    KeyInvalid,
    KeyStore,
    KeyUnavailable,
    MemoryKeyStore,
    StoreError,
    decrypt,
    first_enrollment,
    forget,
    load_template,
    macos_keyring,
    new_key,
    read_marker,
    save_enrollment,
    template_from,
)
from tau_guard.testing import OWNER, variant

CALIBRATION = Calibration(sign=1, left=0.42, right=0.38)
OTHER_SHA = "f" * 64


def make_template(enrollment: str = "e1") -> object:
    samples = [variant(OWNER, seed) for seed in range(12)]
    return template_from(
        samples,
        enrollment=enrollment,
        created="2026-09-30T12:00:00+00:00",
        model_sha=SFACE_SHA256,
        calibration=CALIBRATION,
    )


def enrolled(tmp_path: Path) -> tuple[Path, MemoryKeyStore, object]:
    guard = tmp_path / "data" / "guard"
    keys = MemoryKeyStore(new_key())
    template = make_template()
    save_enrollment(guard, template, keys.key)
    return guard, keys, template


def test_round_trip(tmp_path: Path) -> None:
    guard, keys, template = enrolled(tmp_path)
    loaded = load_template(guard, keys, SFACE_SHA256)
    assert loaded.enrollment == "e1" and loaded.calibration == CALIBRATION
    assert len(loaded.samples) == 12 and len(loaded.vector) == 128
    assert max(abs(a - b) for a, b in zip(loaded.vector, template.vector, strict=True)) < 1e-6


def test_the_file_format_and_modes(tmp_path: Path) -> None:
    guard, keys, _ = enrolled(tmp_path)
    blob = (guard / TEMPLATE_FILE).read_bytes()
    assert blob.startswith(MAGIC) and blob[:5] == b"TAUG1"
    assert stat.S_IMODE(os.stat(guard).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(guard / TEMPLATE_FILE).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(guard / MARKER_FILE).st_mode) == 0o600
    assert not list(guard.glob(".*tmp"))  # atomic: no temp file left behind
    payload = json.loads(decrypt(blob, keys.key, SFACE_SHA256))
    assert set(payload) == {
        "v",
        "enrollment",
        "created",
        "model",
        "dim",
        "template",
        "samples",
        "calibration",
    }
    assert payload["model"] == {"name": "sface-2021dec", "sha256": SFACE_SHA256}
    assert payload["dim"] == 128


def test_an_existing_loose_directory_is_tightened(tmp_path: Path) -> None:
    guard = tmp_path / "data" / "guard"
    guard.mkdir(parents=True, mode=0o755)
    os.chmod(guard, 0o755)
    save_enrollment(guard, make_template(), new_key())
    assert stat.S_IMODE(os.stat(guard).st_mode) == 0o700


def test_the_marker_is_what_tau_core_reads(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    save_enrollment(config.data_dir / "guard", make_template("abc123"), new_key())
    marker = read_marker(config.data_dir / "guard")
    assert marker == {
        "v": 1,
        "enrollment": "abc123",
        "model": SFACE_SHA256,
        "created": "2026-09-30T12:00:00+00:00",
    }
    assert read_enrollment(config) == "abc123"


def test_the_template_decrypts_only_with_its_key_and_model(tmp_path: Path) -> None:
    guard, keys, _ = enrolled(tmp_path)
    blob = (guard / TEMPLATE_FILE).read_bytes()
    with pytest.raises(StoreError) as wrong_key:
        decrypt(blob, new_key(), SFACE_SHA256)
    assert wrong_key.value.reason == "template_invalid"
    with pytest.raises(StoreError) as wrong_model:
        decrypt(blob, keys.key, OTHER_SHA)  # the AAD binds the model sha
    assert wrong_model.value.reason == "template_invalid"


def test_a_copy_of_guard_without_the_key_cannot_be_decrypted(tmp_path: Path) -> None:
    guard, keys, _ = enrolled(tmp_path)
    copy = tmp_path / "backup" / "guard"
    shutil.copytree(guard, copy)
    for store, reason in (
        (MemoryKeyStore(), "key_unavailable"),
        (MemoryKeyStore(new_key()), "template_invalid"),
    ):
        with pytest.raises(StoreError) as caught:
            load_template(copy, store, SFACE_SHA256)
        assert caught.value.reason == reason
    assert load_template(copy, keys, SFACE_SHA256).enrollment == "e1"


def test_tampering_is_template_invalid(tmp_path: Path) -> None:
    guard, keys, _ = enrolled(tmp_path)
    path = guard / TEMPLATE_FILE
    blob = bytearray(path.read_bytes())
    blob[40] ^= 0x01
    path.write_bytes(bytes(blob))
    with pytest.raises(StoreError) as caught:
        load_template(guard, keys, SFACE_SHA256)
    assert caught.value.reason == "template_invalid"
    path.write_bytes(b"TAUG0" + bytes(blob[5:]))
    with pytest.raises(StoreError):
        load_template(guard, keys, SFACE_SHA256)


def test_a_model_change_is_model_changed(tmp_path: Path) -> None:
    guard, keys, _ = enrolled(tmp_path)
    with pytest.raises(StoreError) as caught:
        load_template(guard, keys, OTHER_SHA)
    assert caught.value.reason == "model_changed"
    assert keys.reads == 0  # decided from the public marker, before the Keychain


def test_missing_pieces(tmp_path: Path) -> None:
    guard, keys, _ = enrolled(tmp_path)
    (guard / TEMPLATE_FILE).unlink()
    with pytest.raises(StoreError) as caught:
        load_template(guard, keys, SFACE_SHA256)
    assert caught.value.reason == "not_enrolled"
    guard2, keys2, _ = enrolled(tmp_path / "b")
    with pytest.raises(StoreError) as failing:
        load_template(guard2, MemoryKeyStore(fail=True), SFACE_SHA256)
    assert failing.value.reason == "key_unavailable"


def test_the_template_is_read_again_every_time(tmp_path: Path) -> None:
    guard, keys, _ = enrolled(tmp_path)
    assert load_template(guard, keys, SFACE_SHA256).enrollment == "e1"
    save_enrollment(guard, make_template("e2"), keys.key)
    assert load_template(guard, keys, SFACE_SHA256).enrollment == "e2"
    forget(guard, keys)
    with pytest.raises(StoreError) as caught:
        load_template(guard, keys, SFACE_SHA256)
    assert caught.value.reason == "not_enrolled"


def test_forget_removes_template_marker_and_key(tmp_path: Path) -> None:
    guard, keys, _ = enrolled(tmp_path)
    removed = forget(guard, keys)
    assert set(removed) == {TEMPLATE_FILE, MARKER_FILE, "key"}
    assert not (guard / TEMPLATE_FILE).exists() and not (guard / MARKER_FILE).exists()
    assert keys.key is None
    assert forget(guard, keys) == []
    with pytest.raises(StoreError):
        forget(guard, MemoryKeyStore(fail=True))


def test_first_enrollment_is_decided_from_the_key_store(tmp_path: Path) -> None:
    guard, keys, _ = enrolled(tmp_path)
    assert first_enrollment(keys) is False
    (guard / TEMPLATE_FILE).unlink()  # deleting the file does not make the next one first
    (guard / MARKER_FILE).unlink()
    assert first_enrollment(keys) is False
    assert first_enrollment(MemoryKeyStore()) is True
    with pytest.raises(StoreError) as caught:
        first_enrollment(MemoryKeyStore(fail=True))
    assert caught.value.reason == "key_unavailable"


def test_nothing_in_guard_holds_an_embedding(tmp_path: Path) -> None:
    guard, _, template = enrolled(tmp_path)
    needles = [f"{value:.5f}"[2:] for value in template.vector[:8]]
    needles += [f"{value:.5f}"[2:] for value in template.samples[0][:8]]
    for path in guard.rglob("*"):
        if path.is_file():
            text = path.read_bytes().decode("latin-1")
            for needle in needles:
                assert needle not in text, (path.name, needle)


class FakeKeyring:
    def __init__(self, delay: float = 0.0) -> None:
        self.items: dict[tuple[str, str], str] = {}
        self.delay = delay

    def get_password(self, service: str, account: str) -> str | None:
        time.sleep(self.delay)
        return self.items.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.items[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        del self.items[(service, account)]


def test_the_keychain_store_through_keyring() -> None:
    backend = FakeKeyring()
    store = KeychainKeyStore(backend=backend)
    assert isinstance(store, KeyStore)
    assert store.get() is None and store.delete() is False
    key = new_key()
    store.set(key)
    assert (KEY_SERVICE, KEY_ACCOUNT) in backend.items
    assert store.get() == key
    assert store.delete() is True and store.get() is None
    backend.items[(KEY_SERVICE, KEY_ACCOUNT)] = "not a key"
    with pytest.raises(KeyInvalid):
        store.get()


def test_a_keychain_item_that_is_not_a_key_can_still_be_forgotten(tmp_path: Path) -> None:
    backend = FakeKeyring()
    store = KeychainKeyStore(backend=backend)
    for junk in ("not a key", "c2hvcnQ="):  # not base64; base64 but 5 bytes
        backend.items[(KEY_SERVICE, KEY_ACCOUNT)] = junk
        with pytest.raises(KeyInvalid):
            store.get()
        with pytest.raises(StoreError) as caught:
            first_enrollment(store)  # an enrollment refuses it (key_unavailable) ...
        assert caught.value.reason == "key_unavailable"
        assert forget(tmp_path / "guard", store) == ["key"]  # ... and forget removes it
        assert backend.items == {}


def test_the_store_pins_the_macos_keychain_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """``PYTHON_KEYRING_BACKEND`` (a null or plaintext backend) never decides where the key
    goes: off macOS the store refuses instead of falling back to another backend. Nothing here
    reads or writes a real Keychain item."""
    import platform

    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")
    try:
        from keyring.backends import macOS
    except ImportError:  # keyring is a macOS-only dependency
        macOS = None  # noqa: N806
    if macOS is not None and platform.system() == "Darwin":
        backend = macos_keyring()  # built, never called
        assert type(backend) is macOS.Keyring and backend.keychain is None
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    with pytest.raises(KeyUnavailable):
        macos_keyring()
    with pytest.raises(KeyUnavailable):
        KeychainKeyStore().get()


def test_the_keychain_read_has_a_timeout() -> None:
    store = KeychainKeyStore(backend=FakeKeyring(delay=2.0), timeout=0.1)
    started = time.monotonic()
    with pytest.raises(KeyUnavailable):
        store.get()
    assert time.monotonic() - started < 1.5
    assert not [t for t in threading.enumerate() if t.name == "tau-guard-keychain" and not t.daemon]


def test_a_failing_keyring_is_key_unavailable() -> None:
    class Broken:
        def get_password(self, service: str, account: str) -> str:
            raise RuntimeError("locked keychain")

    with pytest.raises(KeyUnavailable):
        KeychainKeyStore(backend=Broken()).get()
