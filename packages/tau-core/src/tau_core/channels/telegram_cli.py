"""``tau telegram``: pair the owner's chat with the bot and show the channel's state.

``tau telegram pair`` (ADR 0014 §5, issue 172):

1. With the owner guard active it runs only while tau is unlocked: a paired chat talks to tau
   without the guard (ADR 0008), so pairing one is guarded like a turn.
2. It takes the bot token at a hidden prompt, or with ``--json`` as ``{"token": "..."}`` on one
   stdin line, never in argv. An empty token keeps the one ``<home>/.env`` has.
3. One ``getMe`` checks the token; it is written to ``<home>/.env`` as ``TELEGRAM_BOT_TOKEN``
   (that line replaced or appended, the others kept, the file at 0600).
4. A one-time code is stored hashed (:mod:`tau_core.channels.telegram_pairing`) and shown with
   ``Open t.me/<bot> and send: /start <code>`` and the deep link.
5. It waits until the code is accepted, runs out or is voided, and exactly one process polls
   the Bot API meanwhile:

   - **A hub runs:** it calls the hub's signed ``POST /telegram/reload``. The hub's Telegram
     service re-reads the token and the code and accepts ``/start <code>`` in its own poll
     loop; this command only watches the record (and the hub's ``/health``).
   - **No hub runs:** it polls ``getUpdates`` itself from the hub's saved offset and writes the
     offset back, so a hub started later neither answers an update twice nor skips one. It
     stops right after the pairing update, leaving later updates with Telegram for the hub.
     Messages from chats that stay allowed go to ``inflight.json``, which the hub runs at its
     next start. A 409 (another poller) makes it look for a hub that started meanwhile.

With ``--json`` every line on stdout is one JSON object: ``bot``, ``code``, ``waiting``,
``note``, ``paired`` or ``error`` events (``docs/reference/cli.md``). The token never reaches
the output, argv or a log line.

``tau telegram status`` shows whether a token is set (the bot's name from one ``getMe``),
whether an owner chat is paired, whether a code waits and what the hub's poller does.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import click

from tau_core.channels.telegram import (
    ALLOWED_CHATS_ENV,
    ALLOWED_UPDATES,
    RELOAD_PATH,
    RELOAD_TIMEOUT,
    TOKEN_ENV,
    BotApi,
    HttpBotApi,
    TelegramError,
    TelegramFiles,
    parse_chat_ids,
)
from tau_core.channels.telegram_pairing import (
    CODE_TTL_SECONDS,
    Pairing,
    PairingStore,
    deep_link,
    format_code,
    new_code,
    try_pair,
)
from tau_core.cli import help_option
from tau_core.config import Config, ConfigError
from tau_core.guard import GuardTurn, admit_turn, process_client_id, resolve_guard
from tau_core.hub.client import HubClient, HubError, HubUnavailable
from tau_core.i18n import DEFAULT_LANGUAGE, t

__all__ = ["HubLink", "PairDeps", "run_pair", "telegram", "token_looks_valid"]

logger = logging.getLogger(__name__)

TOKEN_SHAPE = re.compile(r"[0-9]{3,20}:[A-Za-z0-9_-]{20,100}")
"""What @BotFather hands out: the bot id, a colon and a secret."""
CLI_POLL_TIMEOUT = 25
"""Seconds one ``getUpdates`` of the command waits on Telegram's side."""
WAIT_INTERVAL = 0.5
"""How often the command looks at the record while the hub polls."""
HEALTH_EVERY = 10
"""Look at the hub's ``/health`` every this many record checks."""
BACKOFF_MAX = 30.0
HUB_TIMEOUT = 3.0
POLLER_STATES = frozenset({"starting", "polling", "retrying"})
GUARD_CHANNEL = "telegram-pair"
"""The audit label of the admission this command asks the guard for."""


