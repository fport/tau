"""Base64url, addresses and the scheme rule of the tau network (protocol v1, §1).

- ``b64u`` is RFC 4648 §5 without padding; :func:`b64u_decode` accepts input with or without
  padding and rejects anything else (other alphabets, whitespace, a stray ``=``).
- A **host** is ``host`` or ``host:port``, lower case, matching :data:`HOST_PATTERN` exactly:
  the address of a spine, and of a universe.
- An **address** is a host, or a host followed by ``/@handle`` (ADR 0013): a tau hosted under a
  path, such as ``tau.example.com/@alice``. The handle matches :data:`HANDLE_PATTERN` (the
  GitHub login rules in lower case); the whole address matches :data:`ADDRESS_PATTERN`. A
  tau's card is at ``<scheme>://<address>/.well-known/tau.json`` and its inbox at
  ``<scheme>://<address>/net/inbox`` either way.
- The **scheme** is ``https`` for every host. Only while developing, with
  ``TAU_NET_ALLOW_INSECURE=1`` on the hub, ``localhost`` and ``127.0.0.1`` use ``http``.
- A **sub-tau name** matches :data:`SUB_NAME_PATTERN` (ADR 0012); a person reaches a public
  sub-tau as ``<address>/<name>`` (:func:`parse_target`). A name never starts with ``@``, so
  ``host/@handle/name`` and ``host/name`` never read two ways.
"""

from __future__ import annotations

import base64
import binascii
import re
from collections.abc import Mapping

__all__ = [
    "ADDRESS_PATTERN",
    "ALLOW_INSECURE_ENV",
    "HANDLE_PATTERN",
    "HOST_PATTERN",
    "ID_PATTERN",
    "INSECURE_HOSTS",
    "SUB_NAME_PATTERN",
    "AddressError",
    "EncodingError",
    "b64u_decode",
    "b64u_encode",
    "base_url",
    "handle_of",
    "host_of",
    "insecure_allowed",
    "is_valid_address",
    "is_valid_handle",
    "is_valid_host",
    "is_valid_id",
    "is_valid_sub_name",
    "parse_address",
    "parse_host",
    "parse_target",
    "split_address",
    "validate_address",
    "validate_host",
]

ALLOW_INSECURE_ENV = "TAU_NET_ALLOW_INSECURE"
INSECURE_HOSTS = frozenset({"localhost", "127.0.0.1"})
"""The only hosts that may use ``http``, and only when insecure peers are allowed."""

_HOST = r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*(:[0-9]{1,5})?"
_HANDLE = r"[a-z0-9]([a-z0-9-]{0,37}[a-z0-9])?"

HOST_PATTERN = re.compile(_HOST)
"""A host, ``host`` or ``host:port`` (§1), used with ``fullmatch`` (a trailing newline never
slips through)."""
HANDLE_PATTERN = re.compile(_HANDLE)
"""A handle (ADR 0013: ``^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$``), used with ``fullmatch``."""
ADDRESS_PATTERN = re.compile(_HOST + r"(/@" + _HANDLE + r")?")
"""An address, ``host[:port]`` or ``host[:port]/@handle`` (§1), used with ``fullmatch``."""

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
    """``host[:port]`` or ``host[:port]/@handle``, exactly (lower case, nothing around it)."""
    return isinstance(address, str) and ADDRESS_PATTERN.fullmatch(address) is not None


def is_valid_host(host: object) -> bool:
    """``host[:port]`` only: the address of a spine or a universe, never one with a handle."""
    return isinstance(host, str) and HOST_PATTERN.fullmatch(host) is not None


def is_valid_handle(handle: object) -> bool:
    return isinstance(handle, str) and HANDLE_PATTERN.fullmatch(handle) is not None


def validate_address(address: object) -> str:
    """``address`` unchanged when it is a valid address, else :class:`AddressError`."""
    if not is_valid_address(address):
        raise AddressError(f"not a tau address: {address!r}")
    return str(address)


