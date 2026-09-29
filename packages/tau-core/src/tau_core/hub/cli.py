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

NOT_RUNNING = "tau hub çalışmıyor."
NO_LAUNCHD = "launchd yalnızca macOS'ta var. Linux'ta systemd için: tau hub systemd-unit"


@click.group(name="hub", help="tau'yu hub rolünde uzun süre çalışan bir servis olarak yönetir.")
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
            f"tau hub çalışıyor (pid {os.getpid()}, profil {hub.config.profile}). "
            f"Kontrol API: {self.api.url}"
        )
        if hub.crash_report is not None:
            click.echo(f"Önceki hub temiz kapanmamıştı: {hub.crash_report.reason}")
        click.echo("Durdurmak için Ctrl-C veya: tau hub stop")
        sys.stdout.flush()

    async def stop(self) -> None:
        pass


@hub.command(
    name="run",
    help="Hub'ı ön planda çalıştırır (launchd ve systemd de bunu çalıştırır).",
    short_help="Hub'ı ön planda çalıştırır.",
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
        click.echo("tau hub durdu.")
    else:
        click.echo(
            f"tau hub beklenmedik şekilde durdu: {daemon.crash_reason}. Ayrıntı günlükte.",
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
        return f"{s} sn önce"
    if s < 3600:
        return f"{s // 60} dk önce"
    if s < 86400:
        return f"{s // 3600} sa {s % 3600 // 60} dk önce"
    return f"{s // 86400} gün önce"


def _when(value: str | None, now: datetime) -> str:
    moment = parse_timestamp(value)
    if moment is None:
        return "bilinmiyor"
    local = moment.astimezone().strftime("%d.%m.%Y %H:%M:%S")
    return f"{local} ({_ago((now - moment).total_seconds())})"


def format_status(info: dict[str, Any]) -> list[str]:
    """Turkish lines for :func:`collect_status` output."""
    now = parse_timestamp(info["checked_at"]) or utc_now()
    state = info.get("state") or None
    lines = []
    if info["running"]:
        lines.append(f"tau hub çalışıyor (pid {info['pid'] if info['pid'] else '?'}).")
        if state:
            lines.append(
                f"  Profil: {state['profile']} · Rol: {state['role']} · Sürüm: {state['version']}"
            )
            lines.append(f"  Başlangıç: {_when(state['started_at'], now)}")
            beat = f"  Son nabız: {_when(state['heartbeat_at'], now)}"
            last_beat = parse_timestamp(state["heartbeat_at"])
            if last_beat and (now - last_beat).total_seconds() > 3 * info["heartbeat_seconds"]:
                beat += " — gecikmiş; hub yanıt vermiyor olabilir"
            lines.append(beat)
        lines.append(f"  Kontrol API: {info['control_url']}")
    else:
        lines.append(NOT_RUNNING)
        if state and state.get("stopped_at"):
            lines.append(
                f"  Son çalışma: pid {state['pid']}, {_when(state['stopped_at'], now)} temiz durdu."
            )
        elif state:
            lines.append(
                f"  Son çalışma temiz kapanmadı (pid {state['pid']}, son nabız "
                f"{_when(state['heartbeat_at'], now)}); bir sonraki başlatma bunu çökme olarak "
                "kaydeder."
            )
    crash = info.get("last_crash")
    if crash:
        lines.append(
            f"  Son çökme: pid {crash.get('pid', '?')}, son nabız "
            f"{_when(crash.get('last_heartbeat_at'), now)}: {crash.get('reason', '?')}"
        )
    else:
        lines.append("  Son çökme: yok")
    launchd = info.get("launchd")
    if launchd is not None:
        if launchd["loaded"]:
            lines.append(f"  launchd: kurulu ve yüklü ({launchd['label']})")
        elif launchd["installed"]:
            lines.append("  launchd: plist var ama yüklü değil (yüklemek için: tau hub install)")
        else:
            lines.append("  launchd: kurulu değil (kurmak için: tau hub install)")
    return lines


@hub.command(name="status", help="Hub'ın durumunu ve son çökme nedenini gösterir.")
@help_option()
@click.option("--json", "as_json", is_flag=True, help="Durumu JSON olarak yazdırır.")
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


@hub.command(name="stop", help="Çalışan hub'ı durdurur (SIGTERM, temiz kapanış).")
@help_option()
@click.option(
    "--timeout",
    type=float,
    default=15.0,
    show_default=True,
    metavar="SANİYE",
    help="Hub'ın durmasını en fazla bu kadar bekler.",
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
        click.echo(f"Hub çalışıyor ama pid okunamadı ({files.lock}).", err=True)
        ctx.exit(1)
    launchctl = _obj(ctx).get("launchctl") or SystemLaunchctl()
    try:
        launchctl.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        click.echo(NOT_RUNNING)
        return
    except PermissionError:
        click.echo(f"pid {pid} durdurulamadı: izin yok.", err=True)
        ctx.exit(1)
    click.echo(f"Durdurma sinyali gönderildi (pid {pid}).")
    deadline = time.monotonic() + max(0.0, timeout)
    while HubLock.probe(files.lock)[0]:
        if time.monotonic() >= deadline:
            click.echo(f"tau hub {timeout:g} sn içinde durmadı.", err=True)
            ctx.exit(1)
        time.sleep(0.1)
    click.echo("tau hub durdu.")


# -- service management --------------------------------------------------------------------


@hub.command(
    name="install",
    help="Hub'ı launchd kullanıcı ajanı olarak kurar ve başlatır (macOS).",
    short_help="launchd ajanını kurar ve başlatır (macOS).",
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
        click.echo(f"launchd ajanı kurulamadı: {exc}", err=True)
        ctx.exit(1)
    verb = "yeniden kuruldu" if result.replaced else "kuruldu"
    click.echo(f"launchd ajanı {verb}: {result.plist}")
    click.echo("  Hub oturum açılınca başlar; çökerse ya da öldürülürse birkaç saniyede yeniden")
    click.echo("  başlatılır. Temiz durdurma (tau hub stop) sonrası yeniden başlatılmaz.")
    click.echo(f"  launchd günlükleri: {HubFiles(config.hub_dir).logs}")
    if running and not was_loaded:
        click.echo(
            f"  Uyarı: elle başlatılmış bir hub çalışıyor (pid {pid}); launchd'nin hub'ı o "
            "durana kadar başlayamaz. Durdurmak için: tau hub stop"
        )
    click.echo("  Durum için: tau hub status")


@hub.command(
    name="uninstall",
    help="launchd kullanıcı ajanını durdurur ve kaldırır (macOS).",
    short_help="launchd ajanını kaldırır (macOS).",
)
@help_option()
@click.pass_context
def uninstall_command(ctx: click.Context) -> None:
    launchctl = _launchctl(ctx, required=True)
    assert launchctl is not None
    try:
        removed = uninstall_launch_agent(launchctl)
    except (LaunchctlError, OSError) as exc:
        click.echo(f"launchd ajanı kaldırılamadı: {exc}", err=True)
        ctx.exit(1)
    click.echo("launchd ajanı kaldırıldı." if removed else "launchd ajanı kurulu değildi.")


@hub.command(name="systemd-unit", help="systemd unit dosyasını yazdırır (RPi5 hub'ı için).")
@help_option()
@click.option(
    "--python",
    "python",
    metavar="YOL",
    help="Servisin çalıştıracağı Python (varsayılan: şu anki yorumlayıcı).",
)
@click.pass_context
def systemd_unit_command(ctx: click.Context, python: str | None) -> None:
    config = _load_config(ctx)
    click.echo(render_systemd_unit(ServicePaths.from_config(config, python=python)), nl=False)
