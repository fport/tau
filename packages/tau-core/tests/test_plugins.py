from __future__ import annotations

import logging
from importlib import metadata

import click
import pytest
from tau_core import Tier, plugins
from tau_core.plugins import discover_commands, discover_tools
from tau_core.tiers import tier_of


def test_tool_from_another_distribution_is_discovered() -> None:
    tools = {tool.tool_name: tool for tool in discover_tools()}
    echo = tools["example_echo"]
    assert echo.tau_distribution == "tau-example-tool"
    assert tier_of(echo) is Tier.READ
    assert echo._tool_func("merhaba") == "merhaba"  # noqa: SLF001 - direct call of the function
    assert tools["current_time"].tau_distribution == "tau-core"


def test_broken_entry_point_is_skipped(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    real = plugins._entry_points("tau.tools")
    broken = metadata.EntryPoint(name="broken", value="tau_example_tool:missing", group="tau.tools")
    not_a_tool = metadata.EntryPoint(
        name="odd", value="tau_core.plugins:TOOLS_GROUP", group="tau.tools"
    )
    monkeypatch.setattr(plugins, "_entry_points", lambda group: [broken, not_a_tool, *real])
    with caplog.at_level(logging.WARNING, logger="tau_core.plugins"):
        names = [tool.tool_name for tool in discover_tools()]
    assert "example_echo" in names
    assert "broken" in caplog.text and "odd" in caplog.text


def test_factory_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = metadata.EntryPoint(
        name="factory", value="tau_core.builtin_tools:TOOLS.copy", group="tau.tools"
    )
    monkeypatch.setattr(plugins, "_entry_points", lambda group: [factory])
    assert [t.tool_name for t in discover_tools()] == ["current_time", "demo_physical_action"]


def test_commands_discovered() -> None:
    commands = discover_commands()
    assert {"chat", "hub", "tui"} <= set(commands)
    assert all(isinstance(c, click.Command) for c in commands.values())
    assert isinstance(commands["hub"], click.Group)


def test_broken_command_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    broken = metadata.EntryPoint(name="kırık", value="nowhere.module:cmd", group="tau.commands")
    monkeypatch.setattr(plugins, "_entry_points", lambda group: [broken])
    assert discover_commands() == {}
    assert plugins.load_command("kırık") is None
