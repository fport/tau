"""The settings screen, the first-run setup screen and the no-credentials start (issue 083).

Offline: the fake provider, a registered ``needy`` provider that returns a ``FakeModel`` once
its variable is set, and a temp home. No credential value here is real, and the tests assert
that none of them ever reaches a widget text, a notice, a screenshot or the log.
"""

from __future__ import annotations

import html
import logging
import os
import re
import stat
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from helpers import SESSION_ID, finish, fixed_clock, make_app, send, steady, wait_until
from tau_core import Config, MemorySessionStore, Tier, registry, t, tau_tool
from tau_core.builder import Check
from tau_core.settings import set_credential
from tau_core.testing import FakeModel, ToolCall, test_config
from tau_tui import SettingsScreen, SetupResult, build_app
from tau_tui.settings import SECTIONS
from tau_tui.setup import SetupApp, SetupScreen, provider_labels
from tau_tui.transcript import NoticeRow, WelcomeCard
from textual.widgets import Input, Select, Static
from textual.widgets.select import InvalidSelectValueError

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
PLANNED_TOML = """\
[models.roles.brain]
provider = "futurebox"
model_id = "f"

[models.roles.fast]
provider = "fake"
model_id = "fake-fast"

[sessions]
backend = "memory"
"""
HUB_DOWN = Check("hub", "info", "hub is not running (nothing answers on http://127.0.0.1/health)")
ROW_LABELS = {
    "roles": ("provider", "model_id", "max_tokens", "fallback", "fallback_model"),
    "credentials": (),
    "interface": ("language", "profile"),
    "agent": ("context", "window_size", "max_turns", "max_total_tokens"),
    "doctor": (),
    "files": (),
}
"""The ``tui.settings.*`` keys of the row labels each section shows."""


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


def rendered(app) -> str:
    """What is on screen: every text run of the exported SVG, whitespace normalised (a
    widget's ``content`` says what it holds, this says what the terminal shows of it)."""
    runs = re.findall(r"<text[^>]*>(.*?)</text>", app.export_screenshot())
    text = html.unescape(" ".join(runs)).replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", text)


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


async def test_long_status_errors_wrap_at_phone_width(tmp_path: Path) -> None:
    """A 75-character validation error is fully visible at 50 columns: the status line grows
    to three rows instead of clipping the reason (M2)."""
    app = make_app(tmp_path, [])
    async with app.run_test(size=(50, 24)) as pilot:
        screen = await open_settings(pilot)
        screen.query_one("#window_size", Input).value = "0"
        await pilot.press("ctrl+s")
        await pilot.pause()
        message = "Not saved: tau.toml: [agent] 'window_size' must be an integer of 1 or more."
        assert len(message) == 75
        status = screen.query_one("#status", Static)
        assert status.content.plain == message
        assert 2 <= status.region.height <= 3  # wrapped, not clipped
        assert "of 1 or more." in rendered(app)  # the tail is on screen
        assert isinstance(app.screen, SettingsScreen)


