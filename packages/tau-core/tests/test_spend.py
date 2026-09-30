"""The spend ledger, calendar periods, the report and its readers (ADR 0011)."""

from __future__ import annotations

import asyncio
import json
import stat
from datetime import UTC, datetime
from pathlib import Path

from click.testing import CliRunner
from tau_core import Config
from tau_core.cli import cli
from tau_core.config import BudgetConfig, RoleConfig
from tau_core.hub.control import ControlApi, ControlRequest
from tau_core.persona import TIMEZONE, default_context_factory
from tau_core.spend import (
    Ledger,
    RoleSpend,
    SpendService,
    context_source,
    describe,
    ledger_for,
    period_bounds,
    spend_report,
)
from tau_core.testing import test_config

NOW = datetime(2026, 9, 30, 14, 0, tzinfo=TIMEZONE)  # a Wednesday


def budgeted(tmp_path: Path) -> Config:
    config = test_config(tmp_path)
    return config.with_overrides(
        roles={
            "brain": RoleConfig(
                "anthropic", "claude-sonnet-5", budget=BudgetConfig(15.0, "month", "fast")
            ),
            "fast": RoleConfig("anthropic", "claude-haiku-4-5", budget=BudgetConfig(1.0, "day")),
            "local": RoleConfig("ollama", "qwen3.5:9b", failover="fast"),
        }
    )


def at(day: int, hour: int = 12, month: int = 9) -> float:
    return datetime(2026, month, day, hour, tzinfo=TIMEZONE).timestamp()


def usage(inp: int = 100, out: int = 50) -> dict:
    return {"inputTokens": inp, "outputTokens": out, "totalTokens": inp + out}


def test_period_bounds_are_calendar_periods_in_istanbul() -> None:
    assert period_bounds("day", NOW) == (
        datetime(2026, 9, 30, tzinfo=TIMEZONE),
        datetime(2026, 10, 1, tzinfo=TIMEZONE),
    )
    assert period_bounds("week", NOW) == (
        datetime(2026, 9, 28, tzinfo=TIMEZONE),  # Monday
        datetime(2026, 10, 5, tzinfo=TIMEZONE),
    )
    assert period_bounds("month", NOW) == (
        datetime(2026, 9, 1, tzinfo=TIMEZONE),
        datetime(2026, 10, 1, tzinfo=TIMEZONE),
    )
    december = datetime(2026, 12, 31, 23, 59, tzinfo=TIMEZONE)
    assert period_bounds("month", december)[1] == datetime(2027, 1, 1, tzinfo=TIMEZONE)
    # 22:30 UTC on the 30th is already the 1st in Istanbul (UTC+3).
    late = datetime(2026, 9, 30, 22, 30, tzinfo=UTC)
    assert period_bounds("day", late)[0] == datetime(2026, 10, 1, tzinfo=TIMEZONE)


def test_ledger_records_and_sums_per_role_and_period(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "data" / "spend.sqlite3")
    ledger.record(
        role="brain", provider="anthropic", model_id="m", usage=usage(), cost_usd=0.5, at=at(29)
    )
    ledger.record(
        role="brain", provider="anthropic", model_id="m", usage=usage(), cost_usd=0.25, at=at(30)
    )
    ledger.record(
        role="brain", provider="x", model_id="unpriced", usage=usage(), cost_usd=None, at=at(30)
    )
    ledger.record(
        role="fast", provider="anthropic", model_id="m", usage=usage(), cost_usd=9.0, at=at(30)
    )
    assert ledger.spent("brain", datetime(2026, 9, 30, tzinfo=TIMEZONE)) == 0.25
    assert ledger.spent("brain", datetime(2026, 9, 1, tzinfo=TIMEZONE)) == 0.75
    assert ledger.unpriced("brain", datetime(2026, 9, 1, tzinfo=TIMEZONE)) == 1
    assert ledger.spent("nobody", datetime(2026, 9, 1, tzinfo=TIMEZONE)) == 0.0
    assert stat.S_IMODE(ledger.path.stat().st_mode) == 0o600  # life data stays private
    # A second process (a second Ledger on the same file) sees the same numbers.
    assert Ledger(ledger.path).spent("fast", datetime(2026, 9, 30, tzinfo=TIMEZONE)) == 9.0


