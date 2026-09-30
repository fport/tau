"""The main tau's tools: ``ask_sub`` (tier 0, the turn's approver) and ``create_sub`` (tier 2)."""

from __future__ import annotations

import asyncio
import stat
import threading
from types import SimpleNamespace

import pytest
from sub_helpers import BELL_EFFECT, CATALOG, OWNER_FACT, SideEffects, run, save_coach, tool_names
from tau_core import (
    Config,
    Decision,
    Tier,
    ToolFinished,
    build_agent,
    effect_of,
    tier_of,
)
from tau_core.testing import FakeGuard, FakeModel, ScriptedApprover, ToolCall
from tau_sub import CREATE_EFFECT, TOOLS, SubRegistry, tools
from tau_sub.tools import ask_sub, create_sub

BELL = [ToolCall("ring_bell", {"times": 3})]


def use(config: Config, sub_model: FakeModel | None = None) -> None:
    tools.config_factory = lambda: config
    tools.catalog_factory = lambda: list(CATALOG)
    if sub_model is not None:
        tools.model_factory = lambda role: sub_model


def main_agent(config: Config, calls: list, approver=None, final: str = "Done."):
    model = FakeModel([calls, final])
    agent = build_agent(config=config, model=model, tools=TOOLS, approver=approver)
    return agent, model


def tool_result(model: FakeModel) -> str:
    return model.calls[1].messages[-1]["content"][0]["toolResult"]["content"][0]["text"]


def test_tiers_and_effects() -> None:
    assert [tool.tool_name for tool in TOOLS] == ["ask_sub", "create_sub"]
    assert tier_of(ask_sub) is Tier.READ
    assert tier_of(create_sub) is Tier.PHYSICAL
    assert effect_of(create_sub) == CREATE_EFFECT
    assert CREATE_EFFECT.startswith("Creates a new sub-tau of your tau that can use the listed")
    # the tool context is injected, never part of the schema the model sees
    schema = ask_sub.tool_spec["inputSchema"]["json"]
    assert sorted(schema["properties"]) == ["name", "question"]


def test_ask_sub_returns_the_sub_taus_answer(config: Config) -> None:
    save_coach(config)
    sub_model = FakeModel(["Monday, Wednesday and Friday, 25 minutes each."])
    use(config, sub_model)
    agent, model = main_agent(
        config, [ToolCall("ask_sub", {"name": "coach", "question": "Plan my week."})]
    )
    events = run(agent, "Ask my coach for a plan.")
    [finished] = [e for e in events if isinstance(e, ToolFinished)]
    assert finished.tool == "ask_sub" and finished.status == "ok" and finished.approval is None
    answer = tool_result(model)
    assert answer == "/coach answered:\nMonday, Wednesday and Friday, 25 minutes each."
    # the sub-tau ran with its own prompt, its own tools and the owner's user.md
    [call] = sub_model.calls
    assert call.system_prompt.startswith("You are /coach, a specialist of your owner's tau")
    assert OWNER_FACT in call.system_prompt
    assert sorted(tool_names(call)) == ["lookup_plan", "ring_bell"]
    assert call.messages[-1]["content"][0]["text"] == "Plan my week."


@pytest.mark.parametrize("decision", [Decision.APPROVED, Decision.REJECTED])
def test_a_tier2_call_inside_ask_sub_asks_the_turns_approver(
    config: Config, decision: Decision
) -> None:
    save_coach(config)
    use(config, FakeModel([BELL, "The bell rang." if decision == "approved" else "No bell."]))
    approver = ScriptedApprover([decision])
    agent, model = main_agent(
        config, [ToolCall("ask_sub", {"name": "coach", "question": "Ring the bell."})], approver
    )
    run(agent, "Have the coach ring the bell.")
    [request] = approver.requests
    assert request.tool == "ring_bell" and request.tier is Tier.PHYSICAL
    assert request.channel == "sub:coach"
    assert request.arguments == {"times": 3}
    assert request.effect == f"/coach, a sub-tau your tau asked, wants to: {BELL_EFFECT}"
    answer = tool_result(model)
    if decision is Decision.APPROVED:
        assert SideEffects.bells == ["3"]
        assert "did not approve" not in answer
    else:
        assert SideEffects.bells == []
        assert answer.endswith("The owner did not approve: ring_bell.")


