"""``/compact`` building blocks: ``summarize``, ``seed_messages``, the seed's persistence."""

from __future__ import annotations

from pathlib import Path

import pytest
from tau_core import (
    CompactionError,
    Config,
    build_agent,
    compaction_title,
    record_compaction,
    seed_messages,
    summarize,
)
from tau_core.compaction import SUMMARY_PROMPT, SYSTEM_PROMPT
from tau_core.config import SessionsConfig
from tau_core.sessions import FileSessionStore, MemorySessionStore, open_session_store
from tau_core.testing import FakeModel, test_config


def texts(messages: list) -> list[str]:
    return [block["text"] for m in messages for block in m["content"] if "text" in block]


async def test_summarize_uses_a_copy_of_the_history_and_the_agents_model(config: Config) -> None:
    model = FakeModel(["Salon 22 derece.", "The user asked for the room temperature: 22 °C."])
    agent = build_agent(config=config, model=model, tools=[])
    await agent.ask("Salon kaç derece?")
    before = [dict(m) for m in agent.messages]

    summary = await summarize(agent)

    assert summary == "The user asked for the room temperature: 22 °C."
    call = model.calls[-1]  # the throwaway agent used the same model instance
    assert call.system_prompt == SYSTEM_PROMPT
    assert "Focus on" not in call.system_prompt
    assert texts(call.messages) == ["Salon kaç derece?", "Salon 22 derece.", SUMMARY_PROMPT]
    assert not call.tool_specs  # no tools: the tier gate is not involved
    assert agent.messages == before  # the live history is untouched
    assert len(agent.messages) == 2


async def test_summarize_appends_the_focus(config: Config) -> None:
    model = FakeModel(["ok", "Focused summary."])
    agent = build_agent(config=config, model=model, tools=[])
    await agent.ask("hi")
    assert await summarize(agent, focus="  the open  tasks ") == "Focused summary."
    assert model.calls[-1].system_prompt.endswith("\n\nFocus on: the open tasks")


async def test_summarize_repairs_a_history_that_ends_on_the_user(config: Config) -> None:
    def boom(messages, system_prompt):
        raise RuntimeError("provider down")

    model = FakeModel([boom, "Summary after a failed turn."])
    agent = build_agent(config=config, model=model, tools=[])
    await agent.ask("soru")  # the model failed: the history ends on the user message
    assert agent.messages[-1]["role"] == "user"

    assert await summarize(agent) == "Summary after a failed turn."
    sent = model.calls[-1].messages
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert texts(sent) == ["soru", "(The previous turn did not finish.)", SUMMARY_PROMPT]


async def test_summarize_repairs_a_history_that_ends_on_a_tool_use(config: Config) -> None:
    """M2: after a trailing ``toolUse`` the SDK inserts its own user ``toolResult`` message,
    so the request must come as ``[assistant repair, user request]`` to keep roles alternating
    (the same rule as ``TauAgent``: ``tau_core.agent.dangling``)."""
    model = FakeModel(["ok", "Summary after a crash-cut tool call."])
    agent = build_agent(config=config, model=model, tools=[])
    await agent.ask("soru")
    # A turn cut before the tool result was stored (the hub died during an approval): the
    # history ends on the assistant's toolUse. Set up by hand only because it is a test.
    agent.agent.messages.append(
        {
            "role": "assistant",
            "content": [{"toolUse": {"toolUseId": "t9", "name": "relay", "input": {}}}],
        }
    )
    assert await summarize(agent) == "Summary after a crash-cut tool call."
    sent = model.calls[-1].messages
    roles = ["user", "assistant", "assistant", "user", "assistant", "user"]
    assert [m["role"] for m in sent] == roles
    assert "toolResult" in sent[3]["content"][0]  # the SDK's synthetic result
    assert texts(sent)[-2:] == ["(The previous turn did not finish.)", SUMMARY_PROMPT]
    assert len(agent.messages) == 3  # the live history is untouched


