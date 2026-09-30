"""Public test helpers: a scripted model, scripted approvers and a throwaway config.

Everything here runs offline. Other tau packages (tau-tui, plugins) use these in their tests.
There is deliberately no approver that approves everything: an approved path is scripted with
``ScriptedApprover([Decision.APPROVED])`` so every approval is visible in the test.
"""

from __future__ import annotations

import copy
import json
from collections.abc import AsyncGenerator, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from strands.models.model import Model
from strands.types.content import Message, SystemContentBlock
from strands.types.tools import ToolSpec

from tau_core.approval import ApprovalRequest, AutoRejectApprover, Decision
from tau_core.config import Config

__all__ = [
    "AutoRejectApprover",
    "FakeCall",
    "FakeModel",
    "Reply",
    "ScriptedApprover",
    "ToolCall",
    "Truncated",
    "test_config",
]


@dataclass
class ToolCall:
    """One tool use the fake model asks for."""

    name: str
    input: dict[str, Any] = field(default_factory=dict)
    tool_use_id: str | None = None


@dataclass
class Truncated:
    """A text reply cut by the provider's output limit (``stopReason: max_tokens``)."""

    text: str


Reply = str | Truncated | list[ToolCall] | Callable[[list[Message], str | None], "Reply"]


@dataclass
class FakeCall:
    """What the agent sent on one model call.

    ``system_prompt`` is the string form the SDK derives (text blocks joined with a newline);
    ``system_prompt_content`` is the block list with cache points, when the agent used one.
    """

    messages: list[Message]
    system_prompt: str | None
    tool_specs: list[ToolSpec] | None
    system_prompt_content: list[SystemContentBlock] | None = None


