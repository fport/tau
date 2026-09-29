from __future__ import annotations

from pathlib import Path

import pytest
from tau_core import Config, ConfigError
from tau_core.config import AgentConfig, UiConfig
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
    assert config.profile == "home"
    assert config.ui.language == "en"
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
        dotenv="TAU_PROFILE=sport\nTAU_DATA_DIR=/from/dotenv\nTAU_HUB_PORT=9000\n",
    )
    config = Config.load(home, env={"TAU_DATA_DIR": str(tmp_path / "data")})
    assert config.data_dir == (tmp_path / "data").resolve()  # explicit env wins
    assert config.profile == "sport"  # .env fills what the env lacks
    assert config.hub.control_port == 9000  # TAU_HUB_PORT overrides [hub]


def test_home_from_tau_home_then_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_env: None
) -> None:
    home = write_home(tmp_path)
    assert Config.load(env={"TAU_HOME": str(home)}).home == home.resolve()
    monkeypatch.chdir(home)
    assert Config.load(env={}).home == home.resolve()


def test_missing_config_names_path(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as info:
        Config.load(tmp_path / "nowhere", env={})
    message = str(info.value)
    assert "Configuration file not found" in message
    assert str((tmp_path / "nowhere" / "tau.toml").resolve()) in message
    assert "TAU_HOME" in message


def test_unknown_provider_rejected(tmp_path: Path) -> None:
    home = write_home(tmp_path, MINIMAL.replace('"fake"', '"openai"'))
    with pytest.raises(ConfigError, match="unknown provider"):
        Config.load(home, env={})


def test_unknown_backend_rejected(tmp_path: Path) -> None:
    home = write_home(tmp_path, MINIMAL + '\n[sessions]\nbackend = "sqlite"\n')
    with pytest.raises(ConfigError, match="unknown session backend"):
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
    changed = config.with_overrides(profile="travel", agent=AgentConfig(max_turns=2))
    assert changed.profile == "travel" and changed.agent.max_turns == 2
    assert config.profile == "home"


def test_test_config_layout(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    assert {r.provider for r in config.roles.values()} == {"fake"}
    assert (config.persona_dir / "persona.md").is_file()
    assert config.data_dir == (tmp_path / "data").resolve()


def test_repo_tau_toml_loads() -> None:
    config = Config.load(ROOT, env={})
    assert set(config.roles) >= {"brain", "fast", "local"}
    assert config.roles["brain"].fallback is not None


# -- [ui] language ---------------------------------------------------------------------------


def test_ui_language_from_file_env_and_overrides(tmp_path: Path) -> None:
    home = write_home(tmp_path, MINIMAL + '\n[ui]\nlanguage = "tr"\n')
    assert Config.load(home, env={}).ui.language == "tr"
    assert Config.load(home, env={"TAU_LANG": "en"}).ui.language == "en"  # env wins
    assert Config.load(write_home(tmp_path), env={"TAU_LANG": "tr"}).ui.language == "tr"
    overridden = Config.load(home, env={}).with_overrides(ui=UiConfig(language="en"))
    assert overridden.ui.language == "en"


@pytest.mark.parametrize(
    ("toml", "env", "message"),
    [
        (
            MINIMAL + '\n[ui]\nlanguage = "de"\n',
            {},
            r"tau.toml: \[ui\] 'language' must be one of en, tr, not 'de'",
        ),
        (MINIMAL + "\n[ui]\nlanguage = 3\n", {}, r"tau.toml: \[ui\] 'language' must be one of"),
        ("ui = 5\n" + MINIMAL, {}, r"tau.toml: \[ui\] must be a table"),
        (MINIMAL, {"TAU_LANG": "fr"}, "TAU_LANG must be one of en, tr, not 'fr'"),
    ],
    ids=["file-unknown", "file-not-a-string", "not-a-table", "env-unknown"],
)
def test_ui_language_is_validated(tmp_path: Path, toml: str, env: dict, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        Config.load(write_home(tmp_path, toml), env=env)


# --- [agent] context, window_size, max_total_tokens (issue 064) -------------------------------


def test_agent_context_defaults(tmp_path: Path) -> None:
    agent = Config.load(write_home(tmp_path), env={}).agent
    assert agent == AgentConfig(
        max_turns=12, context="sliding", window_size=60, max_total_tokens=None
    )


def test_agent_context_parsed(tmp_path: Path) -> None:
    toml = MINIMAL + '\n[agent]\ncontext = "summarize"\nwindow_size = 5\nmax_total_tokens = 1000\n'
    agent = Config.load(write_home(tmp_path, toml), env={}).agent
    assert (agent.context, agent.window_size, agent.max_total_tokens) == ("summarize", 5, 1000)


@pytest.mark.parametrize("value", ['"auto"', '"agentic"', '"window"', "3"])
def test_agent_context_rejects_sdk_presets_and_junk(tmp_path: Path, value: str) -> None:
    home = write_home(tmp_path, MINIMAL + f"\n[agent]\ncontext = {value}\n")
    with pytest.raises(ConfigError, match="context"):
        Config.load(home, env={})


@pytest.mark.parametrize("key", ["window_size", "max_total_tokens"])
@pytest.mark.parametrize("value", ["0", "-1", "true", '"9"', "2.5"])
def test_agent_sizes_must_be_positive_integers(tmp_path: Path, key: str, value: str) -> None:
    home = write_home(tmp_path, MINIMAL + f"\n[agent]\n{key} = {value}\n")
    with pytest.raises(ConfigError, match=key):
        Config.load(home, env={})


# --- [models.roles.<role>] cache ----------------------------------------------------------------


def test_role_cache_table_parsed(tmp_path: Path) -> None:
    toml = (
        MINIMAL + '\n[models.roles.brain.cache]\nstrategy = "auto"\nttl = "1h"\ntools_ttl = true\n'
    )
    brain = Config.load(write_home(tmp_path, toml), env={}).roles["brain"]
    assert brain.cache == {"strategy": "auto", "ttl": "1h", "tools_ttl": True}
    assert Config.load(write_home(tmp_path), env={}).roles["brain"].cache is None


def test_role_cache_strategy_defaults_to_auto(tmp_path: Path) -> None:
    toml = MINIMAL + '\n[models.roles.brain.cache]\nttl = "5m"\n'
    assert Config.load(write_home(tmp_path, toml), env={}).roles["brain"].cache == {
        "strategy": "auto",
        "ttl": "5m",
    }


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ('cache = "auto"', "must be a table"),
        ('[models.roles.brain.cache]\nstrategy = "magic"', "cache.strategy"),
        ("[models.roles.brain.cache]\nttl = 5", "cache.ttl"),
        ("[models.roles.brain.cache]\nsystem_prompt_ttl = 3", "cache.system_prompt_ttl"),
        ("[models.roles.brain.cache]\nsize = 3", "unknown keys: size"),
    ],
)
def test_role_cache_rejects_invalid_tables(tmp_path: Path, body: str, match: str) -> None:
    home = write_home(tmp_path, MINIMAL + "\n" + body + "\n")
    with pytest.raises(ConfigError, match=match):
        Config.load(home, env={})
