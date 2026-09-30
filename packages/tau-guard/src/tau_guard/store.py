"""The face template on disk (ADR 0008 decision 14): encrypted, keyed from the Keychain.

Layout of ``TAU_DATA_DIR/guard/`` (0700, chmod explicitly):

- ``owner.face.v1.bin`` (0600, written atomically): ``b"TAUG1" | nonce(12) |
  AESGCM(key).encrypt(nonce, payload, aad=b"tau-guard/v1|" + model_sha)``, where ``model_sha``
  is the recognizer's sha256 as lowercase hex (ASCII) and ``payload`` is JSON ``{v,
  enrollment, created, model: {name, sha256}, dim, template, samples, calibration,
  touch_id?}``. The template is the renormalised mean of the samples; the calibration is the
  head-turn sign and amplitudes (:class:`tau_guard.liveness.Calibration`); ``touch_id`` is
  ``{"domain_state": "<sha256>"}``, the Touch ID fingerprint set pinned at enrollment (issue
  114, :mod:`tau_guard.localauth`), absent on a Mac without Touch ID.
- ``enrolled`` (0600): the public marker ``{"v": 1, "enrollment", "model", "created"}`` that
  tau-core's ``resolve_guard`` and ``read_enrollment`` read. It holds no biometric data.

The key (256 bits, base64) lives in the macOS Keychain through ``keyring`` (service
``tau-guard``, account ``template-key-v1``) and is read only inside the worker, with a timeout
(:class:`KeychainKeyStore`); a timeout or a failure is ``key_unavailable``. A copy of the data
dir or a backup therefore cannot decrypt the template. The store always builds keyring's macOS
Keychain backend itself (:func:`macos_keyring`), never the default backend that
``PYTHON_KEYRING_BACKEND``, a ``keyringrc.cfg`` or an installed plugin (a null or a plaintext
file backend) would pick; the hub drops that variable from the worker's environment too. A
first enrollment reads the new key back before it writes anything, so a key store that drops
writes fails the enrollment (``key_unavailable``) instead of leaving a template nobody can
decrypt. Tests use :class:`MemoryKeyStore`, and no test touches the real Keychain.

The key timeout is :data:`KEY_TIMEOUT` (5 s) for a check and :data:`KEY_TIMEOUT_AT_MAC` (30 s)
for an enrollment or ``forget``, where the owner is at the Mac and may have to allow access in
macOS's Keychain prompt (it appears after a Python upgrade changed the interpreter). A Keychain
item that is not a 32-byte base64 key is :class:`KeyInvalid` (``key_unavailable``); ``forget``
still removes it.

:func:`load_template` reads the file again for every verification, so ``tau guard forget``
takes effect at once. It raises :class:`StoreError` with ``not_enrolled`` (no template),
``model_changed`` (the marker or the payload names another recognizer), ``key_unavailable``
(no key, a Keychain failure or timeout) or ``template_invalid`` (anything that does not
decrypt or does not parse, and a template whose enrollment id is not the marker's: a
re-enrollment keeps the key, so an older template file put back must not match again).
Whether an enrollment is the first one is decided from the Keychain item
(:func:`first_enrollment`), never from the template file, so deleting the file does not turn
the next enrollment into a first one. :func:`read_pin` reads the pinned fingerprint set with the
marker's model, so a model change does not lose it.
"""

from __future__ import annotations

import base64
import json
import math
import os
import re
import secrets
import tempfile
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from tau_guard.engine import EMBEDDING_DIM, SFACE_NAME
from tau_guard.liveness import Calibration

__all__ = [
    "KEY_ACCOUNT",
    "KEY_SERVICE",
    "MAGIC",
    "MARKER_FILE",
    "TEMPLATE_FILE",
    "KEY_TIMEOUT",
    "KEY_TIMEOUT_AT_MAC",
    "KeyInvalid",
    "KeyStore",
    "KeyUnavailable",
    "KeychainKeyStore",
    "MemoryKeyStore",
    "StoreError",
    "Template",
    "decrypt",
    "encrypt",
    "first_enrollment",
    "forget",
    "load_template",
    "macos_keyring",
    "new_key",
    "read_marker",
    "read_pin",
    "save_enrollment",
    "secure_dir",
    "template_from",
]

