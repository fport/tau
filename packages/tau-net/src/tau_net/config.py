"""``[component.net]`` in ``tau.toml`` and the network's variables in ``.env`` (§7).

.. code-block:: toml

    [component.net]
    name = "Alice's tau"              # display name on the card
    auto_reply = true
    max_hops = 6
    max_auto_replies_per_hour = 20
    public_note = "net.md"            # under persona/; replaces user.md in network turns
    store = "file"                    # file | spine (cloud mode)
    poll_timeout_seconds = 25
    universe = "tau.getporti.com"     # the universe host; "" switches the universe off
    universe_links = true             # report mutual links (with counts) to listed contacts
    universe_report_minutes = 60      # 5 or more

The owner's personal values (the card name, the universe membership, owner and about) are
runtime data in the network store's ``profile`` document (:mod:`tau_net.profile`), never
``tau.toml``; ``name`` here is only a fallback for the card name.

``TAU_SPINE_URL`` and ``TAU_SPINE_TOKEN`` point the hub at its spine; ``TAU_NET_IDENTITY``
replaces the identity file (cloud mode); ``TAU_NET_ALLOW_INSECURE=1`` lets development peers on
``localhost``/``127.0.0.1`` use ``http``. The spine URL itself may use ``http`` only for those
two hosts. Every message here is plain English: it can be raised before a channel exists.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tau_core import Config

from tau_net.encoding import INSECURE_HOSTS, AddressError, parse_address
from tau_net.spine import MAX_POLL_TIMEOUT, SpineClient, Transport
from tau_net.store import STORE_KINDS
from tau_net.universe import DEFAULT_UNIVERSE

__all__ = [
    "COMPONENT",
    "NAME_LIMIT",
    "SPINE_TOKEN_ENV",
    "SPINE_URL_ENV",
    "NetConfigError",
    "NetSettings",
    "net_env",
    "spine_from_env",
]

logger = logging.getLogger(__name__)

COMPONENT = "net"
SPINE_URL_ENV = "TAU_SPINE_URL"
SPINE_TOKEN_ENV = "TAU_SPINE_TOKEN"
NAME_LIMIT = 80
KNOWN_KEYS = frozenset(
    {
        "name",
        "auto_reply",
        "max_hops",
        "max_auto_replies_per_hour",
        "public_note",
        "store",
        "poll_timeout_seconds",
        "universe",
        "universe_links",
        "universe_report_minutes",
    }
)
REPORT_MINUTES_RANGE = (5, 1440)
"""``universe_report_minutes``: at least 5; at most a day (a universe shows a tau as online
for 2 hours after its last report and forgets it after 30 days)."""
PRIVATE_NOTES = frozenset({"user.md", "persona.md"})
"""Files a network turn may never read as the public note."""


_UNIVERSE_ERROR = (
    "tau.toml: [component.net] 'universe' must be a host such as \"tau.getporti.com\", "
    'or "" to switch the universe off.'
)


class NetConfigError(ValueError):
    """``[component.net]``, a network variable or a profile value that cannot be used."""


def _int(settings: Mapping[str, Any], key: str, default: int, low: int, high: int) -> int:
    value = settings.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise NetConfigError(
            f"tau.toml: [component.net] '{key}' must be an integer from {low} to {high}."
        )
    return value


@dataclass(frozen=True)
class NetSettings:
    name: str = "tau"
    auto_reply: bool = True
    max_hops: int = 6
    max_auto_replies_per_hour: int = 20
    public_note: str = "net.md"
    store: str = "file"
    poll_timeout_seconds: int = MAX_POLL_TIMEOUT
    universe: str = DEFAULT_UNIVERSE
    """The universe host; ``""`` switches the universe off."""
    universe_links: bool = True
    universe_report_minutes: int = 60

    @classmethod
    def from_mapping(cls, settings: Mapping[str, Any]) -> NetSettings:
        """Validate a ``[component.net]`` table; unknown keys are logged and ignored."""
        unknown = sorted(set(settings) - KNOWN_KEYS)
        if unknown:
            logger.warning("tau.toml: [component.net] ignores unknown keys: %s", ", ".join(unknown))
        name = settings.get("name", cls.name)
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > NAME_LIMIT:
            raise NetConfigError(
                f"tau.toml: [component.net] 'name' must be 1 to {NAME_LIMIT} characters."
            )
        auto_reply = settings.get("auto_reply", cls.auto_reply)
        if not isinstance(auto_reply, bool):
            raise NetConfigError("tau.toml: [component.net] 'auto_reply' must be true or false.")
        public_note = settings.get("public_note", cls.public_note)
        if (
            not isinstance(public_note, str)
            or not public_note
            or Path(public_note).name != public_note
            or public_note in (".", "..")
            or public_note in PRIVATE_NOTES
        ):
            raise NetConfigError(
                "tau.toml: [component.net] 'public_note' must be a file name under persona/ "
                'other than user.md and persona.md, such as "net.md".'
            )
        store = settings.get("store", cls.store)
        if store not in STORE_KINDS:
            raise NetConfigError(
                f"tau.toml: [component.net] 'store' must be one of {', '.join(STORE_KINDS)}."
            )
        universe = settings.get("universe", cls.universe)
        if not isinstance(universe, str):
            raise NetConfigError(_UNIVERSE_ERROR)
        if universe.strip():
            try:
                universe = parse_address(universe)
            except AddressError:
                raise NetConfigError(_UNIVERSE_ERROR) from None
        else:
            universe = ""
        universe_links = settings.get("universe_links", cls.universe_links)
        if not isinstance(universe_links, bool):
            raise NetConfigError(
                "tau.toml: [component.net] 'universe_links' must be true or false."
            )
        return cls(
            name=name.strip(),
            auto_reply=auto_reply,
            max_hops=_int(settings, "max_hops", cls.max_hops, 0, 100),
            max_auto_replies_per_hour=_int(
                settings, "max_auto_replies_per_hour", cls.max_auto_replies_per_hour, 0, 10_000
            ),
            public_note=public_note,
            store=store,
            poll_timeout_seconds=_int(
                settings, "poll_timeout_seconds", cls.poll_timeout_seconds, 0, MAX_POLL_TIMEOUT
            ),
            universe=universe,
            universe_links=universe_links,
            universe_report_minutes=_int(
                settings,
                "universe_report_minutes",
                cls.universe_report_minutes,
                *REPORT_MINUTES_RANGE,
            ),
        )

    @classmethod
    def from_config(cls, config: Config) -> NetSettings:
        return cls.from_mapping(config.component(COMPONENT))


def net_env(config: Config, env: Mapping[str, str] | None = None) -> dict[str, str]:
    """``env`` (default: the process environment) on top of ``<home>/.env``: a variable that
    is already set never loses to the file, the rule of ``Config.load``."""
    from tau_core.builder import env_with_dotenv

    return env_with_dotenv(config.home, os.environ if env is None else env)


def spine_from_env(
    env: Mapping[str, str], *, transport: Transport | None = None
) -> SpineClient | None:
    """The owner's spine from ``TAU_SPINE_URL`` and ``TAU_SPINE_TOKEN``; ``None`` when either
    is missing. :class:`NetConfigError` for a URL that is not ``https`` (``http`` is allowed
    for ``localhost`` and ``127.0.0.1`` only)."""
    url = (env.get(SPINE_URL_ENV) or "").strip()
    token = (env.get(SPINE_TOKEN_ENV) or "").strip()
    if not url or not token:
        return None
    parts = urllib.parse.urlsplit(url)
    if parts.scheme == "http" and parts.hostname in INSECURE_HOSTS:
        pass
    elif parts.scheme != "https" or not parts.hostname:
        raise NetConfigError(
            f"{SPINE_URL_ENV} must be an https URL such as https://tau.example.com "
            "(http only for localhost and 127.0.0.1)."
        )
    return SpineClient(url, token, transport=transport)
