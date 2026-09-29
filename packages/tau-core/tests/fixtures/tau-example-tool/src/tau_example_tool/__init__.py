"""Test fixture: a tool that reaches tau from a separate distribution via ``tau.tools``."""

from tau_core import Tier, tau_tool


@tau_tool(tier=Tier.READ)
def example_echo(text: str) -> str:
    """Verilen metni aynen geri döndürür (test eklentisi).

    Args:
        text: Geri döndürülecek metin.
    """
    return text


TOOLS = [example_echo]
