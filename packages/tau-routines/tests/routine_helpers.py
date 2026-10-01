"""Test tools (one per tier, plus one that fails), a fake clock and small runners."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from click.testing import CliRunner, Result
from tau_core import Config, Tier, tau_tool
from tau_core.builtin_tools import current_time, demo_physical_action
from tau_core.testing import test_config

ZONE_NAME = "Europe/Istanbul"
ZONE = ZoneInfo(ZONE_NAME)
LAMP_EFFECT = "Switches the hall lamp (test tool; nothing real happens)."


def local(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0):
    """An aware datetime in the test zone (Europe/Istanbul, UTC+3 all year)."""
    return datetime(year, month, day, hour, minute, second, tzinfo=ZONE)


class Clock:
    """A clock the test moves by hand; returns aware UTC datetimes."""

    def __init__(self, start: datetime):
        self.now = start.astimezone(UTC)

    def __call__(self) -> datetime:
        return self.now

    def set(self, moment: datetime) -> None:
        self.now = moment.astimezone(UTC)

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


class SideEffects:
    """What the test tools did, so a refused call can be shown to have done nothing."""

    lamp: list[dict[str, Any]] = []
    notes: list[str] = []
    broken_calls = 0
    flaky_script: list[bool] = []

    @classmethod
    def reset(cls) -> None:
        cls.lamp = []
        cls.notes = []
        cls.broken_calls = 0
        cls.flaky_script = []


@tau_tool(tier=Tier.PHYSICAL, effect=LAMP_EFFECT)
def hall_lamp(on: bool, brightness: int = 100) -> str:
    """Switches the hall lamp (test tool).

    Args:
        on: True for on, False for off.
        brightness: Percent.
    """
    SideEffects.lamp.append({"on": on, "brightness": brightness})
    return f"Hall lamp {'on' if on else 'off'} at {brightness}%."


@tau_tool(tier=Tier.DIGITAL_WRITE)
def write_note(text: str) -> str:
    """Writes a note (test tool).

    Args:
        text: The note.
    """
    SideEffects.notes.append(text)
    return "Noted."


@tau_tool(tier=Tier.PHYSICAL, effect="Opens the garage door (test tool that always fails).")
def broken_door() -> str:
    """Opens the garage door (test tool that always fails)."""
    SideEffects.broken_calls += 1
    raise RuntimeError("the door motor did not answer")


@tau_tool(tier=Tier.PHYSICAL, effect="Feeds the fish (test tool that fails when scripted to).")
def flaky_feeder() -> str:
    """Feeds the fish (test tool)."""
    ok = SideEffects.flaky_script.pop(0) if SideEffects.flaky_script else True
    if not ok:
        raise RuntimeError("the feeder jammed")
    return "Fed."


CATALOG = [demo_physical_action, current_time, hall_lamp, write_note, broken_door, flaky_feeder]


def routine_config(tmp_path: Path, table: str | None = None) -> Config:
    """``test_config`` plus a ``[component.routines]`` table (default: the test zone)."""
    config = test_config(tmp_path)
    toml = config.home / "tau.toml"
    body = table if table is not None else f'timezone = "{ZONE_NAME}"\n'
    toml.write_text(
        toml.read_text(encoding="utf-8") + f"\n[component.routines]\n{body}", encoding="utf-8"
    )
    return Config.load(config.home, env={"TAU_DATA_DIR": str(config.data_dir)})


def run_cli(
    config: Config,
    *args: str,
    clock: Clock | None = None,
    approver: Any = None,
    guard: Any = None,
    tools: list | None = None,
    input: str | None = None,
) -> Result:
    from tau_routines.cli import routine

    obj: dict[str, Any] = {
        "home": config.home,
        "routine_tools": list(CATALOG if tools is None else tools),
    }
    if clock is not None:
        obj["routine_clock"] = clock
    if approver is not None:
        obj["routine_approver"] = approver
    if guard is not None:
        obj["routine_guard"] = guard
    return CliRunner().invoke(
        routine, list(args), obj=obj, input=input, env={"TAU_DATA_DIR": str(config.data_dir)}
    )
