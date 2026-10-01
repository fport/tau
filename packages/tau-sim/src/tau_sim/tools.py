"""The lamp tools (``tau.tools`` entry point ``sim``).

- ``lamp_list`` (tier 0) lists the simulated lamps and whether each is on.
- ``lamp_set`` (tier 2) switches one. It stands for a physical action, so every call needs the
  owner's approval like a real lamp will; the approval shows :data:`SET_EFFECT`.

Every answer says the lamps are simulated, the failures too, so the model never tells the owner
that a real lamp changed. A real lamp arrives later as an MCP node with the same tool names
(069 decides its tiers), so routines that call ``lamp_set`` keep working.

The tools find the configuration lazily at call time (``Config.load()``); tests replace
:data:`config_factory`. Answers are short English for the model.
"""

from __future__ import annotations

from collections.abc import Callable

from tau_core import Config, ConfigError, Tier, tau_tool

from tau_sim.lamps import LampStore, UnknownLamp

__all__ = ["SET_EFFECT", "SIMULATED_NOTE", "TOOLS", "config_factory", "lamp_list", "lamp_set"]

SET_EFFECT = "Switches a simulated lamp on or off. It is a simulation: no real device changes."
SIMULATED_NOTE = "These lamps are simulated by tau-sim: no real lamp is connected."

config_factory: Callable[[], Config] | None = None
"""Replaces ``Config.load()`` (tests); ``None`` = the default."""


def _store() -> LampStore:
    config = config_factory() if config_factory is not None else Config.load()
    return LampStore.from_config(config)


def _word(on: bool) -> str:
    return "on" if on else "off"


def _unavailable(exc: BaseException) -> str:
    detail = " ".join(str(exc).split()) or type(exc).__name__
    return f"The simulated lamps are not available: {detail} {SIMULATED_NOTE}"


@tau_tool(tier=Tier.READ)
def lamp_list() -> str:
    """Lists the owner's lamps and whether each one is on. They are simulated by tau-sim: no
    real lamp is connected, so say so when you tell the owner about them."""
    try:
        lamps = _store().lamps()
    except (ConfigError, OSError) as exc:
        return _unavailable(exc)
    if not lamps:
        return (
            f"No simulated lamps are configured ([component.sim] lamps is empty). {SIMULATED_NOTE}"
        )
    lines = ["Simulated lamps (tau-sim; no real lamp is connected):"]
    lines += [f"- {lamp.name}: {_word(lamp.on)} (simulated)" for lamp in lamps]
    return "\n".join(lines)


@tau_tool(tier=Tier.PHYSICAL, effect=SET_EFFECT)
def lamp_set(name: str, on: bool) -> str:
    """Switches one of the owner's lamps on or off. The lamps are simulated by tau-sim: no
    real lamp changes, so say so when you tell the owner.

    Args:
        name: The lamp's name as lamp_list shows it, for example "desk".
        on: true to switch the lamp on, false to switch it off.
    """
    try:
        store = _store()
        lamp, changed = store.set(name, on)
    except UnknownLamp as exc:
        known = ", ".join(exc.known) or "none"
        return f"No simulated lamp is called {name!r}; nothing changed. Simulated lamps: {known}."
    except (ConfigError, OSError) as exc:
        return _unavailable(exc)
    if not changed:
        return (
            f"The simulated lamp {lamp.name} was already {_word(lamp.on)}; nothing changed. "
            f"{SIMULATED_NOTE}"
        )
    return f"The simulated lamp {lamp.name} is now {_word(lamp.on)}. {SIMULATED_NOTE}"


TOOLS = [lamp_list, lamp_set]
