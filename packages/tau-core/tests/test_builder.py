"""``tau components``, ``tau doctor`` and ``tau init`` with CliRunner and isolated roots."""

from __future__ import annotations

import json
import logging
import socket
import sys
from importlib import metadata
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from tau_core import Config, ConfigError, registry
from tau_core.builder import (
    Check,
    env_names,
    init_home,
    inventory,
    model_ids,
    pick_provider,
    render_config,
    run_doctor,
    template_text,
)
from tau_core.cli import cli
from tau_core.hub import ControlApi
from tau_core.testing import test_config

ROOT = Path(__file__).resolve().parents[3]

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
        "EXAMPLE_API_KEY",
        "TAU_PROFILE",
        "TAU_ROLE",
        "TAU_HUB_PORT",
        "TAU_LANG",
    )
}


def run(
    args: list[str], tmp_path: Path, *, home: Path | None, env: dict | None = None, stdin=None
) -> Result:
    full: dict[str, str | None] = dict(CREDENTIALS_UNSET)
    full["TAU_DATA_DIR"] = str(tmp_path / "data")
    full["TAU_HOME"] = str(home) if home is not None else str(tmp_path / "nowhere")
    full["HOME"] = str(tmp_path / "userhome")
    full.update(env or {})
    return CliRunner().invoke(cli, args, env=full, input=stdin, prog_name="tau")


# -- tau components --------------------------------------------------------------------------


def test_inventory_lists_every_group_with_state(config: Config) -> None:
    rows = inventory(config)
    by = {(row.group, row.name): row for row in rows}
    assert set(registry.GROUPS) <= {row.group for row in rows}

    echo = by[("tau.tools", "example_echo")]
    assert echo.distribution == "tau-example-tool" and echo.version == "0.0.1"
    assert echo.enabled and echo.note == "tier 0" and echo.error is None
    assert by[("tau.tools", "demo_physical_action")].note == "tier 2"

    bedrock = by[("tau.providers", "bedrock")]
    assert bedrock.source == "built-in" and bedrock.distribution == "tau-core"
    assert by[("tau.providers", "fake")].note == "in use: brain, fast, local"
    fake2 = by[("tau.providers", "fake2")]
    assert fake2.source == "entry point" and fake2.distribution == "tau-example-provider"
    assert by[("tau.sessions", "memory")].note == "in use"
    assert by[("tau.sessions", "example")].note == "available"
    assert by[("tau.context", "example")].enabled
    assert by[("tau.hub_services", "example")].enabled
    assert by[("tau.commands", "components")].note == "tau components"


