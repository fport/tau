"""The parts of ``tau setup`` the terminal wizard and the JSON mode share.

- :func:`install_plan` builds the one ``uv tool install --force tau-core==<version> --with …``
  that turns the installed set into the wanted one (lockstep packages pinned to the running
  tau-core, the others left to uv's resolver, anything else in the receipt kept).
- :func:`write_state` / :func:`read_state` carry the wizard across its re-execution in the new
  environment: a JSON file of mode 0600 in a fresh temporary directory, removed when read.
- :func:`preflight`, :func:`step_argv` and :func:`store_secrets` decide whether a step can run,
  build its argv from the inputs and put secret inputs into ``<home>/.env``, never argv.
- :func:`write_user_md` writes "about you" into ``persona/user.md``.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tau_core.builder import write_env_key
from tau_core.setup.catalog import Catalog, Feature, Input, Step
from tau_core.setup.host import Host
from tau_core.setup.state import Snapshot, expand

__all__ = [
    "STATE_VERSION",
    "InstallPlan",
    "Outcome",
    "ResumeError",
    "Skip",
    "command_text",
    "find_uv",
    "install_plan",
    "new_tau",
    "parse_ids",
    "preflight",
    "read_state",
    "render_user_md",
    "step_argv",
    "store_secrets",
    "write_state",
    "write_user_md",
]

STATE_VERSION = 1
STATE_LIMIT = 64 * 1024
USER_MD_FIELD = 200
"""The longest value "about you" keeps for one line of ``user.md``."""


# -- the install -----------------------------------------------------------------------------


@dataclass(frozen=True)
class InstallPlan:
    uv: str | None
    argv: tuple[str, ...]
    """The uv command; empty when uv was not found."""
    packages: tuple[str, ...]
    """Every feature package of the environment after the install, in catalog order."""
    added: tuple[str, ...]
    removed: tuple[str, ...]
    upgrade: bool = False


def find_uv(host: Host) -> str | None:
    """``uv`` on ``PATH``, else where Astral's installer puts it."""
    found = host.which("uv")
    if found:
        return found
    user = host.environ.get("HOME")
    candidates = [host.environ.get("UV_INSTALL_DIR", "")]
    if user:
        candidates += [f"{user}/.local/bin", f"{user}/.cargo/bin"]
    for directory in candidates:
        if (
            directory
            and Path(directory, "uv").is_file()
            and os.access(Path(directory, "uv"), os.X_OK)
        ):
            return str(Path(directory, "uv"))
    return None


def install_plan(
    catalog: Catalog,
    snapshot: Snapshot,
    host: Host,
    *,
    add: Iterable[str] = (),
    remove: Iterable[str] = (),
    upgrade: bool = False,
) -> InstallPlan:
    """The command that installs the packages of the features ``add`` and uninstalls those of
    ``remove``, keeping every other installed feature package and every other requirement in
    the uv tool receipt. ``upgrade`` drops the pins and lets uv take the newest releases."""
    installed = {s.feature.package for s in snapshot.features if s.feature.package and s.installed}
    wanted_add = {
        feature.package
        for feature_id in add
        if (feature := catalog.get(feature_id)) is not None and feature.package
    }
    wanted_remove = {
        feature.package
        for feature_id in remove
        if (feature := catalog.get(feature_id)) is not None and feature.package
    }
    target = (installed | wanted_add) - wanted_remove
    packages = tuple(p for p in catalog.packages() if p in target)
    added = tuple(p for p in packages if p not in installed)
    removed = tuple(p for p in catalog.packages() if p in installed and p not in target)
    uv = find_uv(host)
    if uv is None:
        return InstallPlan(None, (), packages, added, removed, upgrade)
    version = snapshot.version
    lockstep = {f.package for f in catalog.features if f.lockstep and f.package}
    argv: list[str] = [uv, "tool", "install", "--force"]
    if upgrade:
        argv.append("--upgrade")
    receipt = snapshot.receipt
    if receipt is not None and receipt.python:
        argv += ["--python", receipt.python]
    argv.append("tau-core" if upgrade else f"tau-core=={version}")
    for package in packages:
        pinned = package in lockstep and not upgrade
        argv += ["--with", f"{package}=={version}" if pinned else package]
    known = {"tau-core", *catalog.packages()}
    for requirement in receipt.requirements if receipt is not None else ():
        if requirement.name not in known and requirement.spec:
            argv += ["--with", requirement.spec]
    return InstallPlan(uv, tuple(argv), packages, added, removed, upgrade)