def token_looks_valid(token: str) -> bool:
    """Digits, a colon and a secret of URL-safe characters (no whitespace or quotes)."""
    return bool(TOKEN_SHAPE.fullmatch(token))


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _local_time(moment: datetime) -> str:
    from tau_core.persona import TIMEZONE

    return f"{moment.astimezone(TIMEZONE):%H:%M}"


def _dotenv_values(home: Path) -> dict[str, str | None]:
    from dotenv import dotenv_values

    path = home / ".env"
    return dict(dotenv_values(path)) if path.is_file() else {}


def current_allowlist(home: Path) -> frozenset[int]:
    """``TELEGRAM_ALLOWED_CHAT_IDS`` as a hub reload reads it: ``.env`` first, then the
    environment."""
    raw = _dotenv_values(home).get(ALLOWED_CHATS_ENV)
    if raw is None:
        raw = os.environ.get(ALLOWED_CHATS_ENV)
    return parse_chat_ids(raw)[0]


# -- output -------------------------------------------------------------------------------------


class Output:
    """Text in the UI language, or one JSON object per line with ``--json``."""

    def __init__(self, as_json: bool, language: str = DEFAULT_LANGUAGE):
        self.as_json = as_json
        self.language = language

    def text(self, key: str, **kwargs: object) -> str:
        return t(key, self.language, **kwargs)

    def say(self, key: str, **kwargs: object) -> None:
        if not self.as_json:
            click.echo(self.text(key, **kwargs))

    def event(self, kind: str, /, **fields: Any) -> None:
        if self.as_json:
            click.echo(json.dumps({"event": kind, **fields}, ensure_ascii=False))

    def note(self, key: str, **kwargs: object) -> None:
        if self.as_json:
            self.event("note", message=self.text(key, **kwargs))
        else:
            click.echo(self.text(key, **kwargs), err=True)

    def fail(self, reason: str, message: str) -> None:
        if self.as_json:
            self.event("error", reason=reason, message=message)
        else:
            click.echo(message, err=True)


class PairFailed(Exception):
    """Pairing stopped with ``reason`` (a stable word for ``--json``) and a message key."""

    def __init__(self, reason: str, key: str, **kwargs: object):
        self.reason = reason
        self.key = key
        self.kwargs = kwargs
        super().__init__(reason)


# -- the hub ------------------------------------------------------------------------------------


class HubPort(Protocol):
    """What the command needs from a running hub; tests pass a fake."""

    async def reload(self) -> Any: ...

    async def status(self) -> dict[str, Any] | None: ...

    async def alive(self) -> bool: ...


class HubLink:
    """The hub's control API through :class:`~tau_core.hub.client.HubClient` (loopback, signed
    requests, proven answers)."""

    def __init__(self, config: Config, *, port: int | None = None):
        self.client = HubClient(config, port=port)

    async def reload(self) -> Any:
        """``POST /telegram/reload``; raises ``HubUnavailable`` or ``HubError``."""
        return await asyncio.to_thread(
            self.client.post, RELOAD_PATH, {}, timeout=RELOAD_TIMEOUT + 5
        )

    async def status(self) -> dict[str, Any] | None:
        """The open ``GET /status``; ``None`` when no hub answers."""
        try:
            payload = await asyncio.to_thread(self.client.get, "/status", timeout=HUB_TIMEOUT)
        except (HubUnavailable, HubError):
            return None
        return payload if isinstance(payload, dict) else None

    async def alive(self) -> bool:
        try:
            payload = await asyncio.to_thread(self.client.get, "/health", timeout=HUB_TIMEOUT)
        except (HubUnavailable, HubError):
            return False
        return isinstance(payload, dict) and payload.get("ok") is True


# -- pairing ------------------------------------------------------------------------------------


@dataclass
class PairDeps:
    """Everything :func:`run_pair` touches; tests replace the API, the hub, time and the code."""

    config: Config
    api: BotApi
    hub: HubPort
    out: Output
    clock: Callable[[], datetime] = _utc_now
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    make_code: Callable[[], str] = new_code
    poll_timeout: float = CLI_POLL_TIMEOUT
    wait_interval: float = WAIT_INTERVAL
    announced: set[str] = field(default_factory=set)

    @property
    def files(self) -> TelegramFiles:
        return TelegramFiles(self.config.data_dir / "telegram")