def test_spend_report_and_describe(tmp_path: Path) -> None:
    config = budgeted(tmp_path)
    ledger = ledger_for(config)
    ledger.record(
        role="brain",
        provider="anthropic",
        model_id="claude-sonnet-5",
        usage=usage(),
        cost_usd=0.42,
        at=at(30),
    )
    ledger.record(
        role="fast",
        provider="anthropic",
        model_id="claude-haiku-4-5",
        usage=usage(),
        cost_usd=1.0,
        at=at(30),
    )
    ledger.record(
        role="fast",
        provider="anthropic",
        model_id="claude-haiku-4-5",
        usage=usage(),
        cost_usd=5.0,
        at=at(29),
    )  # yesterday: not today's
    report = spend_report(config, now=NOW)
    brain, fast, local = report["brain"], report["fast"], report["local"]
    assert (brain.spent, brain.cap, brain.period, brain.degrade_to) == (0.42, 15.0, "month", "fast")
    assert brain.reset_at == datetime(2026, 10, 1, tzinfo=TIMEZONE)
    assert fast.spent == 1.0 and fast.exhausted
    assert local.cap is None and local.period == "month"
    assert describe(report) == (
        "brain $0.42 of $15.00 this month (resets 01.10.2026 00:00); "
        "fast $1.00 of $1.00 today, spent (resets 01.10.2026 00:00)"
    )
    assert brain.to_json() == {
        "provider": "anthropic",
        "model_id": "claude-sonnet-5",
        "spent_usd": 0.42,
        "cap_usd": 15.0,
        "period": "month",
        "since": "2026-09-01T00:00:00+03:00",
        "reset_at": "2026-10-01T00:00:00+03:00",
        "exhausted": False,
        "degrade_to": "fast",
        "unpriced_calls": 0,
        "metered": True,
    }
    spent_brain = RoleSpend("brain", "anthropic", "m", 16.0, "month", NOW, NOW, 15.0, "fast")
    assert describe({"brain": spent_brain}).startswith(
        "brain $16.00 of $15.00 this month, spent, fast answers instead (resets"
    )
    free = RoleSpend("local", "ollama", "q", 0.0, "month", NOW, NOW)
    assert describe({"local": free}) is None


def test_context_source_puts_the_budget_under_now(tmp_path: Path) -> None:
    config = budgeted(tmp_path)
    ledger_for(config).record(
        role="brain", provider="anthropic", model_id="claude-sonnet-5", usage=usage(), cost_usd=0.42
    )
    factory = default_context_factory(config, sources=[context_source(config)])
    rendered = factory().render()
    assert "- Budget: brain $0.42 of $15.00 this month (resets " in rendered
    assert "fast $0.00 of $1.00 today" in rendered


def test_spend_service_adds_status_and_route(tmp_path: Path) -> None:
    config = budgeted(tmp_path)
    ledger_for(config).record(
        role="fast", provider="anthropic", model_id="claude-haiku-4-5", usage=usage(), cost_usd=1.5
    )
    service = SpendService(config)
    api = ControlApi(0, lambda: {})
    sources: list = []

    class Hub:
        def add_status_source(self, source) -> None:
            sources.append(source)

        def find_service(self, name: str):
            return api if name == "control-api" else None

    asyncio.run(service.start(Hub()))  # type: ignore[arg-type]
    code, payload = api.handle(ControlRequest("GET", "/spend"))
    assert code == 200 and payload["roles"]["fast"]["exhausted"] is True
    assert payload["roles"]["fast"]["spent_usd"] == 1.5
    (source,) = sources
    assert source()["spend"]["roles"]["brain"]["cap_usd"] == 15.0


def test_spend_command(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "persona").mkdir(parents=True)
    (home / "tau.toml").write_text(
        '[models.roles.brain]\nprovider = "anthropic"\nmodel_id = "claude-sonnet-5"\n'
        'budget = { usd = 15, period = "month" }\n',
        encoding="utf-8",
    )
    data = tmp_path / "data"
    Ledger(data / "spend.sqlite3").record(
        role="brain",
        provider="anthropic",
        model_id="claude-sonnet-5",
        usage=usage(),
        cost_usd=16.0,
    )
    env = {"TAU_DATA_DIR": str(data)}
    result = CliRunner().invoke(cli, ["--home", str(home), "spend"], env=env, prog_name="tau")
    assert result.exit_code == 0, result.output
    assert result.output.startswith("  brain    anthropic $16.00 of $15.00 this month, resets ")
    assert result.output.rstrip().endswith("· SPENT")
    result = CliRunner().invoke(
        cli, ["--home", str(home), "spend", "--json"], env=env, prog_name="tau"
    )
    assert json.loads(result.output)["brain"]["exhausted"] is True
