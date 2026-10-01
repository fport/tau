"""``[component.web]``: where the web service listens and how long it waits.

The service listens on loopback or on the hub's tailnet address, never anywhere else (ADR
0006: the ways in are Tailscale Serve and the Tunnel + Access). ``hostnames`` adds the names a
browser reaches it by (``hub.tau.<domain>`` behind the tunnel, ``my-mac.tailXXXXXX.ts.net``
behind Tailscale Serve) to the allowed ``Host`` headers; ``access_aud`` and ``access_team``
turn on the Cloudflare Access check.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any

from tau_core import Config, ConfigError

COMPONENT = "web"
DEFAULT_PORT = 7878
DEFAULT_BIND = "127.0.0.1"
DEFAULT_APPROVAL_TIMEOUT = 300.0
DEFAULT_TURN_KEEP = 300.0

TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")


class WebConfigError(ConfigError):
    """``[component.web]`` is wrong; the message says which key."""


def bind_allowed(bind: str) -> bool:
    """Loopback, or an address Tailscale hands out; never ``0.0.0.0``, ``::`` or a LAN."""
    try:
        address = ipaddress.ip_address(bind)
    except ValueError:
        return bind == "localhost"
    if address.is_loopback:
        return True
    network = TAILNET_V4 if address.version == 4 else TAILNET_V6
    return address in network


@dataclass(frozen=True)
class WebSettings:
    bind: str = DEFAULT_BIND
    port: int = DEFAULT_PORT
    hostnames: tuple[str, ...] = ()
    """Names in front of the hub (the tunnel's, Tailscale Serve's), allowed as ``Host``."""
    access_aud: str | None = None
    """The Access application's audience tag; with ``access_team`` it turns the JWT check on."""
    access_team: str | None = None
    """The Zero Trust team name: keys come from ``https://<team>.cloudflareaccess.com``."""
    approval_timeout: float = DEFAULT_APPROVAL_TIMEOUT
    turn_keep: float = DEFAULT_TURN_KEEP
    """Seconds a finished turn's events stay for a client that re-attaches."""

    @property
    def access_check(self) -> bool:
        return bool(self.access_aud and self.access_team)

    @classmethod
    def from_config(cls, config: Config) -> WebSettings:
        return cls.from_table(config.component(COMPONENT))

    @classmethod
    def from_table(cls, table: dict[str, Any]) -> WebSettings:
        bind = table.get("bind", DEFAULT_BIND)
        if not isinstance(bind, str) or not bind_allowed(bind):
            raise WebConfigError(
                f"[component.web] bind = {bind!r}: the web app listens only on loopback "
                "(127.0.0.1) or the hub's tailnet address (100.x.y.z), never on every interface "
                "or the LAN. Reach it through Tailscale Serve or the Tunnel."
            )
        port = table.get("port", DEFAULT_PORT)
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise WebConfigError(f"[component.web] port = {port!r}: expected 1-65535.")
        hostnames = table.get("hostnames", [])
        if not isinstance(hostnames, list) or not all(
            isinstance(name, str) and name.strip() for name in hostnames
        ):
            raise WebConfigError("[component.web] hostnames must be a list of host names.")
        access_aud = _optional_str(table, "access_aud")
        access_team = _optional_str(table, "access_team")
        if bool(access_aud) != bool(access_team):
            raise WebConfigError(
                "[component.web] access_aud and access_team go together: set both to check "
                "Cloudflare Access tokens, or neither."
            )
        return cls(
            bind=bind,
            port=port,
            hostnames=tuple(name.strip().lower() for name in hostnames),
            access_aud=access_aud,
            access_team=access_team,
            approval_timeout=_positive(table, "approval_timeout_seconds", DEFAULT_APPROVAL_TIMEOUT),
            turn_keep=_positive(table, "turn_keep_seconds", DEFAULT_TURN_KEEP),
        )

    def allowed_hosts(self) -> frozenset[str]:
        """``Host`` header values (without the port) this service answers."""
        return frozenset({"127.0.0.1", "localhost", "[::1]", self.bind, *self.hostnames})


def _optional_str(table: dict[str, Any], key: str) -> str | None:
    value = table.get(key)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise WebConfigError(f"[component.web] {key} must be a string.")
    return value.strip()


def _positive(table: dict[str, Any], key: str, default: float) -> float:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise WebConfigError(f"[component.web] {key} must be a positive number of seconds.")
    return float(value)
