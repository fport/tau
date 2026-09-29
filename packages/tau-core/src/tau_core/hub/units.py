"""Service definitions for the hub: the launchd plist and the systemd unit.

Both are rendered from the package templates in ``tau_core/hub/templates/`` with the paths of
the machine they are installed on (:meth:`ServicePaths.from_config`). The examples committed in
``infra/services/`` are the same templates rendered with :data:`PLACEHOLDER_PATHS`.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from importlib.resources import files
from string import Template
from xml.sax.saxutils import escape

from tau_core.config import Config

LABEL = "com.tau.hub"
PLIST_NAME = f"{LABEL}.plist"
UNIT_NAME = "tau-hub.service"
DEFAULT_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


@dataclass(frozen=True)
class ServicePaths:
    """The absolute paths a service definition needs."""

    python: str  # interpreter that has tau-core installed (the venv's python)
    tau_home: str  # TAU_HOME: tau.toml, persona/, tools/
    data_dir: str  # TAU_DATA_DIR: sessions, hub state, logs
    hub_dir: str  # <data_dir>/hub
    path: str  # PATH for the service

    @property
    def log_dir(self) -> str:
        return f"{self.hub_dir}/logs"

    @classmethod
    def from_config(
        cls, config: Config, *, python: str | None = None, path: str | None = None
    ) -> ServicePaths:
        return cls(
            python=python or sys.executable,
            tau_home=str(config.home),
            data_dir=str(config.data_dir),
            hub_dir=str(config.hub_dir),
            path=path if path is not None else os.environ.get("PATH", DEFAULT_PATH),
        )


PLACEHOLDER_PATHS = ServicePaths(
    python="/path/to/venv/bin/python",
    tau_home="/path/to/tau",
    data_dir="/path/to/tau-data",
    hub_dir="/path/to/tau-data/hub",
    path=DEFAULT_PATH,
)
"""Example values for the committed ``infra/services/`` files; never real paths."""


def template_text(name: str) -> str:
    """The raw template ``name`` shipped in the package."""
    return (files("tau_core.hub") / "templates" / name).read_text(encoding="utf-8")


def render_plist(paths: ServicePaths, *, label: str = LABEL) -> str:
    """The launchd user agent plist for ``paths`` (values XML-escaped)."""
    values = {
        "label": label,
        "python": paths.python,
        "tau_home": paths.tau_home,
        "data_dir": paths.data_dir,
        "path": paths.path,
        "log_dir": paths.log_dir,
    }
    return Template(template_text(PLIST_NAME)).substitute(
        {key: escape(value) for key, value in values.items()}
    )


def _systemd_escape(value: str) -> str:
    """Escape specifiers (``%``) and quote the value when it has spaces or quotes."""
    value = value.replace("%", "%%")
    if any(ch in value for ch in " \t\"'\\"):
        value = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def render_systemd_unit(paths: ServicePaths) -> str:
    """The systemd user unit for ``paths``."""
    python = _systemd_escape(paths.python).replace("$", "$$")
    values = {
        "exec_start": f"{python} -m tau_core hub run",
        "working_directory": paths.tau_home.replace("%", "%%"),
        "env_home": _systemd_escape(f"TAU_HOME={paths.tau_home}"),
        "env_data_dir": _systemd_escape(f"TAU_DATA_DIR={paths.data_dir}"),
        "env_path": _systemd_escape(f"PATH={paths.path}"),
    }
    return Template(template_text(UNIT_NAME)).substitute(values)
