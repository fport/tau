"""Tools that ship with tau-core, exposed through the ``tau.tools`` entry point.

Descriptions and effects are Turkish: the model and the user read them.
"""

from __future__ import annotations

from datetime import datetime

from tau_core.persona import TIMEZONE
from tau_core.tiers import Tier, tau_tool

_WEEKDAYS = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")


@tau_tool(tier=Tier.READ)
def current_time() -> str:
    """Şu anki tarih ve saati Europe/Istanbul saat diliminde döndürür."""
    now = datetime.now(TIMEZONE)
    return f"{now:%d.%m.%Y %H:%M:%S}, {_WEEKDAYS[now.weekday()]} (Europe/Istanbul)"


@tau_tool(
    tier=Tier.PHYSICAL,
    effect="Demo: fiziksel bir eylemi taklit eder; gerçek bir cihaz hareket etmez.",
)
def demo_physical_action(action: str) -> str:
    """Fiziksel bir eylemi taklit eden demo aracı (tier 2, her çağrıda onay ister).

    Args:
        action: Yapılacak eylemin kısa açıklaması, örneğin "masa lambasını yak".
    """
    return f"Demo eylem simüle edildi: {action}. Gerçek bir cihaz hareket etmedi."


TOOLS = [current_time, demo_physical_action]