TEMPLATE_FILE = "owner.face.v1.bin"
MARKER_FILE = "enrolled"
MAGIC = b"TAUG1"
AAD_PREFIX = b"tau-guard/v1|"
NONCE_BYTES = 12
KEY_BYTES = 32
KEY_SERVICE = "tau-guard"
KEY_ACCOUNT = "template-key-v1"
KEY_TIMEOUT = 5.0
KEY_TIMEOUT_AT_MAC = 30.0
MAX_TEMPLATE_BYTES = 1024 * 1024
MAX_SAMPLES = 64
VERSION = 1
STORE_REASONS = ("not_enrolled", "template_invalid", "model_changed", "key_unavailable")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class StoreError(Exception):
    """The template cannot be used; ``reason`` is one of :data:`STORE_REASONS`. ``removed``
    lists what :func:`forget` removed before it failed."""

    def __init__(self, reason: str, detail: str = "", *, removed: list[str] | None = None) -> None:
        self.reason = reason
        self.removed = list(removed or [])
        super().__init__(f"{reason}: {detail}" if detail else reason)


class KeyUnavailable(Exception):
    """The key store failed or did not answer in time."""


class KeyInvalid(KeyUnavailable):
    """The key store holds something under the key's name that is not a key."""


def secure_dir(path: Path) -> Path:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


# -- keys ------------------------------------------------------------------------------------------


@runtime_checkable
class KeyStore(Protocol):
    def get(self) -> bytes | None:
        """The key, ``None`` when there is none; raises :class:`KeyUnavailable`."""
        ...

    def set(self, key: bytes) -> None:
        """Store ``key``; raises :class:`KeyUnavailable`."""
        ...

    def delete(self) -> bool:
        """Remove the key; ``True`` when one was removed. Raises :class:`KeyUnavailable`."""
        ...


def new_key() -> bytes:
    return secrets.token_bytes(KEY_BYTES)


class MemoryKeyStore:
    """An in-memory :class:`KeyStore` (tests). ``fail=True`` makes every call raise."""

    def __init__(self, key: bytes | None = None, *, fail: bool = False) -> None:
        self.key = key
        self.fail = fail
        self.reads = 0

    def get(self) -> bytes | None:
        self.reads += 1
        if self.fail:
            raise KeyUnavailable("the key store is failing")
        return self.key

    def set(self, key: bytes) -> None:
        if self.fail:
            raise KeyUnavailable("the key store is failing")
        self.key = bytes(key)

    def delete(self) -> bool:
        if self.fail:
            raise KeyUnavailable("the key store is failing")
        existed, self.key = self.key is not None, None
        return existed


def macos_keyring() -> Any:
    """keyring's macOS Keychain backend, built explicitly: never the backend that
    ``PYTHON_KEYRING_BACKEND``, a ``keyringrc.cfg`` or an installed plugin would choose. Raises
    :class:`KeyUnavailable` when it cannot be loaded or is not usable (not macOS, no Security
    framework)."""
    try:
        from keyring.backends import macOS  # type: ignore[import-not-found]
    except Exception as exc:
        name = type(exc).__name__
        raise KeyUnavailable(f"the macOS Keychain backend cannot be loaded: {name}") from exc
    if not macOS.Keyring.viable:
        raise KeyUnavailable("the macOS Keychain backend is not usable here")
    backend = macOS.Keyring()
    backend.keychain = None  # the login keychain, never a KEYCHAIN_PATH or property override
    return backend


class KeychainKeyStore:
    """The key in the macOS Keychain through ``keyring`` (service ``tau-guard``, account
    ``template-key-v1``). Every call runs in a daemon thread and gives up after ``timeout``
    seconds (a Keychain prompt nobody answers must not hang the worker). ``backend`` is a
    keyring backend (tests pass a fake); by default :func:`macos_keyring`, built lazily."""

    def __init__(self, *, timeout: float = KEY_TIMEOUT, backend: Any | None = None) -> None:
        self.timeout = timeout
        self._backend = backend

    def _keyring(self) -> Any:
        if self._backend is None:
            self._backend = macos_keyring()
        return self._backend

    def _call(self, name: str, *args: Any) -> Any:
        box: dict[str, Any] = {}
        done = threading.Event()

        def run() -> None:
            try:
                box["value"] = getattr(self._keyring(), name)(*args)
            except BaseException as exc:  # handed to the caller below
                box["error"] = exc
            done.set()

        threading.Thread(target=run, name="tau-guard-keychain", daemon=True).start()
        if not done.wait(self.timeout):
            raise KeyUnavailable(f"the Keychain did not answer within {self.timeout:g} s")
        if "error" in box:
            error = box["error"]
            if isinstance(error, KeyUnavailable):
                raise error
            raise KeyUnavailable(f"the Keychain failed: {type(error).__name__}")
        return box.get("value")

    def get(self) -> bytes | None:
        value = self._call("get_password", KEY_SERVICE, KEY_ACCOUNT)
        if value is None:
            return None
        try:
            key = base64.b64decode(str(value), validate=True)
        except ValueError as exc:
            raise KeyInvalid("the Keychain item is not a key") from exc
        if len(key) != KEY_BYTES:
            raise KeyInvalid("the Keychain item is not a key")
        return key

    def set(self, key: bytes) -> None:
        self._call("set_password", KEY_SERVICE, KEY_ACCOUNT, base64.b64encode(key).decode())

    def delete(self) -> bool:
        """Remove the item, whether or not it holds a valid key."""
        if self._call("get_password", KEY_SERVICE, KEY_ACCOUNT) is None:
            return False
        self._call("delete_password", KEY_SERVICE, KEY_ACCOUNT)
        return True


