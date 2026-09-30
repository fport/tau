"""The installed tau-cloud version, importable without the package's public API."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("tau-cloud")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0"
