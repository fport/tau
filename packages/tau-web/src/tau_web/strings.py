"""The ``tau web`` message keys, registered into ``tau_core.i18n`` at import.

What ``tau web`` prints goes through ``t(key, language)`` with the configured UI language.
Error lines are the English text of the exception. The keys must not collide with tau-core's
table, because ``register_messages`` overrides silently; the assertion keeps that honest.
"""

from __future__ import annotations

from tau_core.i18n import MESSAGES, register_messages

WEB_MESSAGES: dict[str, dict[str, str]] = {
    "web.device.pair_link": {
        "en": "Open this link in the browser to pair it as {name!r} "
        "(valid for {minutes} minutes, once):",
        "tr": "Bu bağlantıyı tarayıcıda açarak {name!r} adıyla eşle "
        "({minutes} dakika geçerli, tek kullanımlık):",
    },
    "web.device.pair_remote": {
        "en": "From another device, use the same path on the name it reaches the hub by "
        "(Tailscale Serve or the tunnel).",
        "tr": "Başka bir cihazdan, hub'a ulaştığı adla (Tailscale Serve ya da tunnel) "
        "aynı yolu kullan.",
    },
    "web.device.none": {
        "en": "No browser is paired yet: tau web device add <name>",
        "tr": "Henüz eşlenmiş tarayıcı yok: tau web device add <ad>",
    },
    "web.device.row": {
        "en": "  {name}  ({id})  paired {created}, last seen {seen}",
        "tr": "  {name}  ({id})  eşlendi {created}, son görülme {seen}",
    },
    "web.device.never": {"en": "never", "tr": "hiç"},
    "web.device.removed": {
        "en": "Removed {name!r}; that browser can no longer use the web app.",
        "tr": "{name!r} kaldırıldı; o tarayıcı artık web uygulamasını kullanamaz.",
    },
}

_collisions = set(WEB_MESSAGES) & set(MESSAGES)
assert not _collisions, f"tau-web message keys collide with tau-core: {sorted(_collisions)}"

register_messages(WEB_MESSAGES)