def first_enrollment(keys: KeyStore) -> bool:
    """Whether the next enrollment is the first one: there is no key in the key store. A key
    store that fails raises :class:`StoreError` (``key_unavailable``); it never counts as
    "no key"."""
    try:
        return keys.get() is None
    except KeyUnavailable as exc:
        raise StoreError("key_unavailable", str(exc)) from exc


# -- the template ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Template:
    enrollment: str
    created: str
    model_sha256: str
    vector: tuple[float, ...]
    samples: tuple[tuple[float, ...], ...]
    calibration: Calibration
    model_name: str = SFACE_NAME
    domain_state: str | None = None
    """The Touch ID fingerprint set pinned at enrollment (a sha256), ``None`` without one."""

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "v": VERSION,
            "enrollment": self.enrollment,
            "created": self.created,
            "model": {"name": self.model_name, "sha256": self.model_sha256},
            "dim": len(self.vector),
            "template": [round(value, 7) for value in self.vector],
            "samples": [[round(value, 7) for value in sample] for sample in self.samples],
            "calibration": self.calibration.to_json(),
        }
        if self.domain_state is not None:
            payload["touch_id"] = {"domain_state": self.domain_state}
        return payload


def _aad(model_sha: str) -> bytes:
    return AAD_PREFIX + model_sha.encode("ascii")


def encrypt(payload: bytes, key: bytes, model_sha: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = secrets.token_bytes(NONCE_BYTES)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, payload, _aad(model_sha))


