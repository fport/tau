"""Sub-tau definitions: ``persona/subs/<name>.md`` (ADR 0012).

A definition is TOML front matter between two ``+++`` lines, then the persona text::

    +++
    about = "A strict but kind workout coach who plans three short sessions a week."
    role = "brain"                      # brain | fast | local (default brain)
    tools = ["current_time"]            # names from the tool catalog (default none)
    public = false                      # contacts reach it as <address>/<name> (default false)
    # public_note = "coach.public.md"   # optional, a file next to the definition
    +++

    You plan the owner's workouts: ...

The file name is the name (``coach.md`` is ``/coach``); names match ``[a-z][a-z0-9-]{1,30}``.
The front matter is parsed with :mod:`tomllib` and nothing in it reaches the model; the
persona text does (HTML comments stripped, like ``persona.md``). Loading validates
everything: unknown keys, types, the role, the ``about`` length and every tool name, which
must be in the tool catalog. ``ask_sub`` and ``create_sub`` are never allowed, so a sub-tau
cannot call or create other sub-taus.

Definitions are the owner's files: gitignored in this repository like ``user.md``, written
atomically with mode 0600 in a 0700 directory, and never overwritten without ``force``.
Every error message is plain English: it is raised before a channel exists.
"""

from __future__ import annotations

import logging
import re
import tomllib
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from strands.types.tools import AgentTool
from tau_core import Config, UntieredToolError, tier_of
from tau_core.agent import discovered_tools

from tau_sub._files import private_dir, write_private

__all__ = [
    "ABOUT_LIMIT",
    "DEFAULT_ROLE",
    "FENCE",
    "FORBIDDEN_TOOLS",
    "KEYS",
    "NAME_RE",
    "PERSONA_LIMIT",
    "ROLES",
    "SUBS_DIR",
    "ForbiddenToolError",
    "SubRegistry",
    "SubTau",
    "SubTauError",
    "SubTauExists",
    "SubTauNotFound",
    "UnknownToolError",
    "parse",
    "render",
    "split_front_matter",
    "template",
    "tool_catalog",
    "validate",
    "validate_name",
]

logger = logging.getLogger(__name__)

NAME_RE = re.compile(r"[a-z][a-z0-9-]{1,30}")
"""A sub-tau name, matched with ``fullmatch`` (ADR 0012: ``^[a-z][a-z0-9-]{1,30}$``)."""
ROLES = ("brain", "fast", "local")
DEFAULT_ROLE = "brain"
ABOUT_LIMIT = 200
PERSONA_LIMIT = 20_000
"""Characters of persona text; a definition is a prompt, not a document."""
FENCE = "+++"
SUBS_DIR = "subs"
SUFFIX = ".md"
KEYS = ("about", "role", "tools", "public", "public_note")
FORBIDDEN_TOOLS = frozenset({"ask_sub", "create_sub"})
"""Never in a sub-tau's allowlist: a sub-tau cannot call or create other sub-taus."""

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_NOTE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.md")


class SubTauError(ValueError):
    """An invalid, missing or conflicting sub-tau definition; the message is for the owner."""


class UnknownToolError(SubTauError):
    """A tool name that is not in the tool catalog; ``tool`` is the name."""

    def __init__(self, name: str, tool: str):
        self.name = name
        self.tool = tool
        super().__init__(
            f"/{name}: unknown tool '{tool}': it is not in the tool catalog "
            "(`tau components` lists the installed tools)."
        )


class ForbiddenToolError(SubTauError):
    """``ask_sub`` or ``create_sub`` in an allowlist."""

    def __init__(self, name: str, tool: str):
        self.name = name
        self.tool = tool
        super().__init__(
            f"/{name}: the tool '{tool}' is never allowed in a sub-tau "
            "(a sub-tau cannot call or create other sub-taus)."
        )


class SubTauNotFound(SubTauError):
    def __init__(self, name: str, path: Path):
        self.name = name
        self.path = path
        super().__init__(f"There is no sub-tau named /{name} ({path} does not exist).")


