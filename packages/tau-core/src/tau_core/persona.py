"""Persona files plus dynamic context → the system prompt, rebuilt before every model call.

``persona/persona.md`` is tau's character (tracked, no personal facts); ``persona/user.md``
holds facts about the user (gitignored; ``user.example.md`` is the template). Before every
model call :class:`PersonaHook` asks :class:`PersonaLoader` for the prompt; a file is re-read
only when its ``(st_mtime_ns, st_size)`` stamp changed, so an edit takes effect on the next
model call without a restart. HTML comments (``<!-- ... -->``) in either file are notes for
humans and never reach the model.

The prompt layout is fixed::

    <persona.md>

    ## Kullanıcı
    <user.md, or NO_USER_FILE when it is missing or empty>

    ## Şu an
    <DynamicContext.render()>

The dynamic block carries the time (always Europe/Istanbul), the profile, the host role and
the values later layers fill through :data:`ContextSource` callables (live nodes, today's
budget). A value nobody provides renders as ``bilinmiyor``, so the model never has to guess.

Failure rules: a missing, empty or unreadable ``persona.md`` raises :class:`ConfigError` on the
first read (``build_agent`` reads eagerly, so tau fails at startup); later it keeps the last
good version. A missing or empty ``user.md`` means "no facts, address the user as siz"; an
unreadable one keeps the last good version. A failing context source is skipped. Each problem
is logged once until it clears, so a broken file or source never floods the terminal.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, fields, replace
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from strands.hooks import BeforeModelCallEvent, HookProvider, HookRegistry

from tau_core.config import Config, ConfigError

__all__ = [
    "NO_USER_FILE",
    "TIMEZONE",
    "UNKNOWN",
    "ContextSource",
    "DynamicContext",
    "Persona",
    "PersonaHook",
    "PersonaLoader",
    "default_context_factory",
]

logger = logging.getLogger(__name__)


def _istanbul() -> tzinfo:
    try:
        return ZoneInfo("Europe/Istanbul")
    except ZoneInfoNotFoundError:  # slim images without tzdata; Türkiye is on UTC+3 all year
        return timezone(timedelta(hours=3), "Europe/Istanbul")


TIMEZONE = _istanbul()
UNKNOWN = "bilinmiyor"
NONE_LIVE = "yok"
NO_USER_FILE = "Kullanıcı dosyası yok (persona/user.md). Hitap: siz."

_WEEKDAYS = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BLANK_RUNS = re.compile(r"\n{3,}")

ContextSource = Callable[[], dict[str, Any]]
"""Partial :class:`DynamicContext` overrides, e.g. ``{"nodes": [...]}`` or ``{"budget": ...}``.

Sources run before every model call, in order; a later source wins. They must be fast and
read a cached value (no network round trip per call). Unknown keys are ignored, ``None`` means
"unknown", and a source that raises or returns something other than a mapping is skipped.
"""


def _in_timezone(now: datetime) -> datetime:
    """``now`` in Europe/Istanbul; a naive datetime is taken to be Istanbul time already."""
    if now.tzinfo is None:
        return now.replace(tzinfo=TIMEZONE)
    return now.astimezone(TIMEZONE)


@dataclass(frozen=True)
class DynamicContext:
    """The live facts appended to the system prompt under ``## Şu an``."""

    now: datetime
    profile: str
    role: str
    nodes: list[str] | None = None
    budget: str | None = None

    def render(self) -> str:
        now = _in_timezone(self.now)
        nodes = UNKNOWN if self.nodes is None else (", ".join(self.nodes) or NONE_LIVE)
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


_CONTEXT_FIELDS = frozenset(f.name for f in fields(DynamicContext))


@dataclass(frozen=True)
class Persona:
    persona: str
    user: str | None


def _clean(text: str) -> str:
    """Drop HTML comments (notes for humans), squeeze the blank lines they leave, strip."""
    text = _COMMENT.sub("", text)
    return _BLANK_RUNS.sub("\n\n", text).strip()


class _Problems:
    """Logs a warning the first time a problem appears and again only after it cleared."""

    def __init__(self) -> None:
        self._active: dict[str, str] = {}

    def report(self, key: str, message: str, *args: Any, exc_info: bool = False) -> None:
        text = message % args if args else message
        if self._active.get(key) == text:
            logger.debug(text)
            return
        self._active[key] = text
        logger.warning(text, exc_info=exc_info)

    def clear(self, key: str) -> None:
        if self._active.pop(key, None) is not None:
            logger.info("%s: recovered", key)


class _CachedFile:
    """A text file re-read only when its ``(st_mtime_ns, st_size)`` stamp changes."""

    def __init__(self, path: Path):
        self.path = path
        self._stamp: tuple[int, int] | None = None
        self._text: str | None = None

    def read(self) -> str | None:
        """The cleaned text, ``None`` when the file does not exist.

        Raises ``OSError``/``UnicodeDecodeError`` when the file exists but cannot be read; the
        stamp is then left alone so the next call tries again.
        """
        try:
            stat = self.path.stat()
        except FileNotFoundError:
            self._stamp, self._text = None, None
            return None
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp != self._stamp:
            text = _clean(self.path.read_text(encoding="utf-8-sig"))
            self._stamp, self._text = stamp, text
            logger.debug("persona file loaded: %s", self.path.name)
        return self._text


