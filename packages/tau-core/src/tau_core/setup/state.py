"""What is installed and what is set up: the snapshot ``tau setup`` starts from.

- A feature's package is installed when its distribution is in this environment
  (``importlib.metadata``, through the :class:`~tau_core.setup.host.Host`).
- It is set up when the catalog's ``[feature.configured]`` rules hold: files under the
  configuration root, the data dir or the home directory, and variables in the environment
  or ``<home>/.env`` (the guard's enrollment marker, the network identity, the Telegram
  token, the launchd agent).
- The configuration exists when ``<home>/tau.toml`` does, and "about you" is done when
  ``persona/user.md`` holds something other than the shipped example.
- tau runs from a ``uv tool`` environment when ``sys.prefix`` holds ``uv-receipt.toml``; the
  receipt lists the requirements the environment was installed with.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from tau_core.builder import env_with_dotenv, template_text
from tau_core.config import CONFIG_FILE, DEFAULT_DATA_DIR, resolve_home
from tau_core.i18n import LANGUAGES
from tau_core.setup.catalog import Catalog, Feature
from tau_core.setup.host import Host

__all__ = [
    "RECEIPT_FILE",
    "FeatureState",
    "Receipt",
    "Requirement",
    "Snapshot",
    "about_done",
    "configured_language",
    "core_version",
    "data_dir",
    "expand",
    "feature_state",
    "read_receipt",
    "take_snapshot",
]

RECEIPT_FILE = "uv-receipt.toml"
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


@dataclass(frozen=True)
class Requirement:
    """One requirement of a uv tool receipt, as ``--with`` can take it again."""

    name: str
    spec: str | None
    """``name[extras]specifier``, a path or a URL; ``None`` when uv recorded a source that
    cannot be passed back (a git checkout, an editable directory)."""


@dataclass(frozen=True)
class Receipt:
    requirements: tuple[Requirement, ...] = ()
    python: str | None = None


@dataclass(frozen=True)
class FeatureState:
    feature: Feature
    available: bool
    installed: bool
    """The package is in this environment (always true for a feature without a package)."""
    version: str | None
    configured: bool
    state: str
    """``done``, ``installed`` (the package is there, the feature is not set up), ``missing``
    (the package is not installed), ``available`` (nothing to install and nothing that says
    it is set up) or ``unavailable`` (not on this platform)."""

    @property
    def done(self) -> bool:
        return self.state == "done"


@dataclass(frozen=True)
class Snapshot:
    platform: str
    version: str
    home: Path
    data: Path
    config: bool
    about: bool
    ssh: bool
    receipt: Receipt | None
    features: tuple[FeatureState, ...] = field(default_factory=tuple)

    @property
    def uv_tool(self) -> bool:
        return self.receipt is not None

    def get(self, feature_id: str) -> FeatureState | None:
        return next((s for s in self.features if s.feature.id == feature_id), None)


def core_version(host: Host) -> str:
    return host.version_of("tau-core") or "0.0.0"


def expand(
    path: str, *, home: Path, data: Path, environ: Mapping[str, str], root: Path = Path("/")
) -> Path:
    """A catalog path with ``{home}``, ``{data}`` and a leading ``~`` resolved; a path the
    catalog writes as absolute (``/Applications/...``) is taken under ``root``."""
    if path.startswith("/"):
        return Path(root, path.lstrip("/"))
    value = path.replace("{home}", str(home)).replace("{data}", str(data))
    if value == "~" or value.startswith("~/"):
        user_home = environ.get("HOME") or str(Path.home())
        value = user_home + value[1:]
    return Path(value)


def data_dir(home: Path, environ: Mapping[str, str]) -> Path:
    """``TAU_DATA_DIR`` from the environment or ``<home>/.env``, else the default."""
    merged = env_with_dotenv(home, environ)
    raw = merged.get("TAU_DATA_DIR") or DEFAULT_DATA_DIR
    return expand(raw, home=home, data=home, environ=environ).resolve()


def about_done(home: Path) -> bool:
    """``persona/user.md`` holds facts of its own (not empty, not the shipped example)."""
    path = home / "persona" / "user.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    own = _COMMENT.sub("", text).strip()
    example = _COMMENT.sub("", template_text("user.example.md")).strip()
    return bool(own) and own != example


def _requirement(raw: object) -> Requirement | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
        return None
    name = raw["name"]
    for source in ("path", "url"):
        value = raw.get(source)
        if isinstance(value, str) and value:
            return Requirement(name, value)
    if any(key in raw for key in ("git", "directory", "editable")):
        return Requirement(name, None)
    extras = raw.get("extras")
    extra = f"[{','.join(extras)}]" if isinstance(extras, list) and extras else ""
    specifier = raw.get("specifier")
    return Requirement(name, f"{name}{extra}{specifier if isinstance(specifier, str) else ''}")


def read_receipt(prefix: Path) -> Receipt | None:
    """The uv tool receipt of the environment at ``prefix``; ``None`` outside a uv tool."""
    path = prefix / RECEIPT_FILE
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    tool = raw.get("tool")
    if not isinstance(tool, dict):
        return None
    requirements = tool.get("requirements", [])
    if not isinstance(requirements, list):
        requirements = []
    parsed = [item for item in map(_requirement, requirements) if item is not None]
    python = tool.get("python")
    return Receipt(tuple(parsed), python if isinstance(python, str) and python else None)


def _configured(
    feature: Feature, *, home: Path, data: Path, env: Mapping[str, str], root: Path
) -> bool:
    rules = feature.configured
    assert rules is not None
    environ = env

    def exists(path: str) -> bool:
        return expand(path, home=home, data=data, environ=environ, root=root).exists()

    if not all(exists(path) for path in rules.files):
        return False
    if rules.any_files and not any(exists(path) for path in rules.any_files):
        return False
    return all((env.get(name) or "").strip() for name in rules.env)


def feature_state(
    feature: Feature, host: Host, *, home: Path, data: Path, env: Mapping[str, str]
) -> FeatureState:
    available = feature.available_on(host.platform)
    version = host.version_of(feature.package) if feature.package else None
    installed = feature.package is None or version is not None
    if feature.configured is not None:
        configured = installed and _configured(
            feature, home=home, data=data, env=env, root=host.root
        )
    else:
        configured = installed and feature.package is not None
    if not available:
        state = "unavailable"
    elif configured:
        state = "done"
    elif not installed:
        state = "missing"
    elif feature.package is not None:
        state = "installed"
    else:
        state = "available"
    return FeatureState(feature, available, installed, version, configured, state)


def take_snapshot(host: Host, catalog: Catalog) -> Snapshot:
    home = resolve_home(None, host.environ)
    data = data_dir(home, host.environ)
    env = env_with_dotenv(home, host.environ)
    return Snapshot(
        platform=host.platform,
        version=core_version(host),
        home=home,
        data=data,
        config=(home / CONFIG_FILE).is_file(),
        about=about_done(home),
        ssh=host.over_ssh(),
        receipt=read_receipt(host.prefix),
        features=tuple(
            feature_state(feature, host, home=home, data=data, env=env)
            for feature in catalog.features
        ),
    )


def configured_language(home: Path, environ: Mapping[str, str]) -> str | None:
    """``TAU_LANG``, else ``[ui] language`` of ``<home>/tau.toml``; ``None`` when neither is
    set (``tau setup`` then asks first)."""
    value = environ.get("TAU_LANG", "")
    if value in LANGUAGES:
        return value
    try:
        raw = tomllib.loads((home / CONFIG_FILE).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    ui = raw.get("ui")
    language = ui.get("language") if isinstance(ui, dict) else None
    return language if language in LANGUAGES else None