class FakeModel(Model):
    """A Strands model that replays scripted replies.

    Replies are used in order; when they run out, ``default`` is returned. A ``str`` streams
    as two text deltas, a ``Truncated`` streams its text and stops with ``max_tokens``, a
    ``list[ToolCall]`` streams tool uses (``stopReason: tool_use``), a callable receives
    ``(messages, system_prompt)`` and returns one of those (or raises, to fail the call).
    """

    def __init__(self, replies: Sequence[Reply] | None = None, *, default: str = "Okay."):
        self.replies: list[Reply] = list(replies or [])
        self.default = default
        self.calls: list[FakeCall] = []
        self.config: dict[str, Any] = {"model_id": "fake"}
        self._tool_counter = 0

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return dict(self.config)

    def _next_reply(self, messages: list[Message], system_prompt: str | None) -> str | list:
        reply: Reply = self.replies.pop(0) if self.replies else self.default
        while callable(reply):
            reply = reply(messages, system_prompt)
        return reply

    async def stream(
        self,
        messages: list[Message],
        tool_specs: list[ToolSpec] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[dict[str, Any], None]:
        self.calls.append(
            FakeCall(
                messages=copy.deepcopy(messages),
                system_prompt=system_prompt,
                tool_specs=tool_specs,
                system_prompt_content=copy.deepcopy(kwargs.get("system_prompt_content")),
            )
        )
        reply = self._next_reply(messages, system_prompt)
        yield {"messageStart": {"role": "assistant"}}
        if isinstance(reply, str | Truncated):
            text = reply if isinstance(reply, str) else reply.text
            half = len(text) // 2
            yield {"contentBlockStart": {"start": {}}}
            for part in (text[:half], text[half:]):
                yield {"contentBlockDelta": {"delta": {"text": part}}}
            yield {"contentBlockStop": {}}
            stop = "end_turn" if isinstance(reply, str) else "max_tokens"
            yield {"messageStop": {"stopReason": stop}}
        else:
            for call in reply:
                self._tool_counter += 1
                tool_use_id = call.tool_use_id or f"t{self._tool_counter}"
                start = {"toolUse": {"toolUseId": tool_use_id, "name": call.name}}
                yield {"contentBlockStart": {"start": start}}
                delta = {"toolUse": {"input": json.dumps(call.input, ensure_ascii=False)}}
                yield {"contentBlockDelta": {"delta": delta}}
                yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
                "metrics": {"latencyMs": 1},
            }
        }

    async def structured_output(
        self, output_model: Any, prompt: Any, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncGenerator[dict[str, Any], None]:
        try:
            output = output_model()
        except Exception:
            output = output_model.model_construct()
        yield {"output": output}


class ScriptedApprover:
    """Returns scripted decisions in order and records every request; exhausted → REJECTED."""

    name = "scripted"

    def __init__(self, decisions: Iterable[Decision] = ()):
        self.decisions: list[Decision] = list(decisions)
        self.requests: list[ApprovalRequest] = []

    async def decide(self, request: ApprovalRequest) -> Decision:
        self.requests.append(request)
        return self.decisions.pop(0) if self.decisions else Decision.REJECTED


_TEST_TOML = """\
[models.roles.brain]
provider = "fake"
model_id = "fake-brain"

[models.roles.fast]
provider = "fake"
model_id = "fake-fast"

[models.roles.local]
provider = "fake"
model_id = "fake-local"

[agent]
max_turns = 12

[sessions]
backend = "memory"

[hub]
control_port = 7877
heartbeat_seconds = 5

[ui]
language = "en"
"""

_TEST_PERSONA = "You are tau: a polite assistant who keeps replies short.\n"
_TEST_USER = "Address the user formally.\n"


def test_config(tmp_path: Path, **overrides: Any) -> Config:
    """A ``Config`` under ``tmp_path``: fake roles, memory sessions, a minimal persona.

    ``tmp_path/home`` holds ``tau.toml`` and ``persona/``; ``tmp_path/data`` is the data dir.
    ``overrides`` are applied with :meth:`Config.with_overrides`.
    """
    home = Path(tmp_path) / "home"
    persona_dir = home / "persona"
    persona_dir.mkdir(parents=True, exist_ok=True)
    (home / "tau.toml").write_text(_TEST_TOML, encoding="utf-8")
    (persona_dir / "persona.md").write_text(_TEST_PERSONA, encoding="utf-8")
    (persona_dir / "user.md").write_text(_TEST_USER, encoding="utf-8")
    data_dir = Path(tmp_path) / "data"
    config = Config.load(home, env={"TAU_DATA_DIR": str(data_dir)})
    return config.with_overrides(**overrides) if overrides else config


# Not a test, despite the name; keep pytest from collecting it when imported into a test module.
test_config.__test__ = False  # type: ignore[attr-defined]


# Approval and event helpers (issue 006). Appended here so the section above stays untouched.

import asyncio  # noqa: E402

from tau_core.events import AgentEvent, EventBus  # noqa: E402

__all__ += ["UnansweredApprover", "record_events"]


class UnansweredApprover:
    """Never answers, like a user who walked away. For approval-timeout tests.

    ``decide`` waits until it is cancelled (by the gate's ``timeout_seconds`` or the
    approver's own), records every request and counts the cancellations. It never approves.
    """

    name = "unanswered"

    def __init__(self, *, timeout_seconds: float | None = None):
        self.timeout_seconds = timeout_seconds
        self.requests: list[ApprovalRequest] = []
        self.cancelled = 0

    async def decide(self, request: ApprovalRequest) -> Decision:
        self.requests.append(request)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return Decision.REJECTED  # pragma: no cover  (the wait above never ends on its own)


def record_events(bus: EventBus, *kinds: str) -> list[AgentEvent]:
    """Subscribe to ``bus``; the returned list fills with its events (only ``kinds`` if given)."""
    seen: list[AgentEvent] = []

    def sink(event: AgentEvent) -> None:
        if not kinds or event.kind in kinds:
            seen.append(event)

    bus.subscribe(sink)
    return seen


# Telegram Bot API stand-in (issue 014). Appended here so the sections above stay untouched.

from contextlib import suppress  # noqa: E402

from tau_core.channels.telegram import MAX_MESSAGE_LENGTH, TelegramError  # noqa: E402

__all__ += ["FakeBotApi"]


class FakeBotApi:
    """An offline Telegram Bot API for :class:`tau_core.channels.telegram.TelegramService`.

    Queue updates with :meth:`push_message` / :meth:`push_callback` / :meth:`push`; read what
    the bot did from :attr:`calls` and :attr:`sent`. ``getUpdates`` behaves like Telegram's:
    an ``offset`` confirms (drops) every update below it, ``allowed_updates`` filters, and an
    empty queue waits up to ``timeout`` seconds for a push. It refuses to run while
    :attr:`webhook_url` is set (409), as the real API does. :meth:`fail` scripts errors
    (``ConnectionError`` for a network loss, :class:`TelegramError` for a refusal) for the next
    calls of one method; ``reject_html`` makes every ``parse_mode="HTML"`` message fail with 400.
    """

    def __init__(
        self, *, username: str = "tau_test_bot", reject_html: bool = False, webhook_url: str = ""
    ):
        self.username = username
        self.reject_html = reject_html
        self.webhook_url = webhook_url
        self.updates: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        """Every method called with its parameters, failed calls included."""
        self.sent: list[dict[str, Any]] = []
        """The parameters of every ``sendMessage`` that went through."""
        self.commands: dict[str, list[dict[str, str]]] = {}
        """Command menus by ``setMyCommands`` scope (JSON); read one with :meth:`menu`."""
        self.edits: list[dict[str, Any]] = []
        """The parameters of every ``editMessageText``."""
        self.answers: list[dict[str, Any]] = []
        """The parameters of every ``answerCallbackQuery``."""
        self._failures: dict[str, list[BaseException]] = {}
        self._next_update_id = 1
        self._next_message_id = 1
        self._arrived: asyncio.Event | None = None

    # -- scripting ---------------------------------------------------------------------------

    def push(self, update: dict[str, Any]) -> dict[str, Any]:
        """Queue a raw update; an ``update_id`` is assigned when it has none."""
        update = copy.deepcopy(update)
        if "update_id" not in update:
            update["update_id"] = self._next_update_id
        self._next_update_id = max(self._next_update_id, update["update_id"]) + 1
        self.updates.append(update)
        if self._arrived is not None:
            self._arrived.set()
        return update

    def push_message(
        self, chat_id: int, text: str | None, *, chat_type: str = "private"
    ) -> dict[str, Any]:
        """Queue a message from ``chat_id``; ``text=None`` is a message without text (a photo)."""
        message: dict[str, Any] = {
            "message_id": self._next_message_id,
            "date": 0,
            "chat": {"id": chat_id, "type": chat_type},
            "from": {"id": chat_id, "is_bot": False, "first_name": "Test"},
        }
        if text is None:
            message["photo"] = [{"file_id": "x", "width": 1, "height": 1}]
        else:
            message["text"] = text
        self._next_message_id += 1
        return self.push({"message": message})

    def push_callback(
        self,
        chat_id: int,
        data: str = "approve",
        *,
        message_id: int = 1,
        from_id: int | None = None,
    ) -> dict[str, Any]:
        """Queue an inline-button press in ``chat_id`` on ``message_id``; ``from_id`` is the
        user who pressed (the chat itself by default, as in a private chat)."""
        presser = chat_id if from_id is None else from_id
        return self.push(
            {
                "callback_query": {
                    "id": f"cb{self._next_update_id}",
                    "from": {"id": presser, "is_bot": False, "first_name": "Test"},
                    "message": {"message_id": message_id, "date": 0, "chat": {"id": chat_id}},
                    "data": data,
                }
            }
        )

    def buttons(self, chat_id: int) -> list[dict[str, str]]:
        """The inline buttons of the latest message sent to ``chat_id`` that had any."""
        for sent in reversed(self.sent):
            keyboard = (sent.get("reply_markup") or {}).get("inline_keyboard")
            if sent["chat_id"] == chat_id and keyboard:
                return [button for row in keyboard for button in row]
        return []

    def press(self, chat_id: int, index: int, *, from_id: int | None = None) -> dict[str, Any]:
        """Press button ``index`` (0 = the first) of the latest message with buttons in
        ``chat_id``, as the user ``from_id`` (the chat itself by default)."""
        for sent in reversed(self.sent):
            keyboard = (sent.get("reply_markup") or {}).get("inline_keyboard")
            if sent["chat_id"] == chat_id and keyboard:
                button = [b for row in keyboard for b in row][index]
                return self.push_callback(
                    chat_id,
                    button["callback_data"],
                    message_id=sent["message_id"],
                    from_id=from_id,
                )
        raise AssertionError(f"no message with buttons was sent to chat {chat_id}")

    def fail(self, method: str, *errors: BaseException) -> None:
        """The next ``len(errors)`` calls of ``method`` raise these, in order."""
        self._failures.setdefault(method, []).extend(errors)

    # -- reading ---------------------------------------------------------------------------

    def texts(self, chat_id: int | None = None) -> list[str]:
        """The text of every message sent (to ``chat_id``), in order."""
        return [p["text"] for p in self.sent if chat_id is None or p["chat_id"] == chat_id]

    def methods(self) -> list[str]:
        """Every method called, in order (failed calls included)."""
        return [method for method, _ in self.calls]

    # -- the API ---------------------------------------------------------------------------

    async def call(self, method: str, **params: Any) -> Any:
        self.calls.append((method, copy.deepcopy(params)))
        queued = self._failures.get(method)
        if queued:
            raise queued.pop(0)
        handler = getattr(self, f"_api_{method}", None)
        if handler is None:
            raise TelegramError(method, 404, "Not Found: method not found", None)
        return await handler(**params)

    async def _api_getMe(self) -> dict[str, Any]:
        return {"id": 1, "is_bot": True, "first_name": "tau", "username": self.username}

    async def _api_deleteWebhook(self, **params: Any) -> bool:
        self.webhook_url = ""
        return True

    async def _api_getWebhookInfo(self) -> dict[str, Any]:
        return {"url": self.webhook_url, "pending_update_count": len(self.updates)}

    async def _api_getUpdates(
        self,
        offset: int | None = None,
        timeout: float = 0,
        allowed_updates: list[str] | None = None,
        **params: Any,
    ) -> list[dict[str, Any]]:
        if self.webhook_url:
            raise TelegramError(
                "getUpdates",
                409,
                "Conflict: can't use getUpdates method while webhook is active; "
                "use deleteWebhook to delete the webhook first",
                None,
            )
        if offset is not None:
            self.updates = [u for u in self.updates if u["update_id"] >= offset]

        def pending() -> list[dict[str, Any]]:
            if not allowed_updates:
                return list(self.updates)
            return [u for u in self.updates if any(kind in u for kind in allowed_updates)]

        if not pending() and timeout:
            self._arrived = asyncio.Event()
            with suppress(TimeoutError):
                await asyncio.wait_for(self._arrived.wait(), timeout)
            self._arrived = None
        return copy.deepcopy(pending())

    async def _api_sendMessage(
        self, chat_id: int, text: str, parse_mode: str | None = None, **params: Any
    ) -> dict[str, Any]:
        if parse_mode == "HTML" and self.reject_html:
            raise TelegramError(
                "sendMessage", 400, "Bad Request: can't parse entities: unsupported tag", None
            )
        if len(text.encode("utf-16-le")) // 2 > MAX_MESSAGE_LENGTH:
            raise TelegramError("sendMessage", 400, "Bad Request: message is too long", None)
        if not text.strip():
            raise TelegramError("sendMessage", 400, "Bad Request: message text is empty", None)
        message_id = self._next_message_id
        self._next_message_id += 1
        record = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "message_id": message_id,
            **params,
        }
        self.sent.append(record)
        return {"message_id": message_id, "chat": {"id": chat_id}, "text": text}

    async def _api_sendChatAction(self, chat_id: int, action: str, **params: Any) -> bool:
        return True

    async def _api_setMyCommands(
        self, commands: list[dict[str, str]], scope: dict[str, Any] | None = None, **params: Any
    ) -> bool:
        key = json.dumps(scope or {"type": "default"}, sort_keys=True)
        self.commands[key] = copy.deepcopy(commands)
        return True

    def menu(self, chat_id: int) -> list[dict[str, str]] | None:
        """The command menu set for ``chat_id`` with ``setMyCommands``; ``None`` if none."""
        return self.commands.get(json.dumps({"chat_id": chat_id, "type": "chat"}, sort_keys=True))

    async def _api_answerCallbackQuery(self, callback_query_id: str, **params: Any) -> bool:
        self.answers.append({"callback_query_id": callback_query_id, **params})
        return True

    async def _api_editMessageText(
        self, chat_id: int, message_id: int, text: str, **params: Any
    ) -> dict[str, Any]:
        self.edits.append({"chat_id": chat_id, "message_id": message_id, "text": text, **params})
        return {"message_id": message_id, "chat": {"id": chat_id}, "text": text}