async def check_token(api: BotApi) -> str:
    """The bot's username from one ``getMe``; :class:`PairFailed` when Telegram refuses the
    token or cannot be reached. Error texts never hold the token (``HttpBotApi`` masks it)."""
    try:
        me = await api.call("getMe")
    except TelegramError as exc:
        if exc.code in (401, 403, 404):
            raise PairFailed(
                "token_refused", "telegram.pair.token_refused", detail=exc.code
            ) from None
        raise PairFailed(
            "unreachable", "telegram.pair.unreachable", detail=f"{exc.code} {exc.description}"
        ) from None
    except Exception as exc:
        raise PairFailed(
            "unreachable", "telegram.pair.unreachable", detail=type(exc).__name__
        ) from None
    username = me.get("username") if isinstance(me, dict) else None
    if not isinstance(username, str) or not username or not me.get("is_bot", True):
        raise PairFailed("token_refused", "telegram.pair.token_refused", detail="getMe")
    return username


async def _hub_takes_it(deps: PairDeps) -> bool:
    """Ask a running hub to take the code. ``True`` when its Telegram service now waits for
    it; ``False`` when no hub runs or the hub has no Telegram channel (the command polls)."""
    try:
        reply = await deps.hub.reload()
    except HubUnavailable:
        return False
    except HubError as exc:
        if exc.status == 404:  # a hub without the route: no telegram service, or an old hub
            status = await deps.hub.status()
            poller = status.get("telegram") if isinstance(status, dict) else None
            if isinstance(poller, dict) and poller.get("state") in POLLER_STATES:
                raise PairFailed("hub_conflict", "telegram.pair.hub_conflict") from None
            return False
        raise PairFailed(
            "hub_error", "telegram.pair.hub_error", detail=f"HTTP {exc.status}"
        ) from None
    if not isinstance(reply, dict) or not reply.get("pairing") or not reply.get("configured"):
        reason = reply.get("reason") if isinstance(reply, dict) else None
        raise PairFailed(
            "hub_mismatch", "telegram.pair.hub_mismatch", reason=reason or "no pairing code"
        )
    return True


async def _watch(deps: PairDeps, store: PairingStore) -> None:
    """Wait while the hub polls, until the record is no longer pending or the hub is gone."""
    ticks = 0
    while True:
        view = store.current()
        if view is None or not view.pending:
            return
        await deps.sleep(deps.wait_interval)
        ticks += 1
        if ticks % HEALTH_EVERY == 0 and not await deps.hub.alive():
            return


def _backoff(failures: int) -> float:
    return min(BACKOFF_MAX, 2.0 ** (failures - 1))


async def _confirm(deps: PairDeps, chat_id: int) -> None:
    try:
        await deps.api.call(
            "sendMessage", chat_id=chat_id, text=t("telegram.pair.done", deps.out.language)
        )
    except Exception as exc:
        logger.warning("telegram pair: could not confirm the pairing in the chat: %s", exc)


def _hand_over(deps: PairDeps, kept: Mapping[int, dict[str, Any]]) -> None:
    """Put the messages of chats that are still allowed into ``inflight.json``: the hub runs
    them at its next start."""
    allowed = current_allowlist(deps.config.home)
    keep = {
        update_id: update
        for update_id, update in kept.items()
        if ((update.get("message") or {}).get("chat") or {}).get("id") in allowed
    }
    if not keep:
        return
    files = deps.files
    try:
        inflight = files.read_inflight()
        inflight.update(keep)
        files.write_inflight(inflight)
    except OSError as exc:
        logger.warning("telegram pair: could not hand %d messages over: %s", len(keep), exc)