class SubTauExists(SubTauError):
    def __init__(self, name: str, path: Path):
        self.name = name
        self.path = path
        super().__init__(f"/{name} already exists ({path}); pass --force to replace it.")


@dataclass(frozen=True)
class SubTau:
    """One sub-tau. ``persona`` is the text after the front matter, as written."""

    name: str
    about: str
    persona: str
    role: str = DEFAULT_ROLE
    tools: tuple[str, ...] = ()
    public: bool = False
    public_note: str | None = None
    path: Path | None = field(default=None, compare=False)
    """Where the definition was read from, when it was read from a file."""

    @property
    def slash(self) -> str:
        """``/name``, how the owner and the universe show it."""
        return f"/{self.name}"

    @property
    def channel(self) -> str:
        """The channel its sessions are recorded on: ``sub:<name>``."""
        return f"sub:{self.name}"


def validate_name(name: object) -> str:
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise SubTauError(
            f"Invalid sub-tau name {name!r}: use 2 to 31 characters (lowercase letters, digits "
            "and '-'), starting with a letter."
        )
    return name


def _about(name: str, about: object) -> str:
    if not isinstance(about, str):
        raise SubTauError(f"/{name}: 'about' must be a string.")
    line = " ".join(about.split())
    if not line:
        raise SubTauError(f"/{name}: 'about' is empty; say in one line what /{name} does.")
    if len(line) > ABOUT_LIMIT:
        raise SubTauError(
            f"/{name}: 'about' is {len(line)} characters; the limit is {ABOUT_LIMIT}."
        )
    return line


def _persona(name: str, persona: object) -> str:
    if not isinstance(persona, str):
        raise SubTauError(f"/{name}: the persona must be text.")
    text = persona.replace("\r\n", "\n").strip()
    if not _COMMENT.sub("", text).strip():
        raise SubTauError(
            f"/{name}: the persona text after the front matter is empty; describe the "
            "specialist's character and task there."
        )
    if len(text) > PERSONA_LIMIT:
        raise SubTauError(
            f"/{name}: the persona is {len(text)} characters; the limit is {PERSONA_LIMIT}."
        )
    return text


def _tools(name: str, tools: object, catalog: Collection[str] | None) -> tuple[str, ...]:
    if isinstance(tools, str) or not isinstance(tools, list | tuple):
        raise SubTauError(f"/{name}: 'tools' must be a list of tool names.")
    kept: list[str] = []
    for tool in tools:
        if not isinstance(tool, str) or not tool.strip():
            raise SubTauError(f"/{name}: 'tools' must hold tool names, not {tool!r}.")
        tool = tool.strip()
        if tool in FORBIDDEN_TOOLS:
            raise ForbiddenToolError(name, tool)
        if catalog is not None and tool not in catalog:
            raise UnknownToolError(name, tool)
        if tool not in kept:
            kept.append(tool)
    return tuple(kept)


def _public_note(name: str, note: object) -> str | None:
    if note is None:
        return None
    if not isinstance(note, str):
        raise SubTauError(f"/{name}: 'public_note' must be a file name.")
    note = note.strip()
    # A plain .md file next to the definitions, whose name can never be read as a definition.
    if not _NOTE_RE.fullmatch(note) or NAME_RE.fullmatch(note.removesuffix(SUFFIX)):
        raise SubTauError(
            f"/{name}: 'public_note' must be a file name in persona/{SUBS_DIR}/ ending in .md "
            f"that is not itself a sub-tau name, for example '{name}.public.md'; got {note!r}."
        )
    return note


def validate(sub: SubTau, *, catalog: Collection[str] | None = None) -> SubTau:
    """Check every field and return a normalized copy; ``catalog`` is the known tool names
    (``None`` skips that check, e.g. for a definition shown while the catalog is unknown)."""
    name = validate_name(sub.name)
    if sub.role not in ROLES:
        raise SubTauError(f"/{name}: unknown role {sub.role!r}; use one of {', '.join(ROLES)}.")
    if not isinstance(sub.public, bool):
        raise SubTauError(f"/{name}: 'public' must be true or false.")
    return replace(
        sub,
        about=_about(name, sub.about),
        persona=_persona(name, sub.persona),
        tools=_tools(name, sub.tools, catalog),
        public_note=_public_note(name, sub.public_note),
    )