async def test_profile_override_survives_a_rebuild_and_the_header_follows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``tau tui --profile travel`` stays ``travel`` after a settings save rebuilt the agent
    (the override is passed through ``build_app``); without an override the header shows the
    profile a save wrote to ``.env`` (m4)."""
    monkeypatch.delenv("TAU_PROFILE", raising=False)
    app = make_app(tmp_path, [], profile="travel")
    async with app.run_test(size=(80, 24)) as pilot:
        await steady(pilot)
        assert app.config.profile == "travel" and "tau  travel · " in app.header.text
        screen = await open_settings(pilot)
        assert screen.query_one("#profile", Input).value == "travel"
        screen.query_one("#model-brain", Input).value = "fake-brain-2"
        old = app.agent
        await pilot.press("ctrl+s")
        await wait_until(pilot, lambda: app.agent is not old)
        await pilot.pause()
        assert app.config.roles["brain"].model_id == "fake-brain-2"
        assert app.config.profile == "travel" and "tau  travel · " in app.header.text
        assert notices(app)[-1] == "▸ Settings saved; model reloaded."

    app = make_app(tmp_path, [])  # no override: the saved profile wins and the header follows
    async with app.run_test(size=(80, 24)) as pilot:
        await steady(pilot)
        assert "tau  home · " in app.header.text
        screen = await open_settings(pilot)
        screen.query_one("#profile", Input).value = "sport"
        old = app.agent
        await pilot.press("ctrl+s")
        await wait_until(pilot, lambda: app.agent is not old)
        await pilot.pause()
        assert app.config.profile == "sport" and "tau  sport · " in app.header.text
        assert (app.config.home / ".env").read_text(encoding="utf-8") == "TAU_PROFILE=sport\n"


async def test_planned_provider_is_not_offered_and_a_stored_one_recovers_in_the_ui(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A planned provider is not in the provider select, only in a note; a stored config that
    already puts ``brain`` on it opens the app without an agent on Model roles instead of
    exiting 2, and a save on an available provider builds the agent (M1)."""
    import tau_core.models as models

    monkeypatch.setitem(models.PLANNED_PROVIDERS, "futurebox", "999")
    config = test_config(tmp_path)
    home = config.home
    (home / "tau.toml").write_text(PLANNED_TOML, encoding="utf-8")
    config = Config.load(home, env={"TAU_DATA_DIR": str(tmp_path / "data")})
    app = build_app(
        config, tools=[], session_id=SESSION_ID, clock=fixed_clock, motion=False, show_paths=False
    )
    assert app.agent is None and app.missing_credentials is None
    assert app.unsupported_provider is not None
    assert app.unsupported_provider.provider == "futurebox"
    async with app.run_test(size=(80, 24), notifications=True) as pilot:
        await wait_until(pilot, lambda: isinstance(app.screen, SettingsScreen))
        await pilot.pause()
        screen = app.screen
        assert screen.current == "roles"
        brain = screen.query_one("#provider-brain", Select)
        assert brain.value == "futurebox"  # the stored value stays, labelled as planned
        assert "futurebox (planned)" in rendered(app)
        with pytest.raises(InvalidSelectValueError):
            screen.query_one("#provider-fast", Select).value = "futurebox"  # never offered
        with pytest.raises(InvalidSelectValueError):
            screen.query_one("#fbprovider-fast", Select).value = "futurebox"
        assert "planned, not selectable yet: futurebox (issue 999)" in screen.text
        await pilot.press("escape")
        await pilot.pause()
        assert app.composer.state == "disabled"
        assert app.composer.prompt.placeholder == "Choose an available provider in /settings"
        said = "\n".join(notices(app))
        assert "Provider 'futurebox' is not supported yet (issue 999)." in said
        assert "Choose an available provider in /settings" in said
        assert app.header.text == "τ tau  home · —  brain · en"
        await send(pilot, "hello")
        await pilot.pause()
        assert app.composer.text == "hello"  # kept, with a toast
        assert any("available provider" in str(n.message) for n in app._notifications)
        app.composer.clear()

        screen = await open_settings(pilot)
        assert screen.current == "roles"
        screen.query_one("#provider-brain", Select).value = "fake"
        screen.query_one("#model-brain", Input).value = "fake-brain"
        await pilot.press("ctrl+s")
        await wait_until(pilot, lambda: app.agent is not None)
        await pilot.pause()
        assert app.agent.session_id == SESSION_ID and app.agent.role == "brain"
        assert app.composer.state == "idle" and app.query(WelcomeCard)
        assert app.unsupported_provider is None
        assert notices(app)[-1] == "▸ Settings saved; model reloaded."
        assert Config.load(home, env={}).roles["brain"].provider == "fake"
        await send(pilot, "hello")
        await finish(pilot)
        assert "Okay." in app.transcript.text  # the fake provider's default reply


@pytest.mark.parametrize("language", ["tr", "en"])
async def test_labels_fit_at_phone_width(tmp_path: Path, language: str) -> None:
    """At 50 columns every section and row label is shown in full in both languages: the
    section list is as wide as its longest label and the label column fits the longest row
    label (m8)."""
    app = make_app(tmp_path, [])
    async with app.run_test(size=(50, 24)) as pilot:
        app.language = language
        screen = await open_settings(pilot)
        assert screen.has_class("-phone")
        sections = [t(f"tui.settings.section.{name}", language) for name in SECTIONS]
        longest = max(len(label) for label in sections)
        assert longest <= screen.sections.content_region.width <= 18
        for name in SECTIONS:
            screen.show_section(name)
            await pilot.pause()
            if name == "doctor":
                summary = "kontrol:" if language == "tr" else "checks:"
                await wait_until(pilot, lambda done=summary: done in screen.text)
                await pilot.pause()
            labels = [t(f"tui.settings.{key}", language) for key in ROW_LABELS[name]]
            for widget in screen.query(f"#sec-{name} .label"):
                text = widget.content.plain
                assert len(text) <= widget.content_region.width, (name, text)
            shown = rendered(app)
            for label in sections + labels:
                assert label in shown, (name, label)


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


