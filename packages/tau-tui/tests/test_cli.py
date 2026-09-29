"""``tau tui`` startup: help, config and credential errors before any UI, logging, entry point."""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from click.testing import CliRunner
from tau_core import Config, t
from tau_core.testing import FakeModel
from tau_tui import build_app
from tau_tui.cli import LOG_FILE, file_logging, tui

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


def test_missing_config_exits_2(tmp_path: Path) -> None:
    result = run([], tmp_path / "missing", tmp_path)
    assert result.exit_code == 2
    assert "Configuration file not found" in result.output


def test_missing_credentials_exit_2_before_the_ui(tmp_path: Path) -> None:
    result = run([], make_home(tmp_path, BEDROCK_TOML), tmp_path)
    assert result.exit_code == 2
    assert "Missing model credentials for role 'brain' (bedrock)." in result.output
    assert "Traceback" not in result.output


def test_resume_unknown_session_exits_2(tmp_path: Path) -> None:
    result = run(["--resume", "20260101-000000-0000"], make_home(tmp_path, FAKE_TOML), tmp_path)
    assert result.exit_code == 2
    assert "Session not found: 20260101-000000-0000." in result.output


def test_file_logging_writes_mutes_stderr_and_cleans_up(tmp_path: Path) -> None:
    root = logging.getLogger()
    stderr_handler = logging.StreamHandler()
    root.addHandler(stderr_handler)
    try:
        before = list(root.handlers)
        level = root.level
        with file_logging(tmp_path / "logs") as path:
            assert path == tmp_path / "logs" / LOG_FILE
            assert stderr_handler not in root.handlers  # nothing reaches stderr meanwhile
            logging.getLogger("tau_tui.test").info("tui log line")
        assert root.handlers == before
        assert root.level == level
        assert "tui log line" in path.read_text(encoding="utf-8")
    finally:
        root.removeHandler(stderr_handler)


def test_file_logging_survives_an_unwritable_directory(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory", encoding="utf-8")
    with file_logging(blocker / "logs") as path:
        assert path is None
        logging.getLogger("tau_tui.test").info("dropped, never raises")


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
