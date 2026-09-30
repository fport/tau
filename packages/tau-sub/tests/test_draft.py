"""``tau sub new``: templates, drafts from the brain role, the tool filter, confirmation."""

from __future__ import annotations

import json
import stat

import pytest
from click.testing import CliRunner, Result
from sub_helpers import CATALOG, OWNER_FACT, save_coach, tool_names
from tau_core import Config
from tau_core.testing import FakeModel
from tau_sub import DraftError, SubRegistry, parse_draft
from tau_sub.cli import sub
from tau_sub.draft import DRAFT_PERSONA, DROP_FORBIDDEN, DROP_TIER2, DROP_UNKNOWN

DESCRIPTION = "a strict but kind workout coach that plans three short sessions a week"
CATALOG_BY_NAME = {tool.tool_name: tool for tool in CATALOG}


def draft_reply(**overrides) -> str:
    data = {
        "about": "A strict but kind workout coach who plans three short sessions a week.",
        "persona": "You plan three short workouts a week.\n\nYou are strict and kind.",
        "tools": ["lookup_plan", "ring_bell", "teleport", "ask_sub", "lookup_plan"],
    }
    data.update(overrides)
    return "Here is the draft:\n```json\n" + json.dumps(data) + "\n```"


@pytest.fixture
def invoke(monkeypatch: pytest.MonkeyPatch):
    def run(config: Config, *args: str, model=None, input: str | None = None) -> Result:
        monkeypatch.setenv("TAU_DATA_DIR", str(config.data_dir))
        obj = {"home": config.home, "sub_tools": list(CATALOG)}
        if model is not None:
            obj["sub_model"] = lambda role: model
        return CliRunner().invoke(sub, list(args), obj=obj, input=input)

    return run


def test_parse_draft_filters_the_tools() -> None:
    draft = parse_draft(draft_reply(), CATALOG_BY_NAME)
    assert draft.tools == ("lookup_plan",)
    assert draft.dropped == (
        ("ring_bell", DROP_TIER2),
        ("teleport", DROP_UNKNOWN),
        ("ask_sub", DROP_FORBIDDEN),
    )
    allowed = parse_draft(draft_reply(), CATALOG_BY_NAME, allow_tier2=True)
    assert allowed.tools == ("lookup_plan", "ring_bell")
    assert ("ring_bell", DROP_TIER2) not in allowed.dropped


def test_parse_draft_cuts_a_long_about_and_refuses_garbage() -> None:
    draft = parse_draft(draft_reply(about="word " * 80, tools=[]), CATALOG_BY_NAME)
    assert len(draft.about) == 200 and draft.about.endswith("…")
    for bad in ["no json here", "{not json}", json.dumps({"about": "x"}), "[1, 2]"]:
        with pytest.raises(DraftError):
            parse_draft(bad, CATALOG_BY_NAME)


def test_new_describe_writes_a_valid_definition(config: Config, invoke) -> None:
    model = FakeModel([draft_reply()])
    result = invoke(config, "new", "coach", "--describe", DESCRIPTION, "--yes", model=model)
    assert result.exit_code == 0, result.output
    registry = SubRegistry(config, tools=CATALOG)
    coach = registry.get("coach")
    assert coach.tools == ("lookup_plan",)  # only catalog tools, no tier 2, no ask_sub
    assert coach.role == "brain" and coach.public is False
    assert coach.persona.startswith("You plan three short workouts a week.")
    path = registry.path("coach")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert f"Draft of {path}:" in result.output and 'about = "A strict' in result.output
    assert "Left out of the tool list: ring_bell (tier 2; pass --allow-tier2" in result.output
    assert "teleport (not in the tool catalog)" in result.output
    assert "ask_sub (never allowed in a sub-tau)" in result.output
    assert f"Created /coach: {path}" in result.output
    # the drafter: the fixed English persona, never user.md, no tools, no tier-2 tools offered
    [call] = model.calls
    assert call.system_prompt.startswith(DRAFT_PERSONA.strip()[:40])
    assert OWNER_FACT not in call.system_prompt
    assert tool_names(call) == []
    request = call.messages[0]["content"][0]["text"]
    assert DESCRIPTION in request
    assert "- lookup_plan (tier 0)" in request and "- log_workout (tier 1)" in request
    assert "ring_bell" not in request


