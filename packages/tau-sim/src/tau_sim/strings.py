"""The ``tau sim`` message keys, registered into ``tau_core.i18n`` at import.

What ``tau sim`` prints goes through ``t(key, language)`` with the UI language of the
configuration (``[ui] language``, ``TAU_LANG``, ``tau --lang``). Error lines are the English
text of the exception. The keys must not collide with tau-core's table, because
``register_messages`` overrides silently; the assertion at import keeps that honest.
"""

from __future__ import annotations

from tau_core.i18n import MESSAGES, register_messages

SIM_MESSAGES: dict[str, dict[str, str]] = {
    "sim.lamps.header": {
        "en": "Simulated lamps (tau-sim; no real lamp is connected):",
        "tr": "Simüle lambalar (tau-sim; bağlı gerçek bir lamba yok):",
    },
    "sim.lamps.row": {
        "en": "  {name}  {state}  (simulated, since {since})",
        "tr": "  {name}  {state}  (simüle, {since} itibarıyla)",
    },
    "sim.lamps.none": {
        "en": "No simulated lamps are configured: [component.sim] lamps is empty.",
        "tr": "Hiç simüle lamba ayarlı değil: [component.sim] lamps boş.",
    },
    "sim.lamps.file": {
        "en": "State: {path}",
        "tr": "Durum: {path}",
    },
    "sim.on": {"en": "on", "tr": "açık"},
    "sim.off": {"en": "off", "tr": "kapalı"},
}

_collisions = set(SIM_MESSAGES) & set(MESSAGES)
assert not _collisions, f"tau-sim message keys collide with tau-core: {sorted(_collisions)}"

register_messages(SIM_MESSAGES)
