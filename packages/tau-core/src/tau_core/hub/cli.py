"""``tau hub`` commands: run the daemon, show its status, stop it, manage its service.

Tests inject a launchctl through the click context object (``obj={"launchctl": fake}``);
without one, ``install``/``uninstall`` use the real ``/bin/launchctl`` on macOS only, and
``stop`` sends a real SIGTERM.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import datetime
from typing import Any

import click

from tau_core.cli import help_option
from tau_core.config import Config, ConfigError
from tau_core.hub.control import HOST, ControlApi
from tau_core.hub.daemon import Hub
from tau_core.hub.launchd import (
    Launchctl,
    LaunchctlError,
    SystemLaunchctl,
    gui_domain,
    install_launch_agent,
    launch_agents_dir,
    uninstall_launch_agent,
)
from tau_core.hub.lock import AlreadyRunning, HubLock
from tau_core.hub.state import HubFiles, parse_timestamp, timestamp, utc_now
from tau_core.hub.units import LABEL, PLIST_NAME, ServicePaths, render_systemd_unit
from tau_core.logs import configure_logging

NOT_RUNNING = "tau hub is not running."
NO_LAUNCHD = "launchd exists only on macOS. For systemd on Linux: tau hub systemd-unit"


@click.group(name="hub", help="Run and manage tau as a long-lived service in the hub role.")
@help_option()
def hub() -> None:
    pass


def _obj(ctx: click.Context) -> dict[str, Any]:
    return ctx.find_object(dict) or {}


def _load_config(ctx: click.Context) -> Config:
    obj = _obj(ctx)
    try:
        config = Config.load(obj.get("home"))
    except ConfigError as exc:
        click.echo(str(exc), err=True)
        ctx.exit(2)
    if obj.get("profile"):
        config = config.with_overrides(profile=obj["profile"])
    return config


def _launchctl(ctx: click.Context, *, required: bool) -> Launchctl | None:
    """The injected launchctl, else the real one on macOS; ``None`` elsewhere (or exit 2)."""
    injected = _obj(ctx).get("launchctl")
    if injected is not None:
        return injected
    if sys.platform == "darwin":
        return SystemLaunchctl()
    if required:
        click.echo(NO_LAUNCHD, err=True)
        ctx.exit(2)
    return None


# -- run -----------------------------------------------------------------------------------


class _Banner:
    """Prints where the hub listens once every other service has started."""

    name = "banner"

    def __init__(self, api: ControlApi):
        self.api = api

    async def start(self, hub: Hub) -> None:
        click.echo(
            f"tau hub is running (pid {os.getpid()}, profile {hub.config.profile}). "
            f"Control API: {self.api.url}"
        )
        if hub.crash_report is not None:
            click.echo(f"The previous hub did not stop cleanly: {hub.crash_report.reason}")
        click.echo("To stop: Ctrl-C or `tau hub stop`")
        sys.stdout.flush()

    async def stop(self) -> None:
        pass


@hub.command(
    name="run",
    help="Run the hub in the foreground (launchd and systemd run this too).",
    short_help="Run the hub in the foreground.",
)
@help_option()
@click.pass_context
def run_command(ctx: click.Context) -> None:
    config = _load_config(ctx)
    configure_logging(config.logs_dir, verbose=bool(_obj(ctx).get("verbose")))
    daemon = Hub(config)
    api = ControlApi(config.hub.control_port, daemon.status)
    daemon.add_service(api)
    daemon.add_service(_Banner(api))
    try:
        code = daemon.run()
    except AlreadyRunning as exc:
        click.echo(str(exc), err=True)
        ctx.exit(1)
    if code == 0:
        click.echo("tau hub stopped.")
    else:
        click.echo(
            f"tau hub stopped unexpectedly: {daemon.crash_reason}. Details are in the log.",
            err=True,
        )
    ctx.exit(code)


# -- status --------------------------------------------------------------------------------


def collect_status(
    config: Config, *, launchctl: Launchctl | None, now: datetime | None = None
) -> dict[str, Any]:
    """Everything ``tau hub status`` shows, read from the hub's files (no network)."""
    files = HubFiles(config.hub_dir)
    running, lock_pid = HubLock.probe(files.lock)
    state = files.read_state()
    pid = None
    if running:
        pid = lock_pid if lock_pid is not None else (state.pid if state else None)
    launchd = None
    if launchctl is not None:
        plist = launch_agents_dir() / PLIST_NAME
        launchd = {
            "label": LABEL,
            "plist": str(plist),
            "installed": plist.is_file(),
            "loaded": launchctl.is_loaded(gui_domain(), LABEL),
        }
    return {
        "running": running,
        "pid": pid,
        "control_url": f"http://{HOST}:{config.hub.control_port}",
        "heartbeat_seconds": config.hub.heartbeat_seconds,
        "state": state.to_dict() if state else None,
        "last_crash": files.read_last_crash(),
        "launchd": launchd,
        "checked_at": timestamp(now or utc_now()),
    }


