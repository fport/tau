"""The installed tau-core version, importable without the package's public API."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("tau-core")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0"
