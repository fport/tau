"""Spend per model role: the ledger on the hub and every place that reads it (ADR 0011).

Every answer of a role with a budget is priced (:mod:`tau_core.prices`) and recorded in a small
SQLite ledger under ``TAU_DATA_DIR`` (``spend.sqlite3``): time, role, provider, model id,
token counts and dollars, never any text. Every process on the hub (``tau chat``, the TUI, the
hub itself) writes to and reads from the same file, so a budget counts every call, whichever
channel made it.

Budgets run per calendar period in tau's time zone (Europe/Istanbul): a ``day`` resets at
midnight, a ``week`` on Monday, a ``month`` on the 1st.

The readers:

- :class:`tau_core.budget.RoleModel` checks a role's period spend before every call;
- the ``budget`` context source (``tau.context``) puts one line under ``## Now``;
- the ``spend`` hub service adds ``GET /spend`` and a ``spend`` key in ``GET /status``;
- ``/status`` in the channels and ``tau spend``.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from tau_core.config import Config, ConfigError

if TYPE_CHECKING:
    from tau_core.hub.control import ControlRequest
    from tau_core.hub.daemon import Hub

__all__ = [
    "LEDGER_FILE",
    "Ledger",
    "RoleSpend",
    "SpendService",
    "context_source",
    "describe",
    "ledger_for",
    "make_service",
    "period_bounds",
    "spend_command",
    "spend_report",
]

logger = logging.getLogger(__name__)

LEDGER_FILE = "spend.sqlite3"
DEFAULT_PERIOD = "month"
"""The period a role without a budget is reported for."""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY,
    at REAL NOT NULL,
    role TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL,
    priced INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS calls_role_at ON calls (role, at);
"""


class Ledger:
    """The spend ledger: one row per priced model call. Safe across processes (SQLite, WAL)."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        connection = sqlite3.connect(self.path, timeout=5.0)
        if new:
            try:
                os.chmod(self.path, 0o600)
            except OSError:  # pragma: no cover - a filesystem without modes
                logger.warning("could not make %s private", self.path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(_SCHEMA)
        return connection

    def record(
        self,
        *,
        role: str,
        provider: str,
        model_id: str,
        usage: Mapping[str, Any],
        cost_usd: float | None,
        at: float | None = None,
    ) -> None:
        """Add one call; ``cost_usd=None`` marks a call on an unpriced model."""
        row = (
            time.time() if at is None else at,
            role,
            provider,
            model_id,
            int(usage.get("inputTokens") or 0),
            int(usage.get("outputTokens") or 0),
            int(usage.get("cacheReadInputTokens") or 0),
            int(usage.get("cacheWriteInputTokens") or 0),
            cost_usd,
            int(cost_usd is not None),
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO calls (at, role, provider, model_id, input_tokens, output_tokens, "
                "cache_read_tokens, cache_write_tokens, cost_usd, priced) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )

    def spent(self, role: str, since: datetime) -> float:
        """Dollars ``role`` spent from ``since`` on (unpriced calls count as 0). Reading never
        creates the ledger: before the first call there is nothing to count."""
        if not self.path.exists():
            return 0.0
        with self._connect() as connection:
            (total,) = connection.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM calls WHERE role = ? AND at >= ?",
                (role, since.timestamp()),
            ).fetchone()
        return float(total)

    def unpriced(self, role: str, since: datetime) -> int:
        """How many of ``role``'s calls since ``since`` had no price."""
        if not self.path.exists():
            return 0
        with self._connect() as connection:
            (count,) = connection.execute(
                "SELECT COUNT(*) FROM calls WHERE role = ? AND at >= ? AND priced = 0",
                (role, since.timestamp()),
            ).fetchone()
        return int(count)


def ledger_for(config: Config) -> Ledger:
    """The ledger of this configuration's data directory."""
    return Ledger(config.data_dir / LEDGER_FILE)


