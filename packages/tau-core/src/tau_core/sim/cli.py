"""``tau sim``: the owner's view of the simulated devices (``tau.commands`` entry point ``sim``).

``tau sim lamps`` lists the simulated lamps and their state, each one marked as simulated.
It only reads: switching a lamp is ``lamp_set``, a tier-2 tool that asks for approval on every
call, so there is deliberately no ``tau sim set``.

The command reads ``tau.toml`` and ``.env`` like the rest of tau (``--home``, ``TAU_HOME``,
``TAU_DATA_DIR``). Output lines go through ``tau_core.i18n`` in the configured UI language;
help texts and error lines are English. Exit codes: 0 ok, 1 error with one line on stderr, 2
when the configuration itself cannot be loaded.
"""

from __future__ import annotations

from typing import Any

import click

from tau_core import Config, ConfigError, t
from tau_core.cli import help_option
from tau_core.sim import strings as _strings  # noqa: F401  (registers the message keys)
from tau_core.sim.lamps import COMPONENT, LampStore

__all__ = ["sim"]


def _config(ctx: click.Context) -> Config:
    obj: dict[str, Any] = ctx.find_object(dict) or {}
    try:
        return Config.load(obj.get("home"))
    except ConfigError as exc:
        click.echo(str(exc), err=True)
        ctx.exit(2)
        raise AssertionError("unreachable") from None  # pragma: no cover


@click.group(
    name="sim",
    help="Simulated devices: stand-ins for hardware that is not on hand yet, such as the lamps "
    "of [component.sim]. tau drives them with the same tools and tiers a real device will have.",
    short_help="Simulated devices (the lamps of [component.sim]).",
)
@help_option()
def sim() -> None:
    pass


@sim.command(name="lamps", help="List the simulated lamps and whether each is on.")
@help_option()
@click.pass_context
def lamps_command(ctx: click.Context) -> None:
    config = _config(ctx)
    language = config.ui.language
    if not config.component_enabled(COMPONENT):
        click.echo(t("sim.disabled", language))
        return
    try:
        store = LampStore.from_config(config)
        lamps = store.lamps()
    except (ConfigError, OSError) as exc:
        click.echo(f"tau sim: {' '.join(str(exc).split())}", err=True)
        ctx.exit(1)
        return
    if not lamps:
        click.echo(t("sim.lamps.none", language))
        return
    click.echo(t("sim.lamps.header", language))
    for lamp in lamps:
        click.echo(
            t(
                "sim.lamps.row",
                language,
                name=lamp.name,
                state=t("sim.on" if lamp.on else "sim.off", language),
                since=f"{lamp.updated.astimezone():%Y-%m-%d %H:%M}",
            )
        )
    click.echo(t("sim.lamps.file", language, path=store.path))
