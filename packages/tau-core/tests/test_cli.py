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
    assert "Bu yardımı gösterir" in result.output


def test_version(tmp_path: Path) -> None:
    result = run(["version"], None, tmp_path)
    assert result.exit_code == 0
    assert f"tau-core {__version__}" in result.output
    assert "tau-tui " in result.output


def test_chat_without_credentials_exits_2(tmp_path: Path) -> None:
    result = run(["chat"], make_home(tmp_path, BEDROCK_TOML), tmp_path)
    assert result.exit_code == 2
    assert (
        "Model kimlik bilgileri eksik (brain rolü, bedrock). "
        "Şu değişkenleri .env dosyasına ekleyin: AWS_REGION, AWS_PROFILE"
    ) in result.output
    assert "Örnek isimler .env.example dosyasında." in result.output
    assert "sen>" not in result.output  # no REPL started
    assert "Traceback" not in result.output


def test_chat_without_config_exits_2(tmp_path: Path) -> None:
    result = run(["chat"], None, tmp_path)
    assert result.exit_code == 2
    assert "Yapılandırma dosyası bulunamadı" in result.output


def test_chat_scripted_conversation(tmp_path: Path) -> None:
    home = make_home(tmp_path, FAKE_TOML)
    stdin = "merhaba\n\n/araçlar\n/ARAÇLAR\nnasılsın?\n/bilinmeyen\n/çık\n"
    result = run(["chat"], home, tmp_path, stdin)
    assert result.exit_code == 0, result.output
    out = result.output
    assert "tau> Merhaba efendim, buyurun." in out
    assert "tau> Elbette." in out
    assert out.count("demo_physical_action  tier 2 · fiziksel, onay gerekir") == 2
    assert "example_echo  tier 0" in out
    assert "Bilinmeyen komut: /bilinmeyen" in out
    assert out.rstrip().endswith("Hoşça kalın.")
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
        ("h", "  ✗ demo_physical_action: onaylanmadı"),
        ("", "  ✗ demo_physical_action: onaylanmadı"),
        ("evet", "  ✓ demo_physical_action: Demo eylem simüle edildi: lambayı yak."),
    ],
)
def test_chat_tier2_asks_in_terminal(tmp_path: Path, answer: str, line: str) -> None:
    home = make_home(tmp_path, APPROVAL_TOML)
    result = run(["chat"], home, tmp_path, f"lambayı yak\n{answer}\n/çık\n")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "  ⚙ demo_physical_action (tier 2)" in out
    assert "⚠️  Onay gerekiyor (tier 2)" in out
    assert '  Argümanlar: {"action": "lambayı yak"}' in out
    assert "  Etki: Demo: fiziksel bir eylemi taklit eder; gerçek bir cihaz hareket etmez." in out
    assert "  Onaylıyor musunuz? [e/H] " in out
    assert line in out
    assert "tau> Anlaşıldı." in out


def test_chat_ctrl_d_exits_cleanly(tmp_path: Path) -> None:
    result = run(["chat"], make_home(tmp_path, FAKE_TOML), tmp_path, "")
    assert result.exit_code == 0
    assert "Hoşça kalın." in result.output


def test_chat_resume_and_session_commands(tmp_path: Path) -> None:
    home = make_home(tmp_path, FAKE_TOML)
    result = run(
        ["--profile", "spor", "chat", "--resume", "--session", "20260929-120000-abcd"],
        home,
        tmp_path,
        "/yeni\n/oturum\n/cik\n",
    )
    assert result.exit_code == 0, result.output
    assert "Profil: spor, oturum: 20260929-120000-abcd" in result.output
    # Full /devam coverage is in test_resume.py; here: nothing earlier, new session, info.
    assert "Devam edilecek önceki oturum yok." in result.output
    assert "Yeni oturum: " in result.output and "Depo: memory" in result.output


def test_home_option(tmp_path: Path) -> None:
    home = make_home(tmp_path, FAKE_TOML)
    env = dict(CREDENTIALS_UNSET, TAU_HOME=None, TAU_DATA_DIR=str(tmp_path / "data"))
    result = CliRunner().invoke(cli, ["--home", str(home), "chat"], env=env, input="/çık\n")
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("args", [["hub", "status"], ["hub", "run"], ["tui"]])
def test_placeholders(tmp_path: Path, args: list[str]) -> None:
    result = run(args, None, tmp_path)
    assert result.exit_code == 0
    assert "Henüz yok (issue 00" in result.output


def test_python_m_tau_core() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "tau_core", "--help"], capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0
    assert "chat" in out.stdout
