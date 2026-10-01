"""``tau web``: pair browsers with the hub's web app (``tau.commands`` entry point ``web``).

``tau web device add <name>`` prints a one-time pairing link (10 minutes, single use);
``list`` and ``remove`` manage the paired browsers. The hub reads the same files, so these work
while it runs. Output lines go through ``tau_core.i18n``; help texts and errors are English.
Exit codes: 0 ok, 1 error with one line on stderr, 2 when the configuration cannot be loaded.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import click
from tau_core import Config, ConfigError, t
from tau_core.cli import help_option

from tau_web import strings as _strings  # noqa: F401  (registers the message keys)
from tau_web.devices import PAIRING_MINUTES, DeviceError, DeviceRegistry
from tau_web.settings import WebSettings

__all__ = ["web"]


def _config(ctx: click.Context) -> Config:
    obj: dict[str, Any] = ctx.find_object(dict) or {}
    try:
        return Config.load(obj.get("home"))
    except ConfigError as exc:
        click.echo(str(exc), err=True)
        ctx.exit(2)
        raise AssertionError("unreachable") from None  # pragma: no cover


def _registry(config: Config) -> DeviceRegistry:
    return DeviceRegistry(config.data_dir / "web")


def _when(value: str | None) -> str:
    if not value:
        return ""
    try:
        return f"{datetime.fromisoformat(value).astimezone():%Y-%m-%d %H:%M}"
    except ValueError:
        return value


@click.group(
    name="web",
    help="The web app on the hub: pair the browsers that may use it. The hub serves it on "
    "127.0.0.1 (or the tailnet); reach it from elsewhere through Tailscale Serve or the tunnel.",
    short_help="Pair browsers with the hub's web app.",
)
@help_option()
def web() -> None:
    pass


@web.group(name="device", help="Paired browsers: add, list, remove.")
@help_option()
def device() -> None:
    pass


@device.command(name="add", help="Print a one-time link that pairs a browser as NAME.")
@click.argument("name")
@help_option()
@click.pass_context
def add_command(ctx: click.Context, name: str) -> None:
    config = _config(ctx)
    language = config.ui.language
    try:
        settings = WebSettings.from_config(config)
        code = _registry(config).start_pairing(name)
    except (ConfigError, DeviceError, OSError) as exc:
        click.echo(f"tau web: {' '.join(str(exc).split())}", err=True)
        ctx.exit(1)
        return
    host = settings.bind if ":" not in settings.bind else f"[{settings.bind}]"
    click.echo(t("web.device.pair_link", language, name=name, minutes=PAIRING_MINUTES))
    click.echo(f"  http://{host}:{settings.port}/pair#{code}")
    click.echo(t("web.device.pair_remote", language))


@device.command(name="list", help="List the paired browsers.")
@help_option()
@click.pass_context
def list_command(ctx: click.Context) -> None:
    config = _config(ctx)
    language = config.ui.language
    try:
        devices = _registry(config).list()
    except (DeviceError, OSError) as exc:
        click.echo(f"tau web: {' '.join(str(exc).split())}", err=True)
        ctx.exit(1)
        return
    if not devices:
        click.echo(t("web.device.none", language))
        return
    for item in devices:
        seen = _when(item.last_seen) or t("web.device.never", language)
        click.echo(
            t(
                "web.device.row",
                language,
                name=item.name,
                id=item.id,
                created=_when(item.created),
                seen=seen,
            )
        )


@device.command(name="remove", help="Unpair a browser by its name or id.")
@click.argument("which")
@help_option()
@click.pass_context
def remove_command(ctx: click.Context, which: str) -> None:
    config = _config(ctx)
    try:
        removed = _registry(config).remove(which)
    except (DeviceError, OSError) as exc:
        click.echo(f"tau web: {' '.join(str(exc).split())}", err=True)
        ctx.exit(1)
        return
    click.echo(t("web.device.removed", config.ui.language, name=removed.name))