def _ago(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 60:
        return f"{s} s ago"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600} h {s % 3600 // 60} min ago"
    return f"{s // 86400} d ago"


def _when(value: str | None, now: datetime) -> str:
    moment = parse_timestamp(value)
    if moment is None:
        return "unknown"
    local = moment.astimezone().strftime("%d.%m.%Y %H:%M:%S")
    return f"{local} ({_ago((now - moment).total_seconds())})"


def format_status(info: dict[str, Any]) -> list[str]:
    """The lines ``tau hub status`` prints for :func:`collect_status` output (English)."""
    now = parse_timestamp(info["checked_at"]) or utc_now()
    state = info.get("state") or None
    lines = []
    if info["running"]:
        lines.append(f"tau hub is running (pid {info['pid'] if info['pid'] else '?'}).")
        if state:
            lines.append(
                f"  Profile: {state['profile']} · Role: {state['role']} · "
                f"Version: {state['version']}"
            )
            lines.append(f"  Started: {_when(state['started_at'], now)}")
            beat = f"  Last heartbeat: {_when(state['heartbeat_at'], now)}"
            last_beat = parse_timestamp(state["heartbeat_at"])
            if last_beat and (now - last_beat).total_seconds() > 3 * info["heartbeat_seconds"]:
                beat += " — overdue; the hub may not be responding"
            lines.append(beat)
        lines.append(f"  Control API: {info['control_url']}")
    else:
        lines.append(NOT_RUNNING)
        if state and state.get("stopped_at"):
            lines.append(
                f"  Last run: pid {state['pid']}, stopped cleanly "
                f"{_when(state['stopped_at'], now)}."
            )
        elif state:
            lines.append(
                f"  Last run did not stop cleanly (pid {state['pid']}, last heartbeat "
                f"{_when(state['heartbeat_at'], now)}); the next start records it as a crash."
            )
    crash = info.get("last_crash")
    if crash:
        lines.append(
            f"  Last crash: pid {crash.get('pid', '?')}, last heartbeat "
            f"{_when(crash.get('last_heartbeat_at'), now)}: {crash.get('reason', '?')}"
        )
    else:
        lines.append("  Last crash: none")
    launchd = info.get("launchd")
    if launchd is not None:
        if launchd["loaded"]:
            lines.append(f"  launchd: installed and loaded ({launchd['label']})")
        elif launchd["installed"]:
            lines.append("  launchd: plist present but not loaded (to load: tau hub install)")
        else:
            lines.append("  launchd: not installed (to install: tau hub install)")
    return lines


@hub.command(name="status", help="Show the hub's status and the reason of its last crash.")
@help_option()
@click.option("--json", "as_json", is_flag=True, help="Print the status as JSON.")
@click.pass_context
def status_command(ctx: click.Context, as_json: bool) -> None:
    config = _load_config(ctx)
    info = collect_status(config, launchctl=_launchctl(ctx, required=False))
    if as_json:
        click.echo(json.dumps(info, ensure_ascii=False, indent=2))
        return
    for line in format_status(info):
        click.echo(line)


# -- stop ----------------------------------------------------------------------------------


@hub.command(name="stop", help="Stop the running hub (SIGTERM, clean shutdown).")
@help_option()
@click.option(
    "--timeout",
    type=float,
    default=15.0,
    show_default=True,
    metavar="SECONDS",
    help="Wait at most this long for the hub to stop.",
)
@click.pass_context
def stop_command(ctx: click.Context, timeout: float) -> None:
    config = _load_config(ctx)
    files = HubFiles(config.hub_dir)
    running, lock_pid = HubLock.probe(files.lock)
    if not running:
        click.echo(NOT_RUNNING)
        return
    state = files.read_state()
    # The lock holder wrote lock_pid; state.json can still be the previous run's for a moment.
    pid = lock_pid if lock_pid is not None else (state.pid if state else None)
    if pid is None:
        click.echo(f"The hub is running but its pid could not be read ({files.lock}).", err=True)
        ctx.exit(1)
    launchctl = _obj(ctx).get("launchctl") or SystemLaunchctl()
    try:
        launchctl.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        click.echo(NOT_RUNNING)
        return
    except PermissionError:
        click.echo(f"Could not stop pid {pid}: permission denied.", err=True)
        ctx.exit(1)
    click.echo(f"Stop signal sent (pid {pid}).")
    deadline = time.monotonic() + max(0.0, timeout)
    while HubLock.probe(files.lock)[0]:
        if time.monotonic() >= deadline:
            click.echo(f"tau hub did not stop within {timeout:g} s.", err=True)
            ctx.exit(1)
        time.sleep(0.1)
    click.echo("tau hub stopped.")


# -- service management --------------------------------------------------------------------


@hub.command(
    name="install",
    help="Install and start the hub as a launchd user agent (macOS).",
    short_help="Install and start the launchd agent (macOS).",
)
@help_option()
@click.pass_context
def install_command(ctx: click.Context) -> None:
    config = _load_config(ctx)
    launchctl = _launchctl(ctx, required=True)
    assert launchctl is not None
    running, pid = HubLock.probe(HubFiles(config.hub_dir).lock)
    was_loaded = launchctl.is_loaded(gui_domain(), LABEL)
    try:
        result = install_launch_agent(config, launchctl)
    except (LaunchctlError, OSError) as exc:
        click.echo(f"launchd agent could not be installed: {exc}", err=True)
        ctx.exit(1)
    verb = "reinstalled" if result.replaced else "installed"
    click.echo(f"launchd agent {verb}: {result.plist}")
    click.echo("  The hub starts at login; after a crash or a kill it is restarted within a few")
    click.echo("  seconds. It is not restarted after a clean stop (tau hub stop).")
    click.echo(f"  launchd logs: {HubFiles(config.hub_dir).logs}")
    if running and not was_loaded:
        click.echo(
            f"  Warning: a hub started by hand is running (pid {pid}); launchd's hub cannot "
            "start until it stops. To stop it: tau hub stop"
        )
    click.echo("  For the status: tau hub status")


@hub.command(
    name="uninstall",
    help="Stop and remove the launchd user agent (macOS).",
    short_help="Remove the launchd agent (macOS).",
)
@help_option()
@click.pass_context
def uninstall_command(ctx: click.Context) -> None:
    launchctl = _launchctl(ctx, required=True)
    assert launchctl is not None
    try:
        removed = uninstall_launch_agent(launchctl)
    except (LaunchctlError, OSError) as exc:
        click.echo(f"launchd agent could not be removed: {exc}", err=True)
        ctx.exit(1)
    click.echo("launchd agent removed." if removed else "launchd agent was not installed.")


@hub.command(name="systemd-unit", help="Print the systemd unit file (for the RPi5 hub).")
@help_option()
@click.option(
    "--python",
    "python",
    metavar="PATH",
    help="The Python the service runs (default: the current interpreter).",
)
@click.pass_context
def systemd_unit_command(ctx: click.Context, python: str | None) -> None:
    config = _load_config(ctx)
    click.echo(render_systemd_unit(ServicePaths.from_config(config, python=python)), nl=False)
