"""Test tools (one per tier), a coach definition and small runners shared by the tests."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from tau_core import Tier, TurnEvent, tau_tool
from tau_sub import SubRegistry, SubTau

OWNER_FACT = "The owner is called Ada and trains in the mornings (test fact)."
BELL_EFFECT = "Rings the gym bell (test tool; nothing real happens)."


class SideEffects:
    """What the test tools did, so a refused call can be shown to have done nothing."""

    bells: list[str] = []
    logged: list[str] = []

    @classmethod
    def reset(cls) -> None:
        cls.bells = []
        cls.logged = []


@tau_tool(tier=Tier.READ)
def lookup_plan(day: str) -> str:
    """Returns the saved workout plan for a day (test tool).

    Args:
        day: The weekday, for example "Monday".
    """
    return f"{day}: 20 minutes of intervals."


@tau_tool(tier=Tier.DIGITAL_WRITE)
def log_workout(text: str) -> str:
    """Writes a workout to the log (test tool).

    Args:
        text: What was done.
    """
    SideEffects.logged.append(text)
    return "Logged."


@tau_tool(tier=Tier.PHYSICAL, effect=BELL_EFFECT)
def ring_bell(times: int = 1) -> str:
    """Rings the gym bell (test tool).

    Args:
        times: How often.
    """
    SideEffects.bells.append(str(times))
    return f"Rang {times} times."


CATALOG = [lookup_plan, log_workout, ring_bell]
COACH_PERSONA = "You plan the owner's workouts: three short sessions a week."


def coach(**overrides: Any) -> SubTau:
    fields: dict[str, Any] = {
        "name": "coach",
        "about": "A strict but kind workout coach.",
        "persona": COACH_PERSONA,
        "tools": ("lookup_plan", "ring_bell"),
    }
    fields.update(overrides)
    return SubTau(**fields)


def save_coach(config, catalog: Iterable = CATALOG, **overrides: Any) -> SubTau:
    registry = SubRegistry(config, tools=list(catalog))
    registry.save(coach(**overrides))
    return registry.get(overrides.get("name", "coach"))


def run(agent, prompt: str) -> list[TurnEvent]:
    async def collect() -> list[TurnEvent]:
        return [event async for event in agent.stream(prompt)]

    return asyncio.run(collect())


def tool_names(call) -> list[str]:
    return [spec["name"] for spec in call.tool_specs or []]
