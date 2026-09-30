"""Public sub-taus for the tau network: the ``tau.subs`` entry point (issue 150).

tau-net finds this tau's public sub-taus through the entry-point group ``tau.subs`` instead of
importing tau-sub, and tau-sub does not import tau-net either: the contract is plain data.
:func:`public_subs` is the factory (``factory(Config) -> PublicSubs``); the directory answers

- :meth:`PublicSubs.public`: one sub-tau by name, only when its definition is valid and says
  ``public = true``, else ``None`` (tau-net then drops the message unanswered);
- :meth:`PublicSubs.public_subs`: every valid public sub-tau, for the universe report.

A :class:`PublicSub` carries the files a network turn reads: the derived persona file (the
fixed English header and the persona text, the same file ``tau sub chat`` uses, rewritten only
when the definition changed) and the sub-tau's public note, ``persona/subs/<public_note>``,
when it has one. ``persona/user.md`` is never one of them. Definitions are read again on every
lookup, so a sub-tau made public or private takes effect with the next message.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from strands.types.tools import AgentTool
from tau_core import Config

from tau_sub.agent import write_prompt
from tau_sub.definition import NAME_RE, SubRegistry, SubTau, SubTauError

__all__ = ["PublicSub", "PublicSubs", "public_subs"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublicSub:
    """One public sub-tau as the network sees it."""

    name: str
    about: str
    role: str
    persona_file: Path
    """``TAU_DATA_DIR/subs/<name>/persona.md``: the header and the persona text."""
    public_note_file: Path | None
    """``persona/subs/<public_note>``, or ``None`` when the definition names none."""


class PublicSubs:
    """The public sub-taus of one tau (``tau.subs`` entry point ``sub``)."""

    def __init__(self, config: Config, *, tools: Iterable[AgentTool] | None = None):
        self.config = config
        self.registry = SubRegistry(config, tools=tools)

    def public(self, name: str) -> PublicSub | None:
        """The public sub-tau ``name``; ``None`` when it is unknown, private or invalid."""
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            return None
        if not self.registry.exists(name):
            return None
        try:
            sub = self.registry.get(name)
        except SubTauError as exc:
            logger.warning("sub: /%s cannot answer the network: %s", name, exc)
            return None
        return self._public(sub) if sub.public else None

    def public_subs(self) -> list[PublicSub]:
        """Every valid public sub-tau, sorted by name (invalid definitions are logged)."""
        return [self._public(sub) for sub in self.registry.list() if sub.public]

    def _public(self, sub: SubTau) -> PublicSub:
        note = self.registry.directory / sub.public_note if sub.public_note else None
        return PublicSub(
            name=sub.name,
            about=sub.about,
            role=sub.role,
            persona_file=write_prompt(self.config, sub).resolve(),
            public_note_file=note.resolve() if note is not None else None,
        )


def public_subs(config: Config) -> PublicSubs:
    """The ``tau.subs`` factory: this tau's public sub-taus."""
    return PublicSubs(config)