def test_inventory_reflects_components_config(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    (config.home / "tau.toml").write_text(
        "[models.roles.brain]\nprovider = 'fake'\nmodel_id = 'b'\n"
        "[models.roles.local]\nprovider = 'ollama'\nmodel_id = 'x'\n"
        "[components]\ncontext = ['nope']\n[components.tools]\n"
        "disabled = ['current_time', 'dist:tau-example-tool']\n"
        "[components.hub]\nservices = ['example']\n",
        encoding="utf-8",
    )
    config = Config.load(config.home, env={})
    by = {(row.group, row.name): row for row in inventory(config)}
    assert not by[("tau.tools", "current_time")].enabled
    assert not by[("tau.tools", "example_echo")].enabled
    assert by[("tau.tools", "demo_physical_action")].enabled
    assert not by[("tau.context", "example")].enabled
    assert by[("tau.context", "example")].note == "not listed in [components]"
    assert by[("tau.hub_services", "example")].enabled
    ollama = by[("tau.providers", "ollama")]
    assert ollama.source == "built-in" and ollama.enabled and ollama.note == "in use: local"


def test_inventory_shows_load_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    real = registry._entry_points
    broken = metadata.EntryPoint("broken", "nowhere_at_all:thing", "tau.context")
    monkeypatch.setattr(
        registry, "_entry_points", lambda g: [*([broken] if g == "tau.context" else []), *real(g)]
    )
    registry.reset()
    row = next(r for r in inventory(None) if r.name == "broken")
    assert not row.enabled and row.error and "ModuleNotFoundError" in row.error


def test_components_command_text_and_json(tmp_path: Path, config: Config) -> None:
    result = run(["components"], tmp_path, home=config.home)
    assert result.exit_code == 0, result.output
    out = result.output
    for group in registry.GROUPS:
        assert f"\n{group}\n" in f"\n{out}"
    assert "  example_echo" in out and "tau-example-tool 0.0.1" in out and "tier 0" in out
    assert "(built-in)" in out and "in use: brain, fast, local" in out

    result = run(["components", "--json"], tmp_path, home=config.home)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["config_error"] is None
    names = {(row["group"], row["name"]) for row in payload["components"]}
    assert ("tau.providers", "fake2") in names and ("tau.hub_services", "example") in names


def test_components_command_without_config_still_lists(tmp_path: Path) -> None:
    result = run(["components"], tmp_path, home=None)
    assert result.exit_code == 0, result.output
    assert "Configuration file not found" in result.output
    assert "  fake2" in result.output and "available" in result.output


# -- tau doctor ------------------------------------------------------------------------------


def statuses(checks: list[Check]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for check in checks:
        out.setdefault(check.name, []).append(check.status)
    return out


def test_doctor_all_green_on_the_test_config(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    # A port nothing listens on: a real hub on the default 7877 must not answer this test.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    result = run(["doctor"], tmp_path, home=config.home, env={"TAU_HUB_PORT": str(free_port)})
    assert result.exit_code == 0, result.output
    out = result.output
    assert "ok   config:" in out
    assert "ok   role brain: provider 'fake', needs no credentials" in out
    assert "ok   sessions: backend 'memory' opens" in out
    assert "ok   persona:" in out and "user.md present" in out
    assert "info .env: no " in out
    assert "ok   components: every component loads" in out
    assert "info hub: hub is not running" in out
    assert "checks: " in out and "0 failed" in out


def test_doctor_reports_credentials_without_building_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = test_config(tmp_path)
    (config.home / "tau.toml").write_text(
        "[models.roles.brain]\nprovider = 'bedrock'\nmodel_id = 'b'\n"
        "[models.roles.brain.fallback]\nprovider = 'anthropic'\nmodel_id = 'a'\n"
        "[models.roles.fast]\nprovider = 'anthropic'\nmodel_id = 'a'\n"
        "[models.roles.local]\nprovider = 'ollama'\nmodel_id = 'o'\n"
        "[models.roles.plug]\nprovider = 'fake2'\nmodel_id = 'p'\n"
        "[models.roles.later]\nprovider = 'futurebox'\nmodel_id = 'f'\n",
        encoding="utf-8",
    )
    import tau_core.models as models

    def never(*args, **kwargs):
        raise AssertionError("doctor must not build a model client")

    monkeypatch.setitem(models.PROVIDERS, "bedrock", never)
    monkeypatch.setitem(models.PROVIDERS, "anthropic", never)
    monkeypatch.setitem(models.PLANNED_PROVIDERS, "futurebox", "999")
    registry.reset()

    checks = run_doctor(config.home, env={"ANTHROPIC_API_KEY": "k"})
    by = {c.name: c for c in checks}
    assert by["role brain"].status == "warn"
    assert "fallback 'anthropic' has credentials" in by["role brain"].detail
    assert by["role fast"].status == "ok" and "credentials present" in by["role fast"].detail
    assert by["role local"].status == "ok" and "needs no credentials" in by["role local"].detail
    assert by["role later"].status == "warn" and "issue 999" in by["role later"].detail
    assert by["role plug"].status == "fail" and "EXAMPLE_API_KEY" in by["role plug"].detail

    checks = run_doctor(config.home, env={})
    assert statuses(checks)["role brain"] == ["fail"]
    result = run(["doctor"], tmp_path, home=config.home)
    assert result.exit_code == 1
    assert "fail role brain: provider 'bedrock' is missing AWS_REGION, AWS_PROFILE" in result.output


def test_doctor_fails_on_missing_config_and_persona(tmp_path: Path) -> None:
    result = run(["doctor"], tmp_path, home=None)
    assert result.exit_code == 1
    assert "fail config: Configuration file not found" in result.output
    assert "1 checks: 0 ok, 0 warnings, 1 failed" in result.output

    config = test_config(tmp_path)
    (config.home / "persona" / "persona.md").write_text("", encoding="utf-8")
    (config.home / "persona" / "user.md").unlink()
    checks = run_doctor(config.home, env={})
    assert statuses(checks)["persona"] == ["fail"]
    (config.home / "persona" / "persona.md").write_text("tau.\n", encoding="utf-8")
    checks = run_doctor(config.home, env={})
    assert statuses(checks)["persona"] == ["ok", "warn"]
    assert "user.md is missing" in [c for c in checks if c.name == "persona"][1].detail


def test_doctor_unknown_table_and_dotenv_names(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config = test_config(tmp_path)
    (config.home / "tau.toml").write_text(
        "[models.roles.brain]\nprovider = 'anthropic'\nmodel_id = 'a'\n[model]\nx = 1\n",
        encoding="utf-8",
    )
    (config.home / ".env").write_text(
        "ANTHROPIC_API_KEY=x\nMY_SECRET=y\nexport TAU_PROFILE=sport\n"
    )
    (config.home / ".env.example").write_text("# ANTHROPIC_API_KEY=sk-...\n# TAU_PROFILE=home\n")
    checks = run_doctor(config.home, env={})
    by = statuses(checks)
    assert by["config"] == ["ok", "warn"]
    assert "[model]" in checks[1].detail
    assert next(c for c in checks if c.name == "role brain").status == "ok"  # .env was merged
    dotenv = next(c for c in checks if c.name == ".env")
    assert dotenv.status == "warn" and dotenv.detail.endswith(": MY_SECRET")
    assert env_names("A=1\n# B=2\nexport C=3\n  # D = 4\nnot a line\n") == {"A", "B", "C", "D"}


def test_doctor_sees_a_running_hub(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    api = ControlApi(0, lambda: {})
    api.serve()
    try:
        result = run(
            ["doctor", "--json"], tmp_path, home=config.home, env={"TAU_HUB_PORT": str(api.port)}
        )
    finally:
        api.shutdown()
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    hub = next(c for c in payload["checks"] if c["name"] == "hub")
    assert hub["status"] == "ok" and "hub is running (pid" in hub["detail"]
    assert payload["ok"] is True


def test_doctor_reports_broken_components(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = registry._entry_points
    broken = metadata.EntryPoint("broken", "nowhere_at_all:thing", "tau.providers")
    monkeypatch.setattr(
        registry, "_entry_points", lambda g: [*([broken] if g == "tau.providers" else []), *real(g)]
    )
    registry.reset()
    config = test_config(tmp_path)
    checks = run_doctor(config.home, env={})
    comp = next(c for c in checks if c.name == "components")
    assert comp.status == "warn" and "tau.providers:broken" in comp.detail

    # A role naming the broken provider: "failed to load", not "unknown provider".
    (config.home / "tau.toml").write_text(
        "[models.roles.brain]\nprovider = 'broken'\nmodel_id = 'b'\n", encoding="utf-8"
    )
    role = next(c for c in run_doctor(config.home, env={}) if c.name == "role brain")
    assert role.status == "fail"
    assert role.detail.startswith("Model provider 'broken' failed to load: ModuleNotFoundError")
    (config.home / "tau.toml").write_text(
        "[models.roles.brain]\nprovider = 'ghost'\nmodel_id = 'b'\n", encoding="utf-8"
    )
    role = next(c for c in run_doctor(config.home, env={}) if c.name == "config")
    assert role.status == "fail" and "ghost" in role.detail  # never declared: Config.load says so


def test_doctor_flags_component_names_nothing_provides(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    (config.home / "tau.toml").write_text(
        "[models.roles.brain]\nprovider = 'fake'\nmodel_id = 'b'\n"
        "[components]\ncontext = ['example', 'nope']\n"
        "[components.tools]\ndisabled = ['current_time', 'dist:tau-example-tool', "
        "'demo_physical_actoin', 'dist:tau-nothing']\n"
        "[components.hub]\nservices = ['voice']\n",
        encoding="utf-8",
    )
    checks = [c for c in run_doctor(config.home, env={}) if c.name == "components"]
    assert [c.status for c in checks] == ["ok", "warn"]
    assert checks[1].detail == (
        "[components] names no installed component provides: "
        "[components.tools] disabled: demo_physical_actoin, dist:tau-nothing; "
        "[components] context: nope; [components.hub] services: voice (see `tau components`)"
    )
    result = run(["doctor"], tmp_path, home=config.home)
    assert result.exit_code == 0, result.output  # a warning, not a failure
    assert "warn components: [components] names no installed component provides" in result.output


# -- tau init --------------------------------------------------------------------------------


def test_shipped_templates_match_the_repository() -> None:
    assert template_text("persona.md") == (ROOT / "persona" / "persona.md").read_text("utf-8")
    assert template_text("user.example.md") == (ROOT / "persona" / "user.example.md").read_text(
        "utf-8"
    )
    assert template_text("tau.toml") == (ROOT / "tau.toml").read_text("utf-8")
    # .env.example: the repository's file minus its L0 remote-access section (an installation
    # made by ``tau init`` has no tailnet values); the header and the L1 sections stay verbatim.
    repo = (ROOT / ".env.example").read_text("utf-8")
    template = template_text("dotenv.example")
    assert template.startswith(repo.split("\n\n", 1)[0] + "\n\n")
    assert template.endswith(repo[repo.index("# --- Agent (L1)") :])
    assert "TAU_TAILNET" not in template and "SHA256" not in template
    assert env_names(template) < env_names(repo)


def test_template_config_loads(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "tau.toml").write_text(template_text("tau.toml"), encoding="utf-8")
    config = Config.load(home, env={})
    for role in ("brain", "fast", "local"):
        assert config.roles[role].provider == "proxy"
        assert config.roles[role].model_id == role  # the proxy's model group
        assert config.roles[role].budget is not None
        assert config.roles[role].fallback is None  # a missing proxy key must not bypass budgets
    assert config.roles["brain"].budget.degrade_to == "fast"
    assert config.components.tools_disabled == ()  # the example stays commented out


def test_render_config_proxy_is_the_template(tmp_path: Path) -> None:
    template = template_text("tau.toml")
    assert render_config(template, provider="proxy", language="en") == template


@pytest.mark.parametrize("provider", ["anthropic", "bedrock", "fake"])
def test_render_config_per_provider(tmp_path: Path, provider: str) -> None:
    text = render_config(template_text("tau.toml"), provider=provider, language="tr")
    home = tmp_path / provider
    home.mkdir()
    (home / "tau.toml").write_text(text, encoding="utf-8")
    config = Config.load(home, env={})
    ids = model_ids(provider)
    for role in ("brain", "fast"):
        assert config.roles[role].provider == provider
        assert config.roles[role].model_id == ids[role]
    assert config.roles["local"].provider == "ollama"  # direct, without the proxy
    assert config.roles["local"].model_id == model_ids("ollama")["local"]
    assert all(role.budget is None for role in config.roles.values())  # only the proxy enforces
    assert "budget]" not in text
    assert config.ui.language == "tr"
    assert "# proxy | anthropic | bedrock | ollama | fake" in text  # comments survive
    assert "# [models.roles.brain.cache]" in text  # also the ones after a dropped budget table
    assert "\n\n\n" not in text


def test_pick_provider_by_credentials() -> None:
    assert pick_provider({}) == "fake"
    assert pick_provider({"ANTHROPIC_API_KEY": "k"}) == "anthropic"
    aws = {"AWS_REGION": "r", "AWS_PROFILE": "p"}
    assert pick_provider(aws) == "bedrock"
    assert pick_provider({"ANTHROPIC_API_KEY": "k", **aws}) == "anthropic"
    assert pick_provider({"ANTHROPIC_API_KEY": "k", "TAU_PROXY_KEY_BRAIN": "sk-x"}) == "proxy"
    assert pick_provider({"TAU_PROXY_KEY_FAST": "sk-x"}) == "fake"  # brain's key decides
    with pytest.raises(ConfigError):
        model_ids("nope")


def test_init_non_interactive(tmp_path: Path) -> None:
    home = tmp_path / "fresh"
    result = run(["init", "--home", str(home), "--yes", "--profile", "travel"], tmp_path, home=None)
    assert result.exit_code == 0, result.output
    assert "Provider: fake." in result.output
    assert f"wrote {home / 'tau.toml'}" in result.output
    assert f"wrote {home / 'persona' / 'user.md'}" in result.output
    assert f"wrote {home / '.env.example'}" in result.output
    assert f"names are in {home / '.env.example'}" in result.output  # the hint names a real file
    assert "UI language (" not in result.output  # --yes asks nothing
    assert (home / "persona" / "persona.md").read_text("utf-8") == template_text("persona.md")
    assert (home / "persona" / "user.md").read_text("utf-8") == template_text("user.example.md")
    assert (home / ".env.example").read_text("utf-8") == template_text("dotenv.example")
    assert (home / ".env").read_text("utf-8") == "TAU_PROFILE=travel\n"
    config = Config.load(home, env={})
    assert config.roles["brain"].provider == "fake" and config.ui.language == "en"
    # the doctor now has a list to compare .env against, in a home outside the repository
    dotenv = next(c for c in run_doctor(home, env={}) if c.name == ".env")
    assert dotenv.status == "ok" and dotenv.detail == "every name in .env is listed in .env.example"

    # a second run refuses to touch the existing tau.toml, before asking anything
    result = run(["init", "--home", str(home)], tmp_path, home=None)
    assert result.exit_code == 1
    assert "already exists. Use --force" in result.output
    assert "UI language" not in result.output


def test_init_asks_the_language_and_keeps_user_md(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "persona").mkdir(parents=True)
    (home / "persona" / "user.md").write_text("- Name: Real Person\n", encoding="utf-8")
    (home / ".env").write_text("TAU_PROFILE=sport", encoding="utf-8")
    result = run(
        ["init", "--home", str(home), "--provider", "anthropic", "--profile", "home"],
        tmp_path,
        home=None,
        stdin="tr\n",
    )
    assert result.exit_code == 0, result.output
    assert "UI language (en, tr) [en]: tr" in result.output
    assert f"kept  {home / 'persona' / 'user.md'}" in result.output
    assert (home / "persona" / "user.md").read_text("utf-8") == "- Name: Real Person\n"
    assert (home / ".env").read_text("utf-8") == "TAU_PROFILE=sport"  # existing value kept
    config = Config.load(home, env={})
    assert config.roles["brain"].provider == "anthropic" and config.ui.language == "tr"

    result = run(
        ["init", "--home", str(home), "--yes", "--force"],
        tmp_path,
        home=None,
        env={"ANTHROPIC_API_KEY": "k"},
    )
    assert result.exit_code == 0, result.output
    assert "Provider: anthropic." in result.output
    assert (home / "persona" / "user.md").read_text("utf-8") == "- Name: Real Person\n"


def test_init_picks_provider_from_home_dotenv(tmp_path: Path) -> None:
    # The documented loop: put the key in <home>/.env, run tau init. Nothing exports that file
    # into the process before init runs, so init must read it itself (never over a set variable).
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text("ANTHROPIC_API_KEY=sk-test-not-real\n", encoding="utf-8")
    result = run(["init", "--home", str(home), "--yes"], tmp_path, home=None)
    assert result.exit_code == 0, result.output
    assert "Provider: anthropic. ANTHROPIC_API_KEY was found" in result.output
    config = Config.load(home, env={})
    assert config.roles["brain"].provider == "anthropic"
    assert config.roles["fast"].provider == "anthropic"
    assert (home / ".env").read_text("utf-8") == "ANTHROPIC_API_KEY=sk-test-not-real\n"

    # TAU_HOME (no --home) reaches the same file; a variable set in the process wins over it
    (home / ".env").write_text("ANTHROPIC_API_KEY=\nTAU_PROXY_KEY_BRAIN=sk-test-not-real\n")
    result = run(["init", "--yes", "--force"], tmp_path, home=home, env={"ANTHROPIC_API_KEY": "k"})
    assert result.exit_code == 0, result.output
    assert "Provider: proxy." in result.output  # the file's proxy key counts too
    assert Config.load(home, env={}).roles["local"].provider == "proxy"
    assert (home / ".env.example").read_text("utf-8") == template_text("dotenv.example")
    assert f"kept  {home / '.env.example'}" in result.output  # --force never touches it


def test_init_home_defaults_to_tau_home(tmp_path: Path) -> None:
    home = tmp_path / "viaenv"
    result = run(["init", "--yes"], tmp_path, home=home)
    assert result.exit_code == 0, result.output
    assert (home / "tau.toml").is_file()
    with pytest.raises(FileExistsError):
        init_home(home, provider="fake", language="en")


def test_version_and_hub_status_do_not_load_provider_entry_points(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    code = (
        "import sys\n"
        "from click.testing import CliRunner\n"
        "from tau_core.cli import cli\n"
        "for args in (['version'], ['hub', 'status']):\n"
        "    r = CliRunner().invoke(cli, args, prog_name='tau')\n"
        "    assert r.exit_code == 0, r.output\n"
        "print('tau_example_provider' in sys.modules, 'strands.models.anthropic' in sys.modules)\n"
    )
    import subprocess

    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "PATH": "/usr/bin:/bin",
            "TAU_HOME": str(config.home),
            "TAU_DATA_DIR": str(config.data_dir),
            "HOME": str(tmp_path),
        },
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False False"


def test_builder_logs_nothing_at_warning_on_a_healthy_install(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING):
        inventory(test_config(tmp_path))
    assert [r for r in caplog.records if r.name.startswith("tau_core")] == []


# -- the proxy in tau doctor ---------------------------------------------------------------------


def test_doctor_checks_the_proxy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tau_core import builder, proxy

    config = test_config(tmp_path)
    (config.home / "tau.toml").write_text(
        "[models.roles.brain]\nprovider = 'proxy'\nmodel_id = 'brain'\n"
        "budget = { usd = 15, period = '1mo' }\n"
        "[models.roles.fast]\nprovider = 'proxy'\nmodel_id = 'fast'\n"
        "budget = { usd = 1, period = '1d' }\n"
        "[models.roles.open]\nprovider = 'proxy'\nmodel_id = 'open'\n"
        "[models.roles.gone]\nprovider = 'proxy'\nmodel_id = 'gone'\n"
        "[models.roles.direct]\nprovider = 'fake'\nmodel_id = 'f'\n"
        "budget = { usd = 1, period = '1d' }\n",
        encoding="utf-8",
    )
    env = {
        "TAU_PROXY_URL": "http://proxy.test",
        "TAU_PROXY_KEY_BRAIN": "sk-b",
        "TAU_PROXY_KEY_FAST": "sk-f",
        "TAU_PROXY_KEY_OPEN": "sk-o",
        "TAU_PROXY_KEY_GONE": "sk-g",
    }
    records = {
        "sk-b": {"spend": 0.4, "max_budget": 15.0, "budget_duration": "1mo"},
        "sk-f": {"spend": 0.1, "max_budget": 5.0, "budget_duration": "1d"},
        "sk-o": {"spend": 0.0, "max_budget": None},
    }

    def fetch(url: str, key: str, **kwargs) -> dict:
        if key not in records:
            raise OSError("HTTP Error 401: Unauthorized")
        return records[key]

    monkeypatch.setattr(proxy, "fetch_key_info", fetch)
    monkeypatch.setattr(builder, "_proxy_alive", lambda url: True)
    by = {c.name: c for c in run_doctor(config.home, env=env)}
    assert by["role brain"].detail == "provider 'proxy', credentials present"
    assert by["proxy brain"].status == "ok"
    assert by["proxy brain"].detail == "$0.40 of $15.00 per 1mo, within budget"
    assert by["proxy fast"].status == "warn" and "run tau proxy keys" in by["proxy fast"].detail
    assert by["proxy open"].status == "warn" and "no budget" in by["proxy open"].detail
    assert by["proxy gone"].status == "fail" and "TAU_PROXY_KEY_GONE" in by["proxy gone"].detail
    assert by["role direct"].status == "warn" and "cannot enforce it" in by["role direct"].detail

    monkeypatch.setattr(builder, "_proxy_alive", lambda url: False)
    by = {c.name: c for c in run_doctor(config.home, env=env)}
    assert by["proxy"].status == "warn"
    assert by["proxy"].detail.startswith("not answering at http://proxy.test; start it with")
    assert "proxy brain" not in by
