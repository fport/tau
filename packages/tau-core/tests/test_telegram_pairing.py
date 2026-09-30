"""Telegram pairing (issue 172) against the offline FakeBotApi: no network, no real token.

``tau telegram pair`` runs through CliRunner with its seams in the click context object
(``telegram_api``, ``telegram_hub``, ``telegram_code``, ``telegram_clock``,
``telegram_guard``); the hub side runs the real ``TelegramService`` on a FakeBotApi, and once
a real assembled hub with its control API. Every token here is a made-up test value, and the
tests check it never reaches the output or a log line.
"""

from __future__ import annotations

import asyncio
import json
import logging
import stat
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result
from dotenv import dotenv_values
from tau_core.channels import telegram as telegram_module
from tau_core.channels.telegram import RELOAD_PATH, TelegramService
from tau_core.channels.telegram_cli import HubLink, token_looks_valid
from tau_core.channels.telegram_pairing import (
    CODE_ALPHABET,
    CODE_LENGTH,
    MAX_FAILURES,
    PairingStore,
    deep_link,
    format_code,
    new_code,
    normalize_code,
    start_payload,
    try_pair,
)
from tau_core.cli import cli
from tau_core.config import Config
from tau_core.hub.client import HubUnavailable
from tau_core.hub.daemon import Hub
from tau_core.i18n import t
from tau_core.testing import FakeBotApi, FakeGuard, test_config

TOKEN = "123456789:AAtest-not-a-real-token_0123456789ab"
OLD_TOKEN = "987654321:AAold-not-a-real-token_0123456789cd"
CODE = "ABCDEFGH"
SHOWN = "ABCD-EFGH"
ME = 111
STRANGER = 999
GROUP = -100200


class Clock:
    """A settable UTC clock."""

    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class NoHub:
    """No hub answers on the control API."""

    def __init__(self) -> None:
        self.reloads = 0

    async def reload(self) -> Any:
        self.reloads += 1
        raise HubUnavailable("no_hub", "no hub answers")

    async def status(self) -> dict[str, Any] | None:
        return None

    async def alive(self) -> bool:
        return False


def start(chat_id: int, code: str, *, chat_type: str = "private") -> dict[str, Any]:
    return {
        "message_id": 1,
        "date": 0,
        "chat": {"id": chat_id, "type": chat_type},
        "from": {"id": chat_id, "is_bot": False, "first_name": "Deniz", "username": "deniz"},
        "text": f"/start {code}",
    }


def home_of(config: Config) -> Path:
    return config.home


def env_file(config: Config) -> Path:
    return config.home / ".env"


def run_pair(
    tmp_path: Path,
    *,
    api: FakeBotApi | None = None,
    hub: Any = None,
    stdin: str | None = None,
    json_mode: bool = True,
    guard: FakeGuard | None = None,
    clock: Clock | None = None,
    env: dict[str, str] | None = None,
) -> tuple[Result, FakeBotApi, Config]:
    config = test_config(tmp_path)
    api = api or FakeBotApi()
    obj: dict[str, Any] = {
        "telegram_api": lambda token: api,
        "telegram_hub": hub or NoHub(),
        "telegram_code": lambda: CODE,
        "telegram_poll_timeout": 0.05,
    }
    if guard is not None:
        obj["telegram_guard"] = guard
    if clock is not None:
        obj["telegram_clock"] = clock
    args = ["--home", str(config.home), "telegram", "pair"] + (["--json"] if json_mode else [])
    if stdin is None:
        stdin = json.dumps({"token": TOKEN}) + "\n" if json_mode else TOKEN + "\n"
    full_env = {"TAU_DATA_DIR": str(config.data_dir), "TAU_LANG": "en", **(env or {})}
    result = CliRunner().invoke(cli, args, input=stdin, env=full_env, obj=obj, prog_name="tau")
    return result, api, config


def events(result: Result) -> list[dict[str, Any]]:
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


# -- the code --------------------------------------------------------------------------------


