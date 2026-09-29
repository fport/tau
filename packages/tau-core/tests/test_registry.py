"""Component registries: seeds, the four entry-point groups, registrations and the cache.

The ``tau.providers``/``tau.sessions`` and ``tau.context``/``tau.hub_services`` fixtures come
from ``tests/fixtures/tau-example-provider`` and ``tau-example-service``, installed in the dev
group; broken entry points are injected by monkeypatching ``registry._entry_points``.
"""

from __future__ import annotations

import logging
from importlib import metadata
from pathlib import Path

import pytest
from tau_core import (
    PROVIDERS,
    SESSION_BACKENDS,
    Config,
    ConfigError,
    MissingCredentials,
    register_provider,
    register_session_backend,
    registry,
)
from tau_core.config import RoleConfig
from tau_core.models import missing_credentials, required_env, resolve_model
from tau_core.sessions import open_session_store
from tau_core.testing import FakeModel, test_config

LOGGER = "tau_core.registry"


def with_entry_points(monkeypatch: pytest.MonkeyPatch, extra: dict[str, list[metadata.EntryPoint]]):
    real = registry._entry_points

    def fake(group: str) -> list[metadata.EntryPoint]:
        return [*extra.get(group, []), *real(group)]

    monkeypatch.setattr(registry, "_entry_points", fake)
    registry.reset()


def ep(name: str, value: str, group: str) -> metadata.EntryPoint:
    return metadata.EntryPoint(name=name, value=value, group=group)


# -- providers -------------------------------------------------------------------------------


def test_provider_from_another_distribution_is_merged_with_the_seed() -> None:
    merged = registry.providers()
    assert set(PROVIDERS) < set(merged)
    assert "fake2" in merged
    assert registry.provider_names() >= {"bedrock", "anthropic", "fake", "fake2"}
    assert "fake2" not in PROVIDERS  # the seed is never mutated


def test_provider_required_env_attribute_is_merged_into_models(tmp_path: Path) -> None:
    role = RoleConfig(provider="fake2", model_id="m")
    assert required_env(role) == [["EXAMPLE_API_KEY"]]
    assert missing_credentials(role, {}) == ["EXAMPLE_API_KEY"]
    assert missing_credentials(role, {"EXAMPLE_API_KEY": "k"}) == []

    config = test_config(tmp_path, roles={"brain": role})
    with pytest.raises(MissingCredentials, match="EXAMPLE_API_KEY"):
        resolve_model("brain", config, env={})
    model = resolve_model("brain", config, env={"EXAMPLE_API_KEY": "k"})
    assert isinstance(model, FakeModel)
    assert model.default == "fake2 for m (k)"


def test_config_accepts_an_entry_point_provider_by_name_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The entry point cannot be loaded (no such module), yet Config.load accepts the name:
    # validation never calls EntryPoint.load; resolving the role is what fails.
    with_entry_points(
        monkeypatch, {"tau.providers": [ep("ghost", "no_such_module_tau:factory", "tau.providers")]}
    )
    home = tmp_path / "home"
    home.mkdir()
    (home / "tau.toml").write_text(
        '[models.roles.brain]\nprovider = "ghost"\nmodel_id = "m"\n', encoding="utf-8"
    )
    config = Config.load(home, env={})
    assert config.roles["brain"].provider == "ghost"
    # The name is declared, so the failure names the entry point's error, not "unknown".
    with pytest.raises(ConfigError, match="Model provider 'ghost' failed to load: ModuleNotF"):
        resolve_model("brain", config, env={})
    broken = registry.load_error("tau.providers", "ghost")
    assert broken is not None and "no_such_module_tau" in (broken.error or "")
    assert registry.load_error("tau.providers", "fake2") is None
    assert registry.load_error("tau.providers", "never-declared") is None
    with pytest.raises(ConfigError, match="Unknown model provider: 'never-declared'"):
        resolve_model(
            "brain",
            test_config(tmp_path, roles={"brain": RoleConfig("never-declared", "m")}),
            env={},
        )