def test_ask_sub_runs_under_the_delegating_turns_guard(config: Config) -> None:
    save_coach(config)
    sub_model = FakeModel(["Rest today."])
    use(config, sub_model)
    guard = FakeGuard(state="unlocked")
    model = FakeModel([[ToolCall("ask_sub", {"name": "coach", "question": "Train?"})], "Done."])
    agent = build_agent(config=config, model=model, tools=TOOLS, guard=guard)
    run(agent, "Ask my coach.")
    admitted = [detail.channel for method, detail in guard.calls if method == "admit"]
    # the main turn, the ask_sub call (tier 0 is exempt), then the sub-tau's own turn
    assert admitted[0] == agent.channel and admitted[-1] == "sub:coach"
    assert tool_result(model) == "/coach answered:\nRest today."

    # locked meanwhile: the delegated turn is refused by the same guard, the model never runs
    guard.set_state("locked")
    sub_model.calls.clear()
    context = SimpleNamespace(agent=agent.agent, cancel_signal=threading.Event())
    answer = asyncio.run(ask_sub(name="coach", question="Train?", tool_context=context))
    assert sub_model.calls == []
    assert guard.calls[-1][0] == "admit" and guard.calls[-1][1].channel == "sub:coach"
    assert answer.startswith("/coach gave no answer (the turn ended with locked).")


def test_without_a_turn_approver_tier2_is_refused(config: Config) -> None:
    save_coach(config)
    sub_model = FakeModel([BELL, "I could not ring the bell."])
    use(config, sub_model)
    context = SimpleNamespace(agent=object(), cancel_signal=threading.Event())
    answer = asyncio.run(ask_sub(name="coach", question="Ring it.", tool_context=context))
    assert SideEffects.bells == []
    assert answer.startswith("/coach answered:\nI could not ring the bell.")
    assert "Its tier-2 tool calls were refused (ring_bell)" in answer
    assert "Tier-2 tools need `tau sub chat coach`" in answer
    refusal = sub_model.calls[1].messages[-1]["content"][0]["toolResult"]["content"][0]["text"]
    assert "Tier-2 tools need `tau sub chat coach`" in refusal


def test_ask_sub_lists_and_explains(config: Config) -> None:
    use(config, FakeModel())
    context = SimpleNamespace(agent=None, cancel_signal=None)

    def ask(name: str, question: str = "hi") -> str:
        return asyncio.run(ask_sub(name=name, question=question, tool_context=context))

    assert ask("") == "The owner has no sub-taus yet."
    save_coach(config)
    save_coach(config, name="landing", about="Writes landing pages.", tools=())
    assert ask("") == (
        "The owner's sub-taus (ask one with ask_sub):\n"
        "- coach: A strict but kind workout coach.\n"
        "- landing: Writes landing pages."
    )
    assert ask("nobody").startswith("There is no sub-tau named /nobody. The owner's sub-taus")
    assert ask("/coach", "  ") == "The question is empty; say what the sub-tau should answer."
    tools.catalog_factory = lambda: CATALOG[:1]  # ring_bell was uninstalled
    assert "unknown tool 'ring_bell'" in ask("coach")


def test_a_sub_tau_never_gets_ask_sub_or_create_sub(config: Config) -> None:
    save_coach(config, tools=("lookup_plan",))
    sub_model = FakeModel([[ToolCall("ask_sub", {"name": "coach", "question": "loop"})], "No."])
    use(config, sub_model)
    tools.catalog_factory = lambda: [*CATALOG, *TOOLS]
    agent, model = main_agent(
        config, [ToolCall("ask_sub", {"name": "coach", "question": "Call yourself."})]
    )
    run(agent, "go")
    assert "ask_sub" not in tool_names(sub_model.calls[0])
    assert "create_sub" not in tool_names(sub_model.calls[0])
    nested = sub_model.calls[1].messages[-1]["content"][0]["toolResult"]["content"][0]["text"]
    assert nested == "Tool 'ask_sub' is not registered; it was not run."
    assert len(sub_model.calls) == 2  # it never ran a second sub-tau