async def test_credential_from_the_shell_is_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``Config.load`` never lets ``.env`` override a variable the shell already set, so the
    row says so; once ``.env`` holds the same value there is nothing to warn about (m5)."""
    shell_value = "shell-only-not-a-real-key-000000"
    monkeypatch.setenv("ANTHROPIC_API_KEY", shell_value)
    app = make_app(tmp_path, [])
    home = app.config.home
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await open_settings(pilot, "/settings credentials")
        state = screen.query_one("#credstate-ANTHROPIC_API_KEY", Static).content.plain
        assert state == "set · she…0000 (from the environment; .env does not override it)"
        assert shell_value not in screen.text and shell_value not in app.export_screenshot()
        await pilot.press("escape")
        await pilot.pause()
        set_credential(home, "ANTHROPIC_API_KEY", shell_value)  # the file agrees
        screen = await open_settings(pilot, "/settings credentials")
        state = screen.query_one("#credstate-ANTHROPIC_API_KEY", Static).content.plain
        assert state == "set · she…0000"


async def test_typed_credential_is_stripped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pasted key with surrounding whitespace is stored without it; a blank field is not a
    value (m6)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    app = make_app(tmp_path, [])
    home = app.config.home
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await open_settings(pilot, "/settings credentials")
        screen.query_one("#cred-ANTHROPIC_API_KEY", Input).value = f"  {SECRET}  "
        screen.query_one("#cred-AWS_REGION", Input).value = "   "
        await pilot.press("ctrl+s")
        await wait_until(pilot, lambda: not isinstance(app.screen, SettingsScreen))
        await pilot.pause()
        assert (home / ".env").read_text(encoding="utf-8") == f"ANTHROPIC_API_KEY='{SECRET}'\n"
        assert os.environ["ANTHROPIC_API_KEY"] == SECRET and "AWS_REGION" not in os.environ


async def test_secret_inputs_are_hidden_and_plain_settings_are_not(tmp_path: Path) -> None:
    """Keys, tokens, secrets, passwords and fingerprints get a password input; ``AWS_REGION``
    and the ``TAU_*`` settings a normal one (nit)."""
    app = make_app(tmp_path, [])
    (app.config.home / ".env.example").write_text(
        "# AWS_REGION=eu-central-1\n# TAU_PROFILE=home\n# TELEGRAM_BOT_TOKEN=...\n",
        encoding="utf-8",
    )
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await open_settings(pilot, "/settings credentials")
        key = screen.query_one("#cred-ANTHROPIC_API_KEY", Input)
        assert key.password and key.placeholder == "new value (hidden)"
        assert screen.query_one("#cred-AWS_BEARER_TOKEN_BEDROCK", Input).password
        assert screen.query_one("#cred-AWS_SECRET_ACCESS_KEY", Input).password
        assert screen.query_one("#cred-TELEGRAM_BOT_TOKEN", Input).password
        region = screen.query_one("#cred-AWS_REGION", Input)
        assert not region.password and region.placeholder == "new value"
        assert not screen.query_one("#cred-AWS_PROFILE", Input).password
        assert not screen.query_one("#cred-TAU_PROFILE", Input).password


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
    """The default home is a ``Path`` under the test's temp directory: the provider detection
    reads its (absent) ``.env``, never the developer's ``~/.tau/.env``."""
    fresh = tmp_path / "fresh"
    app = SetupApp(default_home=fresh, env={}, language="en")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SetupScreen)
        assert isinstance(app.focused, Input) and app.focused.id == "home"
        assert app.focused.value == str(fresh)
        assert screen.query_one("#provider", Select).value == "fake"  # nothing detected
        assert "fake · no credentials needed" in screen.text
        assert "Welcome to tau · first run" in screen.text
        screen.query_one("#language", Select).value = "tr"
        await pilot.pause()
        assert "tau'ya hoş geldiniz" in screen.text and screen.language == "tr"
        assert screen.query_one("#provider", Select).value == "fake"
        await pilot.press("enter")
        await pilot.pause()
    result = app.return_value
    assert isinstance(result, SetupResult)
    assert result == SetupResult(fresh.resolve(), "fake", "tr", created=True)
    config = Config.load(result.home, env={})
    assert config.roles["brain"].provider == "fake" and config.ui.language == "tr"
    assert (result.home / "persona" / "user.md").is_file()


async def test_setup_screen_hides_the_path_for_snapshots(tmp_path: Path) -> None:
    """``show_paths=False`` shows the canonical ``~/.tau`` in the home field while the
    detection still reads the given home, so a snapshot carries no machine path."""
    app = SetupApp(default_home=tmp_path / "fresh", env={}, language="en", show_paths=False)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.screen.query_one("#home", Input).value == "~/.tau"
        assert str(tmp_path) not in app.export_screenshot()
        await pilot.press("escape")
        await pilot.pause()
    assert app.return_value is None


async def test_the_suite_never_sees_the_real_home_directory(tmp_path: Path) -> None:
    """The conftest guard: ``HOME`` is a temp directory, so ``~`` and ``Path.home()`` cannot
    reach the developer's ``~/.tau``."""
    home = Path(os.environ["HOME"])
    assert home == Path.home() == Path("~").expanduser()
    assert home.parent == tmp_path.parent  # a sibling under pytest's base temp
    assert not (home / ".tau").exists()


async def test_setup_screen_detects_credentials_and_reuses_a_home(tmp_path: Path) -> None:
    existing = test_config(tmp_path).home
    app = SetupApp(default_home=str(existing), env={"ANTHROPIC_API_KEY": "k"}, language="en")
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert screen.query_one("#provider", Select).value == "anthropic"
        assert "anthropic · credentials found" in screen.text
        assert provider_labels({"ANTHROPIC_API_KEY": "k"}) == [
            ("proxy · no credentials found", "proxy"),
            ("anthropic · credentials found", "anthropic"),
            ("bedrock · no credentials found", "bedrock"),
            ("fake · no credentials needed", "fake"),
        ]
        assert provider_labels({"TAU_PROXY_KEY_BRAIN": "sk-x"})[0] == (
            "proxy · credentials found",
            "proxy",
        )
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
