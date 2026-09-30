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
    home = write_home(tmp_path, MINIMAL.replace('"fake"', '"nosuch"'))
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
    # ADR 0011: providers are called directly, tau enforces the budgets itself.
    assert config.roles["brain"].provider == "anthropic"
    assert config.roles["brain"].budget is not None
    assert config.roles["brain"].budget.degrade_to == "fast"
    assert config.roles["local"].provider == "ollama"
    assert config.roles["local"].failover == "fast"


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


# -- components (issue 065) ------------------------------------------------------------------

COMPONENTS = (
    MINIMAL
    + """
[components]
context = ["example"]

[components.tools]
disabled = ["demo_physical_action", "dist:tau-example-tool"]

[components.hub]
services = ["telegram"]

[component.telegram]
chat_id_env = "TELEGRAM_CHAT_ID"
retries = 3

[component.example]
nodes = ["mac"]
"""
)


def test_components_tables(tmp_path: Path) -> None:
    config = Config.load(write_home(tmp_path, COMPONENTS), env={})
    assert config.components.tools_disabled == ("demo_physical_action", "dist:tau-example-tool")
    assert config.components.context == ("example",)
    assert config.components.hub_services == ("telegram",)
    assert config.components.tool_disabled("demo_physical_action")
    assert config.components.tool_disabled("example_echo", "tau-example-tool")
    assert not config.components.tool_disabled("current_time", "tau-core")
    assert config.component("telegram") == {"chat_id_env": "TELEGRAM_CHAT_ID", "retries": 3}
    assert config.component("missing") == {}
    table = config.component("example")
    table["nodes"].append("arm")
    assert config.component("example") == {"nodes": ["mac"]}  # a copy each time


def test_components_default_to_everything(tmp_path: Path) -> None:
    config = Config.load(write_home(tmp_path), env={})
    assert config.components.tools_disabled == ()
    assert config.components.context == () and config.components.hub_services == ()
    assert config.component_tables == {}


@pytest.mark.parametrize(
    "extra",
    [
        "[components]\ncontext = 'example'\n",
        "[components]\ncontext = ['']\n",
        "[components.tools]\ndisabled = [1]\n",
        "[components.hub]\nservices = 'x'\n",
        "[components]\ntools = 'x'\n",
        "[components]\nplugins = []\n",
        "[components.tools]\ndisable = ['current_time']\n",  # typo: must not leave the tool on
        "[components.hub]\nservice = ['x']\n",
        "[component]\ntelegram = 'x'\n",
    ],
)
def test_invalid_components_rejected(tmp_path: Path, extra: str) -> None:
    with pytest.raises(ConfigError, match=r"\[component"):
        Config.load(write_home(tmp_path, MINIMAL + "\n" + extra), env={})


def test_unknown_top_level_table_warns_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    home = write_home(tmp_path, MINIMAL + "\n[model]\nx = 1\n\n[telegram]\ntoken = 'x'\n")
    with caplog.at_level(logging.WARNING, logger="tau_core.config"):
        config = Config.load(home, env={})
        Config.load(home, env={})
    assert config.roles["brain"].provider == "fake"  # loading succeeded
    messages = [
        r.getMessage() for r in caplog.records if "unknown top-level table" in r.getMessage()
    ]
    assert len(messages) == 2  # one per table, not per load
    assert any("[model]" in m for m in messages) and any("[telegram]" in m for m in messages)


# -- [models.roles.<role>.budget], failover and [models.prices] --------------------------------

BUDGETED = """\
[models.roles.brain]
provider = "anthropic"
model_id = "claude-sonnet-5"

[models.roles.brain.budget]
usd = 15
period = "month"
degrade_to = "fast"

[models.roles.fast]
provider = "anthropic"
model_id = "claude-haiku-4-5"
budget = { usd = 0.5, period = "day" }

[models.roles.local]
provider = "ollama"
model_id = "qwen3.5:9b"
failover = "fast"

[models.prices."my-model"]
input = 1
output = 2.5
"""


def test_budget_failover_and_price_tables(tmp_path: Path) -> None:
    from tau_core.config import BudgetConfig, Price

    config = Config.load(write_home(tmp_path, BUDGETED), env={})
    assert config.roles["brain"].budget == BudgetConfig(15.0, "month", "fast")
    assert config.roles["fast"].budget == BudgetConfig(0.5, "day")
    assert config.roles["local"].failover == "fast"
    assert config.prices == {"my-model": Price(1.0, 2.5)}


@pytest.mark.parametrize(
    ("budget", "message"),
    [
        ('{ usd = 0, period = "day" }', "needs 'usd', a positive number"),
        ('{ usd = true, period = "day" }', "needs 'usd', a positive number"),
        ('{ usd = 1, period = "1mo" }', "needs 'period', one of day, week, month"),
        ('{ usd = 1, period = "day", cap = 2 }', "has unknown keys: cap"),
        ('{ usd = 1, period = "day", degrade_to = "" }', "must be the name of a role"),
        ('{ usd = 1, period = "day", degrade_to = "brain" }', "cannot name the role itself"),
        ('{ usd = 1, period = "day", degrade_to = "nope" }', "names 'nope', which is not a"),
        ("5", "'budget' must be a table"),
    ],
)
def test_invalid_budgets(tmp_path: Path, budget: str, message: str) -> None:
    toml = f'[models.roles.brain]\nprovider = "fake"\nmodel_id = "b"\nbudget = {budget}\n'
    with pytest.raises(ConfigError, match=message):
        Config.load(write_home(tmp_path, toml), env={})


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ('failover = ""', "'failover' must be the name of a role"),
        ('failover = "brain"', "cannot name the role itself"),
        ('failover = "gone"', "names 'gone', which is not a defined role"),
    ],
)
def test_invalid_failover(tmp_path: Path, extra: str, message: str) -> None:
    toml = f'[models.roles.brain]\nprovider = "fake"\nmodel_id = "b"\n{extra}\n'
    with pytest.raises(ConfigError, match=message):
        Config.load(write_home(tmp_path, toml), env={})


def test_stand_in_loops_and_misplaced_tables_are_refused(tmp_path: Path) -> None:
    loop = (
        '[models.roles.a]\nprovider = "fake"\nmodel_id = "a"\n'
        'budget = { usd = 1, period = "day", degrade_to = "b" }\n'
        '[models.roles.b]\nprovider = "fake"\nmodel_id = "b"\nfailover = "a"\n'
    )
    with pytest.raises(ConfigError, match="stand-ins loop: a → b → a"):
        Config.load(write_home(tmp_path, loop), env={})
    nested = (
        '[models.roles.a]\nprovider = "fake"\nmodel_id = "a"\n'
        '[models.roles.a.fallback]\nprovider = "fake"\nmodel_id = "f"\nfailover = "a"\n'
    )
    with pytest.raises(ConfigError, match="cannot have a 'failover'; set it on the role"):
        Config.load(write_home(tmp_path, nested), env={})
    bad_price = '[models.prices."m"]\ninput = 1\n'
    with pytest.raises(ConfigError, match="needs 'input' and 'output'"):
        Config.load(write_home(tmp_path, MINIMAL + bad_price), env={})
    negative = '[models.prices."m"]\ninput = -1\noutput = 1\n'
    with pytest.raises(ConfigError, match="'input' must be a number of dollars, 0 or more"):
        Config.load(write_home(tmp_path, MINIMAL + negative), env={})
