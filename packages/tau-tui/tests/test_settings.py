"""The settings screen, the first-run setup screen and the no-credentials start (issue 081).

Offline: the fake provider, a registered ``needy`` provider that returns a ``FakeModel`` once
its variable is set, and a temp home. No credential value here is real, and the tests assert
that none of them ever reaches a widget text, a notice, a screenshot or the log.
"""

from __future__ import annotations

import logging
import os
import stat
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from helpers import SESSION_ID, finish, fixed_clock, make_app, send, steady, wait_until
from tau_core import Config, MemorySessionStore, Tier, registry, tau_tool
from tau_core.builder import Check
from tau_core.testing import FakeModel, ToolCall, test_config
from tau_tui import SettingsScreen, SetupResult, build_app
from tau_tui.settings import SECTIONS
from tau_tui.setup import SetupApp, SetupScreen, provider_labels
from tau_tui.transcript import NoticeRow, WelcomeCard
from textual.widgets import Input, Select, Static

SECRET = "sk-test-not-a-real-key-0000abcd"
NEEDY_TOML = """\
[models.roles.brain]
provider = "needy"
model_id = "needy-brain"

[models.roles.fast]
provider = "fake"
model_id = "fake-fast"

[sessions]
backend = "memory"
"""
HUB_DOWN = Check("hub", "info", "hub is not running (nothing answers on http://127.0.0.1/health)")


@pytest.fixture(autouse=True)
def _no_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tau_core.builder._check_hub", lambda config: HUB_DOWN)


