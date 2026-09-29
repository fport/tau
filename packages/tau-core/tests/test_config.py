from __future__ import annotations

from pathlib import Path

import pytest
from tau_core import Config, ConfigError
from tau_core.config import AgentConfig
from tau_core.testing import test_config

ROOT = Path(__file__).resolve().parents[3]

MINIMAL = """\
[models.roles.brain]
provider = "fake"
model_id = "fake-brain"
"""


def write_home(tmp_path: Path, toml: str = MINIMAL, dotenv: str | None = None) -> Path:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "tau.toml").write_text(toml, encoding="utf-8")
    if dotenv is not None:
        (home / ".env").write_text(dotenv, encoding="utf-8")
    return home


def test_defaults(tmp_path: Path) -> None:
    home = write_home(tmp_path)
    config = Config.load(home, env={})
    assert config.home == home.resolve()
    assert config.profile == "ev"
    assert config.role == "hub"
    assert config.data_dir == Path("~/.local/share/tau").expanduser().resolve()
    assert config.agent.max_turns == 12
    assert config.sessions.backend == "memory"
    assert config.hub.control_port == 7877
    assert config.roles["brain"].provider == "fake"
    assert config.persona_dir == config.home / "persona"
    assert config.tools_dir == config.home / "tools"
    assert config.sessions_dir == config.data_dir / "sessions"
    assert config.hub_dir == config.data_dir / "hub"


def test_env_precedence_over_dotenv(tmp_path: Path) -> None:
    home = write_home(
        tmp_path,
        dotenv="TAU_PROFILE=spor\nTAU_DATA_DIR=/from/dotenv\nTAU_HUB_PORT=9000\n",
    )
    config = Config.load(home, env={"TAU_DATA_DIR": str(tmp_path / "data")})
    assert config.data_dir == (tmp_path / "data").resolve()  # explicit env wins
    assert config.profile == "spor"  # .env fills what the env lacks
    assert config.hub.control_port == 9000  # TAU_HUB_PORT overrides [hub]


def test_home_from_tau_home_then_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_env: None
) -> None:
    home = write_home(tmp_path)
    assert Config.load(env={"TAU_HOME": str(home)}).home == home.resolve()
    monkeypatch.chdir(home)
    assert Config.load(env={}).home == home.resolve()


def test_missing_config_is_turkish_and_names_path(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        Config.load(tmp_path / "nowhere", env={})
    message = str(info.value)
    assert "Yapılandırma dosyası bulunamadı" in message
    assert str((tmp_path / "nowhere" / "tau.toml").resolve()) in message
    assert "TAU_HOME" in message


def test_unknown_provider_rejected(tmp_path: Path) -> None:
    home = write_home(tmp_path, MINIMAL.replace('"fake"', '"openai"'))
    with pytest.raises(ConfigError, match="bilinmeyen sağlayıcı"):
        Config.load(home, env={})


def test_unknown_backend_rejected(tmp_path: Path) -> None:
    home = write_home(tmp_path, MINIMAL + '\n[sessions]\nbackend = "sqlite"\n')
    with pytest.raises(ConfigError, match="oturum deposu"):
        Config.load(home, env={})


def test_planned_names_load(tmp_path: Path) -> None:
    toml = MINIMAL + '\n[models.roles.local]\nprovider = "ollama"\nmodel_id = "x"\n'
    toml += '\n[sessions]\nbackend = "file"\n'
    config = Config.load(write_home(tmp_path, toml), env={})
    assert config.roles["local"].provider == "ollama"


def test_unknown_role_key_rejected(tmp_path: Path) -> None:
    home = write_home(tmp_path, MINIMAL + "max_token = 10\n")
    with pytest.raises(ConfigError, match="max_token"):
        Config.load(home, env={})


@pytest.mark.parametrize("value", ["true", "0", '"12"', "2.5"])
def test_invalid_max_turns_rejected(tmp_path: Path, value: str) -> None:
    home = write_home(tmp_path, MINIMAL + f"\n[agent]\nmax_turns = {value}\n")
    with pytest.raises(ConfigError, match="max_turns"):
        Config.load(home, env={})


def test_invalid_host_role_and_port(tmp_path: Path) -> None:
    home = write_home(tmp_path)
    with pytest.raises(ConfigError, match="TAU_ROLE"):
        Config.load(home, env={"TAU_ROLE": "master"})
    with pytest.raises(ConfigError, match="TAU_HUB_PORT"):
        Config.load(home, env={"TAU_HUB_PORT": "yedi"})


def test_fallback_parsed(tmp_path: Path) -> None:
    toml = MINIMAL + '\n[models.roles.brain.fallback]\nprovider = "anthropic"\nmodel_id = "m"\n'
    brain = Config.load(write_home(tmp_path, toml), env={}).roles["brain"]
    assert brain.fallback is not None and brain.fallback.provider == "anthropic"


def test_with_overrides(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    changed = config.with_overrides(profile="seyahat", agent=AgentConfig(max_turns=2))
    assert changed.profile == "seyahat" and changed.agent.max_turns == 2
    assert config.profile == "ev"


def test_test_config_layout(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    assert {r.provider for r in config.roles.values()} == {"fake"}
    assert (config.persona_dir / "persona.md").is_file()
    assert config.data_dir == (tmp_path / "data").resolve()


def test_repo_tau_toml_loads() -> None:
    config = Config.load(ROOT, env={})
    assert set(config.roles) >= {"brain", "fast", "local"}
    assert config.roles["brain"].fallback is not None