def decrypt(blob: bytes, key: bytes, model_sha: str) -> bytes:
    """The payload; raises :class:`StoreError` (``template_invalid``) for a wrong header, a
    wrong key, a wrong model sha or any tampering."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + NONCE_BYTES + 16:
        raise StoreError("template_invalid", "not a tau-guard template")
    nonce = blob[len(MAGIC) : len(MAGIC) + NONCE_BYTES]
    try:
        return AESGCM(key).decrypt(nonce, blob[len(MAGIC) + NONCE_BYTES :], _aad(model_sha))
    except (InvalidTag, ValueError) as exc:
        raise StoreError("template_invalid", "the template does not decrypt") from exc


def _write_atomic(path: Path, data: bytes) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def save_enrollment(guard_dir: Path, template: Template, key: bytes) -> None:
    """Write the encrypted template, then the public marker (both 0600, atomically) in the
    0700 ``guard_dir``."""
    secure_dir(guard_dir)
    payload = json.dumps(template.payload(), separators=(",", ":")).encode("utf-8")
    _write_atomic(guard_dir / TEMPLATE_FILE, encrypt(payload, key, template.model_sha256))
    marker = {
        "v": VERSION,
        "enrollment": template.enrollment,
        "model": template.model_sha256,
        "created": template.created,
    }
    _write_atomic(guard_dir / MARKER_FILE, json.dumps(marker).encode("utf-8"))


def read_marker(guard_dir: Path) -> dict[str, Any] | None:
    """The marker as a dict, ``None`` without a readable one."""
    try:
        raw = json.loads((guard_dir / MARKER_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def load_template(guard_dir: Path, keys: KeyStore, model_sha: str) -> Template:
    """Read and decrypt the template for the recognizer ``model_sha``; raises
    :class:`StoreError`."""
    path = guard_dir / TEMPLATE_FILE
    marker = read_marker(guard_dir)
    if not path.is_file() or marker is None:
        raise StoreError("not_enrolled", "no template")
    if marker.get("model") != model_sha:
        raise StoreError("model_changed", "the enrollment was made with another model")
    try:
        key = keys.get()
    except KeyUnavailable as exc:
        raise StoreError("key_unavailable", str(exc)) from exc
    if key is None:
        raise StoreError("key_unavailable", "the Keychain has no template key")
    try:
        with path.open("rb") as handle:
            blob = handle.read(MAX_TEMPLATE_BYTES + 1)
    except OSError as exc:
        raise StoreError("not_enrolled", f"the template cannot be read ({exc})") from exc
    if len(blob) > MAX_TEMPLATE_BYTES:
        raise StoreError("template_invalid", "the template is too large")
    payload = decrypt(blob, key, model_sha)
    try:
        template = _parse(json.loads(payload.decode("utf-8")), model_sha)
    except StoreError:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        raise StoreError("template_invalid", "the template does not parse") from exc
    if template.enrollment != marker.get("enrollment"):  # an older file put back in place
        raise StoreError("template_invalid", "the template belongs to another enrollment")
    return template


def _vector(value: Any) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != EMBEDDING_DIM:
        raise ValueError("a vector has 128 numbers")
    numbers = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float) or not math.isfinite(item):
            raise ValueError("a vector holds finite numbers")
        numbers.append(float(item))
    return tuple(numbers)


def _parse(data: Any, model_sha: str) -> Template:
    if not isinstance(data, dict) or data.get("v") != VERSION:
        raise ValueError("unknown template version")
    model = data.get("model")
    if not isinstance(model, dict) or model.get("sha256") != model_sha:
        raise StoreError("model_changed", "the template was made with another model")
    if data.get("dim") != EMBEDDING_DIM:
        raise ValueError("unexpected dimension")
    samples = data.get("samples")
    if not isinstance(samples, list) or not samples or len(samples) > MAX_SAMPLES:
        raise ValueError("bad samples")
    calibration = Calibration.from_json(data.get("calibration"))
    if calibration is None:
        raise ValueError("bad calibration")
    enrollment, created = data.get("enrollment"), data.get("created")
    if not isinstance(enrollment, str) or not isinstance(created, str):
        raise ValueError("bad enrollment id")
    return Template(
        enrollment=enrollment,
        created=created,
        model_sha256=model_sha,
        vector=_vector(data.get("template")),
        samples=tuple(_vector(sample) for sample in samples),
        calibration=calibration,
        model_name=str(model.get("name") or SFACE_NAME),
        domain_state=_pin(data.get("touch_id")),
    )


def _pin(value: Any) -> str | None:
    """The ``touch_id`` field of a payload: absent, or ``{"domain_state": "<sha256>"}``."""
    if value is None:
        return None
    state = value.get("domain_state") if isinstance(value, dict) else None
    if not isinstance(state, str) or not _SHA256.fullmatch(state):
        raise ValueError("bad touch_id pin")
    return state


def read_pin(guard_dir: Path, keys: KeyStore) -> str | None:
    """The pinned Touch ID fingerprint set, read with the model the marker names (so it
    survives a model change); ``None`` when the enrollment pinned none. Raises
    :class:`StoreError` like :func:`load_template`."""
    marker = read_marker(guard_dir)
    model = marker.get("model") if marker is not None else None
    if not isinstance(model, str) or not _SHA256.fullmatch(model):
        raise StoreError("not_enrolled", "no readable marker")
    return load_template(guard_dir, keys, model).domain_state


def forget(guard_dir: Path, keys: KeyStore) -> list[str]:
    """Remove the template (with its samples), the marker and the key; returns what was
    removed. The key goes last, so a failing Keychain leaves nothing readable behind; the
    :class:`StoreError` it then raises (``key_unavailable``) carries what was removed."""
    removed: list[str] = []
    for name in (TEMPLATE_FILE, MARKER_FILE):
        path = guard_dir / name
        if path.exists():
            path.unlink()
            removed.append(name)
    for leftover in guard_dir.glob(f".{TEMPLATE_FILE}.*.tmp") if guard_dir.is_dir() else []:
        leftover.unlink(missing_ok=True)
    try:
        if keys.delete():
            removed.append("key")
    except KeyUnavailable as exc:
        raise StoreError("key_unavailable", str(exc), removed=removed) from exc
    return removed


def template_from(
    samples: Sequence[Sequence[float]],
    *,
    enrollment: str,
    created: str,
    model_sha: str,
    calibration: Calibration,
    domain_state: str | None = None,
) -> Template:
    """A :class:`Template` from unit samples (the vector is their renormalised mean)."""
    from tau_guard.engine import mean_vector, normalise

    units = tuple(normalise(sample) for sample in samples)
    return Template(
        enrollment=enrollment,
        created=created,
        model_sha256=model_sha,
        vector=mean_vector(units),
        samples=units,
        calibration=calibration,
        domain_state=domain_state,
    )
