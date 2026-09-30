"""Definitions: parse, validate, render, save (atomic, 0600, never overwritten), list, remove."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from sub_helpers import CATALOG, coach, lookup_plan
from tau_core import Config, Tier, tau_tool
from tau_sub import (
    FORBIDDEN_TOOLS,
    ForbiddenToolError,
    SubRegistry,
    SubTau,
    SubTauError,
    SubTauExists,
    SubTauNotFound,
    UnknownToolError,
    parse,
    render,
    template,
    tool_catalog,
    validate,
    validate_name,
)

NAMES = [tool.tool_name for tool in CATALOG]


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_save_and_get_round_trip(config: Config) -> None:
    registry = SubRegistry(config, tools=CATALOG)
    sub = coach(role="fast", public=True, public_note="coach.public.md")
    path = registry.save(sub)
    assert path == config.persona_dir / "subs" / "coach.md"
    assert mode(path) == 0o600
    assert mode(path.parent) == 0o700
    loaded = registry.get("coach")
    assert loaded == sub and loaded.path == path
    assert loaded.slash == "/coach" and loaded.channel == "sub:coach"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("+++\nabout = ")
    assert 'tools = ["lookup_plan", "ring_bell"]' in text
    assert text.endswith(sub.persona + "\n")
    # no temporary file is left next to it
    assert sorted(p.name for p in path.parent.iterdir()) == ["coach.md"]


def test_render_and_parse_keep_awkward_text() -> None:
    sub = SubTau(
        name="quotes",
        about='Says "hi" \\ and \x7f and ünïcode, in one line.',
        persona='Line one with "quotes" and \\backslashes\\.\n\n+++\nA fence inside the text.',
        tools=("lookup_plan",),
    )
    again = parse("quotes", render(sub), catalog=NAMES)
    assert again == validate(sub)
    assert "A fence inside the text." in again.persona


def test_front_matter_is_parsed_with_tomllib_and_checked() -> None:
    text = (
        "﻿\n+++\n"
        "about = '''A coach.'''  # a comment\n"
        'tools = ["lookup_plan", "lookup_plan"]\n'
        "+++\n\n<!-- a note -->\nYou coach.\n"
    )
    sub = parse("coach", text, catalog=NAMES)
    assert sub.about == "A coach." and sub.role == "brain" and sub.public is False
    assert sub.tools == ("lookup_plan",)  # duplicates collapse
    assert sub.persona == "<!-- a note -->\nYou coach."


@pytest.mark.parametrize("name", ["ab", "coach", "landing-page", "a1", "a" + "b" * 30])
def test_valid_names(name: str) -> None:
    assert validate_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "a",
        "Coach",
        "1coach",
        "-coach",
        "co_ach",
        "co.ach",
        "a" + "b" * 31,
        "coach\n",
        "../x",
        "coach/x",
        "ça",
        None,
        7,
    ],
)
def test_invalid_names(name: object) -> None:
    with pytest.raises(SubTauError, match="Invalid sub-tau name"):
        validate_name(name)


def test_unknown_tool_is_named(config: Config) -> None:
    registry = SubRegistry(config, tools=CATALOG)
    with pytest.raises(UnknownToolError) as info:
        registry.save(coach(tools=("lookup_plan", "teleport")))
    assert info.value.tool == "teleport"
    assert "unknown tool 'teleport'" in str(info.value)
    assert not registry.exists("coach")
    # a definition written by hand is checked when it is loaded
    path = registry.path("coach")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(coach(tools=("teleport",))), encoding="utf-8")
    with pytest.raises(UnknownToolError, match="teleport"):
        registry.get("coach")


@pytest.mark.parametrize("tool", sorted(FORBIDDEN_TOOLS))
def test_ask_sub_and_create_sub_are_never_allowed(tool: str) -> None:
    with pytest.raises(ForbiddenToolError, match=tool):
        validate(coach(tools=(tool,)))
    with pytest.raises(ForbiddenToolError):
        parse("coach", render(coach(tools=(tool,))), catalog=[*NAMES, tool])


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("You coach.", "must start with TOML front matter"),
        ("+++\nabout = 'x'\nYou coach.", "not closed"),
        ("+++\nabout = \n+++\nYou coach.", "not valid TOML"),
        ("+++\nabout = 'x'\nmodel = 'claude'\n+++\nYou coach.", "unknown key 'model'"),
        ("+++\nrole = 'fast'\n+++\nYou coach.", "'about' is missing"),
        ("+++\nabout = ''\n+++\nYou coach.", "'about' is empty"),
        (f"+++\nabout = '{'x' * 201}'\n+++\nYou coach.", "201 characters; the limit is 200"),
        ("+++\nabout = 'x'\nrole = 'genius'\n+++\nYou coach.", "unknown role 'genius'"),
        ("+++\nabout = 'x'\nrole = 1\n+++\nYou coach.", "'role' must be a string"),
        ("+++\nabout = 'x'\npublic = 'yes'\n+++\nYou coach.", "'public' must be true or false"),
        ("+++\nabout = 'x'\ntools = 'lookup_plan'\n+++\nYou coach.", "'tools' must be a list"),
        ("+++\nabout = 'x'\ntools = [1]\n+++\nYou coach.", "must hold tool names"),
        ("+++\nabout = 'x'\n+++\n<!-- only a note -->\n", "persona text after the front"),
        ("+++\nabout = 'x'\npublic_note = 'coach2.md'\n+++\nYou coach.", "public_note"),
        ("+++\nabout = 'x'\npublic_note = '../net.md'\n+++\nYou coach.", "public_note"),
        ("+++\nabout = 'x'\npublic_note = 'note.txt'\n+++\nYou coach.", "public_note"),
    ],
)
def test_invalid_definitions(text: str, message: str) -> None:
    with pytest.raises(SubTauError, match=message):
        parse("coach", text, catalog=NAMES)


def test_public_note_names() -> None:
    sub = parse("coach", "+++\nabout = 'x'\npublic_note = 'coach.public.md'\n+++\nHi.")
    assert sub.public_note == "coach.public.md"


def test_long_persona_is_refused() -> None:
    with pytest.raises(SubTauError, match="the limit is 20000"):
        validate(coach(persona="x" * 20_001))


def test_never_overwritten_without_force(config: Config) -> None:
    registry = SubRegistry(config, tools=CATALOG)
    path = registry.save(coach())
    before = path.read_bytes()
    with pytest.raises(SubTauExists, match="pass --force"):
        registry.save(coach(about="Another coach."))
    assert path.read_bytes() == before
    registry.save(coach(about="Another coach."), force=True)
    assert registry.get("coach").about == "Another coach."
    assert mode(path) == 0o600
    assert sorted(p.name for p in path.parent.iterdir()) == ["coach.md"]


def test_scan_lists_valid_and_broken_definitions(config: Config) -> None:
    registry = SubRegistry(config, tools=CATALOG)
    assert registry.names() == [] and registry.list() == []
    registry.save(coach())
    registry.save(coach(name="landing", about="Writes landing pages.", tools=()))
    directory = registry.directory
    (directory / "broken.md").write_text("no front matter\n", encoding="utf-8")
    (directory / "coach.public.md").write_text("A public note.\n", encoding="utf-8")
    (directory / "README.txt").write_text("not a definition\n", encoding="utf-8")
    assert registry.names() == ["broken", "coach", "landing"]
    subs, broken = registry.scan()
    assert [sub.name for sub in subs] == ["coach", "landing"]
    assert list(broken) == ["broken"] and "front matter" in str(broken["broken"])
    assert [sub.name for sub in registry.list()] == ["coach", "landing"]


def test_remove_deletes_the_definition_only(config: Config) -> None:
    registry = SubRegistry(config, tools=CATALOG)
    path = registry.save(coach())
    state = config.data_dir / "subs" / "coach"
    state.mkdir(parents=True)
    (state / "session").write_text("20260930-120000-abcd\n", encoding="utf-8")
    assert registry.remove("coach") == path
    assert not path.exists()
    assert (state / "session").read_text().strip() == "20260930-120000-abcd"
    with pytest.raises(SubTauNotFound):
        registry.remove("coach")
    with pytest.raises(SubTauNotFound, match="no sub-tau named /coach"):
        registry.get("coach")


def test_template_is_a_valid_definition(config: Config) -> None:
    registry = SubRegistry(config, tools=CATALOG)
    registry.save(template("landing", tools=("lookup_plan",)))
    sub = registry.get("landing")
    assert "/landing" in sub.about and sub.tools == ("lookup_plan",)
    assert sub.persona.startswith("<!--")


def test_tool_catalog_skips_forbidden_and_untiered_tools(config: Config) -> None:
    from strands import tool as strands_tool

    @strands_tool
    def untiered() -> str:
        """No tier."""
        return ""

    @tau_tool(tier=Tier.READ, name="ask_sub")
    def impostor() -> str:
        """Pretends to be ask_sub."""
        return ""

    catalog = tool_catalog(config, [lookup_plan, untiered, impostor])
    assert list(catalog) == ["lookup_plan"]


def test_discovered_catalog(config: Config) -> None:
    catalog = tool_catalog(config)
    assert {"current_time", "demo_physical_action"} <= set(catalog)
    assert not FORBIDDEN_TOOLS & set(catalog)
    disabled = config.with_overrides(
        components=type(config.components)(tools_disabled=("current_time",))
    )
    assert "current_time" not in tool_catalog(disabled)
