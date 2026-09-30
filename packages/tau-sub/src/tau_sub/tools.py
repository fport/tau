"""The main tau's tools for sub-taus (``tau.tools`` entry point ``sub``).

- ``ask_sub`` (tier 0) runs a sub-tau for one turn and returns its answer. The sub-tau's own
  tool calls pass through its own tier gate, whose approver is the approver of the turn that
  called ``ask_sub`` (found through the tool context, see :mod:`tau_sub.approval`): a tier-2
  call asks the owner on the channel the conversation came from. The sub-tau runs under that
  turn's owner guard too (ADR 0008), so a delegation is admitted and stepped up exactly as the
  delegating channel is. When no approver can be
  found (the tool was called outside a tau agent), every tier-2 call of the sub-tau is refused
  and the answer says so. Nothing is ever approved on the owner's behalf.
- ``create_sub`` (tier 2) writes a new definition: it activates a new agent configuration that
  may use tools, like a self-written tool, so the owner approves every call. It validates like
  ``tau sub new`` and never overwrites.

Each ``ask_sub`` call runs on a new session of the sub-tau (channel ``sub:<name>``, recorded
in the session store with ``delegated_from``); the session the owner resumes with
``tau sub chat`` is left alone, so a delegation never races an open chat.

The tools find the configuration lazily at call time (``Config.load()``). Tests replace
:data:`config_factory`, :data:`model_factory` and :data:`catalog_factory`. Everything they
return is short English for the model.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from strands.types.tools import AgentTool, ToolContext
from tau_core import (
    Approver,
    Config,
    ConfigError,
    MissingCredentials,
    Notice,
    TauAgent,
    TextDelta,
    Tier,
    ToolFinished,
    TurnEnd,
    open_session_store,
    tau_tool,
)
from tau_core.guard import DISCOVER

from tau_sub.agent import build_sub_agent
from tau_sub.approval import DelegatedApprover, RefusingApprover, turn_approver, turn_gate
from tau_sub.definition import SubRegistry, SubTau, SubTauError, SubTauNotFound

if TYPE_CHECKING:
    from strands.models.model import Model

__all__ = [
    "CREATE_EFFECT",
    "TOOLS",
    "ask_sub",
    "catalog_factory",
    "config_factory",
    "create_sub",
    "model_factory",
    "no_approver_note",
]

logger = logging.getLogger(__name__)

CREATE_EFFECT = "Creates a new sub-tau of your tau that can use the listed tools."
ANSWER_LIMIT = 8000
CANCEL_POLL_SECONDS = 0.1

config_factory: Callable[[], Config] | None = None
"""Replaces ``Config.load()`` (tests); ``None`` = the default."""
model_factory: Callable[[str], Model] | None = None
"""``role → model`` for the sub-tau (tests); ``None`` = the role's configured model."""
catalog_factory: Callable[[], list[AgentTool]] | None = None
"""Replaces the discovered tool catalog (tests); ``None`` = every ``tau.tools`` tool."""


def no_approver_note(name: str) -> str:
    """The refusal note when ``ask_sub`` runs without a turn approver (fixed English)."""
    return (
        f"Tier-2 tools need `tau sub chat {name}`: no approver was reachable from this "
        "delegation, so the call was refused."
    )


def _config() -> Config:
    return config_factory() if config_factory is not None else Config.load()


def _registry(config: Config) -> SubRegistry:
    return SubRegistry(config, tools=catalog_factory() if catalog_factory is not None else None)


def _listing(registry: SubRegistry) -> str:
    subs = registry.list()
    if not subs:
        return "The owner has no sub-taus yet."
    lines = ["The owner's sub-taus (ask one with ask_sub):"]
    lines += [f"- {sub.name}: {sub.about}" for sub in subs]
    return "\n".join(lines)


async def _watch_cancel(signal: threading.Event, agent: TauAgent) -> None:
    """Stop the sub-tau's turn when the turn that called ``ask_sub`` is cancelled."""
    while not signal.is_set():
        await asyncio.sleep(CANCEL_POLL_SECONDS)
    agent.cancel()


async def _run(agent: TauAgent, question: str, cancel: threading.Event | None) -> dict[str, Any]:
    parts: list[str] = []
    notices: list[str] = []
    finished: list[ToolFinished] = []
    stop_reason = "end_turn"
    watcher = asyncio.create_task(_watch_cancel(cancel, agent)) if cancel is not None else None
    try:
        async for event in agent.stream(question):
            if isinstance(event, TextDelta):
                parts.append(event.text)
            elif isinstance(event, Notice):
                notices.append(event.text)
            elif isinstance(event, ToolFinished):
                finished.append(event)
            elif isinstance(event, TurnEnd):
                stop_reason = event.stop_reason
    finally:
        if watcher is not None:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
    return {
        "text": "".join(parts).strip(),
        "notices": notices,
        "finished": finished,
        "stop_reason": stop_reason,
    }


