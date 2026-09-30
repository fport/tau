"""Base64url, addresses and the scheme rule of the tau network (protocol v1, §1).

- ``b64u`` is RFC 4648 §5 without padding; :func:`b64u_decode` accepts input with or without
  padding and rejects anything else (other alphabets, whitespace, a stray ``=``).
- An **address** is the host of a tau's spine, ``host`` or ``host:port``, lower case, matching
  :data:`ADDRESS_PATTERN` exactly.
- The **scheme** is ``https`` for every host. Only while developing, with
  ``TAU_NET_ALLOW_INSECURE=1`` on the hub, ``localhost`` and ``127.0.0.1`` use ``http``.
- A **sub-tau name** matches :data:`SUB_NAME_PATTERN` (ADR 0012); a person reaches a public
  sub-tau as ``<address>/<name>`` (:func:`parse_target`).
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Mapping

__all__ = [
    "ADDRESS_PATTERN",
    "ALLOW_INSECURE_ENV",
    "ID_PATTERN",
    "INSECURE_HOSTS",
    "SUB_NAME_PATTERN",
    "AddressError",
    "EncodingError",
    "b64u_decode",
    "b64u_encode",
    "base_url",
    "host_of",
    "insecure_allowed",
    "is_valid_address",
    "is_valid_id",
    "is_valid_sub_name",
    "parse_address",
    "parse_target",
    "validate_address",
]

ALLOW_INSECURE_ENV = "TAU_NET_ALLOW_INSECURE"
INSECURE_HOSTS = frozenset({"localhost", "127.0.0.1"})
"""The only hosts that may use ``http``, and only when insecure peers are allowed."""

ADDRESS_PATTERN = re.compile(
    r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*(:[0-9]{1,5})?"
)
"""§1, used with ``fullmatch`` (a trailing newline never slips through)."""

ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{16,64}")
"""Envelope ids, used with ``fullmatch``."""

SUB_NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]{1,30}")
"""A sub-tau name (ADR 0012: ``^[a-z][a-z0-9-]{1,30}$``), used with ``fullmatch``."""

_B64U = re.compile(r"[A-Za-z0-9_-]*={0,2}")


class EncodingError(ValueError):
    """Text that is not valid unpadded (or padded) base64url."""


class AddressError(ValueError):
    """Text that is not a tau address."""


def b64u_encode(data: bytes) -> str:
    """``data`` as base64url without padding."""
    return base64.urlsafe_b64encode(bytes(data)).rstrip(b"=").decode("ascii")


def b64u_decode(text: str) -> bytes:
    """Decode base64url with or without padding; :class:`EncodingError` for anything else."""
    if not isinstance(text, str) or not _B64U.fullmatch(text):
        raise EncodingError("not base64url")
    stripped = text.rstrip("=")
    if len(stripped) % 4 == 1:
        raise EncodingError("not base64url: impossible length")
    if text != stripped and (len(text) % 4 != 0):
        raise EncodingError("not base64url: wrong padding")
    try:
        return base64.urlsafe_b64decode(stripped + "=" * (-len(stripped) % 4))
    except (binascii.Error, ValueError) as exc:  # pragma: no cover - the pattern rules it out
        raise EncodingError(f"not base64url: {exc}") from None


def is_valid_address(address: object) -> bool:
    return isinstance(address, str) and ADDRESS_PATTERN.fullmatch(address) is not None


def validate_address(address: object) -> str:
    """``address`` unchanged when it is a valid address, else :class:`AddressError`."""
    if not is_valid_address(address):
        raise AddressError(f"not a tau address: {address!r}")
    return str(address)


def parse_address(text: str) -> str:
    """An address typed by a person: surrounding space, upper case, a leading ``https://`` or
    ``http://`` and a trailing ``/`` are forgiven; the result must be a valid address."""
    value = (text or "").strip().lower()
    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    value = value.rstrip("/")
    return validate_address(value)


def is_valid_sub_name(value: object) -> bool:
    return isinstance(value, str) and SUB_NAME_PATTERN.fullmatch(value) is not None


def parse_target(text: str) -> tuple[str, str | None]:
    """``(address, sub)`` from ``address`` or ``address/name`` typed by a person: the address
    part is forgiven like :func:`parse_address` (``https://``, upper case), the name must be a
    sub-tau name; :class:`AddressError` otherwise."""
    value = (text or "").strip()
    for prefix in ("https://", "http://"):
        if value.lower().startswith(prefix):
            value = value[len(prefix) :]
    value = value.rstrip("/")
    address, slash, sub = value.partition("/")
    if not slash:
        return parse_address(address), None
    sub = sub.strip().lower()
    if not is_valid_sub_name(sub):
        raise AddressError(
            f"not a sub-tau name: {sub!r} (2 to 31 lowercase letters, digits and '-', "
            "starting with a letter)"
        )
    return parse_address(address), sub


def is_valid_id(value: object) -> bool:
    return isinstance(value, str) and ID_PATTERN.fullmatch(value) is not None


def host_of(address: str) -> str:
    """The host part of an address (without ``:port``)."""
    return address.rsplit(":", 1)[0] if ":" in address else address


def insecure_allowed(env: Mapping[str, str]) -> bool:
    """``TAU_NET_ALLOW_INSECURE=1``: development peers on localhost may use ``http``."""
    return (env.get(ALLOW_INSECURE_ENV) or "").strip() == "1"


def base_url(address: str, *, allow_insecure: bool = False) -> str:
    """``https://<address>``, or ``http://<address>`` for a development host when allowed."""
    validate_address(address)
    if allow_insecure and host_of(address) in INSECURE_HOSTS:
        return f"http://{address}"
    return f"https://{address}"
