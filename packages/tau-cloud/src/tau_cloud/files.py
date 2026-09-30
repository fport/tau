"""The file set cloud mode keeps in the spine (KV) and the helpers that move it.

The set is named relative to the configuration root (``TAU_HOME``), §5 "Files" of
``docs/reference/tau-network.md``: four fixed files,

- ``tau.toml``
- ``persona/persona.md``
- ``persona/user.md`` (private: it only goes up when the owner says so, see ``tau cloud push``)
- ``persona/net.md`` (the public note of the tau network)

and the sub-tau files (ADR 0012): ``persona/subs/<file>``, where ``<file>`` is a plain name
ending in ``.md`` (:data:`SUB_FILE_PATTERN`: sub-tau definitions such as ``coach.md`` and their
public notes such as ``coach.public.md``), directly in that directory.

Nothing outside this set is ever read or sent: every helper refuses another name before it
touches the disk or the network, and ``.env`` (credentials) is never part of it. Files are
UTF-8 text of at most 512 KiB, the spine's limit. :func:`scan_subs` lists what a push may send
from ``persona/subs/`` and refuses the rest (odd names, subdirectories, symbolic links).
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
from tau_net.spine import SpineClient, SpineError
from tomlkit.items import InlineTable, Table

__all__ = [
    "CONFIG_FILE",
    "FILE_NAMES",
    "MAX_FILE_BYTES",
    "PRIVATE_FILES",
    "SUBS_DIR",
    "SUB_FILE_PATTERN",
    "USER_FILE",
    "FileError",
    "LocalFile",
    "Refused",
    "RemoteFile",
    "RemoteListing",
    "WriteResult",
    "check_name",
    "cloud_config",
    "delete_remote",
    "download",
    "is_sub_file",
    "list_remote",
    "local_path",
    "read_local",
    "remote_listing",
    "scan_subs",
    "upload",
    "write_local",
]

CONFIG_FILE = "tau.toml"
USER_FILE = "persona/user.md"
FILE_NAMES: tuple[str, ...] = (
    CONFIG_FILE,
    "persona/persona.md",
    USER_FILE,
    "persona/net.md",
)
"""The fixed files of the set, in upload order."""
SUBS_DIR = "persona/subs"
"""The sub-tau files' directory (ADR 0012), relative to the configuration root."""
SUB_FILE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.md")
"""The name of a sub-tau file directly in :data:`SUBS_DIR` (``fullmatch``): a definition
(``coach.md``) or a public note (``coach.public.md``). No slash, no leading dot."""
PRIVATE_FILES = frozenset({USER_FILE})
"""Written with mode 0600 when pulled: what tau knows about its owner. Sub-tau files are
written 0600 too, in a 0700 directory, like ``tau sub`` writes them."""
MAX_FILE_BYTES = 512 * 1024
_SUBS_PREFIX = SUBS_DIR + "/"


class FileError(ValueError):
    """A file of the set that cannot be read, sent or written; the message is for the user."""


def is_sub_file(name: str) -> bool:
    """``persona/subs/<file>`` with a valid ``<file>`` (:data:`SUB_FILE_PATTERN`)."""
    return name.startswith(_SUBS_PREFIX) and bool(
        SUB_FILE_PATTERN.fullmatch(name[len(_SUBS_PREFIX) :])
    )


def check_name(name: str) -> str:
    """``name`` when it belongs to the file set, else :class:`FileError`."""
    if name not in FILE_NAMES and not is_sub_file(name):
        known = ", ".join((*FILE_NAMES, f"{_SUBS_PREFIX}<name>.md"))
        raise FileError(f"{name!r} is not one of the cloud-mode files ({known}).")
    return name


def local_path(home: Path, name: str) -> Path:
    """Where ``name`` lives under the configuration root ``home``."""
    return Path(home) / check_name(name)


@dataclass(frozen=True)
class LocalFile:
    name: str
    path: Path
    text: str

    @property
    def size(self) -> int:
        return len(self.text.encode("utf-8"))


@dataclass(frozen=True)
class RemoteFile:
    """One entry of ``GET /hub/files``."""

    name: str
    size: int
    updated_at: int