def new_tau(host: Host, uv: str) -> str | None:
    """The ``tau`` that ``uv tool install`` just wrote: ``$(uv tool dir --bin)/tau``, else
    ``tau`` on ``PATH``."""
    code, out = host.capture([uv, "tool", "dir", "--bin"])
    if code == 0 and out.strip():
        candidate = Path(out.strip().splitlines()[-1]) / "tau"
        if candidate.is_file():
            return str(candidate)
    return host.which("tau")


# -- the resume file ----------------------------------------------------------------------------


class ResumeError(ValueError):
    """The resume file cannot be used; the message says why (in English, for the log)."""


def write_state(data: Mapping[str, Any]) -> Path:
    """``data`` as ``<fresh temp dir>/state.json``: the directory 0700, the file 0600."""
    directory = Path(tempfile.mkdtemp(prefix="tau-setup-"))
    path = directory / "state.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"v": STATE_VERSION, **data}, handle)
    return path


def read_state(path: Path) -> dict[str, Any]:
    """The state written by :func:`write_state`, then the file and its directory are removed.

    Refused: a symlink, anything but a regular file owned by this user with no group or other
    permission bits, more than 64 KiB, or JSON that is not a version-1 object. The checks run
    on the open file (``O_NOFOLLOW`` and ``fstat``), so the file cannot be swapped between the
    check and the read."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ResumeError(exc.strerror or "cannot be read") from None
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ResumeError("not a regular file")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise ResumeError("owned by another user")
        if info.st_mode & 0o077:
            raise ResumeError("open to other users")
        if info.st_size > STATE_LIMIT:
            raise ResumeError("too large")
        raw = handle.read(STATE_LIMIT + 1)
    path.unlink(missing_ok=True)
    if path.parent.name.startswith("tau-setup-"):
        try:
            path.parent.rmdir()
        except OSError:
            pass
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise ResumeError(f"not JSON: {exc}") from None
    if not isinstance(data, dict) or data.get("v") != STATE_VERSION:
        raise ResumeError("not a tau setup state")
    return data


# -- steps ---------------------------------------------------------------------------------------


@dataclass
class Outcome:
    """What happened to one step (or one core step: ``init``, ``about``, ``doctor``)."""

    feature: str
    step: str
    label: str
    status: str
    """``done``, ``failed``, ``skipped``, ``info`` (a note) or ``needs_ui``."""
    reason: str | None = None
    """Machine code for skipped and failed: ``platform``, ``ssh``, ``missing_command``,
    ``needs``, ``declined``, ``optional``, ``interactive``, ``no_input``, ``not_installed``,
    ``configured``, ``unavailable``, ``exit``, ``start``, ``interrupted``, ``advisory``."""
    detail: str = ""
    """The localized explanation shown to the owner."""
    code: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    brief: str = ""
    """``detail`` without the longer explanation, for the summary."""

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"step": self.step, "status": self.status}
        if self.reason:
            payload["reason"] = self.reason
        if self.detail:
            payload["detail"] = self.detail
        if self.code is not None:
            payload["code"] = self.code
        payload.update(self.extra)
        return payload


@dataclass(frozen=True)
class Skip:
    reason: str
    fields: dict[str, str] = field(default_factory=dict)
    text_key: str | None = None
    """A catalog text (``unavailable``, ``needs_text``) to show with the skip."""


def command_text(words: Sequence[str]) -> str:
    return " ".join(words)


def preflight(step: Step, feature: Feature, host: Host) -> Skip | None:
    """Why ``step`` cannot run here, or ``None`` when it can."""
    if not step.applies_to(host.platform, feature.platforms):
        return Skip("platform", {"platform": host.platform})
    if step.local_only and host.over_ssh():
        return Skip("ssh", {"command": command_text(step.command)})
    if step.when_command:
        code, _ = host.capture([*host.tau(), *step.when_command, "--help"])
        if code != 0:
            return Skip(
                "missing_command",
                {"command": command_text(step.when_command)},
                step.unavailable,
            )
    missing = [program for program in step.needs if host.which(program) is None]
    if missing:
        return Skip("needs", {"programs": ", ".join(missing)}, step.needs_text)
    return None


def input_value(item: Input, values: Mapping[str, str], environ: Mapping[str, str]) -> str:
    value = (values.get(item.name) or "").strip() or item.default
    if item.path and value:
        value = str(expand(value, home=Path("."), data=Path("."), environ=environ))
    return value


def step_argv(
    step: Step, values: Mapping[str, str], environ: Mapping[str, str]
) -> tuple[list[str], str | None]:
    """``(tau arguments, None)``, or ``([], name)`` for the first required input that has no
    value. Secret inputs never appear here."""
    positional: list[str] = []
    flags: list[str] = []
    for item in step.inputs:
        if item.secret:
            if item.required and not (values.get(item.name) or "").strip():
                return [], item.name
            continue
        value = input_value(item, values, environ)
        if not value:
            if item.required:
                return [], item.name
            continue
        if item.positional:
            positional.append(value)
        else:
            assert item.flag is not None
            flags += [item.flag, value]
    return [*step.command, *positional, *flags], None


def store_secrets(step: Step, values: Mapping[str, str], home: Path) -> list[tuple[str, bool]]:
    """Write every secret input with a value to ``<home>/.env`` (mode 0600); ``[(NAME,
    written)]``, where ``written`` is ``False`` when the name already had a value."""
    stored: list[tuple[str, bool]] = []
    for item in step.inputs:
        value = (values.get(item.name) or "").strip()
        if not item.secret or not value:
            continue
        assert item.env is not None
        home.mkdir(parents=True, exist_ok=True)
        stored.append((item.env, write_env_key(home, item.env, value)))
    return stored


# -- about you ---------------------------------------------------------------------------------

USER_MD_HEADER = """<!--
Facts about you for tau, written by `tau setup`. This file stays on this machine (it is
gitignored in a repository checkout). Edit it freely: an edit takes effect on the next model
call, and HTML comments like this one never reach the model. persona/user.example.md shows
more kinds of facts.
-->
"""


def _one_line(value: str) -> str:
    text = " ".join(value.split())
    text = text.replace("<!--", "").replace("-->", "")
    return text[:USER_MD_FIELD]


def render_user_md(*, name: str, address: str = "", languages: str = "") -> str:
    """``persona/user.md`` for "about you": the header, then one line per answer. The labels
    are English because the model reads them."""
    lines = [USER_MD_HEADER.rstrip("\n")]
    for label, value in (
        ("Name", name),
        ("Form of address", address),
        ("Languages", languages),
    ):
        value = _one_line(value)
        if value:
            lines.append(f"- {label}: {value}")
    return "\n".join(lines) + "\n"


def write_user_md(home: Path, text: str) -> Path:
    """Write ``persona/user.md`` atomically at mode 0600."""
    persona = home / "persona"
    persona.mkdir(parents=True, exist_ok=True)
    path = persona / "user.md"
    fd, tmp = tempfile.mkstemp(dir=persona, prefix=".user.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


# -- feature ids -------------------------------------------------------------------------------

_SPLIT = re.compile(r"[,\s]+")


def parse_ids(values: Iterable[str]) -> list[str]:
    """``["tui,sub", "net"]`` → ``["tui", "sub", "net"]`` (order kept, duplicates dropped)."""
    seen: list[str] = []
    for value in values:
        for part in _SPLIT.split(value.strip()):
            if part and part not in seen:
                seen.append(part)
    return seen
