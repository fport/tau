"""The ``tau guard`` message keys (``guard.cli.*``), registered into ``tau_core.i18n`` at import.

``guard.cli.la.*`` are the LocalAuthentication prompt texts the hub and the CLI put into a
worker request (issue 112).

tau-core's own guard keys (``guard.state.*``, ``guard.verdict.*``, ``guard.lock_trigger.*``,
``guard.start_hub``) are used as they are. The keys below are new and must not collide with
tau-core's table, because ``register_messages`` overrides silently; the assertion at import
keeps that honest. Help texts and error lines stay English.
"""

from __future__ import annotations

import tau_core.guard  # noqa: F401  (registers tau-core's guard keys before the check)
from tau_core.i18n import MESSAGES, register_messages

CLI_MESSAGES: dict[str, dict[str, str]] = {
    # -- tau guard status ----------------------------------------------------------------------
    "guard.cli.off": {
        "en": "The guard is off (no enrollment marker, and [component.guard] enabled is not true).",
        "tr": "Koruma kapalı (kayıt işareti yok ve [component.guard] enabled true değil).",
    },
    "guard.cli.no_hub": {
        "en": "No hub runs, so guarded channels stay locked. {hint}",
        "tr": "Çalışan hub yok, bu yüzden korunan kanallar kilitli kalır. {hint}",
    },
    "guard.cli.hub_off": {
        "en": "The running hub has no active guard service; guarded channels stay locked. "
        "Restart the hub.",
        "tr": "Çalışan hub'da etkin koruma servisi yok; korunan kanallar kilitli kalır. "
        "Hub'ı yeniden başlat.",
    },
    "guard.cli.hub_error": {
        "en": "The hub did not answer as expected: {error}",
        "tr": "Hub beklendiği gibi yanıt vermedi: {error}",
    },
    "guard.cli.state": {"en": "Guard: {state}", "tr": "Koruma: {state}"},
    "guard.cli.reason": {"en": "  Reason: {reason}", "tr": "  Neden: {reason}"},
    "guard.cli.trigger": {"en": "  Why: {trigger}", "tr": "  Kilit nedeni: {trigger}"},
    "guard.cli.method": {"en": "  Unlocked with: {method}", "tr": "  Açan yöntem: {method}"},
    "guard.cli.since": {"en": "  Unlocked since: {when}", "tr": "  Açılış zamanı: {when}"},
    "guard.cli.expires": {
        "en": "  Locks at the latest: {when}",
        "tr": "  En geç kilitlenme: {when}",
    },
    "guard.cli.face_seen": {"en": "  Face last seen: {when}", "tr": "  Yüz son görülme: {when}"},
    "guard.cli.failures": {
        "en": "  Failed attempts since the last unlock: {count}",
        "tr": "  Son açılıştan beri başarısız deneme: {count}",
    },
    "guard.cli.cooldown": {
        "en": "  Too many failed attempts; checks resume at {when}",
        "tr": "  Çok fazla başarısız deneme; kontroller {when} itibarıyla yeniden başlar",
    },
    "guard.cli.enrolled": {"en": "  Face enrolled: {value}", "tr": "  Kayıtlı yüz: {value}"},
    "guard.cli.attempt": {"en": "  Check running: {step}", "tr": "  Süren kontrol: {step}"},
    "guard.cli.screen_unknown": {
        "en": "  The screen lock cannot be read (no GUI session); an unlock lasts at most "
        "idle_lock_minutes.",
        "tr": "  Ekran kilidi okunamıyor (grafik oturum yok); bir açılış en fazla "
        "idle_lock_minutes sürer.",
    },
    "guard.cli.yes": {"en": "yes", "tr": "evet"},
    "guard.cli.no": {"en": "no", "tr": "hayır"},
    # -- tau guard lock ------------------------------------------------------------------------
    "guard.cli.locked": {"en": "tau is locked.", "tr": "tau kilitlendi."},
    "guard.cli.lock_no_hub": {
        "en": "No hub runs; guarded channels are locked anyway.",
        "tr": "Çalışan hub yok; korunan kanallar zaten kilitli.",
    },
    "guard.cli.lock_failed": {
        "en": "The hub did not confirm the lock: {error}",
        "tr": "Hub kilidi doğrulamadı: {error}",
    },
    # -- tau guard log -------------------------------------------------------------------------
    "guard.cli.log.empty": {
        "en": "The guard's audit log has no entries.",
        "tr": "Korumanın denetim günlüğünde kayıt yok.",
    },
    "guard.cli.log.ok": {"en": "ok", "tr": "tamam"},
    "guard.cli.log.failed": {"en": "failed", "tr": "başarısız"},
    "guard.cli.log.event.verify": {"en": "unlock check", "tr": "açma kontrolü"},
    "guard.cli.log.event.step_up": {"en": "step-up", "tr": "ek doğrulama"},
    "guard.cli.log.event.recheck": {"en": "presence recheck", "tr": "varlık yoklaması"},
    "guard.cli.log.event.lock": {"en": "lock", "tr": "kilit"},
    "guard.cli.log.event.unlock": {"en": "unlocked", "tr": "kilit açıldı"},
    "guard.cli.log.event.enroll": {"en": "enrollment", "tr": "kayıt"},
    "guard.cli.log.event.forget": {"en": "forget", "tr": "silme"},
    "guard.cli.log.event.cooldown": {"en": "cooldown", "tr": "bekleme"},
    "guard.cli.log.event.camera_open": {"en": "camera opened", "tr": "kamera açıldı"},
    "guard.cli.log.event.touch_id": {"en": "Touch ID", "tr": "Touch ID"},
    # -- LocalAuthentication prompt texts (macOS shows "<app> is trying to <text>.") -------------
    "guard.cli.la.enroll": {
        "en": "enroll your face for the tau guard",
        "tr": "tau koruması için yüzünü kaydetmek",
    },
    "guard.cli.la.forget": {
        "en": "remove your face from the tau guard",
        "tr": "yüzünü tau korumasından silmek",
    },
}

_collisions = set(CLI_MESSAGES) & set(MESSAGES)
assert not _collisions, f"tau-guard message keys collide with tau-core: {sorted(_collisions)}"

register_messages(CLI_MESSAGES)