# Owner guard stand-in (issue 110). Appended here so the sections above stay untouched.

from datetime import UTC, datetime  # noqa: E402

from tau_core.guard import (  # noqa: E402
    Admission,
    GuardProgress,
    GuardStatus,
    GuardTurn,
    GuardVerdict,
)

__all__ += ["FakeGuard"]


class FakeGuard:
    """A scripted owner guard. It never opens a camera and it never approves anything.

    - ``admit`` follows ``state`` (only ``unlocked`` admits), or pops the next scripted
      ``admissions`` entry first (an :class:`Admission`, a bool, or a refusal reason string).
    - ``unlock`` replays ``progress`` through ``on_progress``, then pops the next verdict
      (default ``GuardVerdict(False, "no_match")``); an ``ok`` verdict unlocks.
    - ``step_up`` pops the next scripted value and returns it as is (an exception instance is
      raised instead); exhausted, it returns ``False``. Whatever it returns, the tier gate
      approves only after the approver said ``APPROVED`` and only for a literal ``True``.
    - ``set_state`` flips the state and bumps ``seq`` for ``watch``.

    Every call is recorded in ``calls`` as ``(method, detail)``.
    """

    name = "fake"

    def __init__(
        self,
        state: str = "locked",
        verdicts: Iterable[GuardVerdict] = (),
        step_ups: Iterable[Any] = (),
        progress: Iterable[GuardProgress] = (),
        admissions: Iterable[Admission | bool | str] | None = None,
    ) -> None:
        self.state = state
        self.seq = 0
        self.lock_trigger: str | None = None
        self.verdicts: list[GuardVerdict] = list(verdicts)
        self.step_ups: list[Any] = list(step_ups)
        self.progress: list[GuardProgress] = list(progress)
        self.admissions: list[Admission | bool | str] | None = (
            list(admissions) if admissions is not None else None
        )
        self.calls: list[tuple[str, Any]] = []

    def set_state(self, state: str, *, trigger: str | None = None) -> None:
        self.state = state
        self.lock_trigger = trigger if state == "locked" else None
        self.seq += 1

    def _status(self) -> GuardStatus:
        return GuardStatus(
            state=self.state,  # type: ignore[arg-type]
            enrolled=True,
            seq=self.seq,
            lock_trigger=self.lock_trigger,
            since=datetime.now(UTC) if self.state == "unlocked" else None,
        )

    async def status(self) -> GuardStatus:
        self.calls.append(("status", None))
        return self._status()

    async def watch(self, since: int, *, wait: float = 25.0) -> GuardStatus:
        self.calls.append(("watch", since))
        deadline = asyncio.get_running_loop().time() + max(0.0, wait)
        while self.seq <= since and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
        return self._status()

    async def admit(self, turn: GuardTurn) -> Admission:
        self.calls.append(("admit", turn))
        if self.admissions:
            scripted = self.admissions.pop(0)
            if isinstance(scripted, Admission):
                return scripted
            if scripted is True:
                return Admission(True)
            return Admission(False, scripted if isinstance(scripted, str) else "locked")
        if self.state == "unlocked":
            return Admission(True)
        return Admission(False, "unavailable" if self.state in ("off", "unavailable") else "locked")

    async def unlock(
        self,
        *,
        channel: str,
        client_id: str,
        kind: str = "unlock",
        on_progress: Callable[[GuardProgress], None] | None = None,
    ) -> GuardVerdict:
        self.calls.append(("unlock", kind))
        for step in self.progress:
            if on_progress is not None:
                on_progress(step)
        verdict = self.verdicts.pop(0) if self.verdicts else GuardVerdict(False, "no_match")
        if verdict.ok:
            self.set_state("unlocked")
        return verdict

    async def cancel(self, *, client_id: str) -> None:
        self.calls.append(("cancel", client_id))

    async def lock(self, *, channel: str, client_id: str, trigger: str = "command") -> None:
        self.calls.append(("lock", trigger))
        self.set_state("locked", trigger=trigger)

    async def step_up(
        self,
        request: ApprovalRequest,
        *,
        client_id: str,
        on_progress: Callable[[GuardProgress], None] | None = None,
    ) -> Any:
        self.calls.append(("step_up", request.request_id))
        for step in self.progress:
            if on_progress is not None:
                on_progress(step)
        answer = self.step_ups.pop(0) if self.step_ups else False
        if isinstance(answer, BaseException):
            raise answer
        return answer