def test_codes_are_random_unambiguous_and_readable() -> None:
    codes = {new_code() for _ in range(50)}
    assert len(codes) == 50
    for code in codes:
        assert len(code) == CODE_LENGTH and set(code) <= set(CODE_ALPHABET)
    assert not set("0O1IL") & set(CODE_ALPHABET)
    assert format_code(CODE) == SHOWN
    assert normalize_code(" abcd-efgh ") == normalize_code("ab cd ef gh") == CODE
    assert deep_link("@tau_test_bot", CODE) == f"https://t.me/tau_test_bot?start={SHOWN}"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        (f"/start {SHOWN}", CODE),
        ("/start@tau_test_bot abcd-efgh", CODE),
        ("/START abcd efgh", CODE),
        ("/start", None),
        ("/start ", None),
        ("/help ABCD", None),
        ("/startABCD", None),
        ("hello", None),
        (None, None),
        ("/start " + "A" * 65, None),
    ],
)
def test_start_payload(text: object, code: str | None) -> None:
    assert start_payload(text) == code


def test_token_shape() -> None:
    assert token_looks_valid(TOKEN)
    for bad in ("", "abc", "123:short", "123456:has space in it 0123456789", "12:'quoted'x" * 3):
        assert not token_looks_valid(bad)


# -- the record ------------------------------------------------------------------------------


def test_the_code_is_stored_hashed_and_private(tmp_path: Path) -> None:
    store = PairingStore(tmp_path / "telegram")
    code, view = store.create(code=CODE)
    assert code == CODE and view.pending
    text = store.path.read_text()
    assert CODE not in text and SHOWN not in text
    record = json.loads(text)
    assert record["kdf"] == "pbkdf2-sha256" and record["state"] == "pending"
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
    assert store.finish() is not None and not store.path.exists()