def _answer(sub: SubTau, outcome: dict[str, Any], *, approver_reachable: bool) -> str:
    text = outcome["text"]
    if len(text) > ANSWER_LIMIT:
        text = text[: ANSWER_LIMIT - 1] + "…"
    if text:
        lines = [f"/{sub.name} answered:", text]
    else:
        lines = [f"/{sub.name} gave no answer (the turn ended with {outcome['stop_reason']})."]
    if outcome["notices"]:
        lines.append("Notices from its turn: " + " ".join(outcome["notices"]))
    refused = [f.tool for f in outcome["finished"] if f.status == "rejected"]
    if refused and not approver_reachable:
        lines.append(
            f"Its tier-2 tool calls were refused ({', '.join(dict.fromkeys(refused))}): "
            + no_approver_note(sub.name)
        )
    elif refused:
        lines.append(f"The owner did not approve: {', '.join(dict.fromkeys(refused))}.")
    return "\n".join(lines)


@tau_tool(tier=Tier.READ, context=True)
async def ask_sub(name: str, question: str, tool_context: ToolContext) -> str:
    """Ask one of the owner's sub-taus a question and return its answer. A sub-tau is a small
    specialist of this tau with its own persona, model and tools (for example /coach for
    workouts). It runs one turn on its own; its tier-2 tools ask the owner for approval like
    yours. Call it with an empty name to list the sub-taus.

    Args:
        name: The sub-tau's name without the slash, for example "coach"; empty to list them.
        question: The question, with every detail the sub-tau needs: it does not see this
            conversation.
    """
    try:
        config = _config()
    except ConfigError as exc:
        return f"Sub-taus are not available: {exc}"
    registry = _registry(config)
    wanted = name.strip().lstrip("/")
    if not wanted:
        return _listing(registry)
    try:
        sub = registry.get(wanted)
    except SubTauNotFound:
        return f"There is no sub-tau named /{wanted}. " + _listing(registry)
    except SubTauError as exc:
        return f"/{wanted} cannot run: {exc}"
    if not question.strip():
        return "The question is empty; say what the sub-tau should answer."
    cancel = getattr(tool_context, "cancel_signal", None)
    if cancel is not None and cancel.is_set():
        return f"The turn was cancelled; /{sub.name} was not asked."

    caller = getattr(tool_context, "agent", None)
    gate = turn_gate(caller)
    inner = turn_approver(caller)
    approver: Approver
    if inner is not None:
        approver = DelegatedApprover(inner, sub.name)
    else:
        logger.warning("sub: ask_sub /%s runs without a turn approver; tier 2 is refused", wanted)
        approver = RefusingApprover(no_approver_note(sub.name))
    try:
        store = open_session_store(config)
        agent = build_sub_agent(
            config,
            sub,
            approver=approver,
            session_store=store,
            model=model_factory(sub.role) if model_factory is not None else None,
            tools=catalog_factory() if catalog_factory is not None else None,
            # The delegating turn's owner guard (ADR 0008); resolved from the configuration
            # when no tau turn called the tool.
            guard=gate.guard if gate is not None else DISCOVER,
        )
    except (ConfigError, MissingCredentials, SubTauError, OSError, ValueError) as exc:
        return f"/{sub.name} cannot run: {exc}"
    with contextlib.suppress(Exception):
        store.write_meta(
            agent.session_id,
            delegated_from=getattr(gate, "session_id", None),
            delegated_channel=getattr(gate, "channel", None),
        )
    try:
        outcome = await _run(agent, question, cancel)
    finally:
        agent.close()
    logger.info(
        "sub: /%s answered a delegation in session %s (%s)",
        sub.name,
        agent.session_id,
        outcome["stop_reason"],
    )
    return _answer(sub, outcome, approver_reachable=inner is not None)


@tau_tool(tier=Tier.PHYSICAL, effect=CREATE_EFFECT)
def create_sub(name: str, about: str, persona: str, tools: list[str]) -> str:
    """Create a new sub-tau: a small specialist of the owner's tau with its own persona and a
    list of tools it may use, saved as persona/subs/<name>.md. Needs the owner's approval
    every time. An existing sub-tau is never replaced.

    Args:
        name: 2 to 31 characters: lowercase letters, digits and "-", starting with a letter.
        about: One line of at most 200 characters saying what the sub-tau does.
        persona: The specialist's character and task, written to it in the second person.
        tools: Names of tools from your catalog it may use; an empty list for none.
            ask_sub and create_sub are never allowed.
    """
    try:
        config = _config()
    except ConfigError as exc:
        return f"Sub-taus are not available: {exc}"
    registry = _registry(config)
    try:
        path = registry.save(
            SubTau(name=name.strip().lstrip("/"), about=about, persona=persona, tools=tuple(tools))
        )
    except SubTauError as exc:
        return f"Not created: {exc}"
    except OSError as exc:
        return f"Not created: the definition could not be written ({exc.strerror or exc})."
    sub = name.strip().lstrip("/")
    logger.info("sub: created /%s at %s", sub, path)
    return (
        f"Created /{sub}. Ask it with ask_sub; the owner can talk to it with "
        f"`tau sub chat {sub}` and edit it with `tau sub edit {sub}`."
    )


TOOLS = [ask_sub, create_sub]
