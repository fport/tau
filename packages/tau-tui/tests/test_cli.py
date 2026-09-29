"""``tau tui`` startup: help, the setup and no-credentials starts, exit 2 paths, logging."""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from click.testing import CliRunner
from tau_core import Config, t
from tau_core.builder import init_home
from tau_core.logs import LOG_FILE
from tau_core.testing import FakeModel
from tau_tui import SetupResult, build_app
from tau_tui.cli import tui

UNSET = {
    name: None
    for name in (
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_PROFILE",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_BEARER_TOKEN_BEDROCK",
        "ANTHROPIC_API_KEY",
        "TAU_PROFILE",
        "TAU_ROLE",
        "TAU_HUB_PORT",
        "TAU_LANG",
    )
}

BEDROCK_TOML = """\
[models.roles.brain]
provider = "bedrock"
model_id = "bedrock-model"
"""

FAKE_TOML = """\
[models.roles.brain]
provider = "fake"
model_id = "fake-brain"
"""


def make_home(tmp_path: Path, toml: str) -> Path:
    home = tmp_path / "home"
    (home / "persona").mkdir(parents=True)
    (home / "tau.toml").write_text(toml, encoding="utf-8")
    (home / "persona" / "persona.md").write_text("You are tau.\n", encoding="utf-8")
    return home


def run(args: list[str], home: Path, tmp_path: Path, **env_extra: str):
    env = dict(UNSET, TAU_HOME=str(home), TAU_DATA_DIR=str(tmp_path / "data"), **env_extra)
    return CliRunner().invoke(tui, args, env=env, prog_name="tau tui")


class StubApp:
    """Stands in for ``TauApp``: records that ``run`` happened and what it was built with."""

    instances: list[StubApp] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.ran = False
        self.closed = False
        self.agent = self

    def run(self) -> None:
        self.ran = True
        logging.getLogger("tau_tui.stub").info("ui ran")

    def close(self) -> None:
        self.closed = True


def stub_build_app(config: Config, **kwargs: Any) -> StubApp:
    app = StubApp(config=config, **kwargs)
    StubApp.instances.append(app)
    return app


def test_help_is_english(tmp_path: Path) -> None:
    result = run(["--help"], tmp_path, tmp_path)
    assert result.exit_code == 0
    assert "Open tau in the Textual interface." in result.output
    assert "--resume [ID]" in result.output
    assert "--profile NAME" in result.output
    assert "Show this help and exit." in result.output


def test_broken_config_exits_2(tmp_path: Path) -> None:
    home = make_home(tmp_path, "[agent]\nmax_turns = 0\n")
    result = run([], home, tmp_path)
    assert result.exit_code == 2
    assert "tau.toml: [agent] 'max_turns' must be an integer of 1 or more." in result.output
    assert "Traceback" not in result.output


def test_missing_config_runs_the_setup_screen_then_the_app(tmp_path: Path, monkeypatch) -> None:
    """No ``tau.toml`` anywhere: the setup screen (stubbed here, it is a Textual app of its
    own) creates the home with ``init_home`` and the command continues on it."""
    seen: dict[str, Any] = {}

    def fake_setup(*, default_home: str, language: str, **kw: Any) -> SetupResult:
        seen.update(default_home=default_home, language=language)
        home = tmp_path / "created"
        result = init_home(home, provider="fake", language="tr")
        return SetupResult(result.home, "fake", "tr", created=True)

    monkeypatch.setattr("tau_tui.cli.run_setup", fake_setup)
    monkeypatch.setattr("tau_tui.cli.build_app", stub_build_app)
    StubApp.instances.clear()
    result = run([], tmp_path / "missing", tmp_path, TAU_LANG="tr")
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "Goodbye."
    assert seen == {"default_home": str(tmp_path / "missing"), "language": "tr"}
    (app,) = StubApp.instances
    assert app.ran and app.closed
    assert app.kwargs["config"].home == (tmp_path / "created").resolve()
    assert app.kwargs["config"].ui.language == "tr"
    assert (tmp_path / "data" / "logs" / LOG_FILE).is_file()