async def _poll(deps: PairDeps, store: PairingStore) -> None:
    """Poll ``getUpdates`` until the record is no longer pending, or until a hub that started
    meanwhile polls the same bot (a 409)."""
    api, files, home = deps.api, deps.files, deps.config.home
    hub_at_start = await deps.hub.alive()
    try:
        await api.call("deleteWebhook", drop_pending_updates=False)
    except TelegramError as exc:
        if exc.code in (401, 403, 404):
            raise PairFailed(
                "token_refused", "telegram.pair.token_refused", detail=exc.code
            ) from None
    except Exception:
        pass  # getUpdates reports what is wrong
    before = current_allowlist(home)
    kept: dict[int, dict[str, Any]] = {}
    offset = files.read_offset()
    failures = 0
    warned = False
    try:
        while True:
            view = store.current()
            if view is None or not view.pending or view.expires_at is None:
                return
            remaining = (view.expires_at - deps.clock()).total_seconds()
            params: dict[str, Any] = {
                "timeout": min(deps.poll_timeout, max(1, math.ceil(remaining))),
                "allowed_updates": list(ALLOWED_UPDATES),
            }
            if offset is not None:
                params["offset"] = offset
            try:
                updates = await api.call("getUpdates", **params)
            except TelegramError as exc:
                if exc.code in (401, 403, 404):
                    raise PairFailed(
                        "token_refused", "telegram.pair.token_refused", detail=exc.code
                    ) from None
                if exc.code == 409 and "webhook" in exc.description.lower():
                    try:
                        await api.call("deleteWebhook", drop_pending_updates=False)
                    except Exception as webhook_error:
                        logger.info("telegram pair: deleteWebhook failed: %s", webhook_error)
                elif exc.code == 409:
                    if not hub_at_start and await deps.hub.alive():
                        return  # a hub started and polls: it takes the code
                    if not warned:
                        deps.out.note("telegram.pair.conflict")
                        warned = True
                failures += 1
                await deps.sleep(max(exc.retry_after or 0.0, _backoff(failures)))
                continue
            except Exception as exc:
                failures += 1
                logger.info("telegram pair: getUpdates failed: %s", type(exc).__name__)
                await deps.sleep(_backoff(failures))
                continue
            failures = 0
            for update in updates or []:
                if not isinstance(update, dict) or not isinstance(update.get("update_id"), int):
                    continue
                update_id = update["update_id"]
                message = update.get("message")
                paired = False
                if isinstance(message, dict):
                    result = await asyncio.to_thread(try_pair, store, home, message)
                    if result is not None and result.ok and result.chat_id is not None:
                        paired = True
                        await _confirm(deps, result.chat_id)
                    elif ((message.get("chat") or {}).get("id")) in before:
                        kept[update_id] = update
                offset = update_id + 1
                try:
                    files.write_offset(offset)
                except OSError as exc:
                    logger.warning("telegram pair: could not write the offset: %s", exc)
                if paired:
                    return  # later updates stay with Telegram for the hub
    finally:
        _hand_over(deps, kept)


async def _wait(deps: PairDeps, store: PairingStore) -> Pairing | None:
    """Until the record is no longer pending: the hub polls while one runs, else this
    command. Returns the record as it ended."""
    while True:
        view = store.current()
        if view is None or not view.pending:
            return view
        by_hub = await _hub_takes_it(deps)
        via = "hub" if by_hub else "cli"
        if via not in deps.announced:
            deps.announced.add(via)
            deps.out.say(f"telegram.pair.via_{via}")
            deps.out.event("waiting", via=via)
        if by_hub:
            await _watch(deps, store)
        else:
            await _poll(deps, store)


def _write_token(deps: PairDeps, token: str) -> None:
    from tau_core.settings import set_credential

    path = deps.config.home / ".env"
    try:
        set_credential(deps.config.home, TOKEN_ENV, token)
    except (OSError, ValueError) as exc:
        reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else "invalid value"
        raise PairFailed(
            "env_write", "telegram.pair.env_failed", name=TOKEN_ENV, path=path, reason=reason
        ) from None


