"""The ``proxy`` provider's model: Strands' ``OpenAIModel`` against the LiteLLM proxy.

Imported only when a role uses the proxy, so ``openai`` stays out of commands that never call a
model. The proxy is ``infra/litellm`` (ADR 0009); budgets and keys are managed by ``tau proxy``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from typing import Any

from strands.models.model import Model
from strands.models.openai import OpenAIModel

from tau_core.models import BudgetDegraded, BudgetExhausted, ProxyUnavailable

__all__ = [
    "BUDGET_ERROR_TYPE",
    "ProxyModel",
    "fetch_key_info",
    "is_budget_error",
    "parse_timestamp",
]

logger = logging.getLogger(__name__)

BUDGET_ERROR_TYPE = "budget_exceeded"
_BUDGET_PHRASES = ("budget has been exceeded", "exceededtokenbudget", "exceeded budget")
KEY_INFO_TIMEOUT = 3.0


def is_budget_error(exc: BaseException) -> bool:
    """Is this (or anything it was raised from) the proxy refusing a key over its budget?

    LiteLLM answers ``429`` with ``{"error": {"type": "budget_exceeded", ...}}``; Strands turns
    a 429 into ``ModelThrottledException`` (and would retry it with backoff), so the chain is
    followed through ``__cause__``, ``__context__`` and ``original_exception``."""
    seen: set[int] = set()
    stack: list[BaseException | None] = [exc]
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if getattr(current, "type", None) == BUDGET_ERROR_TYPE:
            return True
        body = getattr(current, "body", None)
        if isinstance(body, dict):
            error = body.get("error", body)
            if isinstance(error, dict) and error.get("type") == BUDGET_ERROR_TYPE:
                return True
        text = str(current).lower()
        if any(phrase in text for phrase in _BUDGET_PHRASES):
            return True
        stack.extend(
            [current.__cause__, current.__context__, getattr(current, "original_exception", None)]
        )
    return False


def _is_connection_error(exc: BaseException) -> bool:
    import openai

    current: BaseException | None = exc
    for _ in range(8):
        if current is None:
            return False
        if isinstance(current, openai.APIConnectionError):
            return True
        current = current.__cause__ or current.__context__
    return False


def fetch_key_info(base_url: str, api_key: str, *, timeout: float = KEY_INFO_TIMEOUT) -> dict:
    """``GET /key/info`` with the key itself: the proxy's record of that key (``spend``,
    ``max_budget``, ``budget_duration``, ``budget_reset_at``, ``key_alias``, ``models``).

    A virtual key may read its own record, so this needs no master key. Raises ``OSError``
    (``urllib.error.URLError``) or ``ValueError`` on failure."""
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/key/info",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - http(s) only
        payload = json.loads(response.read().decode("utf-8"))
    info = payload.get("info") if isinstance(payload, dict) else None
    if not isinstance(info, dict):
        raise ValueError("the proxy's /key/info answer has no 'info' object")
    return info


def parse_timestamp(raw: Any) -> datetime | None:
    """An ISO timestamp from the proxy (``2026-10-01T00:00:00+00:00``), ``None`` if absent."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value


def _number(raw: Any) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


