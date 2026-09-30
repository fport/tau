"""The ``tau sub`` message keys, registered into ``tau_core.i18n`` at import.

What ``tau sub`` prints goes through ``t(key, language)`` with the UI language of the
configuration (``[ui] language``, ``TAU_LANG``, ``tau --lang``). Error lines are the English
text of the exception, like every error raised before a channel exists. The keys must not
collide with tau-core's table, because ``register_messages`` overrides silently; the assertion
at import keeps that honest.
"""

from __future__ import annotations

from tau_core.i18n import MESSAGES, register_messages

SUB_MESSAGES: dict[str, dict[str, str]] = {
    # -- new -----------------------------------------------------------------------------------
    "sub.new.created": {
        "en": "Created /{name}: {path}",
        "tr": "/{name} oluşturuldu: {path}",
    },
    "sub.new.next": {
        "en": "Edit it with `tau sub edit {name}`; talk to it with `tau sub chat {name}`.",
        "tr": "`tau sub edit {name}` ile düzenle; `tau sub chat {name}` ile konuş.",
    },
    "sub.new.drafting": {
        "en": "Asking the brain role to draft /{name}...",
        "tr": "/{name} taslağı brain rolünden isteniyor...",
    },
    "sub.new.draft_header": {
        "en": "Draft of {path}:",
        "tr": "{path} taslağı:",
    },
    "sub.new.dropped": {
        "en": "Left out of the tool list: {tool} ({reason}).",
        "tr": "Araç listesine alınmadı: {tool} ({reason}).",
    },
    "sub.new.confirm": {
        "en": "Write this sub-tau?",
        "tr": "Bu alt-tau yazılsın mı?",
    },
    "sub.new.not_written": {
        "en": "Nothing was written.",
        "tr": "Hiçbir şey yazılmadı.",
    },
    "sub.reason.unknown": {
        "en": "not in the tool catalog",
        "tr": "araç kataloğunda yok",
    },
    "sub.reason.tier2": {
        "en": "tier 2; pass --allow-tier2 to allow it",
        "tr": "tier 2; izin vermek için --allow-tier2 ver",
    },
    "sub.reason.forbidden": {
        "en": "never allowed in a sub-tau",
        "tr": "bir alt-tau'da asla izinli değil",
    },
    # -- list and show -------------------------------------------------------------------------
    "sub.list.none": {
        "en": 'No sub-taus yet. Create one with `tau sub new NAME --describe "..."`.',
        "tr": 'Henüz alt-tau yok. `tau sub new AD --describe "..."` ile bir tane oluştur.',
    },
    "sub.list.row": {
        "en": "/{name}  role: {role}  tools: {tools}  public: {public}  session: {session}",
        "tr": "/{name}  rol: {role}  araçlar: {tools}  herkese açık: {public}  oturum: {session}",
    },
    "sub.list.about": {"en": "    {about}", "tr": "    {about}"},
    "sub.list.broken": {
        "en": "/{name}  not valid: {error}",
        "tr": "/{name}  geçersiz: {error}",
    },
    "sub.none": {"en": "none", "tr": "yok"},
    "sub.yes": {"en": "yes", "tr": "evet"},
    "sub.no": {"en": "no", "tr": "hayır"},
    "sub.show.title": {"en": "/{name}  ({path})", "tr": "/{name}  ({path})"},
    "sub.show.about": {"en": "about:        {about}", "tr": "hakkında:     {about}"},
    "sub.show.role": {"en": "role:         {role}", "tr": "rol:          {role}"},
    "sub.show.tools": {"en": "tools:        {tools}", "tr": "araçlar:      {tools}"},
    "sub.show.public": {"en": "public:       {public}", "tr": "herkese açık: {public}"},
    "sub.show.public_note": {"en": "public note:  {note}", "tr": "açık not:     {note}"},
    "sub.show.session": {"en": "session:      {session}", "tr": "oturum:       {session}"},
    "sub.show.web": {"en": "web page:     {web}", "tr": "web sayfası:  {web}"},
    "sub.show.web_off_private": {
        "en": "yes, but only public sub-taus get a page (set public = true)",
        "tr": "evet, ama yalnızca herkese açık alt-tau'ların sayfası olur (public = true yap)",
    },
    "sub.show.web_daily": {
        "en": "visitor turns: at most {n} a day (UTC)",
        "tr": "ziyaretçi turu: günde en çok {n} (UTC)",
    },
    "sub.show.starters": {"en": "starters:     {starters}", "tr": "açılışlar:    {starters}"},
    "sub.show.persona": {"en": "persona:", "tr": "persona:"},
    # -- edit and remove -----------------------------------------------------------------------
    "sub.edit.valid": {
        "en": "/{name} is valid.",
        "tr": "/{name} geçerli.",
    },
    "sub.edit.unchanged": {
        "en": "/{name} is unchanged.",
        "tr": "/{name} değişmedi.",
    },
    "sub.remove.confirm": {
        "en": "Remove the definition of /{name}? Its sessions are kept.",
        "tr": "/{name} tanımı kaldırılsın mı? Oturumları korunur.",
    },
    "sub.remove.kept": {
        "en": "Nothing was removed.",
        "tr": "Hiçbir şey kaldırılmadı.",
    },
    "sub.remove.done": {
        "en": "Removed {path}. The sessions of /{name} are kept; nothing else is deleted.",
        "tr": "{path} kaldırıldı. /{name} oturumları korunuyor; başka hiçbir şey silinmedi.",
    },
    # -- chat and ask --------------------------------------------------------------------------
    "sub.chat.ready": {
        "en": "/{name} ready. Session: {session}. Commands: {hint} (Ctrl-D also quits).",
        "tr": "/{name} hazır. Oturum: {session}. Komutlar: {hint} (Ctrl-D de çıkar).",
    },
    "sub.chat.reply_prefix": {"en": "/{name}> ", "tr": "/{name}> "},
    "sub.chat.help": {
        "en": "/tools lists its tools, /new starts a fresh session, /session shows the "
        "current one, /quit leaves.",
        "tr": "/tools araçlarını listeler, /new yeni oturum başlatır, /session geçerli oturumu "
        "gösterir, /quit çıkar.",
    },
    "sub.chat.unsupported": {
        "en": "/{command} is not available in a sub-tau chat. Commands: {hint}",
        "tr": "/{command} alt-tau sohbetinde yok. Komutlar: {hint}",
    },
    "sub.chat.new": {
        "en": "New session: {session}.",
        "tr": "Yeni oturum: {session}.",
    },
    "sub.chat.session": {
        "en": "Session: {session} ({n} messages).",
        "tr": "Oturum: {session} ({n} mesaj).",
    },
    "sub.chat.prompt_reloaded": {
        "en": "/{name} changed on disk; the new persona applies from this turn.",
        "tr": "/{name} diskte değişti; yeni persona bu turdan itibaren geçerli.",
    },
    "sub.chat.rebuilt": {
        "en": "/{name} changed its role or tools; rebuilt on the same session.",
        "tr": "/{name} rolünü ya da araçlarını değiştirdi; aynı oturumda yeniden kuruldu.",
    },
    "sub.chat.reload_failed": {
        "en": "/{name} could not be reloaded ({error}); the previous version keeps running.",
        "tr": "/{name} yeniden yüklenemedi ({error}); önceki sürüm çalışmaya devam ediyor.",
    },
    "sub.tools.none": {
        "en": "/{name} has no tools.",
        "tr": "/{name} için araç yok.",
    },
    "sub.tools.header": {
        "en": "Tools of /{name} ({n}):",
        "tr": "/{name} araçları ({n}):",
    },
}

_collisions = set(SUB_MESSAGES) & set(MESSAGES)
assert not _collisions, f"tau-sub message keys collide with tau-core: {sorted(_collisions)}"

register_messages(SUB_MESSAGES)
