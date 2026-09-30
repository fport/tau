"""The Telegram channel (issue 014) against the offline FakeBotApi: no network, no token."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from tau_core.channels.telegram import (
    MAX_MESSAGE_LENGTH,
    TelegramError,
    TelegramService,
    doctor_check,
    markdown_to_html,
    parse_chat_ids,
    split_message,
)
from tau_core.config import Config, RoleConfig, SessionsConfig
from tau_core.guard import ENROLLED_MARKER
from tau_core.hub.daemon import Hub
from tau_core.i18n import t
from tau_core.testing import FakeBotApi, FakeGuard, test_config

ME = 111
STRANGER = 999
ENV = {"TELEGRAM_BOT_TOKEN": "123:test-token", "TELEGRAM_ALLOWED_CHAT_IDS": str(ME)}


def make_config(
    tmp_path: Path, *, replies: list[Any] | None = None, default: str = "Okay."
) -> Config:
    config = test_config(tmp_path, sessions=SessionsConfig(backend="file"))
    params: dict[str, Any] = {"default": default}
    if replies is not None:
        params["replies"] = replies
    roles = dict(config.roles)
    roles["brain"] = RoleConfig(provider="fake", model_id="fake-brain", params=params)
    return config.with_overrides(roles=roles)


class Run:
    """A started service, its fake API, the hub it registered with and the recorded sleeps."""

    def __init__(self, service: TelegramService, api: FakeBotApi, hub: Hub, sleeps: list[float]):
        self.service, self.api, self.hub, self.sleeps = service, api, hub, sleeps

    async def until(self, condition: Callable[[], bool], timeout: float = 5.0) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        while not condition():
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError(f"timed out; state={self.service.status()}")
            await asyncio.sleep(0.005)


def serve(
    config: Config,
    body: Callable[[Run], Awaitable[None]],
    *,
    api: FakeBotApi | None = None,
    env: dict[str, str] | None = None,
) -> Run:
    """Start a service on ``api``, run ``body`` and stop it again."""
    api = api or FakeBotApi()
    sleeps: list[float] = []

    async def fast_sleep(delay: float) -> None:
        sleeps.append(delay)
        await asyncio.sleep(0)

    service = TelegramService(config, env=ENV if env is None else env, api=api, sleep=fast_sleep)
    hub = Hub(config)
    run = Run(service, api, hub, sleeps)

    async def main() -> None:
        await service.start(hub)
        try:
            await body(run)
        finally:
            await service.stop()

    asyncio.run(main())
    return run


def replies_to(run: Run, n: int) -> Callable[[], bool]:
    return lambda: len(run.api.sent) >= n


# -- pure helpers ----------------------------------------------------------------------------


def test_parse_chat_ids() -> None:
    assert parse_chat_ids("123, -456 789") == (frozenset({123, -456, 789}), [])
    assert parse_chat_ids("12,abc,,") == (frozenset({12}), ["abc"])
    assert parse_chat_ids(None) == (frozenset(), [])


def test_split_message_respects_the_limit_and_prefers_line_breaks() -> None:
    assert split_message("short") == ["short"]
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(200))
    pieces = split_message(text)
    assert len(pieces) > 1
    assert all(len(p) <= MAX_MESSAGE_LENGTH for p in pieces)
    assert all(p.startswith("line ") for p in pieces)  # cut at a line break, not mid-line
    assert "\n".join(pieces) == text


def test_split_message_counts_utf16_units_and_cuts_hard_without_a_separator() -> None:
    emoji = "😀" * 3000  # 2 UTF-16 units each: 6000 units, 3000 characters
    pieces = split_message(emoji)
    assert [len(p) for p in pieces] == [2048, 952]
    assert "".join(pieces) == emoji
    assert split_message("a" * 10, limit=4) == ["aaaa", "aaaa", "aa"]


def test_markdown_to_html_escapes_and_converts_the_common_marks() -> None:
    html = markdown_to_html(
        "# Plan\n**Bold** and `a<b>` and ~~old~~, see [docs](https://example.com/a?b=1&c=2).\n"
        "```python\nif a < b:\n    pass\n```\n1 < 2 & <script>"
    )
    assert html == (
        "<b>Plan</b>\n<b>Bold</b> and <code>a&lt;b&gt;</code> and <s>old</s>, see "
        '<a href="https://example.com/a?b=1&amp;c=2">docs</a>.\n'
        "<pre>if a &lt; b:\n    pass</pre>\n1 &lt; 2 &amp; &lt;script&gt;"
    )
    assert markdown_to_html("snake_case *stays*") == "snake_case *stays*"


# -- idle start ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "reason"),
    [
        ({}, "TELEGRAM_BOT_TOKEN is not set"),
        ({"TELEGRAM_BOT_TOKEN": "123:x"}, "TELEGRAM_ALLOWED_CHAT_IDS is empty"),
        (
            {"TELEGRAM_BOT_TOKEN": "123:x", "TELEGRAM_ALLOWED_CHAT_IDS": "me"},
            "TELEGRAM_ALLOWED_CHAT_IDS is empty",
        ),
    ],
)
def test_without_a_token_or_allowlist_the_service_stays_idle(
    tmp_path: Path, env: dict[str, str], reason: str, caplog: pytest.LogCaptureFixture
) -> None:
    async def body(run: Run) -> None:
        await asyncio.sleep(0.01)

    with caplog.at_level(logging.INFO, logger="tau_core.channels.telegram"):
        run = serve(make_config(tmp_path), body, env=env)
    assert run.api.calls == []  # never touches the Bot API
    assert run.hub.status()["telegram"] == {"configured": False, "reason": reason}
    assert f"{reason}; the channel stays idle" in caplog.text
    assert "123:x" not in caplog.text


# -- the conversation ------------------------------------------------------------------------


def test_allowlisted_message_gets_a_reply_in_a_telegram_session(tmp_path: Path) -> None:
    config = make_config(tmp_path, default="Merhaba, **buradayım**.")

    async def body(run: Run) -> None:
        run.api.push_message(ME, "selam")
        await run.until(replies_to(run, 1))

    run = serve(config, body)
    assert run.api.methods()[:4] == ["getMe", "deleteWebhook", "setMyCommands", "getUpdates"]
    polls = [p for m, p in run.api.calls if m == "getUpdates"]
    assert polls[0]["allowed_updates"] == ["message", "callback_query"]
    assert polls[0]["timeout"] == 50
    assert "sendChatAction" in run.api.methods()
    [sent] = run.api.sent
    assert sent["chat_id"] == ME and sent["parse_mode"] == "HTML"
    assert sent["text"] == "Merhaba, <b>buradayım</b>."
    chats = json.loads((config.data_dir / "telegram" / "chats.json").read_text())
    session_id = chats[str(ME)]
    assert run.service.store is not None
    assert run.service.store.read_meta(session_id)["channel"] == "telegram"
    status = run.hub.status()["telegram"]
    assert status["bot"] == "@tau_test_bot" and status["handled"] == 1
    assert "123:test-token" not in json.dumps(status) and str(ME) not in json.dumps(status)


def test_telegram_turns_run_while_a_guard_is_active(tmp_path: Path) -> None:
    """Telegram is an identified in-hub channel: it builds with ``guard=None`` (ADR 0008)."""
    from tau_core.guard import ENROLLED_MARKER, reset_guards, resolve_guard

    config = make_config(tmp_path, default="Here.")
    marker = config.data_dir / ENROLLED_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('{"v": 1, "enrollment": "E1"}', encoding="utf-8")
    reset_guards()
    assert resolve_guard(config) is not None  # guarded channels would be locked now

    async def body(run: Run) -> None:
        run.api.push_message(ME, "hi")
        await run.until(replies_to(run, 1))
        [chat] = run.service._chats.values()
        assert chat.agent is not None and chat.agent.guard is None

    run = serve(config, body)
    assert run.api.sent[0]["text"] == "Here."
    reset_guards()


def test_messages_from_other_chats_are_dropped_and_logged_never_answered(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def body(run: Run) -> None:
        run.api.push_message(STRANGER, "hi")
        run.api.push_callback(STRANGER)
        run.api.push_message(STRANGER, "/help")
        run.api.push_message(ME, "hi")
        await run.until(replies_to(run, 1))

    with caplog.at_level(logging.INFO, logger="tau_core.channels.telegram"):
        run = serve(make_config(tmp_path), body)
    assert [p["chat_id"] for p in run.api.sent] == [ME]
    assert all(p.get("chat_id") != STRANGER for m, p in run.api.calls if m != "getUpdates")
    assert run.service.dropped == 3
    assert f"dropped a message from chat {STRANGER}" in caplog.text


def test_non_text_messages_get_a_short_note(tmp_path: Path) -> None:
    async def body(run: Run) -> None:
        run.api.push_message(ME, None)
        await run.until(replies_to(run, 1))

    run = serve(make_config(tmp_path), body)
    assert run.api.texts() == [t("telegram.text_only", "en")]


def test_long_replies_are_split_and_rejected_markup_falls_back_to_plain_text(
    tmp_path: Path,
) -> None:
    long = "\n\n".join(f"**Part {i}** " + "y" * 900 for i in range(10))
    api = FakeBotApi(reject_html=True)

    async def body(run: Run) -> None:
        run.api.push_message(ME, "long please")
        await run.until(lambda: len(run.api.sent) >= 3 and run.service.handled == 1)
        await asyncio.sleep(0.05)

    run = serve(make_config(tmp_path, default=long), body, api=api)
    assert all(p["parse_mode"] is None for p in run.api.sent)  # every piece fell back
    assert "".join(run.api.texts()).replace("\n", "") == long.replace("\n", "")
    assert len(run.api.sent) == len(split_message(long))


def test_a_webhook_is_deleted_before_polling(tmp_path: Path) -> None:
    api = FakeBotApi(webhook_url="https://example.com/hook")

    async def body(run: Run) -> None:
        run.api.push_message(ME, "hi")
        await run.until(replies_to(run, 1))

    run = serve(make_config(tmp_path), body, api=api)
    assert run.api.methods().index("deleteWebhook") < run.api.methods().index("getUpdates")
    assert run.api.webhook_url == ""


def test_allowed_callback_queries_are_answered_until_017(tmp_path: Path) -> None:
    async def body(run: Run) -> None:
        run.api.push_callback(ME)
        await run.until(lambda: "answerCallbackQuery" in run.api.methods())

    run = serve(make_config(tmp_path), body)
    assert run.api.sent == []


# -- restarts --------------------------------------------------------------------------------


def test_a_restart_neither_reprocesses_nor_loses_updates(tmp_path: Path) -> None:
    config = make_config(tmp_path, replies=["one", "two", "three"])
    first_api = FakeBotApi()

    async def first(run: Run) -> None:
        run.api.push_message(ME, "1")
        run.api.push_message(ME, "2")
        await run.until(replies_to(run, 2))

    run = serve(config, first, api=first_api)
    assert run.api.texts() == ["one", "two"]
    assert (config.data_dir / "telegram" / "offset").read_text().strip() == "3"
    session_id = run.service._sessions[ME]

    # Telegram keeps the two handled updates until an offset confirms them; a new update arrives
    # while the hub is down.
    second_api = FakeBotApi()
    second_api.push_message(ME, "1")
    second_api.push_message(ME, "2")
    second_api.push_message(ME, "3")

    async def second(run: Run) -> None:
        await run.until(replies_to(run, 1))
        await asyncio.sleep(0.05)

    run = serve(config, second, api=second_api)
    polls = [p for m, p in run.api.calls if m == "getUpdates"]
    assert polls[0]["offset"] == 3
    assert len(run.api.sent) == 1  # only update 3; 1 and 2 are not answered twice
    assert run.service._chats[ME].session_id == session_id  # the chat kept its session
    assert run.service.store is not None
    assert run.service.store.read_meta(session_id)["channel"] == "telegram"


# -- network loss and refusals -----------------------------------------------------------------


def test_network_loss_backs_off_and_reconnects(tmp_path: Path) -> None:
    api = FakeBotApi()
    api.fail("getUpdates", ConnectionError("down"), ConnectionError("down"), ConnectionError("x"))
    api.fail("getMe", ConnectionError("down"))
    states: list[str] = []

    async def body(run: Run) -> None:
        run.api.push_message(ME, "hi")
        await run.until(replies_to(run, 1))
        states.append(run.service.status()["state"])

    run = serve(make_config(tmp_path), body, api=api)
    assert run.sleeps[:4] == [1.0, 1.0, 2.0, 4.0]  # getMe once, then getUpdates three times
    assert states == ["polling"]
    assert run.service.last_error is None


def test_backoff_is_capped_and_status_shows_the_retry(tmp_path: Path) -> None:
    config = make_config(tmp_path).with_overrides(
        component_tables={"telegram": {"backoff_max_seconds": 3, "poll_timeout_seconds": 5}}
    )
    api = FakeBotApi()
    api.fail("getUpdates", *[ConnectionError("down")] * 5)
    seen: list[dict[str, Any]] = []

    async def body(run: Run) -> None:
        await run.until(lambda: len(run.sleeps) >= 5)
        seen.append(run.service.status())

    run = serve(config, body, api=api)
    assert run.sleeps[:5] == [1.0, 2.0, 3.0, 3.0, 3.0]
    assert seen[0]["state"] == "retrying" and "ConnectionError: down" in seen[0]["last_error"]
    polls = [p for m, p in run.api.calls if m == "getUpdates"]
    assert polls[0]["timeout"] == 5


def test_a_rejected_token_stops_polling_and_the_hub_runs_on(tmp_path: Path) -> None:
    api = FakeBotApi()
    api.fail("getMe", TelegramError("getMe", 401, "Unauthorized", None))

    async def body(run: Run) -> None:
        await run.until(lambda: run.service.state == "failed")

    run = serve(make_config(tmp_path), body, api=api)
    assert run.api.methods() == ["getMe"]
    assert run.hub.status()["telegram"]["last_error"] == "getMe: 401 Unauthorized"


def test_flood_control_on_send_waits_and_retries(tmp_path: Path) -> None:
    api = FakeBotApi()
    api.fail("sendMessage", TelegramError("sendMessage", 429, "Too Many Requests", 7.0))

    async def body(run: Run) -> None:
        run.api.push_message(ME, "hi")
        await run.until(replies_to(run, 1))

    run = serve(make_config(tmp_path), body, api=api)
    assert 7.0 in run.sleeps
    assert run.api.texts() == ["Okay."]


# -- slash commands ----------------------------------------------------------------------------


def test_help_uses_the_shared_wording_and_only_lists_what_works_here(tmp_path: Path) -> None:
    async def body(run: Run) -> None:
        run.api.push_message(ME, "/start")
        run.api.push_message(ME, "/yardım")
        run.api.push_message(ME, "/help@tau_test_bot")
        await run.until(replies_to(run, 3))

    run = serve(make_config(tmp_path), body)
    first, second, third = run.api.texts()
    assert first == second == third
    lines = first.splitlines()
    assert lines[0] == t("chat.help_header", "en")
    assert f"/resume [n|id] — {t('command.resume', 'en')}" in lines
    assert f"/new — {t('command.new', 'en')}" in lines
    assert not any(line.startswith(("/quit", "/clear", "/settings")) for line in lines)
    assert "yardım" not in first  # aliases are accepted, never shown


def test_the_command_menu_is_set_for_allowed_chats_only_and_follows_lang(tmp_path: Path) -> None:
    async def body(run: Run) -> None:
        await run.until(lambda: run.api.menu(ME) is not None)
        run.api.push_message(ME, "/lang tr")
        await run.until(replies_to(run, 1))

    run = serve(make_config(tmp_path), body)
    menus = [p for m, p in run.api.calls if m == "setMyCommands"]
    assert [p["scope"] for p in menus] == [{"type": "chat", "chat_id": ME}] * 2  # never default
    english, turkish = (p["commands"] for p in menus)
    assert [c["command"] for c in english] == [
        "help",
        "tools",
        "sessions",
        "resume",
        "new",
        "session",
        "compact",
        "status",
        "model",
        "lang",
        "guard",
    ]
    assert english[0]["description"] == t("command.help", "en")
    assert turkish[0]["description"] == t("command.help", "tr")
    assert run.api.menu(ME) == turkish


def test_a_failing_command_menu_does_not_stop_the_poller(tmp_path: Path) -> None:
    api = FakeBotApi()
    api.fail("setMyCommands", TelegramError("setMyCommands", 400, "Bad Request", None))

    async def body(run: Run) -> None:
        run.api.push_message(ME, "hi")
        await run.until(replies_to(run, 1))

    run = serve(make_config(tmp_path), body, api=api)
    assert run.api.texts() == ["Okay."]


def test_a_bare_slash_shows_the_help(tmp_path: Path) -> None:
    async def body(run: Run) -> None:
        run.api.push_message(ME, "/")
        await run.until(replies_to(run, 1))

    run = serve(make_config(tmp_path), body)
    assert run.api.texts()[0].splitlines()[0] == t("chat.help_header", "en")


def test_unknown_and_unavailable_commands(tmp_path: Path) -> None:
    async def body(run: Run) -> None:
        run.api.push_message(ME, "/nope")
        run.api.push_message(ME, "/quit")
        run.api.push_message(ME, "/çık")
        await run.until(replies_to(run, 3))

    run = serve(make_config(tmp_path), body)
    unknown, quit_, quit_alias = run.api.texts()
    assert unknown == (
        "Unknown command: /nope. Commands: /help, /tools, /sessions, /resume, /new, /session, "
        "/compact, /status, /model, /lang, /guard"
    )  # only what works on Telegram
    assert quit_ == quit_alias == t("telegram.unavailable", "en", command="quit")


def test_new_sessions_resume_and_lang(tmp_path: Path) -> None:
    config = make_config(tmp_path, replies=["first reply"])
    ids: dict[str, str | None] = {}

    async def body(run: Run) -> None:
        run.api.push_message(ME, "hello")
        await run.until(replies_to(run, 1))
        ids["first"] = run.service._chats[ME].session_id
        run.api.push_message(ME, "/new")
        await run.until(replies_to(run, 2))
        ids["second"] = run.service._chats[ME].session_id
        chats = json.loads((config.data_dir / "telegram" / "chats.json").read_text())
        assert chats == {str(ME): ids["second"]}
        run.api.push_message(ME, "/sessions")
        run.api.push_message(ME, "/devam 1")
        run.api.push_message(ME, "/lang tr")
        run.api.push_message(ME, "/session")
        await run.until(replies_to(run, 6))

    run = serve(config, body)
    first, second = ids["first"], ids["second"]
    assert first and second and first != second
    assert run.service._chats[ME].session_id == first
    reply, new, listing, resumed, lang, info = run.api.texts()
    assert new == t("session.new", "en", session=second)
    assert listing.splitlines()[0] == t("session.recent_header", "en")
    assert listing.splitlines()[1].startswith(f"1. {first}  ") and "  telegram  hello" in listing
    assert resumed == t("session.resumed", "en", title="hello", session=first, n=2)
    assert lang == t("lang.switched", "tr", language="tr")
    assert info.splitlines()[0] == t("session.info.id", "tr", session=first)


def test_status_and_model_commands(tmp_path: Path) -> None:
    async def body(run: Run) -> None:
        run.api.push_message(ME, "/status")
        run.api.push_message(ME, "/model")
        run.api.push_message(ME, "/model fast")
        run.api.push_message(ME, "/model nope")
        await run.until(replies_to(run, 4), timeout=10)

    run = serve(make_config(tmp_path), body)
    status, roles, switched, unknown = run.api.texts()
    assert "home" in status  # the profile line
    assert "brain" in roles and "fast" in roles
    assert switched == t("model.current", "en", role="fast", provider="fake")
    assert unknown == t("model.unknown", "en", role="nope", roles="brain, fast, local")
    assert run.service._chats[ME].role == "fast"


def test_compact_moves_the_chat_to_the_summary_session(tmp_path: Path) -> None:
    config = make_config(tmp_path, replies=["hi there", "Summary: said hi."])

    async def body(run: Run) -> None:
        run.api.push_message(ME, "hi")
        await run.until(replies_to(run, 1))
        run.api.push_message(ME, "/compact")
        await run.until(replies_to(run, 2))

    run = serve(config, body)
    before = run.api.texts()[1]
    assert "Summary: said hi." in before
    chats = json.loads((config.data_dir / "telegram" / "chats.json").read_text())
    assert chats[str(ME)] == run.service._chats[ME].session_id


# -- tier 2: approvals with inline buttons ----------------------------------------------------

LAMP = {"tool": "demo_physical_action", "input": {"action": "lamp on"}}
SIMULATED = "Demo action simulated: lamp on. No real device moved."


def lamp_config(tmp_path: Path, **telegram: Any) -> Config:
    config = make_config(tmp_path, replies=[LAMP, "Done."])
    if telegram:
        config = config.with_overrides(component_tables={"telegram": telegram})
    return config


def tool_results(run: Run) -> list[str]:
    agent = run.service._chats[ME].agent
    assert agent is not None
    return [
        block["toolResult"]["content"][0]["text"]
        for message in agent.messages
        for block in message["content"]
        if "toolResult" in block
    ]


def approval_events(run: Run) -> list[dict[str, Any]]:
    assert run.service.store is not None
    session_id = run.service._chats[ME].session_id
    assert session_id is not None
    return [e.data for e in run.service.store.read_events(session_id) if e.kind == "approval"]


async def wait_for_buttons(run: Run) -> None:
    await run.until(lambda: bool(run.api.buttons(ME)) and bool(run.service.approvals))


def test_a_tier2_call_shows_buttons_with_tool_arguments_and_effect(tmp_path: Path) -> None:
    async def body(run: Run) -> None:
        run.api.push_message(ME, "turn on the lamp")
        await wait_for_buttons(run)
        run.api.press(ME, 0)
        await run.until(lambda: "Done." in run.api.texts())

    run = serve(lamp_config(tmp_path), body)
    ask = next(p for p in run.api.sent if p.get("reply_markup"))
    assert ask["text"].splitlines() == [
        f"⚠️ {t('approval.title', 'en', tier=2)}",
        "Tool: demo_physical_action",
        'Arguments: {"action": "lamp on"}',
        "Effect: Demo: simulates a physical action; no real device moves.",
    ]
    assert [b["text"] for b in run.api.buttons(ME)] == ["Approve", "Reject"]
    assert all(b["callback_data"].startswith("ap:") for b in run.api.buttons(ME))


def test_approve_runs_the_tool_once_and_edits_the_message(tmp_path: Path) -> None:
    async def body(run: Run) -> None:
        run.api.push_message(ME, "turn on the lamp")
        await wait_for_buttons(run)
        run.api.press(ME, 0)
        run.api.press(ME, 0)  # a second press finds nothing pending
        await run.until(lambda: "Done." in run.api.texts() and len(run.api.answers) == 2)

    run = serve(lamp_config(tmp_path), body)
    assert tool_results(run) == [SIMULATED]
    [edit] = run.api.edits
    ask = next(p for p in run.api.sent if p.get("reply_markup"))
    assert edit["message_id"] == ask["message_id"]
    assert edit["text"].endswith("\n\n✓ Approved.")
    assert edit["reply_markup"] == {"inline_keyboard": []}
    assert [a.get("text") for a in run.api.answers] == [
        "✓ Approved.",
        t("telegram.approval.expired", "en"),
    ]
    [event] = approval_events(run)
    assert event["decision"] == "approved" and event["channel"] == "telegram"
    assert run.service.approvals == {}


def test_reject_returns_the_refusal_and_edits_the_message(tmp_path: Path) -> None:
    async def body(run: Run) -> None:
        run.api.push_message(ME, "turn on the lamp")
        await wait_for_buttons(run)
        run.api.press(ME, 1)
        await run.until(lambda: "Done." in run.api.texts())

    run = serve(lamp_config(tmp_path), body)
    [result] = tool_results(run)
    assert result.startswith("The user did not approve this action: demo_physical_action.")
    assert run.api.edits[0]["text"].endswith("✗ Rejected.")
    assert f"✗ {t('tool.rejected', 'en', tool='demo_physical_action')}" in run.api.texts()
    assert [e["decision"] for e in approval_events(run)] == ["rejected"]


def test_no_answer_times_out_as_not_approved(tmp_path: Path) -> None:
    async def body(run: Run) -> None:
        run.api.push_message(ME, "turn on the lamp")
        await run.until(lambda: "Done." in run.api.texts())

    run = serve(lamp_config(tmp_path, approval_timeout_seconds=0.05), body)
    [result] = tool_results(run)
    assert result.startswith("The user did not approve this action")
    assert run.api.edits[0]["text"].endswith(t("telegram.approval.timeout", "en"))
    assert [e["decision"] for e in approval_events(run)] == ["timeout"]


def test_presses_from_strangers_or_for_other_requests_have_no_effect(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async def body(run: Run) -> None:
        run.api.push_message(ME, "turn on the lamp")
        await wait_for_buttons(run)
        [approve, _] = run.api.buttons(ME)
        message_id = next(p for p in run.api.sent if p.get("reply_markup"))["message_id"]
        run.api.push_callback(ME, approve["callback_data"], message_id=message_id, from_id=STRANGER)
        run.api.push_callback(STRANGER, approve["callback_data"], message_id=message_id)
        run.api.push_callback(ME, approve["callback_data"], message_id=message_id + 99)
        run.api.push_callback(ME, "ap:0000deadbeef:y", message_id=message_id)
        run.api.push_callback(ME, "something-else", message_id=message_id)
        await run.until(lambda: len(run.api.answers) == 5)
        assert run.service.approvals  # still pending: none of those counted
        run.api.press(ME, 1)
        await run.until(lambda: "Done." in run.api.texts())

    with caplog.at_level(logging.INFO, logger="tau_core.channels.telegram"):
        run = serve(lamp_config(tmp_path), body)
    assert [e["decision"] for e in approval_events(run)] == ["rejected"]
    expired = t("telegram.approval.expired", "en")
    assert [a.get("text") for a in run.api.answers[:5]] == [None, None, expired, expired, expired]
    assert f"ignored a button press from user {STRANGER}" in caplog.text
    assert "unknown or expired request" in caplog.text


def test_the_poller_keeps_polling_while_an_approval_waits_and_queues_messages(
    tmp_path: Path,
) -> None:
    config = make_config(tmp_path, replies=[LAMP, "Done.", "Second reply."])

    async def body(run: Run) -> None:
        run.api.push_message(ME, "turn on the lamp")
        await wait_for_buttons(run)
        run.api.push_message(ME, "and another thing")  # queued behind the waiting turn
        await run.until(lambda: run.service.offset == 3)  # the poller took it meanwhile
        assert run.api.texts()[-1] != "Second reply."
        run.api.press(ME, 0)
        await run.until(lambda: "Second reply." in run.api.texts())

    run = serve(config, body)
    texts = run.api.texts()
    assert texts.index("Done.") < texts.index("Second reply.")


def test_a_stop_while_waiting_closes_the_approval_and_the_message_runs_again(
    tmp_path: Path,
) -> None:
    config = lamp_config(tmp_path)

    async def first(run: Run) -> None:
        run.api.push_message(ME, "turn on the lamp")
        await wait_for_buttons(run)

    run = serve(config, first)
    assert run.api.edits[-1]["text"].endswith(t("telegram.approval.cancelled", "en"))
    inflight = json.loads((config.data_dir / "telegram" / "inflight.json").read_text())
    assert [u["message"]["text"] for u in inflight] == ["turn on the lamp"]

    async def second(run: Run) -> None:  # Telegram has nothing new; the message runs again
        await wait_for_buttons(run)
        run.api.press(ME, 0)
        await run.until(lambda: "Done." in run.api.texts())

    run = serve(config, second)
    assert SIMULATED in tool_results(run)
    assert json.loads((config.data_dir / "telegram" / "inflight.json").read_text()) == []


def test_an_approval_that_cannot_be_sent_is_refused(tmp_path: Path) -> None:
    api = FakeBotApi()

    async def body(run: Run) -> None:
        run.api.fail(
            "sendMessage", TelegramError("sendMessage", 400, "Bad Request: chat not found", None)
        )
        run.api.push_message(ME, "turn on the lamp")
        await run.until(lambda: "Done." in run.api.texts())

    run = serve(lamp_config(tmp_path), body, api=api)
    [result] = tool_results(run)
    assert result.startswith("The user did not approve this action")
    assert [e["decision"] for e in approval_events(run)] == ["rejected"]


# -- tau doctor ------------------------------------------------------------------------------


def test_doctor_check_reports_configuration_and_poller_state(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    assert doctor_check(config, {}, None).status == "info"
    assert doctor_check(config, {"TELEGRAM_BOT_TOKEN": "1:x"}, None).status == "warn"
    configured = doctor_check(config, ENV, None)
    assert configured.status == "ok" and "1 allowed chat" in configured.detail
    polling = {
        "telegram": {"configured": True, "state": "polling", "bot": "@b", "last_poll_at": "t"}
    }
    assert doctor_check(config, ENV, polling).detail.startswith("polling as @b")
    retrying = {"telegram": {"state": "retrying", "retry_in_s": 4.0, "last_error": "down"}}
    assert doctor_check(config, ENV, retrying).status == "warn"
    failed = {"telegram": {"state": "failed", "last_error": "getMe: 401 Unauthorized"}}
    assert doctor_check(config, ENV, failed).status == "fail"
    assert doctor_check(config, ENV, {"pid": 1}).status == "warn"  # a hub without the poller
    assert "123:test-token" not in configured.detail


# -- /guard (issue 113) ----------------------------------------------------------------------


class InHubGuard(FakeGuard):
    """``FakeGuard`` as the hub's ``guard`` service (``hub.find_service("guard")``)."""

    name = "guard"


