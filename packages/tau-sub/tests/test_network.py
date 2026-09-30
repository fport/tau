"""The ``tau.subs`` entry point: public sub-taus for tau-net (issue 150)."""

from __future__ import annotations

import ast
from importlib import metadata
from pathlib import Path

import tau_sub
from sub_helpers import CATALOG, COACH_PERSONA, OWNER_FACT, save_coach
from tau_core import Config, PersonaLoader
from tau_sub import HEADER, PublicSubs, SubRegistry, public_subs


def directory(config: Config) -> PublicSubs:
    return PublicSubs(config, tools=CATALOG)


def test_only_valid_public_sub_taus_are_found(config: Config) -> None:
    save_coach(config, public=True, public_note="coach.public.md")
    save_coach(config, name="diary", about="A private diary helper.")
    subs = directory(config)
    coach = subs.public("coach")
    assert coach is not None
    assert (coach.name, coach.role, coach.about) == (
        "coach",
        "brain",
        "A strict but kind workout coach.",
    )
    assert subs.public("diary") is None  # private
    assert subs.public("nobody") is None  # unknown
    for odd in ("../user", "Coach", "", "c", 7):
        assert subs.public(odd) is None  # type: ignore[arg-type]
    assert [sub.name for sub in subs.public_subs()] == ["coach"]


def test_an_invalid_public_definition_is_not_found(config: Config) -> None:
    save_coach(config, public=True)
    path = SubRegistry(config, tools=CATALOG).path("coach")
    path.write_text(path.read_text().replace("lookup_plan", "no_such_tool"), encoding="utf-8")
    subs = directory(config)
    assert subs.public("coach") is None and subs.public_subs() == []


def test_the_files_a_network_turn_reads(config: Config) -> None:
    save_coach(config, public=True, public_note="coach.public.md")
    note = config.persona_dir / "subs" / "coach.public.md"
    note.write_text("- Public: the owner runs on Sundays.\n", encoding="utf-8")
    coach = directory(config).public("coach")
    assert coach is not None
    assert coach.persona_file.is_absolute() and coach.public_note_file == note.resolve()
    text = coach.persona_file.read_text(encoding="utf-8")
    assert text.startswith(HEADER.format(name="coach", about="A strict but kind workout coach"))
    assert COACH_PERSONA in text and OWNER_FACT not in text
    loader = PersonaLoader(
        config.persona_dir,
        persona_file=str(coach.persona_file),
        user_file=str(coach.public_note_file),
    )
    persona = loader.read()
    assert "runs on Sundays" in (persona.user or "") and OWNER_FACT not in persona.persona
    # without a public note the directory names none (tau-net then uses persona/net.md)
    save_coach(config, name="landing", about="Writes landing-page copy.", public=True)
    landing = directory(config).public("landing")
    assert landing is not None and landing.public_note_file is None


def test_making_a_sub_tau_private_takes_effect_at_once(config: Config) -> None:
    save_coach(config, public=True)
    subs = directory(config)
    assert subs.public("coach") is not None
    registry = SubRegistry(config, tools=CATALOG)
    path = registry.path("coach")
    path.write_text(path.read_text().replace("public = true", "public = false"), encoding="utf-8")
    assert subs.public("coach") is None and subs.public_subs() == []


def test_the_entry_point_and_no_import_of_tau_net(config: Config) -> None:
    [point] = [ep for ep in metadata.entry_points(group="tau.subs") if ep.name == "sub"]
    assert point.load() is public_subs
    assert isinstance(public_subs(config), PublicSubs)
    package = Path(tau_sub.__file__).parent
    for path in package.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(name.split(".")[0] == "tau_net" for name in names), path.name
