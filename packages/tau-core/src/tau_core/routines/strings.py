"""The ``tau routine`` message keys, registered into ``tau_core.i18n`` at import.

What ``tau routine`` prints goes through ``t(key, language)`` with the UI language of the
configuration (``[ui] language``, ``TAU_LANG``, ``tau --lang``). Error lines are the English
text of the exception, like every error raised before a channel exists. Triggers are printed
as written (``daily 07:00 weekdays``), the same in every language. The keys must not collide
with tau-core's table, because ``register_messages`` overrides silently; the assertion at
import keeps that honest.
"""

from __future__ import annotations

from tau_core.i18n import MESSAGES, register_messages

ROUTINE_MESSAGES: dict[str, dict[str, str]] = {
    # -- add and edit ----------------------------------------------------------------------
    "routine.add.done": {
        "en": 'Added the routine {id} "{name}": {trigger}, {tool}. Next run: {next}.',
        "tr": '{id} rutini eklendi, "{name}": {trigger}, {tool}. Sonraki çalışma: {next}.',
    },
    "routine.add.rejected": {
        "en": "Nothing was added: the routine was not approved.",
        "tr": "Hiçbir şey eklenmedi: rutin onaylanmadı.",
    },
    "routine.edit.done": {
        "en": 'Changed the routine {id} "{name}": {trigger}, {tool}. Next run: {next}.',
        "tr": '{id} rutini değişti, "{name}": {trigger}, {tool}. Sonraki çalışma: {next}.',
    },
    "routine.edit.rejected": {
        "en": "Nothing was changed: the new definition was not approved. The routine runs as "
        "before.",
        "tr": "Hiçbir şey değişmedi: yeni tanım onaylanmadı. Rutin eskisi gibi çalışıyor.",
    },
    "routine.edit.renamed": {
        "en": 'The routine {id} is now called "{name}".',
        "tr": '{id} rutininin yeni adı "{name}".',
    },
    "routine.edit.nothing": {
        "en": "Nothing to change: give --name, --trigger, --tool, --args or NAME=VALUE.",
        "tr": "Değişecek bir şey yok: --name, --trigger, --tool, --args ya da AD=DEĞER ver.",
    },
    # -- list ------------------------------------------------------------------------------
    "routine.list.none": {
        "en": 'No routines yet. Add one with `tau routine add "daily 07:00 weekdays" TOOL '
        "NAME=VALUE`.",
        "tr": 'Henüz rutin yok. `tau routine add "daily 07:00 weekdays" ARAÇ AD=DEĞER` ile '
        "bir tane ekle.",
    },
    "routine.list.row": {
        "en": '{id}  "{name}"  [{state}]',
        "tr": '{id}  "{name}"  [{state}]',
    },
    "routine.list.call": {
        "en": "    {trigger}  →  {tool} {arguments}",
        "tr": "    {trigger}  →  {tool} {arguments}",
    },
    "routine.list.next": {
        "en": "    next run: {next}   failures in a row: {failures}",
        "tr": "    sonraki çalışma: {next}   üst üste hata: {failures}",
    },
    "routine.list.zone": {
        "en": "Times are {zone} time.",
        "tr": "Saatler {zone} saatine göre.",
    },
    "routine.state.active": {"en": "active", "tr": "etkin"},
    "routine.state.paused": {"en": "paused", "tr": "duraklatıldı"},
    "routine.state.finished": {"en": "finished", "tr": "bitti"},
    "routine.state.unapproved": {"en": "not approved", "tr": "onaysız"},
    "routine.none": {"en": "none", "tr": "yok"},
    "routine.no_arguments": {"en": "(no arguments)", "tr": "(argüman yok)"},
    # -- pause, resume, remove -------------------------------------------------------------
    "routine.pause.done": {
        "en": 'Paused the routine {id} "{name}". `tau routine resume {id}` starts it again.',
        "tr": '{id} rutini duraklatıldı, "{name}". `tau routine resume {id}` yeniden başlatır.',
    },
    "routine.resume.done": {
        "en": 'Resumed the routine {id} "{name}". Next run: {next}.',
        "tr": '{id} rutini yeniden başladı, "{name}". Sonraki çalışma: {next}.',
    },
    "routine.resume.unapproved": {
        "en": "It does not match its approval and will be refused until it is registered "
        "again (`tau routine edit {id}`).",
        "tr": "Onayıyla eşleşmiyor; yeniden kaydedilene kadar reddedilecek "
        "(`tau routine edit {id}`).",
    },
    "routine.remove.confirm": {
        "en": 'Remove the routine {id} "{name}"?',
        "tr": '{id} rutini kaldırılsın mı, "{name}"?',
    },
    "routine.remove.kept": {
        "en": "Nothing was removed.",
        "tr": "Hiçbir şey kaldırılmadı.",
    },
    "routine.remove.done": {
        "en": 'Removed the routine {id} "{name}"; it will not run again.',
        "tr": '{id} rutini kaldırıldı, "{name}"; bir daha çalışmayacak.',
    },
    # -- log -------------------------------------------------------------------------------
    "routine.log.none": {
        "en": "The routine log is empty.",
        "tr": "Rutin günlüğü boş.",
    },
    "routine.log.row": {
        "en": "{at}  {id}  {name}  {status}  {detail}",
        "tr": "{at}  {id}  {name}  {status}  {detail}",
    },
    "routine.status.ok": {"en": "ran", "tr": "çalıştı"},
    "routine.status.failed": {"en": "failed", "tr": "başarısız"},
    "routine.status.refused": {"en": "refused", "tr": "reddedildi"},
    "routine.status.missed": {"en": "missed", "tr": "kaçırıldı"},
    "routine.status.paused": {"en": "paused", "tr": "duraklatıldı"},
    "routine.status.resumed": {"en": "resumed", "tr": "yeniden başladı"},
    "routine.status.registered": {"en": "registered", "tr": "kaydedildi"},
    "routine.status.changed": {"en": "changed", "tr": "değişti"},
    "routine.status.renamed": {"en": "renamed", "tr": "adı değişti"},
    "routine.status.removed": {"en": "removed", "tr": "kaldırıldı"},
}

_collisions = set(ROUTINE_MESSAGES) & set(MESSAGES)
assert not _collisions, f"routine message keys collide with tau-core: {sorted(_collisions)}"

register_messages(ROUTINE_MESSAGES)
