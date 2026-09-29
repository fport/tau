"""Telegram channel: the hub polls the Bot API itself (ADR 0006 §2).

A ``tau.hub_services`` component (``telegram = "tau_core.channels.telegram:make_service"``)
that runs a ``getUpdates`` long-poll loop inside ``tau hub run``: outbound HTTPS only, no
webhook, no relay, no inbound port. Each text message from an allowlisted chat becomes one turn
of that chat's session (``build_agent(channel="telegram")``) and the reply goes back with
``sendMessage``. Anything from another chat is dropped and logged, never answered, so the bot
does not confirm its existence to strangers.

Configuration comes from ``.env`` (``TELEGRAM_BOT_TOKEN``, ``TELEGRAM_ALLOWED_CHAT_IDS``,
comma-separated) and ``[component.telegram]`` in ``tau.toml`` (``poll_timeout_seconds``,
``backoff_max_seconds``). Without a token, or without an allowed chat, the service starts idle,
logs one line and reports ``telegram: {configured: false}`` in ``/status``; it never fails
the hub.

State lives under ``TAU_DATA_DIR/telegram/``: ``offset`` (the next ``update_id`` to ask for,
written after each update is handled, so a restart neither re-processes nor skips one; an
update whose turn a stop interrupted runs again after the restart) and ``chats.json`` (chat id
→ current session id, so a chat keeps its session across restarts).

Tier 2 is refused on this channel until inline-button approvals land (issue 017):
:class:`RefusingApprover` rejects every request, and the refusal the model reads points the
user at a trusted channel. Nothing is ever auto-approved.

The token never reaches a log line, an exception message or ``/status``.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import tempfile
import threading
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from tau_core.agent import Notice, TauAgent, TextDelta, ToolFinished, build_agent
from tau_core.approval import ApprovalRequest, Decision
from tau_core.commands import SLASH_COMMANDS, command_hint, resolve_command, usage
from tau_core.compaction import (
    CompactionError,
    compaction_title,
    record_compaction,
    seed_messages,
    summarize,
)
from tau_core.config import Config, ConfigError
from tau_core.i18n import LANGUAGES, t
from tau_core.models import MissingCredentials
from tau_core.sessions import SessionStore, open_session_store
from tau_core.status import describe_model, role_lines, status_report, stored_role
from tau_core.tiers import tier_of

if TYPE_CHECKING:
    from tau_core.builder import Check
    from tau_core.hub.daemon import Hub

__all__ = [
    "ALLOWED_CHATS_ENV",
    "MAX_MESSAGE_LENGTH",
    "TOKEN_ENV",
    "BotApi",
    "HttpBotApi",
    "RefusingApprover",
    "TelegramError",
    "TelegramService",
    "doctor_check",
    "make_service",
    "markdown_to_html",
    "parse_chat_ids",
    "split_message",
]

logger = logging.getLogger(__name__)

TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
ALLOWED_CHATS_ENV = "TELEGRAM_ALLOWED_CHAT_IDS"
SERVICE_NAME = "telegram"
CHANNEL = "telegram"

MAX_MESSAGE_LENGTH = 4096
"""Telegram's limit for one message, in UTF-16 code units of the text after parsing."""
ALLOWED_UPDATES = ("message", "callback_query")
"""``callback_query`` is for the approval buttons of issue 017."""
DEFAULT_POLL_TIMEOUT = 50
DEFAULT_BACKOFF_MAX = 60.0
BACKOFF_START = 1.0
TYPING_INTERVAL = 4.5
"""``sendChatAction`` shows "typing…" for about five seconds; refresh it a little earlier."""
DEFAULT_ROLE = "brain"
LIST_LIMIT = 10
SCAN_LIMIT = 100

SEND_ATTEMPTS = 5
"""A reply is retried this often on network errors and flood control before it is dropped."""


# -- small pure helpers ----------------------------------------------------------------------


def parse_chat_ids(raw: str | None) -> tuple[frozenset[int], list[str]]:
    """``(allowed ids, entries that are not integers)`` from ``TELEGRAM_ALLOWED_CHAT_IDS``.

    Commas and whitespace separate entries; group chats have negative ids.
    """
    ids: set[int] = set()
    invalid: list[str] = []
    for entry in re.split(r"[,\s]+", raw or ""):
        if not entry:
            continue
        try:
            ids.add(int(entry))
        except ValueError:
            invalid.append(entry)
    return frozenset(ids), invalid


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _fit(text: str, limit: int) -> int:
    """The largest ``i`` with ``_utf16_len(text[:i]) <= limit``."""
    used = 0
    for i, char in enumerate(text):
        used += 2 if ord(char) > 0xFFFF else 1
        if used > limit:
            return i
    return len(text)