def validate_host(host: object) -> str:
    """``host`` unchanged when it is a valid host (no ``/@handle``), else :class:`AddressError`."""
    if not is_valid_host(host):
        raise AddressError(f"not a host: {host!r}")
    return str(host)


def _typed(text: str) -> str:
    """Text typed by a person with surrounding space, a leading ``https://`` or ``http://``
    (in any case) and trailing ``/`` removed."""
    value = (text or "").strip()
    for prefix in ("https://", "http://"):
        if value.lower().startswith(prefix):
            value = value[len(prefix) :]
    return value.rstrip("/")


def parse_address(text: str) -> str:
    """An address typed by a person: surrounding space, upper case, a leading ``https://`` or
    ``http://`` and a trailing ``/`` are forgiven; the result must be a valid address."""
    return validate_address(_typed(text).lower())


def parse_host(text: str) -> str:
    """A host typed by a person, forgiven like :func:`parse_address`; an address with a
    ``/@handle`` is not a host (:class:`AddressError`)."""
    return validate_host(_typed(text).lower())


def split_address(address: str) -> tuple[str, str | None]:
    """``(host, handle)`` of a valid address; ``handle`` is ``None`` for a plain host."""
    validate_address(address)
    host, _, handle = address.partition("/@")
    return host, handle or None


def handle_of(address: str) -> str | None:
    """The handle of an address (``alice`` for ``tau.example.com/@alice``), else ``None``."""
    return split_address(address)[1]


def is_valid_sub_name(value: object) -> bool:
    return isinstance(value, str) and SUB_NAME_PATTERN.fullmatch(value) is not None


def parse_target(text: str) -> tuple[str, str | None]:
    """``(address, sub)`` from ``address`` or ``address/name`` typed by a person, where the
    address is ``host[:port]`` or ``host[:port]/@handle``: ``tau.example.com/coach`` and
    ``tau.example.com/@alice/coach`` both name ``/coach``. The address part is forgiven like
    :func:`parse_address` (``https://``, upper case), the name must be a sub-tau name;
    :class:`AddressError` otherwise (also for anything after the name)."""
    parts = _typed(text).split("/")
    address, rest = parts[0], parts[1:]
    if rest and rest[0].startswith("@"):
        address, rest = f"{address}/{rest[0]}", rest[1:]
    if len(rest) > 1:
        raise AddressError(f"not a tau address or sub-tau: {text.strip()!r}")
    if not rest:
        return parse_address(address), None
    sub = rest[0].strip().lower()
    if not is_valid_sub_name(sub):
        raise AddressError(
            f"not a sub-tau name: {sub!r} (2 to 31 lowercase letters, digits and '-', "
            "starting with a letter)"
        )
    return parse_address(address), sub


def is_valid_id(value: object) -> bool:
    return isinstance(value, str) and ID_PATTERN.fullmatch(value) is not None


def host_of(address: str) -> str:
    """The host name of an address, without ``:port`` and without ``/@handle``."""
    host = address.split("/", 1)[0]
    return host.rsplit(":", 1)[0] if ":" in host else host


def insecure_allowed(env: Mapping[str, str]) -> bool:
    """``TAU_NET_ALLOW_INSECURE=1``: development peers on localhost may use ``http``."""
    return (env.get(ALLOW_INSECURE_ENV) or "").strip() == "1"


def base_url(address: str, *, allow_insecure: bool = False) -> str:
    """``https://<address>``, or ``http://<address>`` for a development host when allowed;
    ``https://tau.example.com/@alice`` for a handle address, so the card and the inbox are
    ``base_url + "/.well-known/tau.json"`` and ``base_url + "/net/inbox"`` for every address."""
    validate_address(address)
    if allow_insecure and host_of(address) in INSECURE_HOSTS:
        return f"http://{address}"
    return f"https://{address}"
