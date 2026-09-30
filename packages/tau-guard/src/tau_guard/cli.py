"""``tau guard``: the owner's guard commands (``tau.commands`` entry point ``guard``).

This module has ``status``, ``lock`` and ``log`` (issue 111); :mod:`tau_guard.cli_face` adds
``setup``, ``enroll``, ``verify``, ``forget`` and ``doctor`` (issue 112). Output lines go
through ``tau_core.i18n`` in the
configured UI language (``[ui] language``, ``TAU_LANG``, ``tau --lang``); help texts and error
lines are English. ``status`` and ``lock`` talk to the running hub through tau-core's
``HubClient`` (signed requests, proven answers); ``log`` reads ``guard/audit.jsonl`` directly.

Exit codes: 0 ok (including "no hub runs": guarded channels are locked then), 1 when the hub
answered badly, 2 when the configuration cannot be loaded or an option is wrong.

Tests pass a client through the click context object (``obj={"guard_client": ...}``).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import click
from tau_core import Config, ConfigError, t
from tau_core.cli import help_option
from tau_core.guard import (
    LOCK_TRIGGERS,
    PROGRESS_STEPS,
    config_problem,
    guard_active,
    process_client_id,
)
from tau_core.hub import HubClient, HubError, HubUnavailable

from tau_guard import strings as _strings  # noqa: F401  (registers the message keys)
from tau_guard.audit import EVENTS, AuditLog, printable
from tau_guard.liveness import FAILURES
from tau_guard.service import GUARD_DIR

__all__ = ["guard", "parse_since"]

REQUEST_TIMEOUT = 5.0
CLI_CHANNEL = "cli"
_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhdw])\s*$")
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
GUARD_STATES = ("off", "locked", "verifying", "unlocked", "unavailable")


def _obj(ctx: click.Context) -> dict[str, Any]:
    return ctx.find_object(dict) or {}


def _config(ctx: click.Context) -> Config:
    obj = _obj(ctx)
    try:
        config = Config.load(obj.get("home"))
    except ConfigError as exc:
        click.echo(str(exc), err=True)
        ctx.exit(2)
    if obj.get("profile"):
        config = config.with_overrides(profile=obj["profile"])
    return config


def _client(ctx: click.Context, config: Config) -> Any:
    return _obj(ctx).get("guard_client") or HubClient(config)


def _active(config: Config) -> bool:
    return guard_active(config) or config_problem(config.component("guard")) is not None


def _when(value: object) -> str:
    if not isinstance(value, str):
        return "-"
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone().strftime("%d.%m.%Y %H:%M:%S")


def parse_since(value: str | None, *, now: datetime | None = None) -> datetime | None:
    """``30m``, ``2h``, ``7d`` (a duration back from now) or an ISO date or time."""
    if value is None:
        return None
    now = now or datetime.now(UTC)
    match = _DURATION.match(value)
    if match:
        return now - timedelta(seconds=float(match.group(1)) * _UNITS[match.group(2)])
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise click.BadParameter(
            "use a duration such as 30m, 2h or 7d, or an ISO date or time", param_hint="--since"
        ) from exc
    if moment.tzinfo is None:
        moment = moment.astimezone()  # a local time as the owner typed it
    return moment.astimezone(UTC)


@click.group(
    name="guard",
    help="The owner guard: face setup and checks, its state as the hub reports it, locking "
    "tau, the audit log.",
    short_help="The owner guard (setup, verify, status, lock, log).",
)
@help_option()
def guard() -> None:
    pass


# -- status --------------------------------------------------------------------------------------


def status_lines(payload: dict[str, Any], language: str) -> list[str]:
    """The lines ``tau guard status`` prints for a ``/guard/status`` answer."""
    state = payload.get("state")
    state = state if state in GUARD_STATES else "unavailable"
    lines = [t("guard.cli.state", language, state=t(f"guard.state.{state}", language))]
    reason = payload.get("reason")
    if state == "unavailable" and isinstance(reason, str):
        lines.append(t("guard.cli.reason", language, reason=reason))
    trigger = payload.get("lock_trigger")
    if state in ("locked", "verifying") and trigger in LOCK_TRIGGERS:
        label = t(f"guard.lock_trigger.{trigger}", language)
        lines.append(t("guard.cli.trigger", language, trigger=label))
    if state == "unlocked":
        if isinstance(payload.get("method"), str):
            lines.append(t("guard.cli.method", language, method=payload["method"]))
        lines.append(t("guard.cli.since", language, when=_when(payload.get("since"))))
        lines.append(t("guard.cli.expires", language, when=_when(payload.get("expires_at"))))
    if payload.get("face_seen_at"):
        lines.append(t("guard.cli.face_seen", language, when=_when(payload["face_seen_at"])))
    attempt = payload.get("attempt")
    if isinstance(attempt, dict) and attempt.get("step") in PROGRESS_STEPS:
        step = t(f"guard.progress.{attempt['step']}", language)
        lines.append(t("guard.cli.attempt", language, step=step))
    enrolled = t("guard.cli.yes" if payload.get("enrolled") else "guard.cli.no", language)
    lines.append(t("guard.cli.enrolled", language, value=enrolled))
    failures = payload.get("failures")
    if isinstance(failures, int) and failures > 0:
        lines.append(t("guard.cli.failures", language, count=failures))
    if payload.get("cooldown_until"):
        lines.append(t("guard.cli.cooldown", language, when=_when(payload["cooldown_until"])))
    if payload.get("screen") == "unknown" and state != "unavailable":
        lines.append(t("guard.cli.screen_unknown", language))
    return lines


@guard.command(name="status", help="Show the guard's state as the running hub reports it.")
@help_option()
@click.option("--json", "as_json", is_flag=True, help="Print the hub's answer as JSON.")
@click.pass_context
def status_command(ctx: click.Context, as_json: bool) -> None:
    config = _config(ctx)
    language = config.ui.language
    if not _active(config):
        click.echo(json.dumps({"state": "off"}) if as_json else t("guard.cli.off", language))
        return
    try:
        payload = _client(ctx, config).get("/guard/status", timeout=REQUEST_TIMEOUT)
    except HubUnavailable as exc:
        if as_json:
            click.echo(json.dumps({"state": "unavailable", "reason": exc.reason}))
        elif exc.reason == "no_hub":
            click.echo(t("guard.cli.no_hub", language, hint=t("guard.start_hub", language)))
        else:
            click.echo(t("guard.cli.hub_error", language, error=exc.reason), err=True)
        ctx.exit(0 if exc.reason == "no_hub" else 1)
    except HubError as exc:
        if as_json:
            reason = "guard_off" if exc.status == 404 else f"http_{exc.status}"
            click.echo(json.dumps({"state": "unavailable", "reason": reason}))
        elif exc.status == 404:
            click.echo(t("guard.cli.hub_off", language))
        else:
            click.echo(t("guard.cli.hub_error", language, error=exc.status), err=True)
        ctx.exit(1)
    if not isinstance(payload, dict):
        click.echo(t("guard.cli.hub_error", language, error="bad_response"), err=True)
        ctx.exit(1)
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for line in status_lines(payload, language):
        click.echo(line)


# -- lock ----------------------------------------------------------------------------------------


@guard.command(
    name="lock", help="Lock tau now (every guarded channel, until you unlock at the Mac)."
)
@help_option()
@click.pass_context
def lock_command(ctx: click.Context) -> None:
    config = _config(ctx)
    language = config.ui.language
    if not _active(config):
        click.echo(t("guard.cli.off", language))
        return
    body = {"channel": CLI_CHANNEL, "client_id": process_client_id(), "trigger": "command"}
    try:
        answer = _client(ctx, config).post("/guard/lock", body, timeout=REQUEST_TIMEOUT)
    except HubUnavailable as exc:
        if exc.reason == "no_hub":
            click.echo(t("guard.cli.lock_no_hub", language))
            return
        click.echo(t("guard.cli.lock_failed", language, error=exc.reason), err=True)
        ctx.exit(1)
    except HubError as exc:
        if exc.status == 404:
            click.echo(t("guard.cli.hub_off", language), err=True)
        else:
            click.echo(t("guard.cli.lock_failed", language, error=exc.status), err=True)
        ctx.exit(1)
    if not isinstance(answer, dict) or answer.get("state") != "locked":
        click.echo(t("guard.cli.lock_failed", language, error="bad_response"), err=True)
        ctx.exit(1)
    click.echo(t("guard.cli.locked", language))


# -- log -----------------------------------------------------------------------------------------


def entry_line(entry: dict[str, Any], language: str) -> str:
    """One audit record as a line: time, event, outcome and details. Every value from the file
    goes through :func:`~tau_guard.audit.printable`, so an edited or older file cannot drive
    the terminal either."""
    return printable(_entry_line(entry, language))


def _entry_line(entry: dict[str, Any], language: str) -> str:
    event = entry.get("event")
    parts = [_when(entry.get("at"))]
    parts.append(t(f"guard.cli.log.event.{event}", language) if event in EVENTS else str(event))
    ok = entry.get("ok")
    if ok is True:
        parts.append(t("guard.cli.log.ok", language))
    elif ok is False:
        parts.append(t("guard.cli.log.failed", language))
    reason = entry.get("reason")
    if isinstance(reason, str) and reason != "match":
        liveness = entry.get("liveness")
        rule = f" ({liveness})" if reason == "spoof" and liveness in FAILURES else ""
        parts.append(reason + rule)
    trigger = entry.get("trigger")
    if trigger in LOCK_TRIGGERS:
        parts.append(t(f"guard.lock_trigger.{trigger}", language))
    for key in ("channel", "tool"):
        if isinstance(entry.get(key), str):
            parts.append(entry[key])
    score = entry.get("score")
    if isinstance(score, int | float) and not isinstance(score, bool):
        parts.append(f"{score:.2f}")
    duration = entry.get("duration_ms")
    if event == "cooldown" and isinstance(duration, int):
        parts.append(f"{duration / 1000:g} s")
    return "  ".join(parts)


@guard.command(name="log", help="Show the guard's audit log (checks, locks, cooldowns).")
@help_option()
@click.option(
    "--since",
    metavar="WHEN",
    help="Only entries since WHEN: a duration such as 30m, 2h or 7d, or an ISO date or time.",
)
@click.option("--json", "as_json", is_flag=True, help="Print the entries as JSON lines.")
@click.pass_context
def log_command(ctx: click.Context, since: str | None, as_json: bool) -> None:
    config = _config(ctx)
    language = config.ui.language
    cutoff = parse_since(since)
    entries = AuditLog(config.data_dir / GUARD_DIR).read(since=cutoff)
    if as_json:
        for entry in entries:
            click.echo(json.dumps(entry))  # ASCII: every control character stays escaped
        return
    if not entries:
        click.echo(t("guard.cli.log.empty", language))
        return
    for entry in entries:
        click.echo(entry_line(entry, language))


from tau_guard.cli_face import register as _register_face  # noqa: E402  (needs the group above)

_register_face(guard)