class ProxyModel(OpenAIModel):
    """Strands' ``OpenAIModel`` against the LiteLLM proxy: one model group, one virtual key.

    On top of the plain client it reads the proxy's response headers (a fallback the proxy
    made is logged, the key's spend updates :mod:`tau_core.spend`), turns a refused budget
    into ``degrade_to`` or :class:`BudgetExhausted` before Strands can retry it as throttling,
    and an unreachable proxy into :class:`ProxyUnavailable`.
    """

    def __init__(self, *, base_url: str, api_key: str, model_id: str, params: dict[str, Any]):
        super().__init__(
            client_args={"base_url": f"{base_url}/v1", "api_key": api_key},
            model_id=model_id,
            params=params,
        )
        self.proxy_url = base_url
        self._api_key = api_key
        self._degrade_role: str | None = None
        self._degrade_factory: Callable[[], Model] | None = None
        self._degrade_model: Model | None = None
        self._notices: list[BudgetDegraded] = []

    @property
    def group(self) -> str:
        return str(self.get_config().get("model_id") or "")

    @property
    def role(self) -> str:
        return str(getattr(self, "tau_role", None) or self.group)

    def set_degrade(self, role: str, factory: Callable[[], Model]) -> None:
        """When this key's budget is spent, answer with ``factory()`` (built once, lazily)."""
        self._degrade_role = role
        self._degrade_factory = factory
        self._degrade_model = None

    def take_notices(self) -> list[BudgetDegraded]:
        """The degrade notices since the last call (the channel shows each once)."""
        notices, self._notices = self._notices, []
        return notices

    def key_info(self) -> dict:
        """This key's record on the proxy (see :func:`fetch_key_info`)."""
        return fetch_key_info(self.proxy_url, self._api_key)

    # Strands builds a fresh AsyncOpenAI client per request from these arguments (so no
    # connection outlives its event loop); the httpx client below lives exactly as long.
    def _resolve_client_args(self) -> dict[str, Any]:
        import openai

        args = dict(super()._resolve_client_args())
        args["http_client"] = openai.DefaultAsyncHttpxClient(
            event_hooks={"response": [self._on_response]}
        )
        return args

    async def _on_response(self, response: Any) -> None:
        headers = response.headers
        try:
            fallbacks = int(headers.get("x-litellm-attempted-fallbacks") or 0)
        except ValueError:
            fallbacks = 0
        if fallbacks > 0:
            logger.warning(
                "role %s: the proxy fell back from model group %s to %s (%s)",
                self.role,
                self.group,
                headers.get("x-litellm-model-group", "?"),
                headers.get("x-litellm-model-name", "?"),
            )
        spend = _number(headers.get("x-litellm-key-spend"))
        if spend is not None:
            from tau_core import spend as spend_module

            spend_module.note_spend(self.proxy_url, self.group, spend)

    async def stream(
        self,
        messages: Any,
        tool_specs: Any = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        started = False
        try:
            async for event in super().stream(messages, tool_specs, system_prompt, **kwargs):
                started = True
                yield event
            return
        except Exception as exc:
            if started:
                raise
            if _is_connection_error(exc):
                raise ProxyUnavailable(self.proxy_url) from exc
            if not is_budget_error(exc):
                raise
            refused = exc
        spend, max_budget, reset_at = await asyncio.to_thread(self._budget_state)
        if self._degrade_factory is None or self._degrade_role is None:
            logger.info("role %s: budget spent and no degrade role", self.role)
            raise BudgetExhausted(
                self.role, spend=spend, max_budget=max_budget, reset_at=reset_at
            ) from refused
        logger.warning(
            "role %s: budget spent (resets %s); answering with role %s",
            self.role,
            reset_at.isoformat() if reset_at else "?",
            self._degrade_role,
        )
        if self._degrade_model is None:
            self._degrade_model = self._degrade_factory()
        try:
            async for event in self._degrade_model.stream(
                messages, tool_specs, system_prompt, **kwargs
            ):
                yield event
        except BudgetExhausted as spent_too:
            raise BudgetExhausted(
                self.role,
                spend=spend,
                max_budget=max_budget,
                reset_at=reset_at,
                also=spent_too,
            ) from spent_too
        self._notices.append(BudgetDegraded(self.role, self._degrade_role, reset_at))

    def _budget_state(self) -> tuple[float | None, float | None, datetime | None]:
        """``(spend, max_budget, reset_at)`` of this key, all ``None`` when unknown."""
        try:
            info = self.key_info()
        except (OSError, ValueError) as exc:
            logger.warning("role %s: could not read the key's budget: %s", self.role, exc)
            return None, None, None
        return (
            _number(info.get("spend")),
            _number(info.get("max_budget")),
            parse_timestamp(info.get("budget_reset_at")),
        )