def test_ask_sub_sessions_are_recorded_on_the_sub_channel(file_config: Config) -> None:
    from tau_core import open_session_store
    from tau_sub import last_session

    config = file_config
    save_coach(config)
    use(config, FakeModel(["Plan."]))
    store = open_session_store(config)
    model = FakeModel([[ToolCall("ask_sub", {"name": "coach", "question": "Plan."})], "Done."])
    agent = build_agent(config=config, model=model, tools=TOOLS, session_store=store)
    run(agent, "delegate")
    subs = [s for s in store.list_sessions() if s.channel == "sub:coach"]
    [record] = subs
    meta = store.read_meta(record.session_id)
    assert meta["delegated_from"] == agent.session_id
    assert meta["delegated_channel"] == "terminal"
    assert last_session(config, "coach") is None  # the chat session is left alone


class SlowModel(FakeModel):
    """A model that takes a while before it answers, like a real one."""

    async def stream(self, *args, **kwargs):
        await asyncio.sleep(0.4)
        async for event in super().stream(*args, **kwargs):
            yield event


def test_a_cancelled_turn_stops_the_sub_tau(config: Config) -> None:
    save_coach(config)
    sub_model = SlowModel([BELL, "Too late."])
    use(config, sub_model)
    cancel = threading.Event()

    async def cancelled_while_working() -> str:
        loop = asyncio.get_running_loop()
        loop.call_later(0.1, cancel.set)  # the caller's turn is cancelled (Esc)
        context = SimpleNamespace(agent=None, cancel_signal=cancel)
        return await ask_sub(name="coach", question="Ring.", tool_context=context)

    answer = asyncio.run(cancelled_while_working())
    assert SideEffects.bells == []
    assert answer.startswith("/coach gave no answer (the turn ended with cancelled).")
    already = SimpleNamespace(agent=None, cancel_signal=cancel)
    again = asyncio.run(ask_sub(name="coach", question="Ring.", tool_context=already))
    assert again == "The turn was cancelled; /coach was not asked."


@pytest.mark.parametrize("decision", [None, Decision.REJECTED, Decision.TIMEOUT])
def test_create_sub_is_refused_without_an_approval(config: Config, decision) -> None:
    use(config)
    approver = None if decision is None else ScriptedApprover([decision])
    arguments = {
        "name": "landing",
        "about": "Writes landing pages.",
        "persona": "You write short landing pages.",
        "tools": ["lookup_plan"],
    }
    agent, _ = main_agent(config, [ToolCall("create_sub", arguments)], approver)
    [finished] = [e for e in run(agent, "make a landing helper") if isinstance(e, ToolFinished)]
    assert finished.status == "rejected"
    assert not SubRegistry(config).exists("landing")
    if approver is not None:
        [request] = approver.requests
        assert request.tool == "create_sub" and request.effect == CREATE_EFFECT
        assert request.arguments == arguments


def test_create_sub_works_with_an_approval(config: Config) -> None:
    use(config)
    approver = ScriptedApprover([Decision.APPROVED])
    arguments = {
        "name": "landing",
        "about": "Writes landing pages.",
        "persona": "You write short landing pages.",
        "tools": ["lookup_plan", "ring_bell"],
    }
    agent, model = main_agent(config, [ToolCall("create_sub", arguments)], approver)
    [finished] = [e for e in run(agent, "make a landing helper") if isinstance(e, ToolFinished)]
    assert finished.status == "ok" and finished.approval == "approved"
    assert tool_result(model).startswith("Created /landing.")
    registry = SubRegistry(config, tools=CATALOG)
    landing = registry.get("landing")
    assert landing.tools == ("lookup_plan", "ring_bell") and landing.role == "brain"
    assert stat.S_IMODE(registry.path("landing").stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"name": "coach"}, "already exists"),
        ({"tools": ["teleport"]}, "unknown tool 'teleport'"),
        ({"tools": ["create_sub"]}, "never allowed in a sub-tau"),
        ({"name": "Bad Name"}, "Invalid sub-tau name"),
        ({"about": ""}, "'about' is empty"),
    ],
)
def test_create_sub_validates_and_never_overwrites(
    config: Config, arguments: dict, message: str
) -> None:
    save_coach(config)
    before = SubRegistry(config).path("coach").read_bytes()
    use(config)
    full = {"name": "helper", "about": "Helps.", "persona": "You help.", "tools": []}
    full.update(arguments)
    answer = create_sub(**full)
    assert answer.startswith("Not created: ") and message in answer
    assert SubRegistry(config).path("coach").read_bytes() == before
