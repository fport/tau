from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner
from tau_core import __version__
from tau_core.cli import cli

CREDENTIALS_UNSET = {
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

[models.roles.brain.params]
replies = ["Merhaba efendim, buyurun.", "Elbette."]
"""


def make_home(tmp_path: Path, toml: str) -> Path:
    home = tmp_path / "home"
    (home / "persona").mkdir(parents=True)
    (home / "tau.toml").write_text(toml, encoding="utf-8")
    (home / "persona" / "persona.md").write_text("Sen tau'sun.\n", encoding="utf-8")
    return home


def run(args: list[str], home: Path | None, tmp_path: Path, stdin: str | None = None):
    env: dict[str, str | None] = dict(CREDENTIALS_UNSET)
    env["TAU_DATA_DIR"] = str(tmp_path / "data")
    env["TAU_HOME"] = str(home) if home is not None else str(tmp_path / "empty")
    return CliRunner().invoke(cli, args, env=env, input=stdin, prog_name="tau")


def test_help_lists_commands(tmp_path: Path) -> None:
    result = run(["--help"], None, tmp_path)
    assert result.exit_code == 0
    for name in ("chat", "hub", "tui", "version"):
        assert f"  {name}" in result.output
    assert "Show this help" in result.output


def test_version(tmp_path: Path) -> None:
    result = run(["version"], None, tmp_path)
    assert result.exit_code == 0
    assert f"tau-core {__version__}" in result.output
    assert "tau-tui " in result.output


def test_chat_without_credentials_exits_2(tmp_path: Path) -> None:
    result = run(["chat"], make_home(tmp_path, BEDROCK_TOML), tmp_path)
    assert result.exit_code == 2
    assert (
        "Missing model credentials for role 'brain' (bedrock). "
        "Add these variables to .env: AWS_REGION, AWS_PROFILE"
    ) in result.output
    assert "Example names are in .env.example." in result.output
    assert "you>" not in result.output  # no REPL started
    assert "Traceback" not in result.output


def test_chat_without_config_exits_2(tmp_path: Path) -> None:
    result = run(["chat"], None, tmp_path)
    assert result.exit_code == 2
    assert "Configuration file not found" in result.output


def test_chat_scripted_conversation(tmp_path: Path) -> None:
    home = make_home(tmp_path, FAKE_TOML)
    # /ARAÇLAR: a Turkish alias, matched case-insensitively (casefold), still works.
    stdin = "merhaba\n\n/tools\n/ARAÇLAR\nnasılsın?\n/bilinmeyen\n/quit\n"
    result = run(["chat"], home, tmp_path, stdin)
    assert result.exit_code == 0, result.output
    out = result.output
    assert "tau ready. Profile: home, session: " in out
    assert "tau> Merhaba efendim, buyurun." in out
    assert "tau> Elbette." in out
    assert out.count("demo_physical_action  tier 2 · physical, needs approval") == 2
    assert "example_echo  tier 0" in out
    assert (
        "Unknown command: /bilinmeyen. Commands: /help, /tools, /sessions, /resume, /new, "
        "/session, /lang, /quit"
    ) in out
    assert out.rstrip().endswith("Goodbye.")
    assert (tmp_path / "data" / "logs" / "tau.log").is_file()


APPROVAL_TOML = """\
[models.roles.brain]
provider = "fake"
model_id = "fake-brain"

[models.roles.brain.params]
replies = [{ tool = "demo_physical_action", input = { action = "lambayı yak" } }, "Anlaşıldı."]
"""


@pytest.mark.parametrize(
    ("answer", "line"),
    [
        ("h", "  ✗ demo_physical_action: not approved"),
        ("n", "  ✗ demo_physical_action: not approved"),
        ("", "  ✗ demo_physical_action: not approved"),
        ("evet", "  ✓ demo_physical_action: Demo action simulated: lambayı yak."),
        ("y", "  ✓ demo_physical_action: Demo action simulated: lambayı yak."),
    ],
)
def test_chat_tier2_asks_in_terminal(tmp_path: Path, answer: str, line: str) -> None:
    home = make_home(tmp_path, APPROVAL_TOML)
    result = run(["chat"], home, tmp_path, f"lambayı yak\n{answer}\n/quit\n")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "  ⚙ demo_physical_action (tier 2)" in out
    assert "⚠️  Approval needed (tier 2)" in out
    assert '  Arguments: {"action": "lambayı yak"}' in out
    assert "  Effect: Demo: simulates a physical action; no real device moves." in out
    assert "  Approve? [y/N] " in out
    assert line in out
    assert "tau> Anlaşıldı." in out


def test_chat_tier2_prompt_follows_the_ui_language(tmp_path: Path) -> None:
    home = make_home(tmp_path, APPROVAL_TOML)
    result = run(["--lang", "tr", "chat"], home, tmp_path, "lambayı yak\ny\n/quit\n")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "⚠️  Onay gerekiyor (tier 2)" in out
    assert '  Argümanlar: {"action": "lambayı yak"}' in out
    assert "  Onaylıyor musunuz? [e/H] " in out
    assert "  ✓ demo_physical_action: Demo action simulated: lambayı yak." in out  # y approves


def test_chat_ctrl_d_exits_cleanly(tmp_path: Path) -> None:
    result = run(["chat"], make_home(tmp_path, FAKE_TOML), tmp_path, "")
    assert result.exit_code == 0
    assert "Goodbye." in result.output


def test_chat_resume_and_session_commands(tmp_path: Path) -> None:
    home = make_home(tmp_path, FAKE_TOML)
    result = run(
        ["--profile", "sport", "chat", "--resume", "--session", "20260929-120000-abcd"],
        home,
        tmp_path,
        "/new\n/session\n/cik\n",
    )
    assert result.exit_code == 0, result.output
    assert "Profile: sport, session: 20260929-120000-abcd" in result.output
    # Full /resume coverage is in test_resume.py; here: nothing earlier, new session, info.
    assert "No earlier session to resume." in result.output
    assert "New session: " in result.output and "Store: memory" in result.output


def test_help_command_and_lang_switch(tmp_path: Path) -> None:
    home = make_home(tmp_path, FAKE_TOML)
    stdin = "/help\n/lang\n/lang xx\n/lang tr\n/yardım\n/dil en\n/quit\n"
    result = run(["chat"], home, tmp_path, stdin)
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Commands:\n  /help " in out
    assert "  /resume [n|id]  resume the most recent earlier session" in out
    assert "Usage: /lang en|tr (current: en)." in out
    assert "Unknown language: xx. Choose one of: en|tr." in out
    assert "Arayüz dili: tr." in out
    assert "Komutlar:\n  /help " in out and "  /quit           çıkar" in out
    assert "UI language: en." in out


def test_lang_option_sets_the_ui_language(tmp_path: Path) -> None:
    home = make_home(tmp_path, FAKE_TOML)
    result = run(["--lang", "tr", "chat"], home, tmp_path, "/bilinmeyen\n/quit\n")
    assert result.exit_code == 0, result.output
    assert "tau hazır. Profil: home, oturum: " in result.output
    assert "Bilinmeyen komut: /bilinmeyen. Komutlar: /help, /tools" in result.output
    assert "Goodbye." in result.output  # plain English, like every other CLI line

    result = run(["--lang", "de", "chat"], home, tmp_path, "/quit\n")
    assert result.exit_code == 2
    assert "Invalid value for '--lang'" in result.output


def test_home_option(tmp_path: Path) -> None:
    home = make_home(tmp_path, FAKE_TOML)
    env = dict(CREDENTIALS_UNSET, TAU_HOME=None, TAU_DATA_DIR=str(tmp_path / "data"))
    result = CliRunner().invoke(cli, ["--home", str(home), "chat"], env=env, input="/çık\n")
    assert result.exit_code == 0, result.output


def test_python_m_tau_core() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "tau_core", "--help"], capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0
    assert "chat" in out.stdout
