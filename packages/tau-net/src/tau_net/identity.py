"""A tau's identity: an Ed25519 signing key and an X25519 box key (protocol v1, §2).

The identity lives in ``TAU_DATA_DIR/net/identity.json`` (mode 0600, directory 0700) as
``{"v": 1, "sign_seed": b64u, "box_seed": b64u}``. :func:`create_identity` never overwrites
an existing file. ``TAU_NET_IDENTITY`` (the same JSON, base64url-encoded) replaces the file when
it is set; cloud mode hands the identity to the container this way.

The seeds never reach a repr, a log line or an exception message.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from tau_net.encoding import EncodingError, b64u_decode, b64u_encode

__all__ = [
    "IDENTITY_ENV",
    "IDENTITY_FILE",
    "Identity",
    "IdentityError",
    "IdentityExists",
    "create_identity",
    "identity_path",
    "load_identity",
    "load_or_none",
]

IDENTITY_ENV = "TAU_NET_IDENTITY"
IDENTITY_FILE = "identity.json"
SEED_BYTES = 32


class IdentityError(Exception):
    """An identity that cannot be read or is malformed; the message names where it came from."""


class IdentityExists(IdentityError):
    """``create_identity`` found an identity file and kept it."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"an identity already exists at {path}; it was kept")


@dataclass(frozen=True)
class Identity:
    """The two key pairs of a tau, built from their 32-byte seeds."""

    sign_seed: bytes = field(repr=False)
    box_seed: bytes = field(repr=False)
    source: str = "memory"
    """Where it came from: ``file:<path>``, ``env`` or ``memory``."""

    def __post_init__(self) -> None:
        for name in ("sign_seed", "box_seed"):
            value = getattr(self, name)
            if not isinstance(value, bytes) or len(value) != SEED_BYTES:
                raise IdentityError(f"{name} must be {SEED_BYTES} bytes")

    @classmethod
    def generate(cls) -> Identity:
        return cls(secrets.token_bytes(SEED_BYTES), secrets.token_bytes(SEED_BYTES))

    @classmethod
    def from_json(cls, data: Any, *, source: str = "memory") -> Identity:
        """From ``{"v": 1, "sign_seed", "box_seed"}``; :class:`IdentityError` otherwise."""
        if not isinstance(data, dict) or data.get("v") != 1:
            raise IdentityError(f"identity from {source} is not a v1 identity")
        try:
            sign_seed = b64u_decode(data.get("sign_seed"))
            box_seed = b64u_decode(data.get("box_seed"))
        except EncodingError:
            raise IdentityError(
                f"identity from {source} has seeds that are not base64url"
            ) from None
        if len(sign_seed) != SEED_BYTES or len(box_seed) != SEED_BYTES:
            raise IdentityError(f"identity from {source} has seeds that are not 32 bytes")
        return cls(sign_seed, box_seed, source=source)

    @classmethod
    def from_env_value(cls, value: str) -> Identity:
        """From the ``TAU_NET_IDENTITY`` form: the identity JSON, base64url-encoded."""
        try:
            data = json.loads(b64u_decode(value.strip()).decode("utf-8"))
        except (EncodingError, UnicodeDecodeError, ValueError):
            raise IdentityError(f"{IDENTITY_ENV} is not base64url-encoded identity JSON") from None
        return cls.from_json(data, source="env")

    def to_json(self) -> dict[str, Any]:
        return {
            "v": 1,
            "sign_seed": b64u_encode(self.sign_seed),
            "box_seed": b64u_encode(self.box_seed),
        }

    def to_env_value(self) -> str:
        """The value for ``TAU_NET_IDENTITY`` (cloud mode)."""
        return b64u_encode(json.dumps(self.to_json(), separators=(",", ":")).encode("utf-8"))

    # -- keys ----------------------------------------------------------------------------------

    @cached_property
    def signing_key(self) -> Ed25519PrivateKey:
        return Ed25519PrivateKey.from_private_bytes(self.sign_seed)

    @cached_property
    def box_private_key(self) -> X25519PrivateKey:
        return X25519PrivateKey.from_private_bytes(self.box_seed)

    @cached_property
    def sign_key_bytes(self) -> bytes:
        return self.signing_key.public_key().public_bytes_raw()

    @cached_property
    def box_key_bytes(self) -> bytes:
        return self.box_private_key.public_key().public_bytes_raw()

    @property
    def sign_key(self) -> str:
        """The public signing key as published on the card (b64u)."""
        return b64u_encode(self.sign_key_bytes)

    @property
    def box_key(self) -> str:
        """The public box key as published on the card (b64u)."""
        return b64u_encode(self.box_key_bytes)

    def sign(self, data: bytes) -> bytes:
        return self.signing_key.sign(data)

    def public_fields(self, name: str) -> dict[str, str]:
        """What the hub publishes with ``PUT /hub/card``."""
        return {"name": name, "sign_key": self.sign_key, "box_key": self.box_key}


def identity_path(data_dir: Path) -> Path:
    """``<data_dir>/net/identity.json``."""
    return Path(data_dir) / "net" / IDENTITY_FILE


def load_identity(path: Path, env: Mapping[str, str] | None = None) -> Identity:
    """``TAU_NET_IDENTITY`` when it is set in ``env``, else the file at ``path``.

    Raises :class:`FileNotFoundError` when neither exists and :class:`IdentityError` when the
    one that exists is malformed.
    """
    value = (env or {}).get(IDENTITY_ENV, "")
    if value and value.strip():
        return Identity.from_env_value(value)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise IdentityError(f"cannot read {path}: {exc.strerror or exc}") from None
    try:
        data = json.loads(text)
    except ValueError:
        raise IdentityError(f"{path} is not JSON") from None
    return Identity.from_json(data, source=f"file:{path}")


def load_or_none(path: Path, env: Mapping[str, str] | None = None) -> Identity | None:
    """Like :func:`load_identity`, but ``None`` when there is no identity at all."""
    try:
        return load_identity(path, env)
    except FileNotFoundError:
        return None


def create_identity(path: Path) -> Identity:
    """Generate a fresh identity and write it to ``path`` (0600; the directory 0700).

    Never overwrites: an existing file raises :class:`IdentityExists` and stays as it is.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    identity = Identity.generate()
    text = json.dumps(identity.to_json(), indent=2) + "\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise IdentityExists(path) from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(path, 0o600)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return Identity(identity.sign_seed, identity.box_seed, source=f"file:{path}")