@pytest.fixture
def needy_provider(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A provider that needs ``NEEDY_KEY`` and then answers with a scripted model."""
    monkeypatch.delenv("NEEDY_KEY", raising=False)
    registry.reset()
    registry.register_provider(
        "needy", lambda role_cfg, env: FakeModel(["Now I can answer."]), [["NEEDY_KEY"]]
    )
    yield
    registry.reset()


def notices(app) -> list[str]:
    return [row.content.plain for row in app.transcript.query(NoticeRow)]


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


async def open_settings(pilot, command: str = "/settings") -> SettingsScreen:
    app = pilot.app
    await steady(pilot)
    await send(pilot, command)
    await wait_until(pilot, lambda: isinstance(app.screen, SettingsScreen))
    await pilot.pause()
    return app.screen


# -- opening, sections, closing ------------------------------------------------------------------


async def test_settings_opens_switches_sections_and_closes(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await open_settings(pilot)
        assert screen.current == "roles" and app.focused is screen.sections
        assert "brain" in screen.text and "✓ no credentials needed" in screen.text
        await pilot.press("down")
        await pilot.pause()
        assert screen.current == "credentials"
        assert "ANTHROPIC_API_KEY" in screen.text and "AWS_REGION" in screen.text
        await pilot.press("down", "down")
        await pilot.pause()
        assert screen.current == "agent"
        await pilot.press("tab")
        await pilot.pause()
        assert isinstance(app.focused, Select) and app.focused.id == "context"
        await pilot.press("tab")
        assert isinstance(app.focused, Input) and app.focused.id == "window_size"
        await pilot.press("shift+tab", "shift+tab")
        assert app.focused is screen.sections
        await pilot.press("down")
        await wait_until(pilot, lambda: "checks:" in screen.text)
        assert screen.current == "doctor" and "role brain: provider 'fake'" in screen.text
        await pilot.press("down")
        await pilot.pause()
        assert screen.current == "files" and "tau.toml" in screen.text
        assert "Edit the persona files in any editor" in screen.text
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsScreen)
        assert notices(app) == []  # nothing saved, nothing said
        await send(pilot, "/ayarlar credentials")
        await wait_until(pilot, lambda: isinstance(app.screen, SettingsScreen))
        assert app.screen.current == "credentials"
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("f10")
        await wait_until(pilot, lambda: isinstance(app.screen, SettingsScreen))
        await pilot.press("f2")  # saves and closes; the app's F2 (picker) stays out of the way
        await pilot.pause()
        assert not isinstance(app.screen, SettingsScreen)
        assert notices(app) == ["▸ Settings saved."]


async def test_settings_is_refused_while_busy(tmp_path: Path) -> None:
    release = threading.Event()

    @tau_tool(tier=Tier.READ)
    def slow() -> str:
        """Blocks until the test releases it."""
        release.wait(5)
        return "x"

    app = make_app(tmp_path, [[ToolCall("slow", {})], "ok"], tools=[slow])
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        await send(pilot, "go")
        await wait_until(pilot, lambda: app.busy)
        await send(pilot, "/settings")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsScreen)
        assert any("before opening the settings" in str(n.message) for n in app._notifications)
        release.set()
        await finish(pilot)


async def test_sections_are_all_listed() -> None:
    assert SECTIONS == ("roles", "credentials", "interface", "agent", "doctor", "files")


# -- saving --------------------------------------------------------------------------------------


async def test_saving_the_language_relabels_the_app(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    home = app.config.home
    (home / "tau.toml").write_text(
        (home / "tau.toml")
        .read_text(encoding="utf-8")
        .replace('language = "en"', 'language = "en"   # chrome language'),
        encoding="utf-8",
    )
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await open_settings(pilot)
        screen.query_one("#language", Select).value = "tr"
        agent = app.agent
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert app.language == "tr"
        assert app.hint.text.startswith("? kısayollar")
        assert app.agent is agent  # a language change rebuilds nothing
        assert notices(app) == ["▸ Ayarlar kaydedildi."]
        text = (home / "tau.toml").read_text(encoding="utf-8")
        assert 'language = "tr"   # chrome language' in text  # tomlkit kept the comment
        assert Config.load(home, env={}).ui.language == "tr"


async def test_saving_a_model_change_rebuilds_on_the_same_session(tmp_path: Path) -> None:
    app = make_app(tmp_path, ["Merhaba."], session_store=MemorySessionStore())
    calls: list[dict] = []
    factory = app.agent_factory

    def spy(target, **kwargs):
        calls.append({"target": target, **kwargs})
        return factory(target, **kwargs)

    app.agent_factory = spy
    async with app.run_test(size=(80, 24)) as pilot:
        await send(pilot, "Merhaba tau")
        await finish(pilot)
        old = app.agent
        screen = await open_settings(pilot)
        screen.query_one("#model-brain", Input).value = "fake-brain-2"
        screen.query_one("#tokens-brain", Input).value = "512"
        await pilot.press("ctrl+s")
        await wait_until(pilot, lambda: app.agent is not old)
        await pilot.pause()
        assert len(calls) == 1
        assert calls[0]["target"] == SESSION_ID and calls[0]["role"] == "brain"
        assert calls[0]["config"].roles["brain"].model_id == "fake-brain-2"
        assert calls[0]["config"].roles["brain"].max_tokens == 512
        assert app.agent.session_id == SESSION_ID and len(app.agent.messages) == 2
        assert app.config.roles["brain"].model_id == "fake-brain-2"
        assert notices(app)[-1] == "▸ Settings saved; model reloaded."
        assert "Merhaba." in app.transcript.text  # the transcript stays
        assert Config.load(app.config.home, env={}).roles["brain"].max_tokens == 512


async def test_invalid_values_stay_in_the_dialog(tmp_path: Path) -> None:
    app = make_app(tmp_path, [])
    before = (app.config.home / "tau.toml").read_text(encoding="utf-8")
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await open_settings(pilot)
        screen.query_one("#window_size", Input).value = "0"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)
        status = screen.query_one("#status", Static).content.plain
        assert (
            status == "Not saved: tau.toml: [agent] 'window_size' must be an integer of 1 or more."
        )
        screen.query_one("#window_size", Input).value = "40"
        screen.query_one("#fbprovider-fast", Select).value = "fake"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert screen.query_one("#status", Static).content.plain == (
            "Not saved: fast: the fallback needs a model id"
        )
        assert (app.config.home / "tau.toml").read_text(encoding="utf-8") == before
        screen.query_one("#fbmodel-fast", Input).value = "fake-fb"
        await pilot.press("ctrl+s")
        await wait_until(pilot, lambda: not isinstance(app.screen, SettingsScreen))
        await pilot.pause()
        config = Config.load(app.config.home, env={})
        assert config.agent.window_size == 40
        assert config.roles["fast"].fallback is not None
        assert config.roles["fast"].fallback.model_id == "fake-fb"


# -- credentials ---------------------------------------------------------------------------------


async def test_credential_input_is_masked_and_never_leaks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    caplog.set_level(logging.DEBUG)
    app = make_app(tmp_path, [])
    home = app.config.home
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await open_settings(pilot, "/settings credentials")
        field = screen.query_one("#cred-ANTHROPIC_API_KEY", Input)
        assert field.password is True
        field.focus()
        await pilot.pause()
        for char in "sk-":
            await pilot.press("minus" if char == "-" else char)
        assert field.value == "sk-"
        field.value = SECRET
        await pilot.pause()
        svg = app.export_screenshot()
        assert SECRET not in svg and SECRET not in screen.text
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert not isinstance(app.screen, SettingsScreen)
        assert notices(app)[-1] == "▸ Settings saved; model reloaded."
        dotenv = home / ".env"
        assert mode_of(dotenv) == 0o600
        assert dotenv.read_text(encoding="utf-8") == f"ANTHROPIC_API_KEY='{SECRET}'\n"
        assert os.environ.get("ANTHROPIC_API_KEY") == SECRET  # the process sees it too
        screen = await open_settings(pilot, "/settings credentials")
        state = screen.query_one("#credstate-ANTHROPIC_API_KEY", Static).content.plain
        assert state == "set · sk-…abcd"
        assert SECRET not in screen.text and SECRET not in app.export_screenshot()
        await pilot.press("tab", "tab")  # the input, then its clear button
        await pilot.press("enter")
        await pilot.pause()
        assert screen.query_one("#credstate-ANTHROPIC_API_KEY", Static).content.plain == (
            "will be removed"
        )
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert "ANTHROPIC_API_KEY" not in dotenv.read_text(encoding="utf-8")
        assert "ANTHROPIC_API_KEY" not in os.environ
        assert SECRET not in app.transcript.text
    assert SECRET not in caplog.text
    log = tmp_path / "data" / "logs"
    for path in log.glob("*.log"):
        assert SECRET not in path.read_text(encoding="utf-8")


# -- the no-credentials start ----------------------------------------------------------------------


async def test_missing_credentials_open_the_credentials_section(
    tmp_path: Path, needy_provider: None
) -> None:
    config = test_config(tmp_path)
    home = config.home
    (home / "tau.toml").write_text(NEEDY_TOML, encoding="utf-8")
    config = Config.load(home, env={"TAU_DATA_DIR": str(tmp_path / "data")})
    app = build_app(
        config, tools=[], session_id=SESSION_ID, clock=fixed_clock, motion=False, show_paths=False
    )
    assert app.agent is None and app.missing_credentials is not None
    assert app.missing_credentials.variables == ["NEEDY_KEY"]
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        await wait_until(pilot, lambda: isinstance(app.screen, SettingsScreen))
        await pilot.pause()
        screen = app.screen
        assert screen.current == "credentials"
        head = screen.query_one("#credname-NEEDY_KEY", Static)
        assert head.has_class("-missing") and "◆ needed" in head.content.plain
        assert isinstance(app.focused, Input) and app.focused.id == "cred-NEEDY_KEY"
        assert screen.text.index("NEEDY_KEY") < screen.text.index("ANTHROPIC_API_KEY")
        await pilot.press("escape")
        await pilot.pause()
        assert app.composer.state == "disabled"
        assert app.composer.prompt.placeholder == "Add credentials in /settings"
        assert "Missing model credentials for role 'brain' (needy)." in "\n".join(notices(app))
        assert app.header.text == "τ tau  home · —  brain · en"
        await send(pilot, "hello")
        await pilot.pause()
        assert app.composer.text == "hello"  # kept, with a toast
        assert any("Add credentials in /settings" in str(n.message) for n in app._notifications)
        app.composer.clear()
        await send(pilot, "/tools")
        await pilot.pause()
        assert "Tools" not in app.transcript.text
        await send(pilot, "/help")
        await pilot.pause()
        assert "Commands:" in app.transcript.text

        screen = await open_settings(pilot)
        assert screen.current == "credentials"  # the missing names still steer the section
        assert screen.query_one("#credname-NEEDY_KEY", Static).has_class("-missing")
        screen.query_one("#cred-NEEDY_KEY", Input).value = "needy-secret-value-0000"
        await pilot.press("ctrl+s")
        await wait_until(pilot, lambda: app.agent is not None)
        await pilot.pause()
        assert app.agent.session_id == SESSION_ID and app.agent.role == "brain"
        assert app.composer.state == "idle" and app.query(WelcomeCard)
        assert app.header.text == f"τ tau  home · {SESSION_ID}  brain · en"
        assert notices(app)[-1] == "▸ Settings saved; model reloaded."
        await send(pilot, "hello")
        await finish(pilot)
        assert "Now I can answer." in app.transcript.text
        assert "needy-secret-value-0000" not in app.transcript.text
        assert "needy-secret-value-0000" not in app.export_screenshot()


async def test_fallback_provider_is_announced_at_start(tmp_path: Path) -> None:
    model = FakeModel([])
    model.tau_provider = "anthropic"  # what resolve_model tags a fallback instance with
    model.tau_fallback_of = "bedrock"
    app = make_app(tmp_path, [], model=model)
    async with app.run_test(size=(80, 24)) as pilot:
        await steady(pilot)
        assert notices(app) == [
            "▸ brain: using the fallback provider anthropic (bedrock has no credentials). "
            "Add them in /settings."
        ]
        assert app.header.text.endswith("brain · en")


# -- the setup screen ----------------------------------------------------------------------------


async def test_setup_screen_creates_a_home(tmp_path: Path) -> None:
    app = SetupApp(default_home="~/.tau", env={}, language="en")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SetupScreen)
        assert isinstance(app.focused, Input) and app.focused.id == "home"
        assert screen.query_one("#provider", Select).value == "fake"  # nothing detected
        assert "fake · no credentials needed" in screen.text
        assert "Welcome to tau · first run" in screen.text
        screen.query_one("#language", Select).value = "tr"
        await pilot.pause()
        assert "tau'ya hoş geldiniz" in screen.text and screen.language == "tr"
        assert screen.query_one("#provider", Select).value == "fake"
        screen.query_one("#home", Input).value = str(tmp_path / "fresh")
        await pilot.press("enter")
        await pilot.pause()
    result = app.return_value
    assert isinstance(result, SetupResult)
    assert result == SetupResult((tmp_path / "fresh").resolve(), "fake", "tr", created=True)
    config = Config.load(result.home, env={})
    assert config.roles["brain"].provider == "fake" and config.ui.language == "tr"
    assert (result.home / "persona" / "user.md").is_file()


async def test_setup_screen_detects_credentials_and_reuses_a_home(tmp_path: Path) -> None:
    existing = test_config(tmp_path).home
    app = SetupApp(default_home=str(existing), env={"ANTHROPIC_API_KEY": "k"}, language="en")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert screen.query_one("#provider", Select).value == "anthropic"
        assert "anthropic · credentials found" in screen.text
        assert provider_labels({"ANTHROPIC_API_KEY": "k"}) == [
            ("bedrock · no credentials found", "bedrock"),
            ("anthropic · credentials found", "anthropic"),
            ("fake · no credentials needed", "fake"),
        ]
        await pilot.press("ctrl+s")
        await pilot.pause()
    assert app.return_value == SetupResult(existing, "anthropic", "en", created=False)
    assert Config.load(existing, env={}).roles["brain"].provider == "fake"  # untouched


async def test_setup_screen_refuses_an_empty_home_and_quits_on_escape(tmp_path: Path) -> None:
    app = SetupApp(default_home="", env={}, language="en")
    async with app.run_test(size=(50, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        await pilot.press("f2")
        await pilot.pause()
        assert screen.query_one("#status", Static).content.plain == "Enter a home directory."
        assert isinstance(app.screen, SetupScreen)
        await pilot.press("escape")
        await pilot.pause()
    assert app.return_value is None