async def test_summarize_honours_the_cancel_signal(config: Config) -> None:
    """M1: a set cancel event ends the SDK invocation with ``cancelled``; the placeholder reply
    is never returned as a summary."""
    import threading

    from tau_core import CompactionCancelled

    model = FakeModel(["ok", "never used"])
    agent = build_agent(config=config, model=model, tools=[])
    await agent.ask("hi")
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(CompactionCancelled, match="cancelled"):
        await summarize(agent, cancel_signal=cancel)
    assert len(agent.messages) == 2


async def test_summarize_errors_are_compaction_errors(config: Config) -> None:
    empty = build_agent(config=config, model=FakeModel(), tools=[])
    with pytest.raises(CompactionError, match="no messages to summarize"):
        await summarize(empty)

    def boom(messages, system_prompt):
        raise RuntimeError("provider down")

    failing = build_agent(config=config, model=FakeModel(["ok", boom]), tools=[])
    await failing.ask("hi")
    with pytest.raises(CompactionError, match="the model call failed: provider down"):
        await summarize(failing)
    assert len(failing.messages) == 2  # still intact

    blank = build_agent(config=config, model=FakeModel(["ok", "   "]), tools=[])
    await blank.ask("hi")
    with pytest.raises(CompactionError, match="empty summary"):
        await summarize(blank)


def test_seed_messages_shape() -> None:
    seed = seed_messages("Two facts.", "20260929-120000-abcd")
    assert [m["role"] for m in seed] == ["user", "assistant"]
    assert seed[0]["content"] == [
        {
            "text": "Summary of the previous conversation (session 20260929-120000-abcd):\n\n"
            "Two facts."
        }
    ]
    assert seed[1]["content"] == [{"text": "Understood. I will continue from this summary."}]


async def test_seed_survives_a_file_store_round_trip(tmp_path: Path) -> None:
    config = test_config(tmp_path, sessions=SessionsConfig(backend="file"))
    store = open_session_store(config)
    assert isinstance(store, FileSessionStore)
    seed = seed_messages("The user prefers short answers.", "20260929-120000-abcd")

    first = build_agent(config=config, model=FakeModel(), tools=[], session_store=store)
    seeded = build_agent(
        config=config, model=FakeModel(), tools=[], session_store=store, seed_messages=seed
    )
    assert seeded.session_id != first.session_id
    assert seeded.messages == seed and seeded.messages is not seed  # a copy went in
    assert len(store.list_messages(seeded.session_id, "tau")) == 2  # persisted on creation
    seeded.close()

    # A new process: a fresh store on the same directory restores the seed as the history.
    model = FakeModel(["Devam ediyorum."])
    resumed = build_agent(
        config=config,
        model=model,
        tools=[],
        session_store=open_session_store(config),
        session_id=seeded.session_id,
    )
    assert texts(resumed.messages) == texts(seed)
    await resumed.ask("Devam.")
    assert texts(model.calls[0].messages) == [*texts(seed), "Devam."]
    assert len(store.list_messages(seeded.session_id, "tau")) == 4


async def test_compaction_title_and_record(config: Config) -> None:
    store = MemorySessionStore()
    agent = build_agent(config=config, model=FakeModel(["ok"]), tools=[], session_store=store)
    assert compaction_title(agent) == ""  # nothing yet
    await agent.ask("  Bir   uzun    başlık sorusu  ")
    assert compaction_title(agent) == "Bir uzun başlık sorusu"  # the stored title

    untracked = build_agent(config=config, model=FakeModel(["ok"]), tools=[])
    await untracked.ask("x" * 80)
    assert compaction_title(untracked) == "x" * 60  # cut like a title, no store needed

    record_compaction(
        store, previous=agent.session_id, new="20260929-130000-beef", title="Bir", role="fast"
    )
    assert store.read_meta("20260929-130000-beef") == {
        "compacted_from": agent.session_id,
        "title": "Bir",
        "role": "fast",
    }
    assert store.read_meta(agent.session_id)["compacted_to"] == "20260929-130000-beef"
    # The old session is written first, so the new one stays the most recent (nit 4).
    assert [s.session_id for s in store.list_sessions()][:2] == [
        "20260929-130000-beef",
        agent.session_id,
    ]
    record_compaction(None, previous="a", new="b")  # no store: nothing to do