def read_local(home: Path, name: str) -> LocalFile | None:
    """The local copy of ``name``, ``None`` when there is none. :class:`FileError` for one
    that is not a regular file, not UTF-8 or larger than :data:`MAX_FILE_BYTES`."""
    path = local_path(home, name)
    if is_sub_file(name) and path.is_symlink():
        # A link could send any file, persona/user.md included, under a sub-tau's name.
        raise FileError(f"{path} is a symbolic link.")
    if not path.exists():
        return None
    if not path.is_file():
        raise FileError(f"{path} is not a regular file.")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise FileError(f"{path} cannot be read: {exc.strerror or exc}") from None
    if len(data) > MAX_FILE_BYTES:
        raise FileError(f"{path} is larger than {MAX_FILE_BYTES // 1024} KiB.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise FileError(f"{path} is not UTF-8 text.") from None
    return LocalFile(name, path, text)


def upload(spine: SpineClient, file: LocalFile) -> RemoteFile:
    """``PUT /hub/files/<name>``; :class:`tau_net.spine.SpineError` when the spine says no."""
    data = spine.call("PUT", f"/hub/files/{check_name(file.name)}", body=file.text)
    size = data.get("size") if isinstance(data, dict) else None
    updated = data.get("updated_at") if isinstance(data, dict) else None
    return RemoteFile(
        file.name,
        size if isinstance(size, int) else file.size,
        updated if isinstance(updated, int) else 0,
    )


def download(spine: SpineClient, name: str) -> str | None:
    """The spine's copy of ``name``, ``None`` when it holds none."""
    response = spine.request("GET", f"/hub/files/{check_name(name)}")
    if response.status == 404 and response.error()[0] == "not_found":
        return None
    if not response.ok:
        code, detail = response.error()
        raise SpineError(response.status, code, detail)
    try:
        return response.body.decode("utf-8")
    except UnicodeDecodeError:
        raise SpineError(response.status, "bad_text", f"{name} is not UTF-8 text") from None


def delete_remote(spine: SpineClient, name: str) -> bool:
    """``DELETE /hub/files/<name>``; ``True`` when the spine held the file."""
    data = spine.call("DELETE", f"/hub/files/{check_name(name)}")
    return bool(data.get("deleted")) if isinstance(data, dict) else False


@dataclass(frozen=True)
class RemoteListing:
    """``GET /hub/files`` after the client's own check of every name."""

    files: list[RemoteFile]
    """The fixed files in :data:`FILE_NAMES` order, then the sub-tau files by name."""
    ignored: list[str]
    """Names outside the file set, which are never downloaded or written."""


def remote_listing(spine: SpineClient) -> RemoteListing:
    """``GET /hub/files``, every name checked again: a spine can never make the hub read or
    write a file outside the set (a name that fails is listed in ``ignored``)."""
    data = spine.call("GET", "/hub/files")
    items = data.get("files") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise SpineError(200, "bad_json", "files is not a list")
    found: dict[str, RemoteFile] = {}
    ignored: list[str] = []
    for item in items:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str):
            continue
        if name not in FILE_NAMES and not is_sub_file(name):
            ignored.append(name)
            continue
        size, updated = item.get("size"), item.get("updated_at")
        found[name] = RemoteFile(
            name,
            size if isinstance(size, int) else 0,
            updated if isinstance(updated, int) else 0,
        )
    fixed = [found[name] for name in FILE_NAMES if name in found]
    subs = [found[name] for name in sorted(found) if name not in FILE_NAMES]
    return RemoteListing(fixed + subs, ignored)


def list_remote(spine: SpineClient) -> list[RemoteFile]:
    """``GET /hub/files``: the files of the set the spine holds, in :data:`FILE_NAMES` order,
    then the sub-tau files by name."""
    return remote_listing(spine).files


@dataclass(frozen=True)
class Refused:
    """A file in ``persona/subs/`` that a push never sends. ``reason`` is ``name`` (not a
    plain ``.md`` name), ``not_file`` (a directory or another special file) or ``link`` (a
    symbolic link)."""

    name: str
    reason: str


