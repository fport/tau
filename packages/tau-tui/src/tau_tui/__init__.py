"""tau-tui: the Textual terminal interface for tau (issue 008)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("tau-tui")
except PackageNotFoundError:
    __version__ = "0.0.0"
