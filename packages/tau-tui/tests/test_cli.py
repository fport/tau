"""``tau tui`` startup: help, config and credential errors before any UI, logging, entry point."""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from pathlib import Path

from click.testing import CliRunner
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
    (home / "persona" / "persona.md").write_text("Sen tau'sun.\n", encoding="utf-8")
    return home


def run(args: list[str], home: Path, tmp_path: Path):
    env = dict(UNSET, TAU_HOME=str(home), TAU_DATA_DIR=str(tmp_path / "data"))
    return CliRunner().invoke(tui, args, env=env, prog_name="tau tui")


def test_help_is_turkish(tmp_path: Path) -> None:
    result = run(["--help"], tmp_path, tmp_path)
    assert result.exit_code == 0
    assert "tau'yu Textual arayüzünde açar." in result.output
    assert "--resume [ID]" in result.output
    assert "--profile AD" in result.output
    assert "Bu yardımı gösterir ve çıkar." in result.output


def test_missing_config_exits_2(tmp_path: Path) -> None:
    result = run([], tmp_path / "yok", tmp_path)
    assert result.exit_code == 2
    assert "Yapılandırma dosyası bulunamadı" in result.output


def test_missing_credentials_exit_2_before_the_ui(tmp_path: Path) -> None:
    result = run([], make_home(tmp_path, BEDROCK_TOML), tmp_path)
    assert result.exit_code == 2
    assert "Model kimlik bilgileri eksik (brain rolü, bedrock)." in result.output
    assert "Traceback" not in result.output


def test_resume_unknown_session_exits_2(tmp_path: Path) -> None:
    result = run(["--resume", "20260101-000000-0000"], make_home(tmp_path, FAKE_TOML), tmp_path)
    assert result.exit_code == 2
    assert "Oturum bulunamadı: 20260101-000000-0000." in result.output


def test_file_logging_writes_and_cleans_up(tmp_path: Path) -> None:
    root = logging.getLogger()
    before = list(root.handlers)
    level = root.level
    with file_logging(tmp_path / "logs") as path:
        assert path == tmp_path / "logs" / LOG_FILE
        logging.getLogger("tau_tui.test").info("tui günlük satırı")
    assert root.handlers == before
    assert root.level == level
    assert "tui günlük satırı" in path.read_text(encoding="utf-8")


def test_mounted_as_tau_tui() -> None:
    commands = {ep.name: ep.value for ep in entry_points(group="tau.commands")}
    assert commands.get("tui") == "tau_tui.cli:tui"
