from __future__ import annotations

import logging
from pathlib import Path

import pytest
from strands import Agent
from strands.models.anthropic import AnthropicModel
from strands.models.bedrock import BedrockModel
from tau_core import Config, ConfigError, MissingCredentials
from tau_core.config import RoleConfig
from tau_core.models import missing_credentials, required_env, resolve_model
from tau_core.testing import FakeModel, ToolCall
from tau_core.tiers import Tier, tau_tool

BEDROCK = RoleConfig(provider="bedrock", model_id="bedrock-model")
ANTHROPIC = RoleConfig(provider="anthropic", model_id="anthropic-model")

TOML = """\
[models.roles.brain]
provider = "bedrock"
model_id = "bedrock-model"
max_tokens = 512

[models.roles.brain.fallback]
provider = "anthropic"
model_id = "anthropic-model"

[models.roles.fast]
provider = "anthropic"
model_id = "anthropic-fast"

[models.roles.test]
provider = "fake"
model_id = "fake"

[models.roles.local]
provider = "ollama"
model_id = "qwen3:8b"
"""


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    (tmp_path / "tau.toml").write_text(TOML, encoding="utf-8")
    return Config.load(tmp_path, env={})


def test_required_env_tables() -> None:
    assert ["AWS_REGION", "AWS_PROFILE"] in required_env(BEDROCK)
    with_region = RoleConfig(provider="bedrock", model_id="m", region="eu-central-1")
    assert ["AWS_PROFILE"] in required_env(with_region)
    assert required_env(ANTHROPIC) == [["ANTHROPIC_API_KEY"]]
    custom = RoleConfig(provider="anthropic", model_id="m", params={"api_key_env": "MY_KEY"})
    assert required_env(custom) == [["MY_KEY"]]
    assert required_env(RoleConfig(provider="fake", model_id="f")) == []


@pytest.mark.parametrize(
    ("env", "missing"),
    [
        ({}, ["AWS_REGION", "AWS_PROFILE"]),
        ({"AWS_REGION": "eu-central-1"}, ["AWS_PROFILE"]),
        ({"AWS_REGION": "eu-central-1", "AWS_PROFILE": "tau"}, []),
        ({"AWS_REGION": "r", "AWS_ACCESS_KEY_ID": "a", "AWS_SECRET_ACCESS_KEY": "s"}, []),
        ({"AWS_REGION": "r", "AWS_BEARER_TOKEN_BEDROCK": "b"}, []),
        ({"AWS_REGION": "", "AWS_PROFILE": "tau"}, ["AWS_REGION"]),
    ],
)
def test_missing_credentials_bedrock(env: dict[str, str], missing: list[str]) -> None:
    assert missing_credentials(BEDROCK, env) == missing


def test_missing_credentials_anthropic_and_fake() -> None:
    assert missing_credentials(ANTHROPIC, {}) == ["ANTHROPIC_API_KEY"]
    assert missing_credentials(ANTHROPIC, {"ANTHROPIC_API_KEY": "k"}) == []
    assert missing_credentials(RoleConfig(provider="fake", model_id="f"), {}) == []


def test_resolve_fake(cfg: Config) -> None:
    assert isinstance(resolve_model("test", cfg, env={}), FakeModel)


def test_resolve_bedrock(cfg: Config) -> None:
    env = {"AWS_REGION": "eu-central-1", "AWS_ACCESS_KEY_ID": "a", "AWS_SECRET_ACCESS_KEY": "s"}
    model = resolve_model("brain", cfg, env=env)
    assert isinstance(model, BedrockModel)
    assert model.get_config()["model_id"] == "bedrock-model"
    assert model.get_config()["max_tokens"] == 512


def test_resolve_anthropic(cfg: Config) -> None:
    model = resolve_model("fast", cfg, env={"ANTHROPIC_API_KEY": "k"})
    assert isinstance(model, AnthropicModel)
    assert model.get_config()["model_id"] == "anthropic-fast"