def split_message(text: str, limit: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split ``text`` into messages of at most ``limit`` UTF-16 units, preferring a blank
    line, then a line break, then a space in the second half of each piece; a piece without
    one is cut hard. Empty pieces are dropped."""
    chunks: list[str] = []
    rest = text
    while _utf16_len(rest) > limit:
        cut = _fit(rest, limit)
        window = rest[:cut]
        for separator in ("\n\n", "\n", " "):
            at = window.rfind(separator)
            if at > cut // 2:
                chunks.append(rest[:at])
                rest = rest[at + len(separator) :]
                break
        else:
            chunks.append(window)
            rest = rest[cut:]
    chunks.append(rest)
    return [chunk for chunk in (c.strip("\n") for c in chunks) if chunk.strip()]


_FENCE = re.compile(r"```[^\n`]*\n(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)\"<>]+)\)")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_HEADING = re.compile(r"(?m)^#{1,6}[ \t]+(.+?)[ \t#]*$")


def _inline_html(text: str) -> str:
    out: list[str] = []
    for i, piece in enumerate(_INLINE_CODE.split(text)):
        if i % 2:
            out.append(f"<code>{html.escape(piece, quote=False)}</code>")
            continue
        s = html.escape(piece, quote=False)
        s = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', s)
        s = _HEADING.sub(r"<b>\1</b>", s)
        s = _BOLD.sub(r"<b>\1</b>", s)
        s = _STRIKE.sub(r"<s>\1</s>", s)
        out.append(s)
    return "".join(out)


def markdown_to_html(text: str) -> str:
    """The model's Markdown as Telegram HTML: fenced and inline code, ``**bold**``,
    ``~~strike~~``, ``[links](https://…)`` and headings (as bold). Everything else is escaped
    and shown as typed. Telegram rejects what does not nest; the caller then sends plain text.
    """
    out: list[str] = []
    for i, piece in enumerate(_FENCE.split(text)):
        if i % 2:
            out.append(f"<pre>{html.escape(piece.rstrip(chr(10)), quote=False)}</pre>")
        else:
            out.append(_inline_html(piece))
    return "".join(out)


# -- the Bot API -----------------------------------------------------------------------------


class TelegramError(Exception):
    """The Bot API answered ``ok: false``. ``code`` is its ``error_code``; ``retry_after``
    is set on 429 (flood control)."""

    def __init__(self, method: str, code: int, description: str, retry_after: float | None):
        self.method = method
        self.code = code
        self.description = description
        self.retry_after = retry_after
        super().__init__(f"{method}: {code} {description}")


class BotApi(Protocol):
    """One Bot API method call: ``await api.call("sendMessage", chat_id=…, text=…)`` returns
    the ``result`` or raises :class:`TelegramError` (the API said no) or another exception
    (the network failed). :class:`tau_core.testing.FakeBotApi` is the offline stand-in."""

    async def call(self, method: str, **params: Any) -> Any: ...


async def _in_daemon_thread[T](func: Callable[[], T]) -> T:
    """Run a blocking call in a daemon thread. Unlike ``asyncio.to_thread``, a long poll in
    flight never delays the hub's exit: awaiting it can be cancelled and nothing joins the
    thread, which ends on its own when the request returns."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[T] = loop.create_future()

    def settle(result: Any, error: BaseException | None) -> None:
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)

    def work() -> None:
        try:
            result, error = func(), None
        except BaseException as exc:
            result, error = None, exc
        with suppress(RuntimeError):  # the loop closed while the request was in flight
            loop.call_soon_threadsafe(settle, result, error)

    threading.Thread(target=work, name="tau-telegram-http", daemon=True).start()
    return await future


class HttpBotApi:
    """The real Bot API over ``urllib`` (no proxy lookups, no extra dependency).

    Errors never carry the URL, which holds the token: HTTP errors become
    :class:`TelegramError` from Telegram's JSON body, anything else is re-raised as
    ``ConnectionError`` with the token masked.
    """

    BASE = "https://api.telegram.org"

    def __init__(self, token: str, *, timeout: float = 30.0):
        self._token = token
        self.timeout = timeout

    def _mask(self, text: str) -> str:
        return text.replace(self._token, "<token>") if self._token else text

    def _request(self, method: str, params: dict[str, Any], timeout: float) -> Any:
        request = urllib.request.Request(
            f"{self.BASE}/bot{self._token}/{method}",
            data=json.dumps(params, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except (OSError, ValueError):
                raise ConnectionError(f"{method}: HTTP {exc.code}") from None
        except (OSError, ValueError) as exc:
            raise ConnectionError(self._mask(f"{method}: {type(exc).__name__}: {exc}")) from None
        if not isinstance(body, dict) or not body.get("ok"):
            body = body if isinstance(body, dict) else {}
            retry_after = (body.get("parameters") or {}).get("retry_after")
            raise TelegramError(
                method,
                int(body.get("error_code") or 0),
                self._mask(str(body.get("description") or "no description")),
                float(retry_after) if retry_after is not None else None,
            )
        return body.get("result")

    async def call(self, method: str, **params: Any) -> Any:
        timeout = self.timeout
        if method == "getUpdates":
            timeout = float(params.get("timeout") or 0) + self.timeout
        return await _in_daemon_thread(lambda: self._request(method, params, timeout))


# -- approvals -------------------------------------------------------------------------------


class RefusingApprover:
    """Rejects every tier-2 request made from Telegram until approvals with inline buttons
    land (issue 017). ``refusal_note`` is appended to the refusal the model reads (fixed
    English), so the reply tells the user where the action can be approved."""

    name = "telegram"
    timeout_seconds: float | None = None
    refusal_note = (
        "Tier-2 actions cannot be approved from Telegram yet; the user can ask for it again "
        "from a trusted channel on the hub (the TUI or tau chat)."
    )

    async def decide(self, request: ApprovalRequest) -> Decision:
        return Decision.REJECTED


# -- state on disk ---------------------------------------------------------------------------


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp)
        raise


class TelegramFiles:
    """``TAU_DATA_DIR/telegram/offset`` and ``chats.json``."""

    def __init__(self, root: Path):
        self.root = root
        self.offset_path = root / "offset"
        self.chats_path = root / "chats.json"

    def read_offset(self) -> int | None:
        try:
            return int(self.offset_path.read_text(encoding="utf-8").strip())
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            logger.warning("telegram: ignoring unreadable %s: %s", self.offset_path, exc)
            return None

    def write_offset(self, offset: int) -> None:
        _write_atomic(self.offset_path, f"{offset}\n")

    def read_chats(self) -> dict[int, str]:
        try:
            raw = json.loads(self.chats_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            logger.warning("telegram: ignoring unreadable %s: %s", self.chats_path, exc)
            return {}
        chats: dict[int, str] = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                with suppress(ValueError):
                    if isinstance(value, str) and value:
                        chats[int(key)] = value
        return chats

    def write_chats(self, chats: Mapping[int, str]) -> None:
        payload = {str(chat): session for chat, session in sorted(chats.items())}
        _write_atomic(self.chats_path, json.dumps(payload, indent=2) + "\n")


# -- one chat --------------------------------------------------------------------------------


@dataclass
class ChatState:
    """What the service keeps per allowed chat while the hub runs."""

    chat_id: int
    language: str
    session_id: str | None = None
    agent: TauAgent | None = None
    role: str = DEFAULT_ROLE
    last_listing: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    """The reply being assembled by a command handler; sent as one message (or several)."""

    def say(self, key: str, **kwargs: object) -> None:
        self.lines.append(t(key, self.language, **kwargs))

    def print(self, line: str) -> None:
        self.lines.append(line)


ChatHandler = Callable[["TelegramService", ChatState, str], Awaitable[None]]


# -- the service -----------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _positive(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


class TelegramService:
    """The ``telegram`` hub service. Build it with :func:`make_service`; tests pass ``api``
    (a :class:`tau_core.testing.FakeBotApi`), ``env`` and a fast ``sleep``."""

    name = SERVICE_NAME

    def __init__(
        self,
        config: Config,
        *,
        env: Mapping[str, str] | None = None,
        api: BotApi | None = None,
        store: SessionStore | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.config = config
        if env is None:
            from tau_core.builder import env_with_dotenv

            env = env_with_dotenv(config.home, os.environ)
        self.token = (env.get(TOKEN_ENV) or "").strip()
        self.allowed, invalid = parse_chat_ids(env.get(ALLOWED_CHATS_ENV))
        if invalid:
            logger.warning(
                "telegram: %s has entries that are not chat ids, ignored: %s",
                ALLOWED_CHATS_ENV,
                ", ".join(invalid),
            )
        settings = config.component(SERVICE_NAME)
        self.poll_timeout = int(
            _positive(settings.get("poll_timeout_seconds"), DEFAULT_POLL_TIMEOUT)
        )
        self.backoff_max = _positive(settings.get("backoff_max_seconds"), DEFAULT_BACKOFF_MAX)
        self.api: BotApi | None = api
        self.store = store
        self.files = TelegramFiles(config.data_dir / "telegram")
        self.approver = RefusingApprover()
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None
        self._chats: dict[int, ChatState] = {}
        self._sessions: dict[int, str] = {}
        self.offset: int | None = None
        self.bot: str | None = None
        self.state = "idle"
        self.idle_reason: str | None = None
        self.last_poll_at: str | None = None
        self.last_error: str | None = None
        self.retry_in_s: float | None = None
        self.handled = 0
        self.dropped = 0

    # -- HubService ---------------------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return bool(self.token) and bool(self.allowed)

    async def start(self, hub: Hub) -> None:
        hub.add_status_source(lambda: {SERVICE_NAME: self.status()})
        if not self.token:
            self.idle_reason = f"{TOKEN_ENV} is not set"
        elif not self.allowed:
            self.idle_reason = f"{ALLOWED_CHATS_ENV} is empty"
        if self.idle_reason is not None:
            logger.info("telegram: %s; the channel stays idle", self.idle_reason)
            return
        if self.api is None:
            self.api = HttpBotApi(self.token)
        if self.store is None:
            self.store = open_session_store(self.config)
        self.offset = self.files.read_offset()
        self._sessions = {
            chat: session
            for chat, session in self.files.read_chats().items()
            if chat in self.allowed
        }
        self.state = "starting"
        self._task = asyncio.create_task(self._run(), name="tau-telegram-poller")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        for chat in self._chats.values():
            if chat.agent is not None:
                chat.agent.close()
        if self.configured:
            self.state = "stopped"

    def status(self) -> dict[str, Any]:
        """The ``telegram`` key of the hub's ``/status``: poller state, never the token or a
        chat id."""
        if not self.configured:
            return {"configured": False, "reason": self.idle_reason}
        return {
            "configured": True,
            "state": self.state,
            "bot": self.bot,
            "allowed_chats": len(self.allowed),
            "last_poll_at": self.last_poll_at,
            "last_error": self.last_error,
            "retry_in_s": self.retry_in_s,
            "handled": self.handled,
            "dropped": self.dropped,
        }

    # -- the poll loop ------------------------------------------------------------------------

    async def _backoff(self, failures: int, error: str, *, at_least: float = 0.0) -> None:
        delay = max(at_least, min(self.backoff_max, BACKOFF_START * 2 ** (failures - 1)))
        self.state, self.last_error, self.retry_in_s = "retrying", error, delay
        if failures == 1:
            logger.warning("telegram: %s; retrying with backoff", error)
        else:
            logger.info("telegram: %s; retry %d in %.0f s", error, failures, delay)
        await self._sleep(delay)

    async def _prepare(self) -> bool:
        """``getMe`` and ``deleteWebhook`` (Telegram refuses ``getUpdates`` while a webhook is
        set). ``False`` when the token is rejected: polling stops, the hub runs on."""
        assert self.api is not None
        failures = 0
        while True:
            try:
                me = await self.api.call("getMe")
                await self.api.call("deleteWebhook", drop_pending_updates=False)
            except TelegramError as exc:
                if exc.code in (401, 403, 404):
                    return self._fail(exc)
                failures += 1
                await self._backoff(failures, str(exc), at_least=exc.retry_after or 0.0)
                continue
            except Exception as exc:
                failures += 1
                await self._backoff(failures, f"{type(exc).__name__}: {exc}")
                continue
            username = (me or {}).get("username") if isinstance(me, dict) else None
            self.bot = f"@{username}" if username else None
            logger.info("telegram: polling as %s", self.bot or "the bot")
            return True

    def _fail(self, exc: TelegramError) -> bool:
        self.state, self.last_error, self.retry_in_s = "failed", str(exc), None
        logger.error(
            "telegram: the Bot API rejected %s (%s); polling stopped. Check %s in .env.",
            exc.method,
            exc,
            TOKEN_ENV,
        )
        return False

    async def _run(self) -> None:
        assert self.api is not None
        if not await self._prepare():
            return
        failures = 0
        while True:
            params: dict[str, Any] = {
                "timeout": self.poll_timeout,
                "allowed_updates": list(ALLOWED_UPDATES),
            }
            if self.offset is not None:
                params["offset"] = self.offset
            if failures == 0:
                self.state, self.retry_in_s = "polling", None
            try:
                updates = await self.api.call("getUpdates", **params)
            except TelegramError as exc:
                if exc.code in (401, 403, 404):
                    self._fail(exc)
                    return
                if exc.code == 409 and "webhook" in exc.description.lower():
                    with suppress(Exception):
                        await self.api.call("deleteWebhook", drop_pending_updates=False)
                failures += 1
                await self._backoff(failures, str(exc), at_least=exc.retry_after or 0.0)
                continue
            except Exception as exc:
                failures += 1
                await self._backoff(failures, f"{type(exc).__name__}: {exc}")
                continue
            if failures:
                logger.info("telegram: reconnected after %d failed polls", failures)
            failures = 0
            self.state, self.last_error, self.retry_in_s = "polling", None, None
            self.last_poll_at = _now_iso()
            for update in updates or []:
                await self._take(update)

    async def _take(self, update: Any) -> None:
        """Handle one update, then move the offset past it (even when handling failed, so one
        bad update cannot wedge the poller)."""
        if not isinstance(update, dict) or not isinstance(update.get("update_id"), int):
            logger.warning("telegram: ignoring a malformed update")
            return
        try:
            await self.handle_update(update)
        except asyncio.CancelledError:
            raise  # a stop: the offset stays, the update runs again after the restart
        except Exception:
            logger.exception("telegram: update %s failed", update["update_id"])
        self.offset = update["update_id"] + 1
        try:
            self.files.write_offset(self.offset)
        except OSError as exc:
            logger.warning("telegram: could not write %s: %s", self.files.offset_path, exc)

    # -- one update ---------------------------------------------------------------------------

    async def handle_update(self, update: dict[str, Any]) -> None:
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            chat_id = ((callback.get("message") or {}).get("chat") or {}).get("id")
            if chat_id not in self.allowed:
                self._drop(chat_id, "callback query")
                return
            # Approval buttons arrive with issue 017; until then, only stop the spinner.
            with suppress(Exception):
                await self._api().call("answerCallbackQuery", callback_query_id=callback["id"])
            return
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id not in self.allowed:
            self._drop(chat_id, "message")
            return
        self.handled += 1
        chat = self._chat(chat_id)
        text = message.get("text")
        if not isinstance(text, str) or not text.strip():
            await self.send(chat_id, t("telegram.text_only", chat.language))
            return
        text = text.strip()
        if text.startswith("/"):
            await self.run_command(chat, text)
        else:
            await self.run_turn(chat, text)

    def _drop(self, chat_id: Any, what: str) -> None:
        self.dropped += 1
        logger.info("telegram: dropped a %s from chat %s (not allowlisted)", what, chat_id)

    def _api(self) -> BotApi:
        assert self.api is not None
        return self.api

    def _chat(self, chat_id: int) -> ChatState:
        chat = self._chats.get(chat_id)
        if chat is None:
            chat = ChatState(
                chat_id=chat_id,
                language=self.config.ui.language,
                session_id=self._sessions.get(chat_id),
            )
            self._chats[chat_id] = chat
        return chat

    # -- sending --------------------------------------------------------------------------------

    async def send(self, chat_id: int, text: str, *, markdown: bool = False) -> None:
        """Send ``text``, split at :data:`MAX_MESSAGE_LENGTH`. With ``markdown`` each piece
        goes as HTML first and as plain text when Telegram rejects the markup."""
        for piece in split_message(text):
            if markdown:
                try:
                    await self._send_one(chat_id, markdown_to_html(piece), parse_mode="HTML")
                    continue
                except TelegramError as exc:
                    if exc.code != 400:
                        raise
                    logger.info("telegram: markup rejected (%s); sending plain text", exc)
            await self._send_one(chat_id, piece)

    async def _send_one(self, chat_id: int, text: str, **params: Any) -> None:
        """One ``sendMessage``, retried with backoff on network errors and flood control
        (429); any other refusal of the Bot API is raised at once."""
        failures = 0
        while True:
            try:
                await self._api().call(
                    "sendMessage",
                    chat_id=chat_id,
                    text=text,
                    link_preview_options={"is_disabled": True},
                    **params,
                )
                return
            except TelegramError as exc:
                failures += 1
                if exc.code != 429 or failures >= SEND_ATTEMPTS:
                    raise
                delay = exc.retry_after or BACKOFF_START
            except Exception:
                failures += 1
                if failures >= SEND_ATTEMPTS:
                    raise
                delay = min(self.backoff_max, BACKOFF_START * 2 ** (failures - 1))
            await self._sleep(delay)

    async def _typing(self, chat_id: int) -> None:
        with suppress(Exception):
            await self._api().call("sendChatAction", chat_id=chat_id, action="typing")

    async def _keep_typing(self, chat_id: int) -> None:
        while True:
            await asyncio.sleep(TYPING_INTERVAL)
            await self._typing(chat_id)

    # -- agents and sessions ----------------------------------------------------------------

    def _build(
        self,
        chat: ChatState,
        session_id: str | None,
        *,
        role: str | None = None,
        seed: list | None = None,
    ) -> bool:
        """Replace the chat's agent with one on ``session_id`` (a fresh session when
        ``None``); on failure the reason is added to the reply and nothing changes."""
        from strands.types.exceptions import SessionException

        if role is None:
            role = stored_role(self.store, session_id, self.config) or chat.role
        try:
            agent = build_agent(
                config=self.config,
                role=role,
                approver=self.approver,
                session_store=self.store,
                session_id=session_id,
                channel=CHANNEL,
                seed_messages=seed,
            )
        except (MissingCredentials, ConfigError) as exc:
            chat.print(str(exc))
            return False
        except (SessionException, OSError, ValueError) as exc:
            chat.say("session.open_failed", error=exc)
            return False
        if chat.agent is not None:
            agent.carry_over(chat.agent)
            chat.agent.close()
        chat.agent, chat.role, chat.session_id = agent, role, agent.session_id
        self._remember(chat)
        return True

    def _remember(self, chat: ChatState) -> None:
        if chat.session_id is None or self._sessions.get(chat.chat_id) == chat.session_id:
            return
        self._sessions[chat.chat_id] = chat.session_id
        try:
            self.files.write_chats(self._sessions)
        except OSError as exc:
            logger.warning("telegram: could not write %s: %s", self.files.chats_path, exc)

    def _agent(self, chat: ChatState) -> TauAgent | None:
        """The chat's agent, built on first use on the session ``chats.json`` remembers."""
        if chat.agent is None and not self._build(chat, chat.session_id):
            return None
        return chat.agent

    # -- turns ----------------------------------------------------------------------------------

    async def run_turn(self, chat: ChatState, prompt: str) -> None:
        agent = self._agent(chat)
        if agent is None:
            await self._flush(chat)
            return
        await self._typing(chat.chat_id)
        typing = asyncio.create_task(self._keep_typing(chat.chat_id), name="tau-telegram-typing")
        parts: list[str] = []
        extra: list[str] = []
        try:
            async for event in agent.stream(prompt):
                if isinstance(event, TextDelta):
                    parts.append(event.text)
                elif isinstance(event, Notice):
                    extra.append(f"ℹ {event.text}")
                elif isinstance(event, ToolFinished) and event.status == "rejected":
                    extra.append(f"✗ {t('tool.rejected', chat.language, tool=event.tool)}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("telegram: turn failed in session %s", agent.session_id)
            extra.append(t("telegram.turn_failed", chat.language, detail=type(exc).__name__))
        finally:
            typing.cancel()
            with suppress(asyncio.CancelledError):
                await typing
        reply = "".join(parts).strip()
        if reply:
            await self.send(chat.chat_id, reply, markdown=True)
        if extra:
            await self.send(chat.chat_id, "\n".join(extra))
        if not reply and not extra:
            await self.send(chat.chat_id, t("telegram.empty_reply", chat.language))

    # -- commands -------------------------------------------------------------------------------

    async def run_command(self, chat: ChatState, text: str) -> None:
        head, _, rest = text.partition(" ")
        head = head.split("@", 1)[0]  # "/help@my_bot" in a group
        if head.casefold() == "/start":
            head = "/help"
        resolved = resolve_command(f"{head} {rest}")
        chat.lines = []
        if resolved is None:
            chat.say("chat.unknown_command", name=head[1:], hint=command_hint(chat.language))
        else:
            name, arg = resolved
            handler = COMMAND_HANDLERS.get(name)
            if handler is None:
                chat.say("telegram.unavailable", command=name)
            else:
                await handler(self, chat, arg)
        await self._flush(chat)

    async def _flush(self, chat: ChatState) -> None:
        lines, chat.lines = chat.lines, []
        if lines:
            await self.send(chat.chat_id, "\n".join(lines))


# -- command handlers (the terminal's wording, through tau_core.i18n) ---------------------------


def _recent(service: TelegramService, chat: ChatState) -> list:
    assert service.store is not None
    return [
        s
        for s in service.store.list_sessions(limit=SCAN_LIMIT)
        if s.session_id != chat.session_id and s.message_count > 0
    ][:LIST_LIMIT]


def _title(service: TelegramService, session_id: str) -> str:
    from strands.types.exceptions import SessionException

    assert service.store is not None
    try:
        return str(service.store.read_meta(session_id).get("title") or "")
    except (SessionException, OSError, ValueError):
        return ""


async def cmd_help(service: TelegramService, chat: ChatState, arg: str) -> None:
    chat.say("chat.help_header")
    for command in SLASH_COMMANDS:
        if command.name in COMMAND_HANDLERS:
            chat.print(f"{usage(command)} — {t(command.help_key, chat.language)}")


async def cmd_tools(service: TelegramService, chat: ChatState, arg: str) -> None:
    agent = service._agent(chat)
    if agent is None:
        return
    tools = agent.catalog.tools()
    if not tools:
        chat.say("tools.none")
        return
    chat.say("tools.header", n=len(tools))
    for tool in tools:
        tier = int(tier_of(tool))
        description = (tool.tool_spec.get("description") or "").strip().splitlines()
        first = description[0] if description else ""
        label = t(f"tier.{tier}", chat.language)
        chat.print(f"{tool.tool_name}  tier {tier} · {label}" + (f" — {first}" if first else ""))


async def cmd_sessions(service: TelegramService, chat: ChatState, arg: str) -> None:
    from tau_core.persona import TIMEZONE

    def when(iso: str) -> str:
        try:
            return f"{datetime.fromisoformat(iso).astimezone(TIMEZONE):%d.%m.%Y %H:%M}"
        except ValueError:
            return iso or "?"

    recent = _recent(service, chat)
    chat.last_listing = [s.session_id for s in recent]
    if not recent:
        chat.say("session.none_earlier")
        return
    chat.say("session.recent_header")
    untitled = t("session.untitled", chat.language)
    for n, s in enumerate(recent, start=1):
        count = t("session.messages", chat.language, n=s.message_count)
        chat.print(
            f"{n}. {s.session_id}  {when(s.updated_at)}  {s.channel or '-'}  "
            f"{s.title or untitled} ({count})"
        )


async def cmd_resume(service: TelegramService, chat: ChatState, arg: str) -> None:
    assert service.store is not None
    current = chat.session_id
    if arg and not (arg.isascii() and arg.isdigit()):
        if arg == current:
            chat.say("session.already_current", session=current)
            return
        try:
            known = service.store.read_session(arg) is not None
        except ValueError as exc:
            chat.print(str(exc))
            return
        if not known:
            chat.say("session.not_found", session=arg)
            return
        target = arg
    elif arg:
        listing = chat.last_listing or [s.session_id for s in _recent(service, chat)]
        n = int(arg)
        if not 1 <= n <= len(listing):
            chat.say("session.no_such_number", n=n, count=len(listing))
            return
        target = listing[n - 1]
        if target == current:
            chat.say("session.already_current", session=current)
            return
    else:
        recent = _recent(service, chat)
        if not recent:
            chat.say("session.none_earlier")
            return
        target = recent[0].session_id
    if not service._build(chat, target):
        return
    assert chat.agent is not None
    title = _title(service, target) or t("session.untitled", chat.language)
    chat.say("session.resumed", title=title, session=target, n=len(chat.agent.messages))


async def cmd_new(service: TelegramService, chat: ChatState, arg: str) -> None:
    if service._build(chat, None, role=chat.role):
        chat.say("session.new", session=chat.session_id)


async def cmd_session(service: TelegramService, chat: ChatState, arg: str) -> None:
    agent = service._agent(chat)
    if agent is None:
        return
    title = _title(service, agent.session_id) or t("session.untitled", chat.language)
    chat.say("session.info.id", session=agent.session_id)
    chat.say("session.info.title", title=title)
    chat.say("session.info.count", n=len(agent.messages))
    chat.say("session.info.store", store=service.config.sessions.backend)


async def cmd_status(service: TelegramService, chat: ChatState, arg: str) -> None:
    agent = service._agent(chat)
    if agent is None:
        return
    for line in await status_report(agent, language=chat.language):
        chat.print(line)


async def cmd_model(service: TelegramService, chat: ChatState, arg: str) -> None:
    agent = service._agent(chat)
    if agent is None:
        return
    if not arg:
        for line in role_lines(agent, chat.language):
            chat.print(line)
        return
    if arg not in service.config.roles:
        chat.say("model.unknown", role=arg, roles=", ".join(service.config.roles))
        return
    if arg != chat.role and not service._build(chat, agent.session_id, role=arg):
        return
    assert service.store is not None and chat.agent is not None
    service.store.write_meta(chat.agent.session_id, role=arg)
    chat.say("model.current", role=arg, provider=describe_model(chat.agent).provider)


async def cmd_compact(service: TelegramService, chat: ChatState, arg: str) -> None:
    old = service._agent(chat)
    if old is None:
        return
    n = len(old.messages)
    try:
        summary = await summarize(old, focus=arg or None)
    except CompactionError as exc:
        chat.say("compact.failed", error=exc)
        return
    title = compaction_title(old)
    if not service._build(chat, None, role=chat.role, seed=seed_messages(summary, old.session_id)):
        return
    assert service.store is not None and chat.session_id is not None
    record_compaction(
        service.store, previous=old.session_id, new=chat.session_id, title=title, role=chat.role
    )
    chat.say("compact.done", n=n, session=chat.session_id, previous=old.session_id)
    chat.print(summary)


async def cmd_lang(service: TelegramService, chat: ChatState, arg: str) -> None:
    choices = "|".join(LANGUAGES)
    if not arg:
        chat.say("lang.usage", choices=choices, language=chat.language)
        return
    if arg not in LANGUAGES:
        chat.say("lang.unknown", language=arg, choices=choices)
        return
    chat.language = arg
    chat.say("lang.switched", language=arg)


COMMAND_HANDLERS: dict[str, ChatHandler] = {
    "help": cmd_help,
    "tools": cmd_tools,
    "sessions": cmd_sessions,
    "resume": cmd_resume,
    "new": cmd_new,
    "session": cmd_session,
    "status": cmd_status,
    "model": cmd_model,
    "compact": cmd_compact,
    "lang": cmd_lang,
}
"""The shared slash commands that make sense on Telegram. The rest (``/clear``, ``/quit``,
``/settings``, …) answer that they are not available here; credentials are never set from a
chat."""


# -- entry point and doctor ----------------------------------------------------------------------


def make_service(config: Config) -> TelegramService:
    """The ``tau.hub_services`` factory."""
    return TelegramService(config)


def doctor_check(config: Config, env: Mapping[str, str], hub_status: Any) -> Check:
    """``tau doctor``'s ``telegram`` line: configuration from ``env`` and, when the hub
    answers, the poller state from its ``/status`` (``hub_status``; ``None`` = no hub)."""
    from tau_core.builder import Check

    token = (env.get(TOKEN_ENV) or "").strip()
    if not token:
        return Check("telegram", "info", f"not configured ({TOKEN_ENV} is not set)")
    enabled = config.components.hub_services
    if enabled and SERVICE_NAME not in enabled:
        return Check("telegram", "info", "switched off in [components.hub] services")
    allowed, invalid = parse_chat_ids(env.get(ALLOWED_CHATS_ENV))
    if invalid:
        return Check(
            "telegram",
            "warn",
            f"{ALLOWED_CHATS_ENV} has entries that are not chat ids: " + ", ".join(invalid),
        )
    if not allowed:
        return Check("telegram", "warn", f"{ALLOWED_CHATS_ENV} is empty; the poller stays idle")
    chats = f"{len(allowed)} allowed chat{'s' if len(allowed) != 1 else ''}"
    poller = hub_status.get(SERVICE_NAME) if isinstance(hub_status, dict) else None
    if not isinstance(poller, dict):
        if hub_status is None:
            return Check("telegram", "ok", f"configured ({chats}); polls while the hub runs")
        return Check("telegram", "warn", "configured, but the running hub has no telegram poller")
    state = poller.get("state")
    bot = poller.get("bot") or "the bot"
    if state == "polling":
        return Check(
            "telegram", "ok", f"polling as {bot} ({chats}, last poll {poller.get('last_poll_at')})"
        )
    if state == "retrying":
        return Check(
            "telegram",
            "warn",
            f"poller retrying in {poller.get('retry_in_s')} s: {poller.get('last_error')}",
        )
    if state == "failed":
        return Check("telegram", "fail", f"poller stopped: {poller.get('last_error')}")
    return Check("telegram", "info", f"poller {state or 'unknown'} ({chats})")