def _report(deps: PairDeps, view: Pairing | None, *, via_hub: bool) -> bool:
    out = deps.out
    if view is not None and view.state == "paired":
        name = view.name or "?"
        out.say("telegram.pair.paired", name=name)
        if view.dropped:
            out.say("telegram.pair.dropped", n=view.dropped)
        if not via_hub:
            out.say("telegram.pair.start_hub")
        out.event("paired", name=name, dropped=view.dropped, hub=via_hub)
        return True
    if view is not None and view.state == "void":
        out.fail("void", out.text("telegram.pair.void"))
    elif view is not None and view.state == "expired":
        out.fail("expired", out.text("telegram.pair.expired"))
    else:
        out.fail("cancelled", out.text("telegram.pair.cancelled"))
    return False


async def run_pair(deps: PairDeps, token: str, *, write_token: bool) -> bool:
    """Check and store ``token``, show a code and wait for it (module docstring). ``True``
    when a chat was paired; every failure is reported through ``deps.out``."""
    out = deps.out
    store = PairingStore(deps.config.data_dir / "telegram", clock=deps.clock)
    try:
        out.say("telegram.pair.checking")
        username = await check_token(deps.api)
        out.say("telegram.pair.token_ok", bot=username)
        dotenv = deps.config.home / ".env"
        if write_token:
            _write_token(deps, token)
            out.say("telegram.pair.token_written", name=TOKEN_ENV, path=dotenv)
        else:
            out.say("telegram.pair.token_kept", name=TOKEN_ENV, path=dotenv)
        out.event("bot", bot=username, token="written" if write_token else "kept")
        try:
            code, view = store.create(code=deps.make_code())
        except OSError as exc:
            raise PairFailed(
                "env_write",
                "telegram.pair.env_failed",
                name="pairing.json",
                path=store.path,
                reason=exc.strerror or type(exc).__name__,
            ) from None
        assert view.expires_at is not None
        shown, link = format_code(code), deep_link(username, code)
        out.say("telegram.pair.instructions", bot=username, code=shown)
        out.say("telegram.pair.link", link=link)
        out.say(
            "telegram.pair.valid",
            minutes=CODE_TTL_SECONDS // 60,
            time=_local_time(view.expires_at),
        )
        out.event(
            "code",
            code=shown,
            link=link,
            bot=username,
            expires_at=view.expires_at.isoformat(timespec="seconds"),
        )
    except PairFailed as exc:
        out.fail(exc.reason, out.text(exc.key, **exc.kwargs))
        return False
    try:
        ended = await _wait(deps, store)
    except PairFailed as exc:
        store.finish()
        out.fail(exc.reason, out.text(exc.key, **exc.kwargs))
        return False
    except asyncio.CancelledError:
        ended = store.finish()
        if ended is not None and ended.state == "paired":
            return _report(deps, ended, via_hub="hub" in deps.announced)
        out.fail("cancelled", out.text("telegram.pair.cancelled"))
        raise
    final = store.finish() or ended
    return _report(deps, final, via_hub="hub" in deps.announced)


# -- the commands -------------------------------------------------------------------------------


@click.group(
    name="telegram",
    help="The Telegram channel: pair your chat with the bot and show the channel's state. "
    "The hub polls the Bot API itself; no server sits in between (ADR 0006).",
    short_help="Pair your Telegram chat and show the channel's state.",
)
@help_option()
def telegram() -> None:
    pass


def _obj(ctx: click.Context) -> dict[str, Any]:
    return ctx.find_object(dict) or {}


def _load_config(ctx: click.Context, out: Output) -> Config:
    try:
        # An explicit mapping: .env is read without being loaded into this process, so the
        # process environment still says what the shell exported.
        return Config.load(_obj(ctx).get("home"), env=dict(os.environ))
    except ConfigError as exc:
        out.fail("config", str(exc))
        ctx.exit(2)
        raise AssertionError("unreachable") from None


