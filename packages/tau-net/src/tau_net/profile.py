"""The owner's network profile: runtime data, never ``tau.toml``.

The card's display name and the universe membership are personal, and ``tau.toml`` may be a
tracked file, so they live in the ``profile`` document of the network store
(``TAU_DATA_DIR/net/profile.json``, or ``net.profile`` on the spine in cloud mode)::

    {"name": "Alice's tau", "universe_join": true, "universe_owner": "Alice",
     "universe_about": "Plans hikes.", "universe_links": false}

- ``name``: the card's display name. It wins over ``[component.net] name`` in ``tau.toml``,
  which stays an optional fallback; without either the name is ``tau``.
- ``universe_join``, ``universe_owner``, ``universe_about``: set by ``tau net universe join``
  and ``leave``; they come only from here.
- ``universe_links``: an override of ``[component.net] universe_links``, written by
  ``join --no-links`` (or ``--links``); absent = the ``tau.toml`` setting.

Reading is lenient (a value of the wrong type counts as absent); :func:`check_profile_changes`
is strict and is applied before anything is written.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tau_net.config import NAME_LIMIT, NetConfigError
from tau_net.universe import ABOUT_LIMIT, OWNER_LIMIT

__all__ = ["PROFILE_KEYS", "NetProfile", "check_profile_changes"]

PROFILE_KEYS = ("name", "universe_join", "universe_owner", "universe_about", "universe_links")


def _one_line(value: str) -> str:
    return " ".join(value.split())


@dataclass(frozen=True)
class NetProfile:
    name: str = ""
    """The card's display name; ``""`` = not set (``[component.net] name`` applies)."""
    universe_join: bool = False
    universe_owner: str = ""
    universe_about: str = ""
    universe_links: bool | None = None
    """``None`` = ``[component.net] universe_links`` applies."""

    @classmethod
    def from_json(cls, data: Any) -> NetProfile:
        data = data if isinstance(data, Mapping) else {}

        def text(key: str, limit: int) -> str:
            value = data.get(key)
            return _one_line(value)[:limit] if isinstance(value, str) else ""

        links = data.get("universe_links")
        return cls(
            name=text("name", NAME_LIMIT),
            universe_join=data.get("universe_join") is True,
            universe_owner=text("universe_owner", OWNER_LIMIT),
            universe_about=text("universe_about", ABOUT_LIMIT),
            universe_links=links if isinstance(links, bool) else None,
        )

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "universe_join": self.universe_join,
            "universe_owner": self.universe_owner,
            "universe_about": self.universe_about,
        }
        if self.name:
            data["name"] = self.name
        if self.universe_links is not None:
            data["universe_links"] = self.universe_links
        return data


def check_profile_changes(changes: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalise changes to the profile; :class:`NetConfigError` otherwise.

    Strings are collapsed to one line. ``name`` must be 1–80 characters, ``universe_owner``
    0–60 and ``universe_about`` 0–200; ``universe_join`` is a bool; ``universe_links`` is a bool
    or ``None`` (``None`` removes the override)."""
    checked: dict[str, Any] = {}
    for key, value in changes.items():
        if key not in PROFILE_KEYS:
            raise NetConfigError(f"the network profile has no field {key!r}")
        if key == "name":
            if not isinstance(value, str) or not 1 <= len(_one_line(value)) <= NAME_LIMIT:
                raise NetConfigError(f"the card name must be 1 to {NAME_LIMIT} characters")
            checked[key] = _one_line(value)
        elif key in ("universe_owner", "universe_about"):
            limit = OWNER_LIMIT if key == "universe_owner" else ABOUT_LIMIT
            what = "owner name" if key == "universe_owner" else "about line"
            if not isinstance(value, str) or len(_one_line(value)) > limit:
                raise NetConfigError(f"the universe {what} must be at most {limit} characters")
            checked[key] = _one_line(value)
        elif key == "universe_join":
            if not isinstance(value, bool):
                raise NetConfigError("universe_join must be true or false")
            checked[key] = value
        else:
            if value is not None and not isinstance(value, bool):
                raise NetConfigError("universe_links must be true, false or unset")
            checked[key] = value
    return checked