def test_resolve_anthropic_workspace_header(cfg: Config) -> None:
    """An org-level key needs the workspace header; tau reads it from the env or params."""
    plain = resolve_model("fast", cfg, env={"ANTHROPIC_API_KEY": "k"})
    assert "anthropic-workspace-id" not in plain.client.default_headers

    from_env = resolve_model(
        "fast", cfg, env={"ANTHROPIC_API_KEY": "k", "ANTHROPIC_WORKSPACE_ID": "wrksp_env"}
    )
    assert from_env.client.default_headers["anthropic-workspace-id"] == "wrksp_env"

    role = RoleConfig(provider="anthropic", model_id="m", params={"workspace_id": "wrksp_toml"})
    from_params = resolve_model(
        "fast",
        cfg.with_overrides(roles={**cfg.roles, "fast": role}),
        env={"ANTHROPIC_API_KEY": "k"},
    )
    assert from_params.client.default_headers["anthropic-workspace-id"] == "wrksp_toml"
    assert "workspace_id" not in (from_params.get_config().get("params") or {})


def test_fallback_used_with_warning(cfg: Config, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="tau_core.models"):
        model = resolve_model("brain", cfg, env={"ANTHROPIC_API_KEY": "k"})
    assert isinstance(model, AnthropicModel)
    assert model.get_config()["model_id"] == "anthropic-model"
    assert "fallback" in caplog.text


def test_missing_credentials_error_is_turkish(cfg: Config) -> None:
    with pytest.raises(MissingCredentials) as info:
        resolve_model("brain", cfg, env={})
    exc = info.value
    assert (exc.role, exc.provider, exc.variables) == (
        "brain",
        "bedrock",
        ["AWS_REGION", "AWS_PROFILE"],
    )
    assert str(exc).startswith(
        "Model kimlik bilgileri eksik (brain rolü, bedrock). "
        "Şu değişkenleri .env dosyasına ekleyin: AWS_REGION, AWS_PROFILE"
    )
    assert "Örnek isimler .env.example dosyasında." in str(exc)


def test_planned_and_unknown(cfg: Config) -> None:
    with pytest.raises(ConfigError, match="issue 012"):
        resolve_model("local", cfg, env={})
    with pytest.raises(ConfigError, match="rolü tau.toml içinde tanımlı değil"):
        resolve_model("nope", cfg, env={})


# -- FakeModel through a real Strands Agent ---------------------------------------------------


async def test_fake_model_text_stream() -> None:
    model = FakeModel(["Merhaba efendim, nasıl yardımcı olabilirim?"])
    agent = Agent(model=model, system_prompt="sistem", callback_handler=None)
    deltas = [e["data"] async for e in agent.stream_async("selam") if "data" in e]
    assert len(deltas) == 2
    assert "".join(deltas) == "Merhaba efendim, nasıl yardımcı olabilirim?"
    assert model.calls[0].system_prompt == "sistem"
    assert model.calls[0].messages[-1]["content"][0]["text"] == "selam"


async def test_fake_model_tool_call_stream() -> None:
    seen: list[str] = []

    @tau_tool(tier=Tier.READ)
    def echo(text: str) -> str:
        """Echo."""
        seen.append(text)
        return f"yankı: {text}"

    model = FakeModel([[ToolCall("echo", {"text": "a"})], "bitti"])
    agent = Agent(model=model, tools=[echo], callback_handler=None)
    result = await agent.invoke_async("dene")
    assert seen == ["a"]
    assert str(result).strip() == "bitti"
    tool_result = model.calls[1].messages[-1]["content"][0]["toolResult"]
    assert tool_result["toolUseId"] == "t1"
    assert tool_result["content"][0]["text"] == "yankı: a"
    assert [s["name"] for s in model.calls[0].tool_specs] == ["echo"]


async def test_fake_model_callable_and_default() -> None:
    model = FakeModel([lambda messages, system: f"{len(messages)} mesaj"], default="varsayılan")
    agent = Agent(model=model, callback_handler=None)
    assert str(await agent.invoke_async("bir")).strip() == "1 mesaj"
    assert str(await agent.invoke_async("iki")).strip() == "varsayılan"
