"""A role's model with tau's budget and failover around it (ADR 0011).

:func:`tau_core.models.resolve_model` wraps the model of a role that has a ``budget`` or a
``failover`` in :class:`RoleModel`. Before a call, it compares the role's spend in the current
period (:mod:`tau_core.spend`) with the cap:

- under the cap, the call goes to the provider, and the answer's token usage is priced
  (:mod:`tau_core.prices`) and written to the ledger;
- at the cap, the role's ``budget.degrade_to`` answers instead and the channel says so, or,
  without one, :class:`~tau_core.models.BudgetExhausted` ends the turn with one sentence that
  says when the budget resets.

When the provider cannot be reached before anything streamed (Ollama on a sleeping Mac, a
connection refused, a 5xx), the role's ``failover`` answers instead, and the channel says so.
Throttling is left to Strands' own retry.

Stand-in roles are ordinary roles: their own budget and failover apply, and their spend is
recorded under their own name.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Callable
from datetime import datetime
from typing import Any

from strands.models.model import Model
from strands.types.exceptions import ModelThrottledException

from tau_core.config import BudgetConfig, Config
from tau_core.models import BudgetDegraded, BudgetExhausted, FailedOver
from tau_core.prices import cost, price_for
from tau_core.spend import Ledger, ledger_for, period_bounds

__all__ = ["RoleModel", "is_unavailable"]

logger = logging.getLogger(__name__)

_UNREACHABLE_NAMES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "RemoteProtocolError",
        "ServiceUnavailableError",
    }
)


def is_unavailable(exc: BaseException) -> bool:
    """Could the model not be reached, or did its provider fail on its side? Connection
    errors, timeouts and 5xx answers anywhere in the chain count; throttling does not (Strands
    retries it)."""
    seen: set[int] = set()
    current: BaseException | None = exc
    stack: list[BaseException | None] = [exc]
    while stack:
        current = stack.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, ModelThrottledException):
            return False
        if isinstance(current, ConnectionError | TimeoutError):
            return True
        if type(current).__name__ in _UNREACHABLE_NAMES:
            return True
        status = getattr(current, "status_code", None)
        if not isinstance(status, int):
            status = getattr(current, "code", None)
        if isinstance(status, int) and 500 <= status < 600:
            return True
        stack.extend(
            [current.__cause__, current.__context__, getattr(current, "original_exception", None)]
        )
    return False


class RoleModel(Model):
    """One role's provider model inside tau's budget and failover (see the module docstring).

    Everything a Strands agent asks of a model (``get_config``, ``update_config``,
    ``count_tokens``, ``stateful``, ``structured_output``) goes to the wrapped model;
    :meth:`stream` adds the budget, the ledger and the failover.
    """

    def __init__(
        self,
        inner: Model,
        *,
        role: str,
        provider: str,
        model_id: str,
        config: Config,
        budget: BudgetConfig | None = None,
        degrade: str | None = None,
        degrade_factory: Callable[[], Model] | None = None,
        failover: str | None = None,
        failover_factory: Callable[[], Model] | None = None,
        ledger: Ledger | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.inner = inner
        self.role = role
        self.provider = provider
        self.model_id = model_id
        self.budget = budget
        self.price = price_for(config, provider, model_id)
        self.ledger = ledger or ledger_for(config)
        self._clock = clock
        self._stand_ins: dict[str, tuple[str, Callable[[], Model]] | None] = {
            "degrade": (degrade, degrade_factory) if degrade and degrade_factory else None,
            "failover": (failover, failover_factory) if failover and failover_factory else None,
        }
        self._built: dict[str, Model] = {}
        self._notices: list[Any] = []

    # -- the Model interface, delegated ----------------------------------------------------

    def update_config(self, **model_config: Any) -> None:
        self.inner.update_config(**model_config)

    def get_config(self) -> Any:
        return self.inner.get_config()

    @property
    def stateful(self) -> bool:
        return self.inner.stateful

    async def count_tokens(self, *args: Any, **kwargs: Any) -> int:
        return await self.inner.count_tokens(*args, **kwargs)

    def structured_output(self, *args: Any, **kwargs: Any) -> AsyncGenerator[Any, None]:
        return self.inner.structured_output(*args, **kwargs)

    # -- what the channel shows about this role's calls ------------------------------------

    def take_notices(self) -> list[Any]:
        """The degrade and failover notices since the last call (each shown once)."""
        notices, self._notices = self._notices, []
        return notices

    # -- the call --------------------------------------------------------------------------

    def _now(self) -> datetime | None:
        return self._clock() if self._clock is not None else None

    def _stand_in(self, kind: str) -> tuple[str, Model] | None:
        entry = self._stand_ins[kind]
        if entry is None:
            return None
        name, factory = entry
        if kind not in self._built:
            self._built[kind] = factory()
        return name, self._built[kind]

    def _spent(self) -> tuple[float, datetime] | None:
        """``(spent, reset_at)`` when the budget is spent, else ``None``."""
        if self.budget is None:
            return None
        since, reset = period_bounds(self.budget.period, self._now())
        spent = self.ledger.spent(self.role, since)
        return (spent, reset) if spent >= self.budget.usd else None

    def _record(self, usage: dict[str, Any]) -> None:
        dollars = None if self.price is None else cost(usage, self.price, self.provider)
        try:
            self.ledger.record(
                role=self.role,
                provider=self.provider,
                model_id=self.model_id,
                usage=usage,
                cost_usd=dollars,
            )
        except Exception:
            logger.exception("role %s: could not record the call's spend", self.role)

    async def stream(
        self,
        messages: Any,
        tool_specs: Any = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        spent = self._spent()
        if spent is not None:
            async for event in self._degraded(spent, messages, tool_specs, system_prompt, kwargs):
                yield event
            return
        usage: dict[str, Any] | None = None
        started = False
        try:
            async for event in self.inner.stream(messages, tool_specs, system_prompt, **kwargs):
                if isinstance(event, dict) and isinstance(event.get("metadata"), dict):
                    usage = event["metadata"].get("usage") or usage
                started = True
                yield event
        except Exception as exc:
            failover = None if started else self._stand_in("failover")
            if failover is None or not is_unavailable(exc):
                raise
            name, model = failover
            logger.warning(
                "role %s: %s %s is not reachable (%s); %s answers instead",
                self.role,
                self.provider,
                self.model_id,
                " ".join(str(exc).split())[:160] or type(exc).__name__,
                name,
            )
            self._notices.append(FailedOver(self.role, name))
            async for event in model.stream(messages, tool_specs, system_prompt, **kwargs):
                yield event
            self._take_from(model)
            return
        finally:
            if usage:
                self._record(usage)

    async def _degraded(
        self,
        spent: tuple[float, datetime],
        messages: Any,
        tool_specs: Any,
        system_prompt: str | None,
        kwargs: dict[str, Any],
    ) -> AsyncGenerator[Any, None]:
        dollars, reset = spent
        cap = self.budget.usd if self.budget else None
        degrade = self._stand_in("degrade")
        if degrade is None:
            logger.info("role %s: budget spent and no degrade role", self.role)
            raise BudgetExhausted(self.role, spend=dollars, max_budget=cap, reset_at=reset)
        name, model = degrade
        logger.warning(
            "role %s: budget spent ($%.2f of $%.2f, resets %s); %s answers instead",
            self.role,
            dollars,
            cap or 0,
            reset.isoformat(),
            name,
        )
        try:
            async for event in model.stream(messages, tool_specs, system_prompt, **kwargs):
                yield event
        except BudgetExhausted as spent_too:
            raise BudgetExhausted(
                self.role, spend=dollars, max_budget=cap, reset_at=reset, also=spent_too
            ) from spent_too
        self._notices.append(BudgetDegraded(self.role, name, reset))
        self._take_from(model)

    def _take_from(self, model: Model) -> None:
        """Pass on what the stand-in has to say (its own degrade or failover)."""
        take = getattr(model, "take_notices", None)
        if callable(take):
            self._notices.extend(take())
