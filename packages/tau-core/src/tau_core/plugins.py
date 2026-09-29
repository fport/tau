"""Entry-point discovery for tools (``tau.tools``) and CLI subcommands (``tau.commands``).

A distribution plugs into tau by declaring entry points; nothing in this repo changes.
``tau.channels`` is reserved for hub-hosted channels (L3) and not read here. A plugin that
fails to load is logged with its distribution name and skipped; it never breaks the CLI.
"""

from __future__ import annotations

import logging
from importlib import metadata
from typing import Any

import click
from strands.types.tools import AgentTool

logger = logging.getLogger(__name__)

TOOLS_GROUP = "tau.tools"
COMMANDS_GROUP = "tau.commands"


def _entry_points(group: str) -> list[metadata.EntryPoint]:
    return list(metadata.entry_points(group=group))


def _dist_name(ep: metadata.EntryPoint) -> str:
    dist = getattr(ep, "dist", None)
    return dist.name if dist is not None else "?"


def _as_tools(obj: Any) -> list[Any]:
    if isinstance(obj, AgentTool):
        return [obj]
    if isinstance(obj, list | tuple):
        return list(obj)
    if callable(obj):
        return _as_tools(obj())
    raise TypeError(f"expected an AgentTool, a list of them or a factory, got {type(obj).__name__}")


def discover_tools(*, group: str = TOOLS_GROUP) -> list[AgentTool]:
    """All tools declared under ``group``; each carries ``tau_distribution``."""
    found: list[AgentTool] = []
    for ep in _entry_points(group):
        dist = _dist_name(ep)
        try:
            items = _as_tools(ep.load())
        except Exception as exc:
            logger.warning("tool entry point %s from %s failed to load: %s", ep.name, dist, exc)
            continue
        for item in items:
            if not isinstance(item, AgentTool):
                logger.warning(
                    "tool entry point %s from %s returned %r, not a tool; skipped",
                    ep.name,
                    dist,
                    item,
                )
                continue
            try:
                item.tau_distribution = dist  # type: ignore[attr-defined]
            except AttributeError:
                pass
            found.append(item)
    return found


def discover_commands(*, group: str = COMMANDS_GROUP) -> dict[str, click.Command]:
    """``{name: command}`` for every loadable entry point under ``group``."""
    commands: dict[str, click.Command] = {}
    for ep in _entry_points(group):
        command = _load_command(ep)
        if command is not None:
            commands.setdefault(ep.name, command)
    return commands


def load_command(name: str, *, group: str = COMMANDS_GROUP) -> click.Command | None:
    """Load only the entry point called ``name`` (keeps ``tau version`` fast)."""
    for ep in _entry_points(group):
        if ep.name == name:
            command = _load_command(ep)
            if command is not None:
                return command
    return None


def command_names(*, group: str = COMMANDS_GROUP) -> list[str]:
    return sorted({ep.name for ep in _entry_points(group)})


def _load_command(ep: metadata.EntryPoint) -> click.Command | None:
    dist = _dist_name(ep)
    try:
        obj = ep.load()
    except Exception as exc:
        logger.warning("command entry point %s from %s failed to load: %s", ep.name, dist, exc)
        return None
    if not isinstance(obj, click.Command):
        logger.warning(
            "command entry point %s from %s is not a click command; skipped", ep.name, dist
        )
        return None
    return obj