class DeafGuard(InHubGuard):
    """A lock that never reaches the state (``HubGuard`` only logs that)."""

    async def lock(self, *, channel: str, client_id: str, trigger: str = "command") -> None:
        self.calls.append(("lock", trigger))


def with_guard(run: Run, guard: FakeGuard | None) -> None:
    run.hub.find_service = lambda name: guard if name == "guard" else None  # type: ignore[method-assign]


def test_guard_without_a_guard_service_says_off_or_no_service(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    async def body(run: Run) -> None:
        run.api.push_message(ME, "/guard")
        run.api.push_message(ME, "/guard lock")
        run.api.push_message(ME, "/koruma unlock")
        await run.until(replies_to(run, 3))
        marker = config.data_dir / ENROLLED_MARKER
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text('{"v": 1, "enrollment": "E1"}', encoding="utf-8")
        run.api.push_message(ME, "/guard")
        await run.until(replies_to(run, 4))

    run = serve(config, body)
    assert run.api.texts() == [t("guard.cmd.off", "en")] * 3 + [t("guard.cmd.no_service", "en")]


def test_guard_shows_the_state_of_the_in_hub_guard(tmp_path: Path) -> None:
    guard = InHubGuard("locked")
    guard.set_state("locked", trigger="idle")

    async def body(run: Run) -> None:
        with_guard(run, guard)
        run.api.push_message(ME, "/guard")
        run.api.push_message(ME, "/lang tr")
        run.api.push_message(ME, "/guard")
        run.api.push_message(ME, "/guard nope")
        await run.until(replies_to(run, 4))

    run = serve(make_config(tmp_path), body)
    english, _, turkish, usage_ = run.api.texts()
    assert english == "Guard: locked · locked after inactivity"
    assert turkish == "Koruma: kilitli · hareketsizlik nedeniyle kilitlendi"
    assert usage_ == t("guard.cmd.usage", "tr")


def test_guard_lock_is_the_remote_kill_switch_and_unlock_stays_at_the_mac(tmp_path: Path) -> None:
    guard = InHubGuard("unlocked")

    async def body(run: Run) -> None:
        with_guard(run, guard)
        run.api.push_message(ME, "/guard lock")
        run.api.push_message(ME, "/guard unlock")
        run.api.push_message(ME, "/guard")
        await run.until(replies_to(run, 3))

    run = serve(make_config(tmp_path), body)
    locked, unlock, state = run.api.texts()
    assert locked == t("guard.cmd.lock_done", "en")
    assert unlock == t("guard.cmd.unlock_at_mac", "en")
    assert state == "Guard: locked · locked from Telegram"
    assert ("lock", "telegram") in guard.calls
    assert not any(name == "unlock" for name, _ in guard.calls)  # never unlocked from here
    assert guard.state == "locked" and guard.lock_trigger == "telegram"


def test_a_lock_that_did_not_take_is_reported(tmp_path: Path) -> None:
    guard = DeafGuard("unlocked")

    async def body(run: Run) -> None:
        with_guard(run, guard)
        run.api.push_message(ME, "/guard lock")
        await run.until(replies_to(run, 1))

    run = serve(make_config(tmp_path), body)
    assert run.api.texts() == [t("guard.cmd.lock_failed", "en")]
    assert ("lock", "telegram") in guard.calls


def test_telegram_turns_keep_running_while_the_guard_is_locked(tmp_path: Path) -> None:
    guard = InHubGuard("locked")

    async def body(run: Run) -> None:
        with_guard(run, guard)
        run.api.push_message(ME, "hello")
        await run.until(replies_to(run, 1))

    run = serve(make_config(tmp_path), body)
    assert run.api.texts() == ["Okay."]
    assert run.service._chats[ME].agent.guard is None  # identified channel: no guard on turns
    assert not any(name == "admit" for name, _ in guard.calls)
