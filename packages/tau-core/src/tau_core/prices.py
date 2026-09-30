"""Model prices and the cost of one model call (ADR 0011).

tau-core ships ``templates/prices.toml`` (US dollars per million tokens, keyed by model id);
``tau.toml`` extends or overrides it with ``[models.prices."<model_id>"]``. A model that is in
neither is *unpriced*: its calls are recorded with no cost, and ``tau doctor`` warns when a role
with a budget uses one, because that budget could never be reached.

Providers report input tokens differently. Anthropic and Bedrock count cached tokens apart from
``inputTokens``; OpenAI-compatible APIs and Gemini include them in it. :func:`cost` takes that
into account through :data:`CACHE_IN_INPUT`.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from functools import cache
from importlib import resources
from typing import Any

from tau_core.config import Config, ConfigError, Price

__all__ = ["CACHE_IN_INPUT", "FREE_PROVIDERS", "cost", "price_for", "shipped_prices"]

CACHE_IN_INPUT = frozenset({"openai", "gemini", "ollama"})
"""Providers whose ``inputTokens`` already include the cached tokens."""

FREE_PROVIDERS = frozenset({"ollama", "fake"})
"""Providers whose calls cost nothing: a local model and the scripted one."""

_FREE = Price(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0)


@cache
def shipped_prices() -> dict[str, Price]:
    """The ``prices.toml`` shipped with tau-core."""
    raw = tomllib.loads(
        resources.files("tau_core").joinpath("templates", "prices.toml").read_text("utf-8")
    )
    try:
        return {str(model_id): Price(**table) for model_id, table in raw.items()}
    except TypeError as exc:  # pragma: no cover - a broken shipped file
        raise ConfigError(f"tau-core's prices.toml is invalid: {exc}") from exc


def price_for(config: Config, provider: str, model_id: str) -> Price | None:
    """The price of ``model_id``: ``tau.toml`` first, then the shipped table; free for a local
    or scripted provider; ``None`` when nobody knows it."""
    if provider in FREE_PROVIDERS:
        return _FREE
    return config.prices.get(model_id) or shipped_prices().get(model_id)


def cost(usage: Mapping[str, Any], price: Price, provider: str) -> float:
    """Dollars for one call's Strands ``Usage`` (``inputTokens``, ``outputTokens`` and the
    optional ``cacheReadInputTokens``/``cacheWriteInputTokens``)."""
    read = int(usage.get("cacheReadInputTokens") or 0)
    write = int(usage.get("cacheWriteInputTokens") or 0)
    fresh = int(usage.get("inputTokens") or 0)
    if provider in CACHE_IN_INPUT:
        fresh = max(fresh - read - write, 0)
    output = int(usage.get("outputTokens") or 0)
    read_price = price.input if price.cache_read is None else price.cache_read
    write_price = price.input if price.cache_write is None else price.cache_write
    total = fresh * price.input + output * price.output + read * read_price + write * write_price
    return total / 1_000_000
