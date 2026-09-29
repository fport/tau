"""Persona files plus dynamic context → the system prompt, rebuilt before every model call.

``persona/persona.md`` is tau's character (tracked), ``persona/user.md`` holds facts about the
user (gitignored). Both are re-read when their mtime or size changes, so an edit takes effect
on the next model call without a restart. The dynamic block carries the time, profile, host
role and the sources that later layers fill (live nodes, today's budget); unknown ones say so.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from strands.hooks import BeforeModelCallEvent, HookProvider, HookRegistry

from tau_core.config import Config, ConfigError

logger = logging.getLogger(__name__)

TIMEZONE = ZoneInfo("Europe/Istanbul")
UNKNOWN = "bilinmiyor"
NO_USER_FILE = "Kullanıcı dosyası yok (persona/user.md). Hitap: siz."

_WEEKDAYS = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")

ContextSource = Callable[[], dict[str, Any]]
"""Partial :class:`DynamicContext` overrides, e.g. ``{"nodes": [...]}`` or ``{"budget": ...}``."""


@dataclass(frozen=True)
class DynamicContext:
    now: datetime
    profile: str
    role: str
    nodes: list[str] | None = None
    budget: str | None = None

    def render(self) -> str:
        now = self.now.astimezone(TIMEZONE)
        nodes = UNKNOWN if self.nodes is None else (", ".join(self.nodes) or "yok")
        return "\n".join(
            [
                f"- Tarih ve saat: {now:%d.%m.%Y %H:%M}, {_WEEKDAYS[now.weekday()]} "
                "(Europe/Istanbul)",
                f"- Profil: {self.profile}",
                f"- Rol: {self.role}",
                f"- Canlı node'lar: {nodes}",
                f"- Bugünkü bütçe: {self.budget or UNKNOWN}",
            ]
        )


@dataclass(frozen=True)
class Persona:
    persona: str
    user: str | None


class _CachedFile:
    def __init__(self, path: Path):
        self.path = path
        self._stamp: tuple[int, int] | None = None
        self._text: str | None = None

    def read(self) -> str | None:
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            self._stamp, self._text = None, None
            return None
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp != self._stamp:
            self._text = self.path.read_text(encoding="utf-8").strip()
            self._stamp = stamp
            logger.debug("persona file loaded: %s", self.path.name)
        return self._text


class PersonaLoader:
    def __init__(
        self,
        persona_dir: Path,
        *,
        user_file: str = "user.md",
        persona_file: str = "persona.md",
    ):
        self.persona_dir = Path(persona_dir)
        self._persona = _CachedFile(self.persona_dir / persona_file)
        self._user = _CachedFile(self.persona_dir / user_file)
        self._last: Persona | None = None

    def read(self) -> Persona:
        """Current persona; files are re-read only when (mtime, size) changed."""
        persona = self._persona.read()
        if persona is None:
            if self._last is not None:
                logger.warning("%s disappeared; keeping the last version", self._persona.path)
                persona = self._last.persona
            else:
                raise ConfigError(f"Persona dosyası bulunamadı: {self._persona.path}")
        self._last = Persona(persona=persona, user=self._user.read())
        return self._last

    def build_system_prompt(self, context: DynamicContext) -> str:
        current = self.read()
        user = current.user or NO_USER_FILE
        return f"{current.persona}\n\n## Kullanıcı\n{user}\n\n## Şu an\n{context.render()}"


class PersonaHook(HookProvider):
    """Sets ``agent.system_prompt`` before every model call."""

    def __init__(self, loader: PersonaLoader, context_factory: Callable[[], DynamicContext]):
        self.loader = loader
        self.context_factory = context_factory

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeModelCallEvent, self._before_model_call)

    def _before_model_call(self, event: BeforeModelCallEvent) -> None:
        event.agent.system_prompt = self.loader.build_system_prompt(self.context_factory())


def default_context_factory(
    config: Config,
    *,
    clock: Callable[[], datetime] | None = None,
    sources: Iterable[ContextSource] = (),
) -> Callable[[], DynamicContext]:
    """Time (Europe/Istanbul), profile and host role; ``sources`` are merged in order."""
    source_list = list(sources)
    allowed = {"now", "profile", "role", "nodes", "budget"}

    def factory() -> DynamicContext:
        now = clock() if clock is not None else datetime.now(TIMEZONE)
        if now.tzinfo is None:
            now = now.replace(tzinfo=TIMEZONE)
        context = DynamicContext(
            now=now.astimezone(TIMEZONE), profile=config.profile, role=config.role
        )
        for source in source_list:
            try:
                overrides = source() or {}
            except Exception:
                logger.exception("context source %r failed; ignoring it", source)
                continue
            context = replace(context, **{k: v for k, v in overrides.items() if k in allowed})
        return context

    return factory
