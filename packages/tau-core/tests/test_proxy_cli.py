"""``tau proxy``: keys and budgets synced from tau.toml, rotation that keeps the spend."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from dotenv import dotenv_values
from tau_core import Config
from tau_core import proxy_cli as cli_module
from tau_core.cli import cli
from tau_core.config import BudgetConfig, ConfigError, RoleConfig
from tau_core.proxy_cli import (
    KeyAction,
    ProxyAdminError,
    desired_key,
    rotate_key,
    sync_keys,
)
from tau_core.testing import test_config


class FakeAdmin:
    """The key endpoints of a LiteLLM proxy, in memory."""

    def __init__(self) -> None:
        self.keys: dict[str, dict[str, Any]] = {}
        self.log: list[tuple[str, Any]] = []
        self.fail_generate = False
        self._n = 0

    def add(self, key: str, **fields: Any) -> None:
        self.keys[key] = {"token": f"hash-{key}", "spend": 0.0, **fields}

    def key_info(self, key: str) -> dict | None:
        return dict(self.keys[key]) if key in self.keys else None

    def keys_by_alias(self, alias: str) -> list[dict]:
        return [dict(v) for v in self.keys.values() if v.get("key_alias") == alias]

    def generate(self, fields: dict) -> str:
        if self.fail_generate:
            raise ProxyAdminError(500, "database down")
        if any(v.get("key_alias") == fields["key_alias"] for v in self.keys.values()):
            raise ProxyAdminError(400, "alias exists")
        self._n += 1
        key = f"sk-new-{self._n}"
        self.add(key, **{k: v for k, v in fields.items()})
        self.log.append(("generate", dict(fields)))
        return key

    def update(self, key: str, fields: dict) -> None:
        self.keys[key].update(fields)
        self.log.append(("update", (key, dict(fields))))

    def delete(self, keys: list[str]) -> None:
        for token in keys:
            for key, value in list(self.keys.items()):
                if token in (key, value["token"]):
                    del self.keys[key]
        self.log.append(("delete", list(keys)))


def proxy_config(tmp_path: Path) -> Config:
    config = test_config(tmp_path)
    return config.with_overrides(
        roles={
            "brain": RoleConfig("proxy", "brain", budget=BudgetConfig(15.0, "1mo", "fast")),
            "fast": RoleConfig("proxy", "fast", budget=BudgetConfig(1.0, "1d")),
            "open": RoleConfig("proxy", "open"),
            "test": RoleConfig("fake", "fake"),
        }
    )


def writer(store: dict[str, str]):
    return lambda name, value: store.__setitem__(name, value)


def test_desired_key() -> None:
    assert desired_key("brain", RoleConfig("proxy", "brain", budget=BudgetConfig(2, "1d"))) == {
        "key_alias": "tau-brain",
        "models": ["brain"],
        "metadata": {"tau_role": "brain", "managed_by": "tau proxy keys"},
        "max_budget": 2,
        "budget_duration": "1d",
    }
    assert "max_budget" not in desired_key("open", RoleConfig("proxy", "open"))


def test_sync_creates_updates_and_leaves_alone(tmp_path: Path) -> None:
    config = proxy_config(tmp_path)
    admin = FakeAdmin()
    admin.add(
        "sk-brain", key_alias="tau-brain", models=["brain"], max_budget=10.0, budget_duration="1mo"
    )
    admin.add(
        "sk-fast", key_alias="tau-fast", models=["fast"], max_budget=1.0, budget_duration="1d"
    )
    env = {"TAU_PROXY_KEY_BRAIN": "sk-brain", "TAU_PROXY_KEY_FAST": "sk-fast"}
    written: dict[str, str] = {}
    actions = sync_keys(config, env, admin, writer(written))
    assert [(a.role, a.action) for a in actions] == [
        ("brain", "updated"),
        ("fast", "unchanged"),
        ("open", "created"),
    ]
    assert actions[0].detail == "max_budget → $15.00 per 1mo, then fast"
    assert admin.keys["sk-brain"]["max_budget"] == 15.0
    assert written == {"TAU_PROXY_KEY_OPEN": "sk-new-1"}
    assert "no budget" in actions[2].detail
    assert admin.keys["sk-new-1"]["models"] == ["open"]
    # Only the selected roles; a non-proxy role is refused by name.
    assert [a.role for a in sync_keys(config, env, admin, writer({}), roles=["fast"])] == ["fast"]
    with pytest.raises(ConfigError, match="not a proxy role in tau.toml: test"):
        sync_keys(config, env, admin, writer({}), roles=["test"])


def test_sync_does_not_take_over_a_key_of_another_home(tmp_path: Path) -> None:
    config = proxy_config(tmp_path)
    admin = FakeAdmin()
    admin.add("sk-other", key_alias="tau-brain", models=["brain"], spend=2.5)
    written: dict[str, str] = {}
    with pytest.raises(ProxyAdminError, match="already has a key named tau-brain"):
        sync_keys(config, {}, admin, writer(written), roles=["brain"])
    assert "sk-other" in admin.keys and written == {}
    actions = sync_keys(config, {}, admin, writer(written), roles=["brain"], replace=True)
    assert actions == [
        KeyAction(
            "brain",
            "created",
            "TAU_PROXY_KEY_BRAIN",
            "$15.00 per 1mo, then fast; $2.50 spent this period carried over",
        )
    ]
    assert "sk-other" not in admin.keys
    assert admin.keys[written["TAU_PROXY_KEY_BRAIN"]]["spend"] == 2.5


def test_a_key_the_proxy_forgot_is_replaced(tmp_path: Path) -> None:
    config = proxy_config(tmp_path)
    admin = FakeAdmin()
    written: dict[str, str] = {}
    env = {"TAU_PROXY_KEY_FAST": "sk-gone"}
    (action,) = sync_keys(config, env, admin, writer(written), roles=["fast"])
    assert action.action == "created" and written["TAU_PROXY_KEY_FAST"].startswith("sk-new")


def test_rotate_keeps_the_spend(tmp_path: Path) -> None:
    config = proxy_config(tmp_path)
    admin = FakeAdmin()
    admin.add("sk-old", key_alias="tau-brain", models=["brain"], spend=3.25)
    written: dict[str, str] = {}
    env = {"TAU_PROXY_KEY_BRAIN": "sk-old"}
    action = rotate_key(config, env, admin, writer(written), "brain", clock=lambda: 1000)
    assert action == KeyAction(
        "brain", "rotated", "TAU_PROXY_KEY_BRAIN", "$3.25 spent this period kept"
    )
    new = written["TAU_PROXY_KEY_BRAIN"]
    assert admin.keys[new]["spend"] == 3.25 and admin.keys[new]["key_alias"] == "tau-brain"
    assert "sk-old" not in admin.keys
    assert [entry[0] for entry in admin.log] == ["update", "generate", "delete"]
    assert admin.log[0][1] == ("sk-old", {"key_alias": "tau-brain-rotated-1000"})


def test_rotate_puts_the_old_alias_back_when_creating_fails(tmp_path: Path) -> None:
    config = proxy_config(tmp_path)
    admin = FakeAdmin()
    admin.add("sk-old", key_alias="tau-brain", models=["brain"])
    admin.fail_generate = True
    written: dict[str, str] = {}
    with pytest.raises(ProxyAdminError, match="database down"):
        rotate_key(config, {"TAU_PROXY_KEY_BRAIN": "sk-old"}, admin, writer(written), "brain")
    assert admin.keys["sk-old"]["key_alias"] == "tau-brain" and written == {}
    with pytest.raises(ConfigError, match="not a key the proxy knows"):
        rotate_key(config, {}, admin, writer(written), "brain")


# -- the command ---------------------------------------------------------------------------------


PROXY_TOML = """\
[models.roles.brain]
provider = "proxy"
model_id = "brain"

