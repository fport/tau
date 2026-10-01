"""The sim component of tau-core: entry points, the public API, the message table, ``tau sim``,
opt-in through ``[component.sim] enabled`` and switching it off through ``[components]``."""

from __future__ import annotations

import json
import re
from importlib import metadata
from pathlib import Path

import tau_core.sim
from click.testing import CliRunner, Result
from tau_core import Config, build_agent, registry
from tau_core.cli import cli
from tau_core.i18n import LANGUAGES, MESSAGES
from tau_core.sim import LampStore
from tau_core.sim.strings import SIM_MESSAGES
from tau_core.testing import FakeGuard, FakeModel

SIM_TOOLS = {"lamp_list", "lamp_set"}


def invoke(config: Config, *args: str) -> Result:
    env = {"TAU_HOME": str(config.home), "TAU_DATA_DIR": str(config.data_dir), "TAU_LANG": None}
    return CliRunner().invoke(cli, list(args), env=env)


def test_entry_points() -> None:
    points = {
        (ep.group, ep.name): ep.value for ep in metadata.distribution("tau-core").entry_points
    }
    assert points[("tau.commands", "sim")] == "tau_core.sim.cli:sim"
    assert points[("tau.tools", "sim")] == "tau_core.sim.tools:TOOLS"
    assert points[("tau.hub_services", "sim")] == "tau_core.sim.service:make_service"


def test_public_api_is_explicit() -> None:
    assert sorted(tau_core.sim.__all__) == sorted(set(tau_core.sim.__all__))
    for name in tau_core.sim.__all__:
        assert hasattr(tau_core.sim, name), name


def test_every_message_has_both_languages() -> None:
    for key, templates in SIM_MESSAGES.items():
        assert key.startswith("sim."), key
        assert set(templates) == set(LANGUAGES), key
        fields = {lang: set(re.findall(r"{(\w+)}", text)) for lang, text in templates.items()}
        assert fields["en"] == fields["tr"], key
        assert MESSAGES[key] == templates


def test_no_turkish_outside_the_message_table() -> None:
    turkish = re.compile(r"[çğıöşüÇĞİÖŞÜ]")
    for path in Path(tau_core.sim.__file__).parent.glob("*.py"):
        if path.name == "strings.py":
            continue
        assert not turkish.search(path.read_text(encoding="utf-8")), path.name


# -- tau sim -----------------------------------------------------------------------------------


def test_tau_sim_lamps_marks_every_lamp_simulated(config: Config) -> None:
    LampStore.from_config(config).set("desk", True)
    result = invoke(config, "sim", "lamps")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == SIM_MESSAGES["sim.lamps.header"]["en"]
    assert re.match(r"^  desk  on  \(simulated, since \d{4}-\d\d-\d\d \d\d:\d\d\)$", lines[1])
    assert re.match(r"^  living-room  off  \(simulated, since ", lines[2])
    assert lines[3] == f"State: {config.data_dir / 'sim' / 'lamps.json'}"

    turkish = invoke(config, "--lang", "tr", "sim", "lamps")
    assert turkish.exit_code == 0, turkish.output
    assert turkish.output.splitlines()[0] == SIM_MESSAGES["sim.lamps.header"]["tr"]


def test_tau_sim_lamps_with_none_and_with_a_bad_table(make_config) -> None:
    empty = make_config("[component.sim]\nenabled = true\nlamps = []\n")
    result = invoke(empty, "sim", "lamps")
    assert result.exit_code == 0 and result.output.strip() == SIM_MESSAGES["sim.lamps.none"]["en"]
    broken = make_config("[component.sim]\nenabled = true\nlamp = ['desk']\n")
    result = invoke(broken, "sim", "lamps")
    assert result.exit_code == 1
    assert "[component.sim] has unknown keys: lamp" in result.output


def test_tau_sim_has_no_way_to_switch_a_lamp(config: Config) -> None:
    result = invoke(config, "sim", "--help")
    assert result.exit_code == 0, result.output
    assert "lamps" in result.output and "set" not in result.output.split("Commands:")[1]


# -- [components] ------------------------------------------------------------------------------


def components(config: Config) -> list[dict]:
    result = invoke(config, "components", "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["config_error"] is None
    names = {*SIM_TOOLS, "sim"}
    return [row for row in payload["components"] if row["name"] in names]


def by_group(rows: list[dict]) -> dict[tuple[str, str], bool]:
    return {(row["group"], row["name"]): row["enabled"] for row in rows}


def catalog(config: Config) -> set[str]:
    """The tools an agent built from ``config`` gets (discovered, minus ``[components]``)."""
    agent = build_agent(config=config, model=FakeModel(), guard=FakeGuard(state="unlocked"))
    return set(agent.catalog.names())


def test_it_is_off_until_enabled(make_config) -> None:
    config = make_config()
    rows = components(config)
    assert by_group(rows) == {
        ("tau.tools", "lamp_list"): False,
        ("tau.tools", "lamp_set"): False,
        ("tau.commands", "sim"): True,
        ("tau.hub_services", "sim"): False,
    }
    assert all(
        "[component.sim] enabled = true" in row["note"] for row in rows if not row["enabled"]
    )
    assert not SIM_TOOLS & catalog(config)
    assert "sim" not in registry.hub_services(config)
    result = invoke(config, "sim", "lamps")
    assert result.exit_code == 0 and result.output.strip() == SIM_MESSAGES["sim.disabled"]["en"]


def test_enabled_it_lists_and_loads_everything(config: Config) -> None:
    assert by_group(components(config)) == {
        ("tau.tools", "lamp_list"): True,
        ("tau.tools", "lamp_set"): True,
        ("tau.commands", "sim"): True,
        ("tau.hub_services", "sim"): True,
    }
    assert SIM_TOOLS <= catalog(config)
    assert "sim" in registry.hub_services(config)


def test_it_can_be_switched_off_through_components(make_config) -> None:
    config = make_config(
        "[component.sim]\nenabled = true\n\n"
        '[components.tools]\ndisabled = ["lamp_list", "lamp_set"]\n\n'
        '[components.hub]\nservices = ["spend"]\n'
    )
    rows = by_group(components(config))
    assert rows[("tau.tools", "lamp_list")] is False
    assert rows[("tau.tools", "lamp_set")] is False
    assert rows[("tau.hub_services", "sim")] is False
    # what the hub and the agent actually load
    assert list(registry.hub_services(config)) == ["spend"]
    assert not SIM_TOOLS & catalog(config)
