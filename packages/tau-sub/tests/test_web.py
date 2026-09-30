"""Reserved names (ADR 0013 §3) and the page settings of a public sub-tau (ADR 0013 §5):
``web``, ``web_daily`` and ``starters`` through parse, render, ``tau sub new``/``show``/``edit``
and the ``tau.subs`` directory tau-net reads."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from sub_helpers import CATALOG, coach, save_coach
from tau_core import Config
from tau_sub import (
    RESERVED_NAMES,
    STARTER_LIMIT,
    WEB_DAILY_DEFAULT,
    PublicSubs,
    SubRegistry,
    SubTau,
    SubTauError,
    is_valid_name,
    parse,
    render,
    validate,
    validate_name,
)
from tau_sub.cli import sub

NAMES = [tool.tool_name for tool in CATALOG]


def invoke(config: Config, *args: str, monkeypatch: pytest.MonkeyPatch, editor=None) -> Result:
    monkeypatch.setenv("TAU_DATA_DIR", str(config.data_dir))
    obj: dict = {"home": config.home, "sub_tools": list(CATALOG)}
    if editor is not None:
        obj["sub_editor"] = editor
    return CliRunner().invoke(sub, list(args), obj=obj, env={"TAU_LANG": "en"})


# -- reserved names ----------------------------------------------------------------------------


def test_reserved_names_are_refused() -> None:
    assert RESERVED_NAMES == {"net", "app", "api", "auth", "claim", "hub"}
    for name in sorted(RESERVED_NAMES):
        assert not is_valid_name(name)
        with pytest.raises(SubTauError, match="reserved name"):
            validate_name(name)
        with pytest.raises(SubTauError, match="reserved name"):
            validate(coach(name=name))
    assert is_valid_name("coach") and is_valid_name("apis") and is_valid_name("hubs")
    assert not is_valid_name("@alice") and not is_valid_name("Coach")


def test_a_reserved_file_is_reported_and_never_public(config: Config) -> None:
    registry = SubRegistry(config, tools=CATALOG)
    registry.directory.mkdir(parents=True)
    (registry.directory / "api.md").write_text(render(coach(public=True)), encoding="utf-8")
    subs, broken = registry.scan()
    assert subs == [] and "reserved name" in str(broken["api"])
    directory = PublicSubs(config, tools=CATALOG)
    assert directory.public("api") is None
    assert directory.public_subs() == []


def test_new_refuses_a_reserved_name(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    result = invoke(config, "new", "claim", monkeypatch=monkeypatch)
    assert result.exit_code == 1
    assert "tau sub: /claim is a reserved name" in result.output
    assert not (config.persona_dir / "subs" / "claim.md").exists()


# -- the page settings ------------------------------------------------------------------------


def test_defaults_and_round_trip() -> None:
    plain = parse("coach", render(coach()), catalog=NAMES)
    assert (plain.web, plain.web_daily, plain.starters) == (False, WEB_DAILY_DEFAULT, ())
    # a definition without page settings renders exactly as before
    assert "web" not in render(coach()) and "starters" not in render(coach())

    paged = coach(public=True, web=True, web_daily=30, starters=("Plan my week", 'A "quote"'))
    text = render(paged)
    assert "web = true\nweb_daily = 30\n" in text
    assert 'starters = ["Plan my week", "A \\"quote\\""]' in text
    again = parse("coach", text, catalog=NAMES)
    assert again == validate(paged)
    assert again.on_the_web and not coach(web=True).on_the_web


def test_starters_are_one_line_without_duplicates() -> None:
    sub_tau = validate(coach(starters=("  Plan   my\nweek ", "Plan my week", "Hi")))
    assert sub_tau.starters == ("Plan my week", "Hi")


@pytest.mark.parametrize(
    ("front", "message"),
    [
        ("web = 1", "'web' must be true or false"),
        ('web = "yes"', "'web' must be true or false"),
        ("web_daily = 0", "'web_daily' must be a whole number from 1 to 1000"),
        ("web_daily = 1001", "'web_daily' must be a whole number from 1 to 1000"),
        ("web_daily = true", "'web_daily' must be a whole number from 1 to 1000"),
        ("web_daily = 2.5", "'web_daily' must be a whole number from 1 to 1000"),
        ('starters = "Plan my week"', "'starters' must be a list"),
        ("starters = [1]", "'starters' must hold text"),
        ('starters = [""]', "each starter must be 1 to 80 characters"),
        (f'starters = ["{"x" * (STARTER_LIMIT + 1)}"]', "each starter must be 1 to 80"),
        ('starters = ["a", "b", "c", "d", "e"]', "at most 4 starters"),
    ],
)
def test_page_settings_are_checked(front: str, message: str) -> None:
    text = render(coach()).replace("public = false\n", f"public = true\n{front}\n")
    with pytest.raises(SubTauError, match=message):
        parse("coach", text, catalog=NAMES)


def test_the_directory_exposes_the_page_settings(config: Config) -> None:
    save_coach(config, public=True, web=True, web_daily=12, starters=("Plan my week",))
    save_coach(config, name="quiet", public=True)
    directory = PublicSubs(config, tools=CATALOG)
    coach_sub = directory.public("coach")
    assert coach_sub is not None
    assert (coach_sub.web, coach_sub.web_daily, coach_sub.starters) == (
        True,
        12,
        ("Plan my week",),
    )
    quiet = directory.public("quiet")
    assert quiet is not None and (quiet.web, quiet.web_daily, quiet.starters) == (False, 50, ())
    assert [s.name for s in directory.public_subs()] == ["coach", "quiet"]


# -- the commands -------------------------------------------------------------------------------


def test_new_writes_the_page_settings(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    result = invoke(
        config,
        "new",
        "coach",
        "--about",
        "A workout coach.",
        "--public",
        "--web",
        "--web-daily",
        "20",
        "--starter",
        "Plan my week",
        "--starter",
        "I missed a run",
        monkeypatch=monkeypatch,
    )
    assert result.exit_code == 0, result.output
    loaded = SubRegistry(config, tools=CATALOG).get("coach")
    assert loaded.public and loaded.web and loaded.web_daily == 20
    assert loaded.starters == ("Plan my week", "I missed a run")

    result = invoke(config, "show", "coach", monkeypatch=monkeypatch)
    assert result.exit_code == 0, result.output
    assert "web page:     yes" in result.output
    assert "visitor turns: at most 20 a day (UTC)" in result.output
    assert "starters:     Plan my week · I missed a run" in result.output


def test_new_checks_the_page_settings_first(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = config.persona_dir / "subs" / "coach.md"
    result = invoke(config, "new", "coach", "--web", monkeypatch=monkeypatch)
    assert result.exit_code == 1 and "--web needs --public" in result.output
    result = invoke(
        config, "new", "coach", "--public", "--web", "--web-daily", "0", monkeypatch=monkeypatch
    )
    assert result.exit_code == 2  # click's range check
    starters = [arg for i in range(5) for arg in ("--starter", f"Starter {i}")]
    result = invoke(config, "new", "coach", "--public", *starters, monkeypatch=monkeypatch)
    assert result.exit_code == 1 and "at most 4 starters" in result.output
    # --describe never calls the model with settings that cannot be written
    result = invoke(
        config,
        "new",
        "coach",
        "--public",
        "--starter",
        "x" * 81,
        "--describe",
        "a coach",
        monkeypatch=monkeypatch,
    )
    assert result.exit_code == 1 and "each starter must be 1 to 80" in result.output
    assert not path.exists()


def test_show_says_when_the_page_is_off(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    save_coach(config)
    result = invoke(config, "show", "coach", monkeypatch=monkeypatch)
    assert "web page:     no" in result.output and "visitor turns" not in result.output
    assert "starters:     none" in result.output

    registry = SubRegistry(config, tools=CATALOG)
    path = registry.path("coach")
    path.write_text(
        path.read_text(encoding="utf-8").replace("public = false", "public = false\nweb = true"),
        encoding="utf-8",
    )
    result = invoke(config, "show", "coach", monkeypatch=monkeypatch)
    assert "only public sub-taus get a page" in result.output


def test_edit_reports_bad_page_settings(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    save_coach(config, public=True)

    def editor(path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("public = true", "public = true\nweb_daily = 5000"), "utf-8")

    result = invoke(config, "edit", "coach", editor=editor, monkeypatch=monkeypatch)
    assert result.exit_code == 1
    assert "'web_daily' must be a whole number from 1 to 1000" in result.output

    def fix(path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("web_daily = 5000", "web = true\nweb_daily = 5"), "utf-8")

    result = invoke(config, "edit", "coach", editor=fix, monkeypatch=monkeypatch)
    assert result.exit_code == 0, result.output
    loaded = SubRegistry(config, tools=CATALOG).get("coach")
    assert loaded.web and loaded.web_daily == 5


def test_a_sub_tau_value_object_keeps_its_defaults() -> None:
    plain = SubTau(name="coach", about="A coach.", persona="You coach.")
    assert (plain.web, plain.web_daily, plain.starters) == (False, 50, ())