def test_broken_and_wrong_kind_entry_points_are_logged_and_skipped(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with_entry_points(
        monkeypatch,
        {
            "tau.providers": [
                ep("broken", "tau_example_provider:missing", "tau.providers"),
                ep("odd", "tau_core.registry:GROUPS", "tau.providers"),
            ]
        },
    )
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        merged = registry.providers()
    assert "broken" not in merged and "odd" not in merged and "fake2" in merged
    assert "broken" in caplog.text and "failed to load" in caplog.text
    assert "odd" in caplog.text and "expected a factory" in caplog.text
    rows = {item.name: item for item in registry.load_group("tau.providers")}
    assert rows["broken"].error is not None and rows["broken"].distribution == "?"
    assert rows["fake2"].error is None and rows["fake2"].distribution == "tau-example-provider"
    assert rows["fake2"].version == "0.0.1"


def test_entry_point_cannot_replace_a_built_in(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with_entry_points(
        monkeypatch,
        {"tau.providers": [ep("fake", "tau_example_provider:make_model", "tau.providers")]},
    )
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert registry.provider_factory("fake") is PROVIDERS["fake"]
    assert "would replace the built-in fake" in caplog.text


def test_register_provider_replaces_and_invalidates_the_cache(tmp_path: Path) -> None:
    before = registry.providers()  # fills the cache
    assert "mine" not in before

    def mine(role_cfg: RoleConfig, env) -> FakeModel:
        return FakeModel(default=f"mine {env.get('MINE_TOKEN')}")

    register_provider("mine", mine, required_env=[["MINE_TOKEN"]])
    assert registry.provider_factory("mine") is mine
    assert "mine" in registry.provider_names()
    assert registry.provider_required_env("mine") == [["MINE_TOKEN"]]
    assert "mine" not in PROVIDERS

    role = RoleConfig(provider="mine", model_id="m")
    assert missing_credentials(role, {}) == ["MINE_TOKEN"]
    config = test_config(tmp_path, roles={"brain": role})
    model = resolve_model("brain", config, env={"MINE_TOKEN": "t"})
    assert isinstance(model, FakeModel) and model.default == "mine t"

    # an in-process registration wins over the seed and over an entry point
    register_provider("fake2", mine)
    assert registry.provider_factory("fake2") is mine
    assert registry.provider_required_env("fake2") == []
    with pytest.raises(TypeError):
        register_provider("bad", "not callable")  # type: ignore[arg-type]


def test_reset_forgets_registrations() -> None:
    register_provider("temp", lambda role_cfg, env: FakeModel())
    assert "temp" in registry.provider_names()
    registry.reset()
    assert "temp" not in registry.provider_names()
    assert registry.provider_factory("temp") is None


# -- sessions --------------------------------------------------------------------------------


def test_session_backend_from_another_distribution(tmp_path: Path) -> None:
    assert "example" in registry.session_backend_names()
    assert "example" not in SESSION_BACKENDS
    home = tmp_path / "home"
    home.mkdir()
    (home / "tau.toml").write_text(
        '[models.roles.brain]\nprovider = "fake"\nmodel_id = "m"\n'
        '[sessions]\nbackend = "example"\n',
        encoding="utf-8",
    )
    config = Config.load(home, env={})
    store = open_session_store(config)
    assert getattr(store, "example", False) is True


def test_register_session_backend(config: Config) -> None:
    from tau_core import MemorySessionStore

    marker = MemorySessionStore()
    register_session_backend("mine", lambda config: marker)
    assert registry.session_backend_factory("mine") is not None
    assert open_session_store(config.with_overrides(sessions=config.sessions.__class__("mine")))
    assert (
        open_session_store(config.with_overrides(sessions=config.sessions.__class__("mine")))
        is marker
    )


# -- context sources and hub services --------------------------------------------------------


def test_context_sources_are_built_from_entry_points(config: Config) -> None:
    sources = registry.context_sources(config)
    assert set(sources) == {"example"}
    assert sources["example"]() == {"nodes": None}  # nothing configured: unknown


def test_context_source_reads_its_component_table(config: Config) -> None:
    config = config.with_overrides(component_tables={"example": {"nodes": ["mac", "arm"]}})
    assert registry.context_sources(config)["example"]() == {"nodes": ["mac", "arm"]}
    assert config.component("example") == {"nodes": ["mac", "arm"]}
    assert config.component("nothing") == {}


def test_components_list_selects_and_warns_about_unknown_names(
    config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    from tau_core.config import ComponentsConfig

    only = config.with_overrides(components=ComponentsConfig(context=("nope",)))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert registry.context_sources(only) == {}
    assert "no installed component is called nope" in caplog.text
    both = config.with_overrides(components=ComponentsConfig(context=("example", "nope")))
    assert set(registry.context_sources(both)) == {"example"}


def test_hub_services_are_built_and_checked(
    config: Config, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with_entry_points(
        monkeypatch,
        {
            "tau.hub_services": [
                ep("not_a_service", "tau_core.registry:discover", "tau.hub_services"),
                ep("raises", "tau_core.config:ConfigError", "tau.hub_services"),
            ]
        },
    )
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        services = registry.hub_services(config)
    assert set(services) == {"example", "telegram"}
    assert services["example"].name == "example"
    assert "not_a_service" in caplog.text and "expected a HubService" in caplog.text
    # ConfigError(config) builds an exception instance, which is not a service either
    assert "raises" in caplog.text


def test_seed_rows_carry_the_installed_version() -> None:
    from tau_core import __version__

    rows = {item.name: item for item in registry.seeds("tau.providers")}
    assert set(rows) == set(PROVIDERS)
    assert rows["fake"].distribution == "tau-core" and rows["fake"].version == __version__
    assert registry.seeds("tau.context") == []