def test_setup_cancelled_exits_2(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("tau_tui.cli.run_setup", lambda **kw: None)
    result = run([], tmp_path / "missing", tmp_path)
    assert result.exit_code == 2
    assert "Configuration file not found" in result.output
    assert "Setup cancelled." in result.output


def test_missing_credentials_open_the_app_without_an_agent(tmp_path: Path, monkeypatch) -> None:
    """Credentials missing for the role: no exit 2 any more, the app opens on the settings
    screen (``build_app`` swallows ``MissingCredentials``; the UI itself is stubbed here)."""
    monkeypatch.setattr("tau_tui.cli.build_app", stub_build_app)
    StubApp.instances.clear()
    result = run([], make_home(tmp_path, BEDROCK_TOML), tmp_path)
    assert result.exit_code == 0, result.output
    assert "Missing model credentials" not in result.output
    (app,) = StubApp.instances
    assert app.ran and app.kwargs["config"].roles["brain"].provider == "bedrock"

    config = Config.load(make_home(tmp_path / "b", BEDROCK_TOML), env={})
    app = build_app(config, tools=[], motion=False)
    assert app.agent is None
    assert app.missing_credentials is not None
    assert app.missing_credentials.variables == ["AWS_REGION", "AWS_PROFILE"]
    assert app.config is config


def test_agentless_app_is_closed_cleanly(tmp_path: Path, monkeypatch) -> None:
    class Agentless:
        agent = None

        def run(self) -> None:
            pass

    monkeypatch.setattr("tau_tui.cli.build_app", lambda *a, **kw: Agentless())
    result = run([], make_home(tmp_path, FAKE_TOML), tmp_path)
    assert result.exit_code == 0, result.output


def test_resume_unknown_session_exits_2(tmp_path: Path) -> None:
    result = run(["--resume", "20260101-000000-0000"], make_home(tmp_path, FAKE_TOML), tmp_path)
    assert result.exit_code == 2
    assert "Session not found: 20260101-000000-0000." in result.output


def test_tui_logs_to_the_file_and_never_to_stderr(tmp_path: Path, monkeypatch: Any) -> None:
    """While the UI owns the terminal, records go to <data_dir>/logs/tau.log only (059)."""

    class StubAgent:
        def close(self) -> None:
            pass

    class StubApp:
        agent = StubAgent()

        def run(self) -> None:
            logging.getLogger("tau_tui.test").warning("only in the file")

    monkeypatch.setattr("tau_tui.cli.build_app", lambda *a, **kw: StubApp())
    result = run([], make_home(tmp_path, FAKE_TOML), tmp_path)
    assert result.exit_code == 0, result.output
    assert "only in the file" not in result.output
    log = tmp_path / "data" / "logs" / LOG_FILE
    assert "only in the file" in log.read_text(encoding="utf-8")
    assert result.output.rstrip().endswith("Goodbye.")


def test_tau_lang_reaches_the_app(tmp_path: Path) -> None:
    home = make_home(tmp_path, FAKE_TOML)
    config = Config.load(home, env={"TAU_LANG": "tr", "TAU_DATA_DIR": str(tmp_path / "data")})
    app = build_app(config, model=FakeModel([]), tools=[], motion=False)
    assert app.language == "tr"
    app.agent.close()


def test_command_runs_the_ui_with_lang_profile_and_resume(tmp_path: Path, monkeypatch) -> None:
    """``TAU_LANG``, ``--profile`` and ``--resume`` reach ``build_app``; the UI runs and logs."""
    monkeypatch.setattr("tau_tui.cli.build_app", stub_build_app)
    StubApp.instances.clear()
    home = make_home(tmp_path, FAKE_TOML)
    result = run(["--profile", "travel", "--resume"], home, tmp_path, TAU_LANG="tr")
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "Goodbye."
    (app,) = StubApp.instances
    assert app.ran and app.closed
    config = app.kwargs["config"]
    assert config.ui.language == "tr" and config.profile == "travel"
    assert app.kwargs["session_store"] is not None  # the store the config asks for
    assert app.kwargs["session_id"] is None  # --resume with an empty store: nothing to resume
    assert app.kwargs["notice"] == t("session.none_earlier", "tr")  # in the UI language
    log = tmp_path / "data" / "logs" / LOG_FILE
    assert log.is_file() and "ui ran" in log.read_text(encoding="utf-8")


def test_lang_flag_from_the_parent_command_wins_over_the_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("tau_tui.cli.build_app", stub_build_app)
    StubApp.instances.clear()
    home = make_home(tmp_path, FAKE_TOML + '\n[ui]\nlanguage = "tr"\n')
    result = run([], home, tmp_path, TAU_LANG="en")  # ``tau --lang en`` exports TAU_LANG
    assert result.exit_code == 0, result.output
    assert StubApp.instances[-1].kwargs["config"].ui.language == "en"


def test_mounted_as_tau_tui() -> None:
    commands = {ep.name: ep.value for ep in entry_points(group="tau.commands")}
    assert commands.get("tui") == "tau_tui.cli:tui"
