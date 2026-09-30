"""``tau setup``: one engine that picks tau's features, installs and configures them (ADR 0014).

- :mod:`~tau_core.setup.catalog` reads the feature catalog, ``templates/features.toml``.
- :mod:`~tau_core.setup.state` finds out what is installed and what is set up.
- :mod:`~tau_core.setup.engine` builds the one ``uv tool install``, carries the wizard across
  its re-execution and prepares each step.
- :mod:`~tau_core.setup.wizard` is the terminal wizard, :mod:`~tau_core.setup.protocol` the
  JSON mode the Mac app drives (``docs/reference/setup.md``), :mod:`~tau_core.setup.cli` the
  ``tau setup`` command.

tau-core never imports a feature's package here: the steps are ``tau`` subcommands run as
subprocesses, found through their entry points.
"""

from __future__ import annotations

from tau_core.setup import strings as _strings  # noqa: F401 - registers the message keys first
from tau_core.setup.catalog import (
    Catalog,
    CatalogError,
    Configured,
    Feature,
    Input,
    Step,
    load_catalog,
    parse_catalog,
)

__all__ = [
    "Catalog",
    "CatalogError",
    "Configured",
    "Feature",
    "Input",
    "Step",
    "load_catalog",
    "parse_catalog",
]