def period_bounds(period: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """``(start, reset)`` of the calendar ``period`` (day, week, month) around ``now``, in
    tau's time zone."""
    from tau_core.persona import TIMEZONE

    local = (now or datetime.now(UTC)).astimezone(TIMEZONE)
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        start = day
        reset = (day + timedelta(days=1, hours=12)).replace(hour=0)
    elif period == "week":
        start = day - timedelta(days=day.weekday())
        reset = (start + timedelta(days=7, hours=12)).replace(hour=0)
    elif period == "month":
        start = day.replace(day=1)
        reset = (start + timedelta(days=32)).replace(day=1)
    else:
        raise ConfigError(f"unknown budget period {period!r}")
    return start, reset


@dataclass(frozen=True)
class RoleSpend:
    """One role's spend in its period, next to its budget."""

    role: str
    provider: str
    model_id: str
    spent: float
    period: str
    since: datetime
    reset_at: datetime
    cap: float | None = None
    degrade_to: str | None = None
    unpriced_calls: int = 0

    @property
    def exhausted(self) -> bool:
        return self.cap is not None and self.spent >= self.cap

    def to_json(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "spent_usd": round(self.spent, 6),
            "cap_usd": self.cap,
            "period": self.period,
            "since": self.since.isoformat(),
            "reset_at": self.reset_at.isoformat(),
            "exhausted": self.exhausted,
            "degrade_to": self.degrade_to,
            "unpriced_calls": self.unpriced_calls,
        }


def spend_report(
    config: Config, *, now: datetime | None = None, ledger: Ledger | None = None
) -> dict[str, RoleSpend]:
    """Every role's spend in its budget period (a role without a budget: this month)."""
    ledger = ledger or ledger_for(config)
    report: dict[str, RoleSpend] = {}
    for name, role in config.roles.items():
        period = role.budget.period if role.budget else DEFAULT_PERIOD
        since, reset = period_bounds(period, now)
        report[name] = RoleSpend(
            role=name,
            provider=role.provider,
            model_id=role.model_id,
            spent=ledger.spent(name, since),
            period=period,
            since=since,
            reset_at=reset,
            cap=role.budget.usd if role.budget else None,
            degrade_to=role.budget.degrade_to if role.budget else None,
            unpriced_calls=ledger.unpriced(name, since),
        )
    return report


_PERIOD_WORDS = {"day": "today", "week": "this week", "month": "this month"}


def describe(spends: Mapping[str, RoleSpend]) -> str | None:
    """One English line for the model and the logs, ``None`` when there is nothing to say:
    ``brain $0.42 of $15.00 this month (resets 01.10.2026 00:00); fast $1.00 of $1.00 today,
    spent (resets …)``. Roles without a budget appear only once they spent something."""
    from tau_core.persona import TIMEZONE

    parts = []
    for spend in spends.values():
        if spend.cap is None and spend.spent <= 0:
            continue
        text = f"{spend.role} ${spend.spent:.2f}"
        if spend.cap is not None:
            text += f" of ${spend.cap:.2f}"
        text += f" {_PERIOD_WORDS.get(spend.period, spend.period)}"
        if spend.exhausted:
            text += ", spent"
            if spend.degrade_to:
                text += f", {spend.degrade_to} answers instead"
        if spend.cap is not None:
            text += f" (resets {spend.reset_at.astimezone(TIMEZONE):%d.%m.%Y %H:%M})"
        parts.append(text)
    return "; ".join(parts) or None


def context_source(config: Config) -> Callable[[], dict[str, Any]]:
    """The ``tau.context`` factory: ``{"budget": describe(...)}``, read from the local ledger
    before every model call (one indexed SQLite query per role, no network). Without any
    budget in tau.toml it says nothing, and the line reads ``unknown``."""
    if not any(role.budget for role in config.roles.values()):
        return lambda: {}

    def source() -> dict[str, Any]:
        return {"budget": describe(spend_report(config))}

    return source


class SpendService:
    """``tau.hub_services`` component: ``GET /spend`` and a ``spend`` key in ``GET /status``."""

    name = "spend"

    def __init__(self, config: Config) -> None:
        self.config = config

    def payload(self) -> dict[str, Any]:
        return {"roles": {name: s.to_json() for name, s in spend_report(self.config).items()}}

    def status(self) -> dict[str, Any]:
        return {self.name: self.payload()}

    def handle_spend(self, request: ControlRequest) -> tuple[int, Any]:
        return 200, self.payload()

    async def start(self, hub: Hub) -> None:
        hub.add_status_source(self.status)
        api = hub.find_service("control-api")
        if api is not None:
            api.add_route("GET", "/spend", self.handle_spend)  # type: ignore[attr-defined]

    async def stop(self) -> None:
        return None


def make_service(config: Config) -> SpendService:
    """The ``tau.hub_services`` factory."""
    return SpendService(config)


def spend_line(spend: RoleSpend) -> str:
    """One ``tau spend`` line."""
    from tau_core.persona import TIMEZONE

    if spend.cap is None and spend.spent <= 0:
        return f"  {spend.role:<8} {spend.provider:<9} no budget (its calls are not counted)"
    cap = f"${spend.cap:.2f}" if spend.cap is not None else "no budget"
    line = f"  {spend.role:<8} {spend.provider:<9} ${spend.spent:.2f} of {cap} "
    line += _PERIOD_WORDS.get(spend.period, spend.period)
    if spend.cap is not None:
        line += f", resets {spend.reset_at.astimezone(TIMEZONE):%d.%m.%Y %H:%M}"
    if spend.exhausted:
        line += " · SPENT" + (f", {spend.degrade_to} answers instead" if spend.degrade_to else "")
    if spend.unpriced_calls:
        line += f" · {spend.unpriced_calls} calls without a price for {spend.model_id}"
    return line


@click.command(
    name="spend",
    help="Show what every model role spent in its budget period (from the ledger under "
    "TAU_DATA_DIR) next to its budget in tau.toml.",
    short_help="Show the spend per model role.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option("--json", "as_json", is_flag=True, help="Print the spend as JSON.")
@click.pass_context
def spend_command(ctx: click.Context, as_json: bool) -> None:
    obj = ctx.find_object(dict) or {}
    try:
        config = Config.load(obj.get("home"))
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    report = spend_report(config)
    if as_json:
        payload = {name: value.to_json() for name, value in report.items()}
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for value in report.values():
        click.echo(spend_line(value))