def split_front_matter(text: str) -> tuple[str, str]:
    """``(front matter, persona text)``; the file must open with a ``+++`` block."""
    lines = text.lstrip("﻿").replace("\r\n", "\n").split("\n")
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines) or lines[start].strip() != FENCE:
        raise SubTauError(
            f"A sub-tau definition must start with TOML front matter between two '{FENCE}' lines."
        )
    for end in range(start + 1, len(lines)):
        if lines[end].strip() == FENCE:
            return "\n".join(lines[start + 1 : end]), "\n".join(lines[end + 1 :])
    raise SubTauError(f"The front matter is not closed: add a '{FENCE}' line after it.")


def parse(
    name: str, text: str, *, catalog: Collection[str] | None = None, path: Path | None = None
) -> SubTau:
    """Parse and validate the definition of ``name`` (the file name without ``.md``)."""
    validate_name(name)
    try:
        front, body = split_front_matter(text)
    except SubTauError as exc:
        raise SubTauError(f"/{name}: {exc}") from None
    try:
        data: dict[str, Any] = tomllib.loads(front)
    except tomllib.TOMLDecodeError as exc:
        raise SubTauError(f"/{name}: the front matter is not valid TOML: {exc}") from None
    unknown = sorted(set(data) - set(KEYS))
    if unknown:
        raise SubTauError(
            f"/{name}: unknown key {unknown[0]!r} in the front matter (known: {', '.join(KEYS)})."
        )
    if "about" not in data:
        raise SubTauError(f"/{name}: 'about' is missing from the front matter.")
    role = data.get("role", DEFAULT_ROLE)
    if not isinstance(role, str):
        raise SubTauError(f"/{name}: 'role' must be a string.")
    tools = data.get("tools", [])
    sub = SubTau(
        name=name,
        about=data["about"],
        persona=body,
        role=role,
        tools=tools if not isinstance(tools, list) else tuple(tools),
        public=data.get("public", False),
        public_note=data.get("public_note"),
        path=path,
    )
    return validate(sub, catalog=catalog)


def _toml_string(value: str) -> str:
    """A TOML basic string (tomllib reads it back unchanged)."""
    out = ['"']
    for ch in value:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def render(sub: SubTau) -> str:
    """The file text of a definition; :func:`parse` reads it back to an equal ``SubTau``."""
    lines = [
        FENCE,
        f"about = {_toml_string(sub.about)}",
        f"role = {_toml_string(sub.role)}",
        "tools = [" + ", ".join(_toml_string(tool) for tool in sub.tools) + "]",
        f"public = {'true' if sub.public else 'false'}",
    ]
    if sub.public_note:
        lines.append(f"public_note = {_toml_string(sub.public_note)}")
    lines.append(FENCE)
    return "\n".join(lines) + "\n\n" + sub.persona.strip() + "\n"


TEMPLATE_ABOUT = "A specialist of your tau; say in one line what /{name} does."
TEMPLATE_PERSONA = """\
<!--
The persona of /{name}: its character and the one task it helps with, written to it in the
second person ("You plan ...", "You answer ..."). The front matter above sets its one-line
about, its model role and the tools it may use (`tau components` lists them). HTML comments
like this one never reach the model. `tau sub edit {name}` opens this file and checks it.
-->
Help your owner with the task in your about line. Keep answers short and concrete, and ask
one short question when something important is unclear.
"""


def template(
    name: str,
    *,
    about: str | None = None,
    role: str = DEFAULT_ROLE,
    tools: Iterable[str] = (),
    public: bool = False,
) -> SubTau:
    """A starter definition for ``tau sub new NAME`` without ``--describe``."""
    validate_name(name)
    return SubTau(
        name=name,
        about=about or TEMPLATE_ABOUT.format(name=name),
        persona=TEMPLATE_PERSONA.format(name=name),
        role=role,
        tools=tuple(tools),
        public=public,
    )


