"""A sub-tau's agent, ``tau sub chat`` and ``tau sub ask``: prompt, allowlist, approvals,
sessions."""

from __future__ import annotations

import dataclasses
import stat

import pytest
from click.testing import CliRunner, Result
from sub_helpers import (
    BELL_EFFECT,
    CATALOG,
    COACH_PERSONA,
    OWNER_FACT,
    SideEffects,
    run,
    save_coach,
    tool_names,
)
from tau_core import Config, Decision, Tier, ToolFinished, open_session_store
from tau_core.testing import FakeModel, ScriptedApprover, ToolCall
from tau_sub import (
    HEADER,
    SubConversation,
    SubRegistry,
    SubTau,
    SubTauNotFound,
    UnknownToolError,
    build_sub_agent,
    last_session,
    prompt_path,
    remember_session,
)
from tau_sub.cli import sub

BELL = [ToolCall("ring_bell", {"times": 2})]


@pytest.fixture
def invoke(monkeypatch: pytest.MonkeyPatch):
    def run_cli(
        config: Config,
        *args: str,
        model=None,
        approver=None,
        lines: list[str] | None = None,
        interactive: bool | None = None,
    ) -> Result:
        monkeypatch.setenv("TAU_DATA_DIR", str(config.data_dir))
        obj: dict = {"home": config.home, "sub_tools": list(CATALOG)}
        if model is not None:
            obj["sub_model"] = lambda role: model
        if approver is not None:
            obj["sub_approver"] = approver
        if interactive is not None:
            obj["sub_interactive"] = interactive
        if lines is not None:
            queue = list(lines)

            def read(prompt: str) -> str:
                if not queue:
                    raise EOFError
                return queue.pop(0)

            obj["sub_input"] = read
        return CliRunner().invoke(sub, list(args), obj=obj)

    return run_cli


def test_the_prompt_holds_the_header_the_persona_and_user_md(config: Config) -> None:
    coach = save_coach(config)
    model = FakeModel(["Monday, Wednesday, Friday."])
    agent = build_sub_agent(config, coach, approver=ScriptedApprover(), model=model, tools=CATALOG)
    events = run(agent, "plan my week")
    assert events[-1].stop_reason == "end_turn"
    prompt = model.calls[0].system_prompt
    header = HEADER.format(name="coach", about="A strict but kind workout coach")
    assert prompt.startswith(header + "\n\n" + COACH_PERSONA)
    assert "## User\n" + OWNER_FACT in prompt
    assert "## Now\n- Date and time:" in prompt
    assert "+++" not in prompt and "about =" not in prompt and "tools =" not in prompt
    path = prompt_path(config, "coach")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_the_catalog_is_exactly_the_allowlist(config: Config) -> None:
    coach = save_coach(config, tools=("ring_bell", "lookup_plan"))
    model = FakeModel(["Okay."])
    agent = build_sub_agent(config, coach, approver=ScriptedApprover(), model=model, tools=CATALOG)
    assert agent.catalog.names() == ["ring_bell", "lookup_plan"]
    assert agent.role == "brain"
    run(agent, "hi")
    assert sorted(tool_names(model.calls[0])) == ["lookup_plan", "ring_bell"]
    none = save_coach(config, name="quiet", tools=())
    empty = build_sub_agent(
        config, none, approver=ScriptedApprover(), model=FakeModel(), tools=CATALOG
    )
    assert len(empty.catalog) == 0


def test_a_tool_outside_the_allowlist_is_refused(config: Config) -> None:
    coach = save_coach(config, tools=("lookup_plan",))
    model = FakeModel([[ToolCall("log_workout", {"text": "sneaky"})], "Done."])
    agent = build_sub_agent(config, coach, approver=ScriptedApprover(), model=model, tools=CATALOG)
    [finished] = [e for e in run(agent, "log it") if isinstance(e, ToolFinished)]
    assert finished.status == "rejected"
    assert SideEffects.logged == []


def test_an_uninstalled_tool_stops_the_build(config: Config) -> None:
    coach = save_coach(config)
    with pytest.raises(UnknownToolError, match="ring_bell"):
        build_sub_agent(
            config, coach, approver=ScriptedApprover(), model=FakeModel(), tools=CATALOG[:1]
        )


