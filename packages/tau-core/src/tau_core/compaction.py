"""Compaction: summarize a session with the agent's own model and seed a new session with it.

``/compact`` respects "sessions are kept forever" (ADR 0003): the current session is never
edited or trimmed. A throwaway Strands ``Agent`` (same model, no tools, no session manager, no
hooks, so the tier gate is not involved) reads a copy of the history and writes the summary;
the summary becomes the first two messages of a *new* session through
``build_agent(seed_messages=...)``, and the two sessions point at each other in their metadata
(``compacted_from`` on the new one, ``compacted_to`` on the old one).
"""

from __future__ import annotations

import copy
import logging
import threading

from strands import Agent
from strands.types.content import Message

from tau_core.agent import TITLE_LIMIT, TauAgent, conversation_manager_for, dangling
from tau_core.sessions import SessionStore

__all__ = [
    "SUMMARY_PROMPT",
    "SYSTEM_PROMPT",
    "CompactionCancelled",
    "CompactionError",
    "compaction_title",
    "record_compaction",
    "seed_messages",
    "summarize",
]

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = "Write the summary now."

SYSTEM_PROMPT = """\
You are compacting a conversation between a user and their personal assistant, so that the \
assistant can continue it in a new session with only your summary as history.

Summarize the conversation so far for the assistant that will continue it. Keep:
- facts about the user: how they want to be addressed, preferences, anything they said about \
themselves or their environment
- decisions that were made, and why
- open tasks, unanswered questions and anything the user is still waiting for
- results of tool calls that still matter (values, identifiers, states), and actions the user \
refused
- the language the user writes in; state it explicitly, so the continuation answers in it

Leave out greetings, small talk and anything that no longer matters. Write in the language the \
user writes in, as plain prose or short bullet lists, without headings, preamble or closing \
remarks. Do not address the user; the text is for the assistant.\
"""

_REPAIR_TEXT = "(The previous turn did not finish.)"


class CompactionError(Exception):
    """The session could not be summarized; ``str(exc)`` says why (plain English)."""


class CompactionCancelled(CompactionError):
    """The caller's ``cancel_signal`` stopped the summarizer; nothing was changed."""


def _text_blocks(message: Message) -> list[str]:
    return [
        str(block["text"])
        for block in message.get("content", [])
        if isinstance(block, dict) and "text" in block
    ]


def _summary_request(history: list[Message]) -> str | list[Message]:
    """The prompt for the summarizer: the request alone, or ``[assistant repair, user
    request]`` when the copied history *dangles* (the same rule as ``TauAgent``, see
    :func:`tau_core.agent.dangling`): after a trailing ``user`` message the pair keeps roles
    alternating; after a trailing ``toolUse`` the SDK first inserts its own synthetic user
    ``toolResult`` message, so a bare request would put two user messages in a row, which
    Bedrock rejects."""
    if history and dangling(history[-1]):
        return [
            {"role": "assistant", "content": [{"text": _REPAIR_TEXT}]},
            {"role": "user", "content": [{"text": SUMMARY_PROMPT}]},
        ]
    return SUMMARY_PROMPT


async def summarize(
    agent: TauAgent, *, focus: str | None = None, cancel_signal: threading.Event | None = None
) -> str:
    """The summary of ``agent``'s current history, written by the agent's own model.

    The summarizer is a throwaway Strands ``Agent`` over a deep copy of ``agent.messages`` (the
    live agent's history, which its conversation manager already windowed), with no tools, no
    hooks and no session manager; ``agent`` itself is left untouched. ``focus`` is an optional
    instruction appended to the system prompt. ``cancel_signal`` is handed to the SDK as the
    invocation's cancel event: setting it (Esc in the TUI) ends the call at the SDK's next
    checkpoint with :class:`CompactionCancelled`. Raises :class:`CompactionError` when there
    is nothing to summarize, when the model call fails or when it returns no text.
    """
    history = copy.deepcopy(agent.messages)
    if not history:
        raise CompactionError("the session has no messages to summarize.")
    system_prompt = SYSTEM_PROMPT
    if focus and focus.strip():
        system_prompt += f"\n\nFocus on: {' '.join(focus.split())}"
    summarizer = Agent(
        model=agent.agent.model,
        system_prompt=system_prompt,
        messages=history,
        tools=[],
        callback_handler=None,
        conversation_manager=conversation_manager_for(agent.config.agent),
        name="tau-compaction",
    )
    try:
        result = await summarizer.invoke_async(
            _summary_request(history), cancel_signal=cancel_signal
        )
    except Exception as exc:
        logger.exception("compaction failed in session %s", agent.session_id)
        detail = " ".join(str(exc).split())[:160].rstrip(". ") or type(exc).__name__
        raise CompactionError(f"the model call failed: {detail}.") from exc
    if result.stop_reason == "cancelled":
        # The SDK stores its "Cancelled by user" placeholder as the reply; never a summary.
        logger.info("compaction cancelled in session %s", agent.session_id)
        raise CompactionCancelled("compaction was cancelled.")
    summary = str(result).strip()
    if not summary:
        raise CompactionError("the model returned an empty summary.")
    return summary


def seed_messages(summary: str, previous_session_id: str) -> list[Message]:
    """The two messages a compacted session starts with: the summary as a user message, and an
    assistant acknowledgement, so the new user turn follows an assistant message."""
    return [
        {
            "role": "user",
            "content": [
                {
                    "text": f"Summary of the previous conversation (session "
                    f"{previous_session_id}):\n\n{summary}"
                }
            ],
        },
        {
            "role": "assistant",
            "content": [{"text": "Understood. I will continue from this summary."}],
        },
    ]


def compaction_title(agent: TauAgent) -> str:
    """The title the new session inherits: the old session's stored title, else the first user
    line of its history (cut like ``TauAgent`` cuts titles), else ``""``."""
    if agent.store is not None:
        try:
            title = str(agent.store.read_meta(agent.session_id).get("title") or "")
        except Exception:
            logger.exception("could not read the title of session %s", agent.session_id)
            title = ""
        if title:
            return title
    for message in agent.messages:
        if message.get("role") != "user":
            continue
        for text in _text_blocks(message):
            line = " ".join(text.split())[:TITLE_LIMIT]
            if line:
                return line
    return ""


def record_compaction(
    store: SessionStore | None,
    *,
    previous: str,
    new: str,
    title: str = "",
    role: str | None = None,
) -> None:
    """Link the two sessions in their metadata: ``compacted_to`` on the old one, then
    ``compacted_from`` (with the inherited ``title`` and ``role``) on the new one. The old
    session is written first on purpose: every write refreshes ``updated_at``, and the new
    session must stay the most recent one in ``/sessions``. A store failure is logged, never
    raised: the switch already happened."""
    if store is None:
        return
    try:
        store.write_meta(previous, compacted_to=new)
        meta: dict[str, str] = {"compacted_from": previous}
        if title:
            meta["title"] = title
        if role:
            meta["role"] = role
        store.write_meta(new, **meta)
    except Exception:
        logger.exception("could not link the compacted sessions %s -> %s", previous, new)