class PersonaLoader:
    """Reads ``persona.md`` and ``user.md`` from ``persona_dir`` and assembles the prompt."""

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
        self._problems = _Problems()

    @property
    def persona_path(self) -> Path:
        return self._persona.path

    @property
    def user_path(self) -> Path:
        return self._user.path

    def read(self) -> Persona:
        """Current persona; files are re-read only when (mtime, size) changed."""
        current = Persona(persona=self._read_persona(), user=self._read_user())
        self._last = current
        return current

    def _read_persona(self) -> str:
        path = self._persona.path
        try:
            text = self._persona.read()
        except (OSError, UnicodeDecodeError) as exc:
            if self._last is None:
                raise ConfigError(f"Persona dosyası okunamadı: {path} ({exc})") from exc
            self._problems.report(
                str(path), "cannot read %s (%s); keeping the last version", path, exc
            )
            return self._last.persona
        if not text:
            if self._last is None:
                if text is None:
                    raise ConfigError(f"Persona dosyası bulunamadı: {path}")
                raise ConfigError(f"Persona dosyası boş: {path}")
            state = "is missing" if text is None else "is empty"
            self._problems.report(str(path), "%s %s; keeping the last version", path, state)
            return self._last.persona
        self._problems.clear(str(path))
        return text

    def _read_user(self) -> str | None:
        path = self._user.path
        try:
            text = self._user.read()
        except (OSError, UnicodeDecodeError) as exc:
            self._problems.report(
                str(path), "cannot read %s (%s); keeping the last version", path, exc
            )
            return self._last.user if self._last is not None else None
        self._problems.clear(str(path))
        return text or None  # missing or empty: no facts, default address "siz"

    def build_system_prompt(self, context: DynamicContext) -> str:
        current = self.read()
        user = current.user or NO_USER_FILE
        return f"{current.persona}\n\n## Kullanıcı\n{user}\n\n## Şu an\n{context.render()}"


class PersonaHook(HookProvider):
    """Sets ``agent.system_prompt`` before every model call.

    If assembling the prompt fails anyway (a broken clock, a custom loader), the previous
    prompt stays in place and the turn goes on; the error is logged.
    """

    def __init__(self, loader: PersonaLoader, context_factory: Callable[[], DynamicContext]):
        self.loader = loader
        self.context_factory = context_factory
        self._problems = _Problems()

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeModelCallEvent, self._before_model_call)

    def _before_model_call(self, event: BeforeModelCallEvent) -> None:
        try:
            prompt = self.loader.build_system_prompt(self.context_factory())
        except Exception as exc:
            self._problems.report(
                "system prompt",
                "could not rebuild the system prompt (%r); keeping the previous one",
                exc,
                exc_info=True,
            )
            return
        self._problems.clear("system prompt")
        event.agent.system_prompt = prompt


def _normalize(overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Known keys only, with the types :class:`DynamicContext` expects."""
    known = {key: value for key, value in overrides.items() if key in _CONTEXT_FIELDS}
    for key in ("profile", "role"):
        if key in known:
            if known[key] is None:  # both are always known; None cannot mean "unknown" here
                del known[key]
            else:
                known[key] = str(known[key])
    if known.get("nodes") is not None:
        nodes = known["nodes"]
        known["nodes"] = [nodes] if isinstance(nodes, str) else [str(node) for node in nodes]
    if known.get("budget") is not None:
        known["budget"] = str(known["budget"])
    if "now" in known and not isinstance(known["now"], datetime):
        raise TypeError(f"'now' must be a datetime, got {type(known['now']).__name__}")
    return known


def default_context_factory(
    config: Config,
    *,
    clock: Callable[[], datetime] | None = None,
    sources: Iterable[ContextSource] = (),
) -> Callable[[], DynamicContext]:
    """Time (Europe/Istanbul), profile and host role; ``sources`` are merged in order.

    The returned factory is called before every model call, so it re-reads ``clock`` and every
    source each time. ``clock`` may return an aware datetime (converted) or a naive one (taken
    as Istanbul time).
    """
    source_list = list(sources)
    problems = _Problems()

    def factory() -> DynamicContext:
        now = clock() if clock is not None else datetime.now(TIMEZONE)
        context = DynamicContext(now=now, profile=config.profile, role=config.role)
        for index, source in enumerate(source_list):
            name = getattr(source, "__name__", type(source).__name__)
            key = f"context source {index} ({name})"
            try:
                overrides = source()
                if overrides is None:
                    overrides = {}
                if not isinstance(overrides, Mapping):
                    raise TypeError(f"returned {type(overrides).__name__}, not a mapping")
                context = replace(context, **_normalize(overrides))
            except Exception as exc:
                problems.report(key, "%s failed (%r); ignoring it", key, exc, exc_info=True)
                continue
            problems.clear(key)
        return replace(context, now=_in_timezone(context.now))

    return factory