@pytest.mark.parametrize("decision", [Decision.APPROVED, Decision.REJECTED])
def test_a_tier2_tool_asks_the_approver(config: Config, decision: Decision) -> None:
    coach = save_coach(config)
    approver = ScriptedApprover([decision])
    model = FakeModel([BELL, "Done."])
    agent = build_sub_agent(config, coach, approver=approver, model=model, tools=CATALOG)
    [finished] = [e for e in run(agent, "ring it") if isinstance(e, ToolFinished)]
    [request] = approver.requests
    assert request.tool == "ring_bell" and request.tier is Tier.PHYSICAL
    assert request.channel == "sub:coach" and request.effect == BELL_EFFECT
    assert request.arguments == {"times": 2}
    if decision is Decision.APPROVED:
        assert finished.status == "ok" and SideEffects.bells == ["2"]
    else:
        assert finished.status == "rejected" and SideEffects.bells == []


def test_ask_answers_with_the_persona_and_tools_only(config: Config, invoke) -> None:
    save_coach(config)
    model = FakeModel(["Three sessions: Monday, Wednesday, Friday."])
    result = invoke(
        config, "ask", "coach", "plan", "my", "week", model=model, approver=ScriptedApprover()
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "Three sessions: Monday, Wednesday, Friday."
    call = model.calls[0]
    assert call.system_prompt.startswith("You are /coach, a specialist of your owner's tau")
    assert sorted(tool_names(call)) == ["lookup_plan", "ring_bell"]
    assert call.messages[-1]["content"][0]["text"] == "plan my week"


@pytest.mark.parametrize("decision", [Decision.APPROVED, Decision.REJECTED])
def test_ask_asks_before_a_tier2_tool(config: Config, invoke, decision: Decision) -> None:
    save_coach(config)
    approver = ScriptedApprover([decision])
    result = invoke(
        config, "ask", "coach", "ring", "twice", model=FakeModel([BELL, "Rung."]), approver=approver
    )
    assert result.exit_code == 0, result.output
    assert [r.tool for r in approver.requests] == ["ring_bell"]
    if decision is Decision.APPROVED:
        assert SideEffects.bells == ["2"] and "✓ ring_bell: Rang 2 times." in result.output
    else:
        assert SideEffects.bells == [] and "✗ ring_bell: not approved" in result.output


def test_ask_without_a_terminal_refuses_tier2(config: Config, invoke) -> None:
    save_coach(config)
    model = FakeModel([BELL, "I could not ring it."])
    result = invoke(config, "ask", "coach", "ring", model=model, interactive=False)
    assert result.exit_code == 0, result.output
    assert SideEffects.bells == []
    refusal = model.calls[1].messages[-1]["content"][0]["toolResult"]["content"][0]["text"]
    assert "did not approve this action: ring_bell" in refusal
    assert "`tau sub chat coach`" in refusal


def test_ask_and_chat_fail_cleanly_for_unknown_sub_taus(config: Config, invoke) -> None:
    for args in (["ask", "nobody", "hi"], ["chat", "nobody"], ["show", "nobody"]):
        result = invoke(config, *args, model=FakeModel())
        assert result.exit_code == 1
        assert "tau sub: There is no sub-tau named /nobody" in result.output


def test_chat_repl(config: Config, invoke) -> None:
    save_coach(config)
    approver = ScriptedApprover([Decision.APPROVED])
    model = FakeModel(["Hello, ready to train?", BELL, "Rung twice."])
    lines = [
        "hello",
        "/tools",
        "ring the bell",
        "/session",
        "/model fast",
        "/help",
        "/quit",
        "never read",
    ]
    result = invoke(config, "chat", "coach", model=model, approver=approver, lines=lines)
    assert result.exit_code == 0, result.output
    out = result.output
    assert out.startswith("/coach ready. Session: ")
    assert "/coach> Hello, ready to train?" in out
    assert "Tools of /coach (2):" in out
    assert "lookup_plan  tier 0 · read" in out and "ring_bell  tier 2 · physical" in out
    assert "⚙ ring_bell (tier 2)" in out and "✓ ring_bell: Rang 2 times." in out
    assert "/coach> Rung twice." in out
    assert "Session: " in out and "(6 messages)" in out
    assert "/model is not available in a sub-tau chat" in out
    assert "/new starts a fresh session" in out
    assert [r.tool for r in approver.requests] == ["ring_bell"]
    assert len(model.calls) == 3


def test_chat_in_turkish(config: Config, invoke, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAU_LANG", "tr")
    save_coach(config)
    result = invoke(config, "chat", "coach", model=FakeModel(["Merhaba."]), lines=["selam"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("/coach hazır. Oturum: ")


def test_sessions_are_remembered_per_sub_tau(file_config: Config, invoke) -> None:
    config = file_config
    save_coach(config)
    save_coach(config, name="landing", about="Writes landing pages.", tools=())
    first = invoke(
        config,
        "ask",
        "coach",
        "plan my week",
        model=FakeModel(["Plan A."]),
        approver=ScriptedApprover(),
    )
    assert first.exit_code == 0, first.output
    session = last_session(config, "coach")
    assert session is not None
    model = FakeModel(["Plan B."])
    again = invoke(
        config, "ask", "coach", "and next week?", model=model, approver=ScriptedApprover()
    )
    assert again.exit_code == 0, again.output
    assert last_session(config, "coach") == session
    texts = [m["content"][0].get("text") for m in model.calls[0].messages]
    assert texts == ["plan my week", "Plan A.", "and next week?"]
    store = open_session_store(config)
    assert store.read_meta(session)["channel"] == "sub:coach"
    assert store.read_meta(session)["title"] == "plan my week"
    # another sub-tau has its own session
    invoke(
        config,
        "ask",
        "landing",
        "a headline",
        model=FakeModel(["Hi."]),
        approver=ScriptedApprover(),
    )
    assert last_session(config, "landing") not in (None, session)
    # --new starts fresh and is remembered from then on
    fresh_model = FakeModel(["Fresh."])
    fresh = invoke(
        config,
        "ask",
        "coach",
        "--new",
        "start over",
        model=fresh_model,
        approver=ScriptedApprover(),
    )
    assert fresh.exit_code == 0, fresh.output
    assert last_session(config, "coach") != session
    assert len(fresh_model.calls[0].messages) == 1
    listing = invoke(config, "list")
    assert f"session: {last_session(config, 'coach')}" in listing.output


def test_chat_new_command_switches_the_session(file_config: Config, invoke) -> None:
    config = file_config
    save_coach(config)
    result = invoke(
        config,
        "chat",
        "coach",
        model=FakeModel(["One.", "Two."]),
        approver=ScriptedApprover(),
        lines=["first", "/new", "second"],
    )
    assert result.exit_code == 0, result.output
    assert "New session: " in result.output
    new_id = result.output.split("New session: ")[1].split(".")[0]
    assert last_session(config, "coach") == new_id


def test_a_pointer_to_another_channel_is_ignored(file_config: Config) -> None:
    from tau_core import build_agent

    config = file_config
    save_coach(config)
    store = open_session_store(config)
    main = build_agent(
        config=config, model=FakeModel(["Main tau here."]), tools=[], session_store=store
    )
    run(main, "a private conversation with the main tau")
    remember_session(config, "coach", main.session_id)
    model = FakeModel(["Coach here."])
    conversation = SubConversation(
        config,
        "coach",
        approver=ScriptedApprover(),
        model_factory=lambda role: model,
        tools=CATALOG,
    )
    assert conversation.session_id != main.session_id
    run(conversation.agent, "hi")
    assert len(model.calls[0].messages) == 1  # nothing of the main tau's history


def test_refresh_picks_up_edits(file_config: Config) -> None:
    config = file_config
    save_coach(config)
    registry = SubRegistry(config, tools=CATALOG)
    model = FakeModel(["One.", "Two.", "Three."])
    conversation = SubConversation(
        config,
        "coach",
        approver=ScriptedApprover(),
        model_factory=lambda role: model,
        tools=CATALOG,
    )
    session = conversation.session_id
    assert conversation.refresh() is None
    registry.save(dataclasses.replace(registry.get("coach"), public=True), force=True)
    assert conversation.refresh() is None  # nothing the agent uses changed
    run(conversation.agent, "first")
    gentle = SubTau(
        name="coach",
        about="A gentle coach.",
        persona="You are gentle.",
        tools=("lookup_plan", "ring_bell"),
    )
    registry.save(gentle, force=True)
    assert conversation.refresh() == "prompt"
    run(conversation.agent, "second")
    assert "You are gentle." in model.calls[1].system_prompt
    assert "A gentle coach" in model.calls[1].system_prompt
    registry.save(dataclasses.replace(gentle, tools=("lookup_plan",)), force=True)
    assert conversation.refresh() == "rebuilt"
    assert conversation.session_id == session
    assert conversation.agent.catalog.names() == ["lookup_plan"]
    run(conversation.agent, "third")
    assert len(model.calls[2].messages) == 5  # the history came along
    registry.remove("coach")
    with pytest.raises(SubTauNotFound, match="no sub-tau named /coach"):
        conversation.refresh()
    conversation.close()


def test_list_show_edit_remove(config: Config, invoke) -> None:
    empty = invoke(config, "list")
    assert "No sub-taus yet" in empty.output
    save_coach(config)
    (SubRegistry(config).directory / "broken.md").write_text("oops\n", encoding="utf-8")
    listing = invoke(config, "list")
    assert listing.exit_code == 0, listing.output
    assert "/broken  not valid: /broken: A sub-tau definition must start" in listing.output
    assert (
        "/coach  role: brain  tools: lookup_plan, ring_bell  public: no  session: none"
        in listing.output
    )
    assert "    A strict but kind workout coach." in listing.output
    shown = invoke(config, "show", "coach")
    assert shown.exit_code == 0, shown.output
    assert "tools:        lookup_plan (tier 0), ring_bell (tier 2)" in shown.output
    assert shown.output.rstrip().endswith(COACH_PERSONA)


def test_edit_checks_the_file(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    save_coach(config)
    path = SubRegistry(config).path("coach")
    monkeypatch.setenv("TAU_DATA_DIR", str(config.data_dir))

    def edit_with(new_text: str | None):
        def editor(target):
            assert target == path
            if new_text is not None:
                target.write_text(new_text, encoding="utf-8")
                target.chmod(0o644)

        obj = {"home": config.home, "sub_tools": list(CATALOG), "sub_editor": editor}
        return CliRunner().invoke(sub, ["edit", "coach"], obj=obj)

    unchanged = edit_with(None)
    assert unchanged.exit_code == 0 and "/coach is unchanged." in unchanged.output
    changed = edit_with(path.read_text().replace("strict but kind", "patient"))
    assert changed.exit_code == 0 and "/coach is valid." in changed.output
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    broken = edit_with(path.read_text().replace('"lookup_plan"', '"teleport"'))
    assert broken.exit_code == 1 and "unknown tool 'teleport'" in broken.output
    assert "teleport" in path.read_text()  # left as saved, for the owner to fix


def test_remove_keeps_sessions(config: Config, invoke) -> None:
    save_coach(config)
    remember_session(config, "coach", "20260930-120000-abcd")
    declined = CliRunner().invoke(
        sub,
        ["remove", "coach"],
        obj={"home": config.home},
        input="n\n",
        env={"TAU_DATA_DIR": str(config.data_dir)},
    )
    assert "Nothing was removed." in declined.output
    assert SubRegistry(config).exists("coach")
    removed = invoke(config, "remove", "coach", "--yes")
    assert removed.exit_code == 0, removed.output
    assert "sessions of /coach are kept" in removed.output
    assert not SubRegistry(config).exists("coach")
    assert last_session(config, "coach") == "20260930-120000-abcd"
    again = invoke(config, "remove", "coach", "--yes")
    assert again.exit_code == 1 and "no sub-tau named /coach" in again.output