def tool_catalog(config: Config, tools: Iterable[AgentTool] | None = None) -> dict[str, AgentTool]:
    """The tools a sub-tau may name: every ``tau.tools`` tool that is switched on in
    ``[components]`` and declares a tier, minus :data:`FORBIDDEN_TOOLS`. ``tools`` replaces
    the discovered ones (tests, embedding code)."""
    source = discovered_tools(config) if tools is None else list(tools)
    catalog: dict[str, AgentTool] = {}
    for tool in source:
        name = tool.tool_name
        if name in FORBIDDEN_TOOLS:
            continue
        try:
            tier_of(tool)
        except UntieredToolError:
            logger.warning("sub: tool %s declares no tier; sub-taus cannot use it", name)
            continue
        catalog[name] = tool
    return catalog


class SubRegistry:
    """The sub-tau definitions under ``persona/subs/``.

    ``tools`` replaces the discovered tool catalog, which is otherwise read once, on first use.
    """

    def __init__(self, config: Config, *, tools: Iterable[AgentTool] | None = None):
        self.config = config
        self._tools = list(tools) if tools is not None else None
        self._catalog: dict[str, AgentTool] | None = None

    @property
    def directory(self) -> Path:
        return self.config.persona_dir / SUBS_DIR

    def path(self, name: str) -> Path:
        return self.directory / f"{validate_name(name)}{SUFFIX}"

    def catalog(self) -> Mapping[str, AgentTool]:
        """Tool name → tool, for the tools a sub-tau may use."""
        if self._catalog is None:
            self._catalog = tool_catalog(self.config, self._tools)
        return self._catalog

    def names(self) -> list[str]:
        """The names of every definition file, valid or not, sorted."""
        try:
            entries = list(self.directory.iterdir())
        except (FileNotFoundError, NotADirectoryError):
            return []
        return sorted(
            entry.stem
            for entry in entries
            if entry.suffix == SUFFIX and NAME_RE.fullmatch(entry.stem) and entry.is_file()
        )

    def exists(self, name: str) -> bool:
        return self.path(name).is_file()

    def get(self, name: str) -> SubTau:
        """The validated definition of ``name``; :class:`SubTauError` when it is missing or
        invalid (an :class:`UnknownToolError` names the tool)."""
        path = self.path(name)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise SubTauNotFound(name, path) from None
        except (OSError, UnicodeDecodeError) as exc:
            raise SubTauError(f"/{name}: {path} cannot be read ({exc}).") from None
        return parse(name, text, catalog=self.catalog(), path=path)

    def scan(self) -> tuple[list[SubTau], dict[str, SubTauError]]:
        """Every valid definition, and the error of every invalid one by name."""
        subs: list[SubTau] = []
        broken: dict[str, SubTauError] = {}
        for name in self.names():
            try:
                subs.append(self.get(name))
            except SubTauError as exc:
                broken[name] = exc
        return subs, broken

    def list(self) -> list[SubTau]:
        """Every valid definition, sorted by name; invalid ones are logged and left out."""
        subs, broken = self.scan()
        for name, error in broken.items():
            logger.warning("sub: skipping /%s: %s", name, error)
        return subs

    def save(self, sub: SubTau, *, force: bool = False) -> Path:
        """Validate and write ``sub``; an existing definition is replaced only with ``force``."""
        checked = validate(sub, catalog=self.catalog())
        path = self.path(checked.name)
        private_dir(self.directory)
        try:
            write_private(path, render(checked), overwrite=force)
        except FileExistsError:
            raise SubTauExists(checked.name, path) from None
        return path

    def remove(self, name: str) -> Path:
        """Delete the definition file only; sessions and state under TAU_DATA_DIR stay."""
        path = self.path(name)
        try:
            path.unlink()
        except FileNotFoundError:
            raise SubTauNotFound(name, path) from None
        return path