[models.roles.brain.budget]
usd = 15
period = "1mo"
"""


def home_with(tmp_path: Path, toml: str) -> Path:
    home = tmp_path / "home"
    (home / "persona").mkdir(parents=True)
    (home / "tau.toml").write_text(toml, encoding="utf-8")
    (home / "persona" / "persona.md").write_text("You are tau.\n", encoding="utf-8")
    return home


def test_keys_command_writes_the_key_to_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = home_with(tmp_path, PROXY_TOML)
    admin = FakeAdmin()
    monkeypatch.setattr(cli_module, "_admin", lambda config, env: admin)
    result = CliRunner().invoke(cli, ["--home", str(home), "proxy", "keys"], prog_name="tau")
    assert result.exit_code == 0, result.output
    assert "brain    created   TAU_PROXY_KEY_BRAIN  $15.00 per 1mo" in result.output
    assert dotenv_values(home / ".env") == {"TAU_PROXY_KEY_BRAIN": "sk-new-1"}
    assert (home / ".env").stat().st_mode & 0o777 == 0o600


def test_keys_command_needs_the_master_key_and_a_proxy_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = home_with(tmp_path, PROXY_TOML)
    result = CliRunner().invoke(cli, ["--home", str(home), "proxy", "keys"], prog_name="tau")
    assert result.exit_code == 1
    assert "LITELLM_MASTER_KEY is not set; run infra/litellm/proxy.sh init" in result.output
    plain = home_with(tmp_path / "plain", "[models.roles.brain]\nprovider='fake'\nmodel_id='f'\n")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master")
    result = CliRunner().invoke(cli, ["--home", str(plain), "proxy", "keys"], prog_name="tau")
    assert result.exit_code == 1 and 'no role in tau.toml uses provider = "proxy"' in result.output


def test_spend_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tau_core import proxy

    home = home_with(tmp_path, PROXY_TOML)
    (home / ".env").write_text("TAU_PROXY_KEY_BRAIN=sk-b\n", encoding="utf-8")
    info = {
        "spend": 16.0,
        "max_budget": 15.0,
        "budget_duration": "1mo",
        "budget_reset_at": "2026-10-01T00:00:00+00:00",
    }
    monkeypatch.setattr(proxy, "fetch_key_info", lambda url, key, **kw: dict(info))
    result = CliRunner().invoke(cli, ["--home", str(home), "proxy", "spend"], prog_name="tau")
    assert result.exit_code == 0, result.output
    assert result.output == (
        "  brain    brain    $16.00 of $15.00 per 1mo, resets 2026-10-01 00:00 UTC · SPENT\n"
    )
    result = CliRunner().invoke(
        cli, ["--home", str(home), "proxy", "spend", "--json"], prog_name="tau"
    )
    assert json.loads(result.output)["brain"]["exhausted"] is True