def test_a_private_chat_with_the_code_becomes_the_owner_chat(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    dotenv = home / ".env"
    lines = [
        "# my settings",
        "ANTHROPIC_API_KEY=sk-test-kept",
        f"TELEGRAM_BOT_TOKEN={OLD_TOKEN}",
        "TELEGRAM_ALLOWED_CHAT_IDS=5,6",
        "",
        "# the end",
    ]
    dotenv.write_text("\n".join(lines) + "\n")
    dotenv.chmod(0o644)
    store = PairingStore(tmp_path / "telegram")
    store.create(code=CODE)

    result = try_pair(store, home, start(ME, SHOWN))
    assert result is not None and result.ok
    assert result.chat_id == ME and result.allowed == frozenset({ME}) and result.dropped == 2
    assert result.name == "Deniz @deniz"
    after = dotenv.read_text().splitlines()
    assert after == [*lines[:3], f"TELEGRAM_ALLOWED_CHAT_IDS={ME}", *lines[4:]]
    assert stat.S_IMODE(dotenv.stat().st_mode) == 0o600
    view = store.current()
    assert view is not None and view.state == "paired" and view.name == "Deniz @deniz"
    # The code works once: a second chat gets nothing.
    assert try_pair(store, home, start(STRANGER, SHOWN)) is None
    assert dotenv_values(dotenv)["TELEGRAM_ALLOWED_CHAT_IDS"] == str(ME)


def test_wrong_group_and_expired_codes_store_nothing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    clock = Clock()
    store = PairingStore(tmp_path / "telegram", clock=clock)
    store.create(code=CODE)

    wrong = try_pair(store, home, start(STRANGER, "WXYZ-2345"))
    assert wrong is not None and (wrong.ok, wrong.reason) == (False, "wrong")
    group = try_pair(store, home, start(GROUP, SHOWN, chat_type="group"))
    assert group is not None and (group.ok, group.reason) == (False, "not_private")
    view = store.current()
    assert view is not None and view.pending and view.failures == 1
    assert not (home / ".env").exists()

    clock.advance(601)
    assert try_pair(store, home, start(ME, SHOWN)) is None  # expired: no pairing attempt
    assert not (home / ".env").exists()
    view = store.current()
    assert view is not None and view.state == "expired"


def test_too_many_wrong_codes_void_the_code(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    store = PairingStore(tmp_path / "telegram")
    store.create(code=CODE)
    outcomes = [try_pair(store, home, start(STRANGER, f"WRONG{i:03d}")) for i in range(10)]
    assert [o.reason for o in outcomes if o is not None] == ["wrong"] * (MAX_FAILURES - 1) + [
        "void"
    ]
    assert try_pair(store, home, start(ME, SHOWN)) is None
    assert not (home / ".env").exists()


# -- tau telegram pair, no hub: the command polls ------------------------------------------------


def test_pair_polls_itself_without_a_hub_and_pairs_the_first_right_code(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    api = FakeBotApi()
    api.push_message(STRANGER, "hello")
    api.push({"message": start(STRANGER, "WXYZ-2345")})
    api.push({"message": start(GROUP, SHOWN, chat_type="group")})
    pairing = api.push({"message": start(ME, SHOWN)})
    later = api.push_message(ME, "are you there?")
    hub = NoHub()

    with caplog.at_level(logging.DEBUG):
        result, api, config = run_pair(tmp_path, api=api, hub=hub)

    assert result.exit_code == 0, result.output
    seen = events(result)
    assert [e["event"] for e in seen] == ["bot", "code", "waiting", "paired"]
    assert seen[0] == {"event": "bot", "bot": "tau_test_bot", "token": "written"}
    assert seen[1]["code"] == SHOWN
    assert seen[1]["link"] == f"https://t.me/tau_test_bot?start={SHOWN}"
    assert seen[2] == {"event": "waiting", "via": "cli"}
    assert seen[3] == {"event": "paired", "name": "Deniz @deniz", "dropped": 0, "hub": False}
    assert hub.reloads >= 1
    # Only the paired chat heard anything, once.
    assert [(p["chat_id"], p["text"]) for p in api.sent] == [(ME, t("telegram.pair.done", "en"))]
    values = dotenv_values(env_file(config))
    assert values["TELEGRAM_BOT_TOKEN"] == TOKEN
    assert values["TELEGRAM_ALLOWED_CHAT_IDS"] == str(ME)
    assert stat.S_IMODE(env_file(config).stat().st_mode) == 0o600
    # The offset stops right after the pairing update: the next one stays for the hub.
    offset = (config.data_dir / "telegram" / "offset").read_text().strip()
    assert offset == str(pairing["update_id"] + 1)
    assert [u["update_id"] for u in api.updates if u["update_id"] >= int(offset)] == [
        later["update_id"]
    ]
    assert not (config.data_dir / "telegram" / "pairing.json").exists()
    assert TOKEN not in result.output and TOKEN not in caplog.text
    assert "getUpdates" in api.methods() and "deleteWebhook" in api.methods()


def test_a_hub_started_after_the_command_continues_from_its_offset(tmp_path: Path) -> None:
    api = FakeBotApi()
    pairing = api.push({"message": start(ME, SHOWN)})
    api.push_message(ME, "hi after pairing")
    result, api, config = run_pair(tmp_path, api=api)
    assert result.exit_code == 0, result.output
    sent_before, calls_before = len(api.sent), len(api.calls)

    service = TelegramService(config, env={"TELEGRAM_BOT_TOKEN": TOKEN}, api=api)

    async def main() -> None:
        await service.start(Hub(config))
        try:
            await service.reload()  # the hub was started without the pairing in its env
            deadline = time.monotonic() + 5
            while len(api.sent) == sent_before and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
        finally:
            await service.stop()

    asyncio.run(main())
    polls = [p for m, p in api.calls[calls_before:] if m == "getUpdates"]
    assert polls[0]["offset"] == pairing["update_id"] + 1  # where the command stopped
    assert [p["chat_id"] for p in api.sent[sent_before:]] == [ME]  # answered once, not twice
    assert service.allowed == frozenset({ME})


def test_messages_of_an_allowed_chat_are_handed_to_the_hub(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    env_file(config).write_text(f"TELEGRAM_ALLOWED_CHAT_IDS={ME}\n")
    api = FakeBotApi()
    kept = api.push_message(ME, "a message while pairing")
    api.push_message(STRANGER, "a stranger")
    api.push({"message": start(ME, SHOWN)})  # the owner re-pairs the same chat
    result, api, config = run_pair(tmp_path, api=api)
    assert result.exit_code == 0, result.output
    inflight = json.loads((config.data_dir / "telegram" / "inflight.json").read_text())
    assert [u["update_id"] for u in inflight] == [kept["update_id"]]


def test_an_expired_code_is_refused_and_nothing_is_paired(tmp_path: Path) -> None:
    clock = Clock()

    class LateApi(FakeBotApi):
        async def _api_getUpdates(self, **params: Any) -> list[dict[str, Any]]:
            clock.advance(601)  # the code runs out before the message arrives
            return await super()._api_getUpdates(**params)

    api = LateApi()
    api.push({"message": start(ME, SHOWN)})
    result, api, config = run_pair(tmp_path, api=api, clock=clock)
    assert result.exit_code == 1
    assert events(result)[-1] == {
        "event": "error",
        "reason": "expired",
        "message": t("telegram.pair.expired", "en"),
    }
    assert api.sent == []  # no answer
    assert "TELEGRAM_ALLOWED_CHAT_IDS" not in dotenv_values(env_file(config))
    assert not (config.data_dir / "telegram" / "pairing.json").exists()


def test_the_text_mode_prompts_hidden_and_never_prints_the_token(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    api = FakeBotApi()
    api.push({"message": start(ME, SHOWN)})
    with caplog.at_level(logging.DEBUG):
        result, api, config = run_pair(tmp_path, api=api, json_mode=False)
    assert result.exit_code == 0, result.output
    assert t("telegram.pair.token_prompt", "en") in result.output
    assert f"Open t.me/tau_test_bot in Telegram and send: /start {SHOWN}" in result.output
    assert f"https://t.me/tau_test_bot?start={SHOWN}" in result.output
    assert "Paired with Deniz @deniz." in result.output
    assert t("telegram.pair.start_hub", "en") in result.output
    assert TOKEN not in result.output and TOKEN not in caplog.text


def test_an_empty_token_keeps_the_one_in_env(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    env_file(config).write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\n")
    api = FakeBotApi()
    api.push({"message": start(ME, SHOWN)})
    result, api, config = run_pair(tmp_path, api=api, stdin='{"token": null}\n')
    assert result.exit_code == 0, result.output
    assert events(result)[0] == {"event": "bot", "bot": "tau_test_bot", "token": "kept"}
    assert dotenv_values(env_file(config))["TELEGRAM_BOT_TOKEN"] == TOKEN


@pytest.mark.parametrize(
    ("stdin", "reason"),
    [
        ('{"token": "not a token"}\n', "token_invalid"),
        ("{}\n", "no_token"),
        ("not json\n", "bad_json"),
        ('{"token": 5}\n', "bad_json"),
    ],
)
def test_bad_input_writes_nothing(tmp_path: Path, stdin: str, reason: str) -> None:
    result, api, config = run_pair(tmp_path, stdin=stdin)
    assert result.exit_code == 1
    assert events(result)[-1]["reason"] == reason
    assert api.calls == [] and not env_file(config).exists()


def test_a_refused_token_writes_nothing(tmp_path: Path) -> None:
    from tau_core.channels.telegram import TelegramError

    api = FakeBotApi()
    api.fail("getMe", TelegramError("getMe", 401, "Unauthorized", None))
    result, api, config = run_pair(tmp_path, api=api)
    assert result.exit_code == 1
    assert events(result)[-1]["reason"] == "token_refused"
    assert not env_file(config).exists()
    assert not (config.data_dir / "telegram" / "pairing.json").exists()


def test_a_locked_guard_refuses_pairing_before_anything_is_asked(tmp_path: Path) -> None:
    result, api, config = run_pair(tmp_path, guard=FakeGuard("locked"))
    assert result.exit_code == 1
    [error] = events(result)
    assert error["reason"] == "locked"
    assert t("guard.refused.locked", "en") in error["message"]
    assert api.calls == [] and not env_file(config).exists()

    api = FakeBotApi()
    api.push({"message": start(ME, SHOWN)})
    result, api, config = run_pair(tmp_path, api=api, guard=FakeGuard("unlocked"))
    assert result.exit_code == 0, result.output


def test_an_old_hub_that_polls_without_the_route_is_a_conflict(tmp_path: Path) -> None:
    from tau_core.hub.client import HubError

    class OldHub(NoHub):
        async def reload(self) -> Any:
            raise HubError(404, {"error": "not found"})

        async def status(self) -> dict[str, Any] | None:
            return {"telegram": {"configured": True, "state": "polling"}}

        async def alive(self) -> bool:
            return True

    result, api, config = run_pair(tmp_path, hub=OldHub())
    assert result.exit_code == 1
    assert events(result)[-1]["reason"] == "hub_conflict"
    assert "getUpdates" not in api.methods()
    assert not (config.data_dir / "telegram" / "pairing.json").exists()


# -- the hub takes the code ------------------------------------------------------------------


def serve_pairing(
    config: Config,
    body: Callable[[TelegramService, FakeBotApi], Awaitable[None]],
    *,
    env: dict[str, str],
    api: FakeBotApi | None = None,
) -> tuple[TelegramService, FakeBotApi]:
    api = api or FakeBotApi()

    async def fast_sleep(delay: float) -> None:
        await asyncio.sleep(0)

    service = TelegramService(config, env=env, api=api, sleep=fast_sleep)

    async def main() -> None:
        await service.start(Hub(config))
        try:
            await body(service, api)
        finally:
            await service.stop()

    asyncio.run(main())
    return service, api


async def until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        await asyncio.sleep(0.005)


def test_the_hub_pairs_the_first_private_chat_that_sends_the_code(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    PairingStore(config.data_dir / "telegram").create(code=CODE)

    async def body(service: TelegramService, api: FakeBotApi) -> None:
        assert service.status()["pairing"] is True and service.polling
        api.push({"message": start(STRANGER, "WXYZ-2345")})
        api.push({"message": start(GROUP, SHOWN, chat_type="group")})
        api.push({"message": start(ME, SHOWN)})
        await until(lambda: len(api.sent) >= 1)
        api.push({"message": start(STRANGER, SHOWN)})  # a second chat after the pairing
        api.push_message(ME, "hello")
        await until(lambda: len(api.sent) >= 2)
        await asyncio.sleep(0.05)

    service, api = serve_pairing(config, body, env={"TELEGRAM_BOT_TOKEN": TOKEN})
    assert [p["chat_id"] for p in api.sent] == [ME, ME]
    assert api.sent[0]["text"] == t("telegram.pair.done", "en")
    assert service.allowed == frozenset({ME})
    assert dotenv_values(env_file(config))["TELEGRAM_ALLOWED_CHAT_IDS"] == str(ME)
    assert service.dropped == 3  # the wrong code, the group and the late second chat
    assert api.menu(ME)  # the command menu, for the paired chat only
    assert api.menu(STRANGER) is None
    view = PairingStore(config.data_dir / "telegram").current()
    assert view is not None and view.state == "paired"


def test_without_a_code_or_allowlist_the_hub_stays_idle_and_goes_idle_after_expiry(
    tmp_path: Path,
) -> None:
    config = test_config(tmp_path)
    clock = Clock()

    async def idle(service: TelegramService, api: FakeBotApi) -> None:
        assert service.status() == {
            "configured": False,
            "reason": "TELEGRAM_ALLOWED_CHAT_IDS is empty",
        }

    serve_pairing(config, idle, env={"TELEGRAM_BOT_TOKEN": TOKEN})

    async def expiring(service: TelegramService, api: FakeBotApi) -> None:
        service.pairing = PairingStore(config.data_dir / "telegram", clock=clock)
        service.pairing.create(code=CODE)
        await service.reload()
        assert service.polling
        clock.advance(601)
        api.push({"message": start(ME, SHOWN)})  # too late: dropped, and the poller stops
        await until(lambda: not service.polling)
        assert service.status()["configured"] is False

    service, api = serve_pairing(config, expiring, env={"TELEGRAM_BOT_TOKEN": TOKEN})
    assert api.sent == [] and service.allowed == frozenset()
    assert not env_file(config).exists()


def test_reload_reads_a_new_token_from_env_first(tmp_path: Path) -> None:
    from tau_core.settings import set_credential

    config = test_config(tmp_path)

    async def body(service: TelegramService, api: FakeBotApi) -> None:
        assert service.status()["reason"] == "TELEGRAM_ALLOWED_CHAT_IDS is empty"
        set_credential(config.home, "TELEGRAM_BOT_TOKEN", TOKEN)
        set_credential(config.home, "TELEGRAM_ALLOWED_CHAT_IDS", str(ME))
        status = await service.reload()
        assert status["configured"] is True and service.token == TOKEN
        api.push_message(ME, "hi")
        await until(lambda: len(api.sent) >= 1)

    # The environment still has the old token, as in a hub that loaded .env when it started.
    service, api = serve_pairing(config, body, env={"TELEGRAM_BOT_TOKEN": OLD_TOKEN})
    assert [p["chat_id"] for p in api.sent] == [ME]


def test_a_replayed_message_from_a_chat_no_longer_allowed_is_dropped(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    root = config.data_dir / "telegram"
    root.mkdir(parents=True)
    stale = {"update_id": 7, "message": {"message_id": 1, "chat": {"id": STRANGER}, "text": "x"}}
    (root / "inflight.json").write_text(json.dumps([stale]))

    async def body(service: TelegramService, api: FakeBotApi) -> None:
        await until(lambda: "getUpdates" in api.methods())

    env = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_ALLOWED_CHAT_IDS": str(ME)}
    service, api = serve_pairing(config, body, env=env)
    assert api.sent == [] and service.dropped == 1
    assert json.loads((root / "inflight.json").read_text()) == []


def test_a_running_hub_takes_the_code_through_its_control_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """End to end: a real assembled hub (control API, signed routes) with the Telegram
    service on a fake Bot API; the command only calls /telegram/reload and watches."""
    from tau_core.hub.cli import assemble_hub

    config = test_config(tmp_path)
    hub_api = FakeBotApi()
    hub_api.push({"message": start(STRANGER, "WXYZ-2345")})
    hub_api.push({"message": start(ME, SHOWN)})
    monkeypatch.setattr(telegram_module, "HttpBotApi", lambda token, **kw: hub_api)
    monkeypatch.setenv("TAU_DATA_DIR", str(config.data_dir))

    daemon, control = assemble_hub(config, port=0)
    outcome: list[int] = []
    thread = threading.Thread(target=lambda: outcome.append(daemon.run()))
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while (control.port == 0 or daemon.state is None) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ("POST", RELOAD_PATH) in control.routes
        assert not control.is_open("POST", RELOAD_PATH)  # signed requests only
        cli_api = FakeBotApi()
        with caplog.at_level(logging.DEBUG):
            result, cli_api, _ = run_pair(
                tmp_path, api=cli_api, hub=HubLink(config, port=control.port)
            )
    finally:
        daemon.request_stop()
        thread.join(timeout=10)
    assert result.exit_code == 0, result.output
    assert [e["event"] for e in events(result)] == ["bot", "code", "waiting", "paired"]
    assert events(result)[2] == {"event": "waiting", "via": "hub"}
    assert events(result)[3]["hub"] is True
    assert "getUpdates" not in cli_api.methods()  # one poller: the hub's
    assert [p["chat_id"] for p in hub_api.sent] == [ME]
    assert dotenv_values(env_file(config))["TELEGRAM_ALLOWED_CHAT_IDS"] == str(ME)
    assert TOKEN not in result.output and TOKEN not in caplog.text


# -- tau telegram status ---------------------------------------------------------------------


def test_status_reports_token_bot_chat_and_code_without_secrets(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    env_file(config).write_text(
        f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_ALLOWED_CHAT_IDS={ME}\n", encoding="utf-8"
    )
    PairingStore(config.data_dir / "telegram").create(code=CODE)

    class RunningHub(NoHub):
        async def status(self) -> dict[str, Any] | None:
            return {"telegram": {"configured": True, "state": "polling", "bot": "@tau_test_bot"}}

    obj = {"telegram_api": lambda token: FakeBotApi(), "telegram_hub": RunningHub()}
    env = {"TAU_DATA_DIR": str(config.data_dir), "TAU_LANG": "en"}
    base = ["--home", str(config.home), "telegram", "status"]
    runner = CliRunner()
    as_json = runner.invoke(cli, [*base, "--json"], env=env, obj=obj, prog_name="tau")
    assert as_json.exit_code == 0, as_json.output
    report = json.loads(as_json.stdout)
    assert report["token"] is True and report["bot"] == "tau_test_bot"
    assert report["paired"] is True and report["allowed_chats"] == 1
    assert report["pairing"] is not None and report["hub"]["running"] is True
    text = runner.invoke(cli, base, env=env, obj=obj, prog_name="tau")
    assert text.exit_code == 0
    assert text.output.splitlines()[0] == "Bot token: set (@tau_test_bot)"
    assert "Owner chat: paired (1 allowed)" in text.output
    assert "Hub: running; polling as @tau_test_bot" in text.output
    for output in (as_json.output, text.output):
        assert TOKEN not in output and str(ME) not in output

    obj = {"telegram_api": lambda token: FakeBotApi(), "telegram_hub": NoHub()}
    empty = test_config(tmp_path / "empty")
    env = {"TAU_DATA_DIR": str(empty.data_dir), "TAU_LANG": "en"}
    out = runner.invoke(
        cli, ["--home", str(empty.home), "telegram", "status"], env=env, obj=obj
    ).output
    assert "Bot token: not set" in out and "Owner chat: not paired" in out
    assert "Hub: not running" in out