def test_new_describe_can_keep_tier2_tools(config: Config, invoke) -> None:
    model = FakeModel([draft_reply()])
    result = invoke(
        config, "new", "coach", "--describe", DESCRIPTION, "--allow-tier2", "-y", model=model
    )
    assert result.exit_code == 0, result.output
    assert SubRegistry(config, tools=CATALOG).get("coach").tools == ("lookup_plan", "ring_bell")
    assert "- ring_bell (tier 2)" in model.calls[0].messages[0]["content"][0]["text"]


def test_new_describe_asks_before_writing(config: Config, invoke) -> None:
    declined = invoke(
        config,
        "new",
        "coach",
        "--describe",
        DESCRIPTION,
        model=FakeModel([draft_reply()]),
        input="n\n",
    )
    assert declined.exit_code == 0, declined.output
    assert "Write this sub-tau? [y/N]" in declined.output
    assert "Nothing was written." in declined.output
    assert not SubRegistry(config).exists("coach")
    accepted = invoke(
        config,
        "new",
        "coach",
        "--describe",
        DESCRIPTION,
        model=FakeModel([draft_reply()]),
        input="y\n",
    )
    assert accepted.exit_code == 0, accepted.output
    assert SubRegistry(config).exists("coach")


def test_options_win_over_the_draft(config: Config, invoke) -> None:
    result = invoke(
        config,
        "new",
        "coach",
        "--describe",
        DESCRIPTION,
        "--about",
        "My coach.",
        "--role",
        "fast",
        "--tools",
        "log_workout",
        "--public",
        "--yes",
        model=FakeModel([draft_reply()]),
    )
    assert result.exit_code == 0, result.output
    coach = SubRegistry(config, tools=CATALOG).get("coach")
    assert (coach.about, coach.role, coach.tools, coach.public) == (
        "My coach.",
        "fast",
        ("log_workout",),
        True,
    )
    assert "Left out of the tool list" not in result.output  # the draft's list was not used


def test_a_bad_draft_writes_nothing(config: Config, invoke) -> None:
    result = invoke(
        config,
        "new",
        "coach",
        "--describe",
        DESCRIPTION,
        "--yes",
        model=FakeModel(["I would rather not."]),
    )
    assert result.exit_code == 1
    assert "tau sub: The draft is not a JSON object" in result.output
    assert not SubRegistry(config).exists("coach")


def test_new_without_describe_writes_a_template(config: Config, invoke) -> None:
    result = invoke(
        config,
        "new",
        "landing",
        "--about",
        "Writes landing pages.",
        "--tools",
        "lookup_plan, log_workout",
    )
    assert result.exit_code == 0, result.output
    landing = SubRegistry(config, tools=CATALOG).get("landing")
    assert landing.about == "Writes landing pages."
    assert landing.tools == ("lookup_plan", "log_workout")
    assert "tau sub edit landing" in result.output and "tau sub chat landing" in result.output


def test_new_refuses_unknown_tools_bad_names_and_existing(config: Config, invoke) -> None:
    unknown = invoke(config, "new", "landing", "--tools", "lookup_plan,teleport")
    assert unknown.exit_code == 1
    assert "unknown tool 'teleport'" in unknown.output
    forbidden = invoke(config, "new", "landing", "--tools", "create_sub")
    assert forbidden.exit_code == 1 and "never allowed" in forbidden.output
    bad = invoke(config, "new", "Landing")
    assert bad.exit_code == 1 and "Invalid sub-tau name 'Landing'" in bad.output
    save_coach(config)
    before = SubRegistry(config).path("coach").read_bytes()
    exists = invoke(
        config, "new", "coach", "--describe", DESCRIPTION, "--yes", model=FakeModel([draft_reply()])
    )
    assert exists.exit_code == 1 and "already exists" in exists.output
    assert SubRegistry(config).path("coach").read_bytes() == before
    forced = invoke(config, "new", "coach", "--force")
    assert forced.exit_code == 0, forced.output
    assert SubRegistry(config).path("coach").read_bytes() != before
