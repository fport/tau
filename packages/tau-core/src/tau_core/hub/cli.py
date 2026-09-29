"""``tau hub`` commands. Placeholders until issue 009 builds the daemon."""

from __future__ import annotations

import click

NOT_YET = "Henüz yok (issue 009)."


@click.group(name="hub", help="tau'yu hub rolünde uzun süre çalışan bir servis olarak yönetir.")
def hub() -> None:
    pass


def _placeholder(name: str, help_text: str) -> click.Command:
    @click.command(name=name, help=help_text)
    def command() -> None:
        click.echo(NOT_YET)

    return command


for _name, _help in (
    ("run", "Hub'ı ön planda çalıştırır."),
    ("status", "Hub'ın durumunu ve son çökme nedenini gösterir."),
    ("stop", "Çalışan hub'ı durdurur."),
    ("install", "Hub'ı launchd kullanıcı ajanı olarak kurar (macOS)."),
    ("uninstall", "launchd kullanıcı ajanını kaldırır."),
    ("systemd-unit", "systemd unit dosyasını yazdırır (RPi5 için)."),
):
    hub.add_command(_placeholder(_name, _help))