def _read_token(ctx: click.Context, out: Output, *, as_json: bool, current: str) -> str:
    if as_json:
        raw = sys.stdin.readline()
        try:
            data = json.loads(raw) if raw.strip() else {}
        except ValueError:
            data = None
        token = data.get("token") if isinstance(data, dict) else 0
        if token is not None and not isinstance(token, str):
            out.fail("bad_json", out.text("telegram.pair.bad_json"))
            ctx.exit(1)
        return (token or "").strip()
    key = "telegram.pair.token_prompt_keep" if current else "telegram.pair.token_prompt"
    typed = click.prompt(out.text(key), default="", show_default=False, hide_input=True)
    return str(typed).strip()


def _admitted(ctx: click.Context, config: Config, out: Output) -> bool:
    obj = _obj(ctx)
    guard = obj["telegram_guard"] if "telegram_guard" in obj else resolve_guard(config)
    if guard is None:
        return True
    turn = GuardTurn(GUARD_CHANNEL, None, process_client_id())
    admission = asyncio.run(admit_turn(guard, turn))
    if admission.allowed:
        return True
    message = f"{out.text(f'guard.refused.{admission.reason}')} {out.text('telegram.pair.locked')}"
    out.fail("locked", message)
    return False


@telegram.command(
    name="pair",
    help="Pair your Telegram chat with the bot, without looking up a chat id. Asks for the "
    "bot token from @BotFather with hidden input (Enter keeps the one in <home>/.env), checks "
    "it with one getMe and writes it to <home>/.env (mode 0600). Then it shows a one-time "
    "code, valid 10 minutes: send /start <code> to the bot, or open the link it prints. The "
    "running hub takes the code; without a hub this command polls Telegram itself. The chat "
    "that sends the code becomes TELEGRAM_ALLOWED_CHAT_IDS; wrong or expired codes get no "
    "answer. With the owner guard on, tau must be unlocked. Exit 0 once paired, 1 otherwise.",
    short_help="Pair your Telegram chat with the bot.",
)
@help_option()
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help='Read {"token": "..."} as one JSON line on stdin instead of prompting (null or "" '
    "keeps the current token) and print one JSON event per line (for the app's wizard).",
)
@click.pass_context
def pair(ctx: click.Context, as_json: bool) -> None:
    from tau_core.builder import env_with_dotenv

    obj = _obj(ctx)
    out = Output(as_json)
    config = _load_config(ctx, out)
    out.language = config.ui.language
    if not _admitted(ctx, config, out):
        ctx.exit(1)
    current = (env_with_dotenv(config.home, os.environ).get(TOKEN_ENV) or "").strip()
    token = _read_token(ctx, out, as_json=as_json, current=current)
    if not token:
        if not current:
            out.fail("no_token", out.text("telegram.pair.no_token"))
            ctx.exit(1)
        token = current
    if not token_looks_valid(token):
        out.fail("token_invalid", out.text("telegram.pair.token_invalid"))
        ctx.exit(1)
    write = (_dotenv_values(config.home).get(TOKEN_ENV) or "").strip() != token
    for name in (TOKEN_ENV, ALLOWED_CHATS_ENV):
        if os.environ.get(name):
            out.note("telegram.pair.env_shadowed", name=name)
    api_factory: Callable[[str], BotApi] = obj.get("telegram_api") or HttpBotApi
    deps = PairDeps(
        config=config,
        api=api_factory(token),
        hub=obj.get("telegram_hub") or HubLink(config),
        out=out,
    )
    if "telegram_clock" in obj:
        deps.clock = obj["telegram_clock"]
    if "telegram_code" in obj:
        deps.make_code = obj["telegram_code"]
    if "telegram_poll_timeout" in obj:
        deps.poll_timeout = obj["telegram_poll_timeout"]
    try:
        paired = asyncio.run(run_pair(deps, token, write_token=write))
    except KeyboardInterrupt:
        ctx.exit(130)
    ctx.exit(0 if paired else 1)


