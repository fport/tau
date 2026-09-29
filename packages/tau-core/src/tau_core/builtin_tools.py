"""Tools that ship with tau-core, exposed through the ``tau.tools`` entry point.

Descriptions and effects are English: the model reads them, and approval prompts show the
effect verbatim.
"""

from __future__ import annotations

from datetime import datetime

from tau_core.persona import TIMEZONE
from tau_core.tiers import Tier, tau_tool

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@tau_tool(tier=Tier.READ)
def current_time() -> str:
    """Returns the current date and time in the Europe/Istanbul time zone."""
    now = datetime.now(TIMEZONE)
    return f"{now:%d.%m.%Y %H:%M:%S}, {_WEEKDAYS[now.weekday()]} (Europe/Istanbul)"


@tau_tool(
    tier=Tier.PHYSICAL,
    effect="Demo: simulates a physical action; no real device moves.",
)
def demo_physical_action(action: str) -> str:
    """Demo tool that simulates a physical action (tier 2, asks for approval on every call).

    Args:
        action: A short description of the action, for example "turn on the desk lamp".
    """
    return f"Demo action simulated: {action}. No real device moved."


TOOLS = [current_time, demo_physical_action]