def scan_subs(home: Path) -> tuple[list[str], list[Refused]]:
    """The sub-tau files a push sends (``persona/subs/<file>`` names, sorted) and the entries
    of that directory it refuses. A missing directory gives two empty lists."""
    directory = Path(home) / SUBS_DIR
    try:
        entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
    except (FileNotFoundError, NotADirectoryError):
        return [], []
    except OSError as exc:
        raise FileError(f"{directory} cannot be read: {exc.strerror or exc}") from None
    names: list[str] = []
    refused: list[Refused] = []
    for entry in entries:
        name = _SUBS_PREFIX + entry.name
        if entry.is_symlink():
            refused.append(Refused(name, "link"))
        elif not entry.is_file():
            refused.append(Refused(name, "not_file"))
        elif not SUB_FILE_PATTERN.fullmatch(entry.name):
            refused.append(Refused(name, "name"))
        else:
            names.append(name)
    return names, refused


@dataclass(frozen=True)
class WriteResult:
    name: str
    path: Path
    outcome: str
    """``written`` (new or replaced), ``unchanged`` (same text) or ``kept`` (differs, not
    replaced without ``force``)."""


def _write_atomic(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp)
        raise


def write_local(home: Path, name: str, text: str, *, force: bool = False) -> WriteResult:
    """Write ``text`` as the local ``name`` (atomically). An existing file with other text is
    only replaced with ``force``; a replaced file keeps its mode. New private files and sub-tau
    files get 0600 (a new ``persona/subs/`` gets 0700), others the process default."""
    path = local_path(home, name)
    sub = is_sub_file(name)
    if sub and path.is_symlink():
        raise FileError(f"{path} is a symbolic link.")
    if path.exists() and not path.is_file():
        raise FileError(f"{path} is not a regular file.")
    try:
        current = path.read_bytes() if path.is_file() else None
    except OSError as exc:
        raise FileError(f"{path} cannot be read: {exc.strerror or exc}") from None
    if current is not None and current == text.encode("utf-8"):
        return WriteResult(name, path, "unchanged")
    if current is not None and not force:
        return WriteResult(name, path, "kept")
    if current is not None:
        mode = stat.S_IMODE(path.stat().st_mode)
    elif name in PRIVATE_FILES or sub:
        mode = 0o600
    else:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    try:
        if sub and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(path.parent, 0o700)
        _write_atomic(path, text, mode)
    except OSError as exc:
        raise FileError(f"{path} cannot be written: {exc.strerror or exc}") from None
    return WriteResult(name, path, "written")


# -- the container's tau.toml ------------------------------------------------------------------


def _table(parent: Any, key: str, where: str) -> Any:
    value = parent.get(key)
    if value is None:
        parent[key] = tomlkit.table()
        return parent[key]
    if not isinstance(value, Table | InlineTable):
        raise FileError(f"tau.toml: {where} must be a table.")
    return value


PATCH_COMMENT = "set by tau cloud run"


def _set(table: Any, key: str, value: str) -> None:
    """``table[key] = value``; the changed line's own comment (it described the old value)
    becomes :data:`PATCH_COMMENT`. An inline table cannot hold comments and gets none."""
    item = tomlkit.item(value)
    if not isinstance(table, InlineTable):
        item.comment(PATCH_COMMENT)
    table[key] = item


def cloud_config(text: str) -> str:
    """``tau.toml`` for the brain container: ``[sessions] backend = "spine"`` and
    ``[component.net] store = "spine"``, everything else (comments and layout included)
    unchanged. :class:`FileError` for a file tomlkit cannot parse or a key of the wrong type."""
    try:
        doc = tomlkit.parse(text)
    except ValueError as exc:  # tomlkit's parse errors are ValueErrors
        raise FileError(f"tau.toml could not be read: {exc}") from None
    _set(_table(doc, "sessions", "[sessions]"), "backend", "spine")
    component = doc.get("component")
    if component is None:
        doc["component"] = tomlkit.table(is_super_table=True)
        component = doc["component"]
    elif not isinstance(component, Table | InlineTable):
        raise FileError("tau.toml: [component] must be a table.")
    _set(_table(component, "net", "[component.net]"), "store", "spine")
    return tomlkit.dumps(doc)