async def _status(
    config: Config, api_factory: Callable[[str], BotApi], hub: HubPort
) -> dict[str, Any]:
    from tau_core.builder import env_with_dotenv

    env = env_with_dotenv(config.home, os.environ)
    token = (env.get(TOKEN_ENV) or "").strip()
    allowed, _ = parse_chat_ids(env.get(ALLOWED_CHATS_ENV))
    bot = error = None
    refused = False
    if token:
        try:
            bot = await check_token(api_factory(token))
        except PairFailed as exc:
            refused = exc.reason == "token_refused"
            error = str(exc.kwargs.get("detail") or exc.reason)
    pairing = PairingStore(config.data_dir / "telegram").current()
    hub_status = await hub.status()
    poller = hub_status.get("telegram") if isinstance(hub_status, dict) else None
    return {
        "token": bool(token),
        "bot": bot,
        "bot_error": error,
        "token_refused": refused,
        "paired": bool(allowed),
        "allowed_chats": len(allowed),
        "pairing": (
            {"expires_at": pairing.expires_at.isoformat(timespec="seconds")}
            if pairing is not None and pairing.pending and pairing.expires_at is not None
            else None
        ),
        "hub": {
            "running": hub_status is not None,
            "telegram": poller if isinstance(poller, dict) else None,
        },
    }


def _status_lines(report: Mapping[str, Any], out: Output) -> list[str]:
    lines: list[str] = []
    if not report["token"]:
        lines.append(out.text("telegram.status.token_missing"))
    elif report["bot"]:
        lines.append(out.text("telegram.status.token_ok", bot=report["bot"]))
    elif report["token_refused"]:
        lines.append(out.text("telegram.status.token_refused", detail=report["bot_error"]))
    else:
        lines.append(out.text("telegram.status.token_unchecked", detail=report["bot_error"]))
    if report["paired"]:
        lines.append(out.text("telegram.status.paired", n=report["allowed_chats"]))
    else:
        lines.append(out.text("telegram.status.unpaired"))
    if report["pairing"]:
        expires = datetime.fromisoformat(report["pairing"]["expires_at"])
        lines.append(out.text("telegram.status.pairing", time=_local_time(expires)))
    hub, poller = report["hub"], report["hub"]["telegram"]
    if not hub["running"]:
        lines.append(out.text("telegram.status.hub_off"))
    elif poller is None:
        lines.append(out.text("telegram.status.hub_none"))
    elif poller.get("configured") is False:
        lines.append(out.text("telegram.status.hub_idle", reason=poller.get("reason") or "-"))
    elif poller.get("state") == "polling":
        lines.append(out.text("telegram.status.hub_polling", bot=poller.get("bot") or "-"))
    else:
        lines.append(out.text("telegram.status.hub_state", state=poller.get("state") or "?"))
    return lines


@telegram.command(
    name="status",
    help="Show whether a bot token is set (and the bot's name, from one getMe), whether an "
    "owner chat is paired, whether a pairing code waits and what the running hub's Telegram "
    "channel does. Never prints the token or a chat id.",
    short_help="Show the Telegram channel's state.",
)
@help_option()
@click.option("--json", "as_json", is_flag=True, help="Print the state as JSON.")
@click.pass_context
def status(ctx: click.Context, as_json: bool) -> None:
    obj = _obj(ctx)
    out = Output(as_json)
    config = _load_config(ctx, out)
    out.language = config.ui.language
    api_factory: Callable[[str], BotApi] = obj.get("telegram_api") or HttpBotApi
    hub = obj.get("telegram_hub") or HubLink(config)
    report = asyncio.run(_status(config, api_factory, hub))
    if as_json:
        click.echo(json.dumps(report, ensure_ascii=False, indent=2))
        return
    for line in _status_lines(report, out):
        click.echo(line)
