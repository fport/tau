"""Public sub-taus on the tau network (ADR 0012, issue 150), without importing tau-sub.

A contact reaches a public sub-tau of this tau as ``<address>/<name>``: the sealed content of
a ``message`` carries ``"sub": "<name>"``. Which sub-taus exist, and which of them are public,
is tau-sub's business, so tau-net asks through an entry point instead of importing it:

- the group is :data:`SUBS_GROUP` (``tau.subs``); tau-sub declares ``sub =
  "tau_sub.network:public_subs"``;
- the object is a factory ``factory(Config) -> SubDirectory``, loaded lazily on first use with
  tau-core's skip-and-log discipline (a broken or missing hook means "no public sub-taus");
- a :class:`SubDirectory` answers :meth:`~SubDirectory.public` (one public sub-tau, or
  ``None`` for an unknown, private or invalid one) and :meth:`~SubDirectory.public_subs`
  (every public one, for the universe report);
- a :class:`PublicSub` is plain data: the name, the about line, the model role, the file with
  the persona the model reads (tau-sub's header plus the persona text) and the file of its
  public note, if it has one; since ADR 0013 also its page settings ``web``, ``web_daily`` and
  ``starters``, read with :func:`page_settings` so a tau-sub that predates them means "no
  page".

Both sides depend only on tau-core, and the contract is duck-typed (:class:`typing.Protocol`),
so neither package imports the other. Without tau-sub installed a hub simply has no public
sub-taus and drops every message addressed to one.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from tau_core import Config

from tau_net.encoding import is_valid_sub_name

__all__ = [
    "MAX_REPORTED_STARTERS",
    "MAX_REPORTED_SUBS",
    "STARTER_LIMIT",
    "SUBS_GROUP",
    "SUB_ABOUT_LIMIT",
    "WEB_DAILY_DEFAULT",
    "PageSettings",
    "PublicSub",
    "SubDirectory",
    "find_sub_directory",
    "page_settings",
    "universe_subs",
]

logger = logging.getLogger(__name__)

SUBS_GROUP = "tau.subs"
"""The entry-point group of the sub-tau directory (``factory(Config) -> SubDirectory``)."""
MAX_REPORTED_SUBS = 20
"""A universe report lists at most this many public sub-taus."""
SUB_ABOUT_LIMIT = 200
"""A reported ``about`` line is cut to this many characters."""
MAX_REPORTED_STARTERS = 4
STARTER_LIMIT = 80
"""A report carries at most 4 starters of 1 to 80 characters per sub-tau."""
WEB_DAILY_DEFAULT = 50
WEB_DAILY_RANGE = (1, 1000)


@runtime_checkable
class PublicSub(Protocol):
    """One public sub-tau, as a network turn and a universe report need it."""

    name: str
    about: str
    role: str
    """The model role of the sub-tau (``brain``, ``fast`` or ``local``)."""
    persona_file: Path
    """The persona the model reads (tau-sub's header, then the persona text); absolute."""
    public_note_file: Path | None
    """Its public note (``persona/subs/<note>.md``), absolute; ``None`` when it has none."""
    # ADR 0013 adds ``web: bool``, ``web_daily: int`` and ``starters: tuple[str, ...]``; they
    # are read with :func:`page_settings`, so an object without them has no page.


class SubDirectory(Protocol):
    """The sub-tau definitions of this tau, as tau-sub exposes them to the network."""

    def public(self, name: str) -> PublicSub | None:
        """The public sub-tau ``name``, or ``None`` when it is unknown, private or invalid."""
        ...

    def public_subs(self) -> Sequence[PublicSub]:
        """Every valid public sub-tau, sorted by name."""
        ...


def _discover(group: str) -> dict[str, Any]:
    # tau-core's loader: an entry point that fails to load is logged and skipped.
    from tau_core.registry import discover

    return discover(group)


def find_sub_directory(
    config: Config, *, discover: Callable[[str], dict[str, Any]] = _discover
) -> SubDirectory | None:
    """The directory of the first ``tau.subs`` entry point (by name) that builds, or ``None``
    when none is installed or none works (logged)."""
    factories = discover(SUBS_GROUP)
    for name in sorted(factories):
        factory = factories[name]
        try:
            directory = factory(config)
        except Exception as exc:
            logger.warning("net: the %s entry point %s failed to build: %s", SUBS_GROUP, name, exc)
            continue
        if not callable(getattr(directory, "public", None)) or not callable(
            getattr(directory, "public_subs", None)
        ):
            logger.warning(
                "net: the %s entry point %s is not a sub-tau directory; ignored", SUBS_GROUP, name
            )
            continue
        return directory
    return None


@dataclass(frozen=True)
class PageSettings:
    """The web page of a public sub-tau (ADR 0013 §5), as tau-net trusts it."""

    web: bool = False
    web_daily: int = WEB_DAILY_DEFAULT
    starters: tuple[str, ...] = ()


def page_settings(sub: object) -> PageSettings:
    """``web``, ``web_daily`` and ``starters`` of a :class:`PublicSub`, checked again: a
    missing or malformed ``web`` means no page, a bad ``web_daily`` the default, and starters
    are kept only when they are 1 to 80 characters on one line (at most 4)."""
    web = getattr(sub, "web", False) is True
    daily = getattr(sub, "web_daily", WEB_DAILY_DEFAULT)
    low, high = WEB_DAILY_RANGE
    if isinstance(daily, bool) or not isinstance(daily, int) or not low <= daily <= high:
        daily = WEB_DAILY_DEFAULT
    raw = getattr(sub, "starters", ())
    starters: list[str] = []
    for starter in raw if isinstance(raw, list | tuple) else ():
        if not isinstance(starter, str):
            continue
        line = " ".join(starter.split())
        if 1 <= len(line) <= STARTER_LIMIT and line not in starters:
            starters.append(line)
    return PageSettings(web, daily, tuple(starters[:MAX_REPORTED_STARTERS]))


def universe_subs(directory: SubDirectory | None) -> list[dict[str, Any]]:
    """The ``subs`` of a universe report: every public sub-tau as ``{"name", "about", "web",
    "starters"}``, at most :data:`MAX_REPORTED_SUBS`, ``about`` on one line and cut to
    :data:`SUB_ABOUT_LIMIT`. Private sub-taus are never listed; a failing directory lists
    nothing (logged)."""
    if directory is None:
        return []
    try:
        subs = list(directory.public_subs())
    except Exception as exc:
        logger.warning("net: could not list the public sub-taus: %s", exc)
        return []
    listed: dict[str, dict[str, Any]] = {}
    for sub in subs:
        name = getattr(sub, "name", None)
        if not is_valid_sub_name(name) or name in listed:
            continue
        about = " ".join(str(getattr(sub, "about", "") or "").split())
        page = page_settings(sub)
        listed[str(name)] = {
            "name": str(name),
            "about": about[:SUB_ABOUT_LIMIT].rstrip(),
            "web": page.web,
            "starters": list(page.starters),
        }
    return [listed[name] for name in sorted(listed)][:MAX_REPORTED_SUBS]
