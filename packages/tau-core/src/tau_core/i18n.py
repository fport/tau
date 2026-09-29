"""UI language and the message table shared by every channel.

Everything a person reads in the chrome of a channel (slash-command help, notices, the approval
prompt, tier labels, pane titles, key hints) is looked up here by a stable dotted key, so the
terminal REPL and the TUI never drift apart. The per-installation language comes from
``Config.ui.language`` (``[ui] language`` in ``tau.toml``, ``TAU_LANG``, ``tau --lang``);
``/lang`` switches it for one run.

What the *model* reads (system-prompt scaffolding, tool descriptions, gate texts) is fixed
English and is not in this table. Errors raised before a ``Config`` exists (``ConfigError``,
``MissingCredentials``, hub messages) are plain English too.

Plugins add their own keys with :func:`register_messages`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

__all__ = [
    "DEFAULT_LANGUAGE",
    "LANGUAGES",
    "MESSAGES",
    "Language",
    "register_messages",
    "t",
]

Language = Literal["en", "tr"]
LANGUAGES: tuple[str, ...] = ("en", "tr")
DEFAULT_LANGUAGE = "en"

MESSAGES: dict[str, dict[str, str]] = {
    # -- slash commands (help lines; the canonical names are in tau_core.commands) ----------
    "command.help": {
        "en": "list the commands",
        "tr": "komutları listeler",
    },
    "command.tools": {
        "en": "registered tools with their tier and description",
        "tr": "kayıtlı araçlar, tier ve açıklamalarıyla",
    },
    "command.sessions": {
        "en": "list the 10 most recent earlier sessions",
        "tr": "en son 10 önceki oturumu listeler",
    },
    "command.resume": {
        "en": "resume the most recent earlier session, the n-th of the last listing, or an id",
        "tr": "en son önceki oturuma, son listenin n'incisine ya da verilen kimliğe devam eder",
    },
    "command.new": {
        "en": "start a fresh session",
        "tr": "yeni bir oturum başlatır",
    },
    "command.session": {
        "en": "current session id, title, message count and store",
        "tr": "geçerli oturumun kimliği, başlığı, mesaj sayısı ve deposu",
    },
    "command.lang": {
        "en": "switch the UI language for this run",
        "tr": "bu çalıştırma için arayüz dilini değiştirir",
    },
    "command.quit": {
        "en": "leave",
        "tr": "çıkar",
    },
    # -- terminal channel ----------------------------------------------------------------------
    "chat.prompt": {"en": "you> ", "tr": "sen> "},
    "chat.reply_prefix": {"en": "tau> ", "tr": "tau> "},
    "chat.ready": {
        "en": "tau ready. Profile: {profile}, session: {session}. Commands: {hint} "
        "(Ctrl-D also quits).",
        "tr": "tau hazır. Profil: {profile}, oturum: {session}. Komutlar: {hint} "
        "(Ctrl-D ile de çıkabilirsiniz).",
    },
    "chat.help_header": {"en": "Commands:", "tr": "Komutlar:"},
    "chat.unknown_command": {
        "en": "Unknown command: /{name}. Commands: {hint}",
        "tr": "Bilinmeyen komut: /{name}. Komutlar: {hint}",
    },
    "chat.interrupted": {"en": "Interrupted.", "tr": "Kesildi."},
    # -- tools -----------------------------------------------------------------------------------
    "tools.none": {"en": "No tools registered.", "tr": "Kayıtlı araç yok."},
    "tools.header": {"en": "Tools ({n}):", "tr": "Araçlar ({n}):"},
    "tool.rejected": {"en": "{tool}: not approved", "tr": "{tool}: onaylanmadı"},
    "tier.0": {"en": "read", "tr": "okuma"},
    "tier.1": {"en": "digital write, logged", "tr": "dijital yazma, günlüğe yazılır"},
    "tier.2": {"en": "physical, needs approval", "tr": "fiziksel, onay gerekir"},
    # -- sessions --------------------------------------------------------------------------------
    "session.recent_header": {"en": "Recent sessions:", "tr": "Son oturumlar:"},
    "session.none_earlier": {
        "en": "No earlier session to resume.",
        "tr": "Devam edilecek önceki oturum yok.",
    },
    "session.untitled": {"en": "(untitled)", "tr": "(başlıksız)"},
    "session.messages": {"en": "{n} messages", "tr": "{n} mesaj"},
    "session.already_current": {
        "en": "You are already in this session: {session}.",
        "tr": "Zaten bu oturumdasınız: {session}.",
    },
    "session.not_found": {
        "en": "Session not found: {session}.",
        "tr": "Oturum bulunamadı: {session}.",
    },
    "session.no_such_number": {
        "en": "There is no session {n} in the list (1-{count}).",
        "tr": "Listede {n} numaralı oturum yok (1-{count}).",
    },
    "session.open_failed": {
        "en": "Could not open the session: {error}",
        "tr": "Oturum açılamadı: {error}",
    },
    "session.resumed": {
        "en": "Resuming: {title} · {session} ({n} messages loaded).",
        "tr": "Devam ediliyor: {title} · {session} ({n} mesaj yüklendi).",
    },
    "session.new": {"en": "New session: {session}.", "tr": "Yeni oturum: {session}."},
    "session.info.id": {"en": "Session: {session}", "tr": "Oturum: {session}"},
    "session.info.title": {"en": "Title: {title}", "tr": "Başlık: {title}"},
    "session.info.count": {"en": "Messages: {n}", "tr": "Mesaj sayısı: {n}"},
    "session.info.store": {"en": "Store: {store}", "tr": "Depo: {store}"},
    # -- language --------------------------------------------------------------------------------
    "lang.switched": {"en": "UI language: {language}.", "tr": "Arayüz dili: {language}."},
    "lang.usage": {
        "en": "Usage: /lang {choices} (current: {language}).",
        "tr": "Kullanım: /lang {choices} (şu an: {language}).",
    },
    "lang.unknown": {
        "en": "Unknown language: {language}. Choose one of: {choices}.",
        "tr": "Bilinmeyen dil: {language}. Seçenekler: {choices}.",
    },
    # -- approval prompt (terminal and TUI share the labels) ------------------------------------
    "approval.title": {
        "en": "Approval needed (tier {tier})",
        "tr": "Onay gerekiyor (tier {tier})",
    },
    "approval.tool": {"en": "Tool", "tr": "Araç"},
    "approval.arguments": {"en": "Arguments", "tr": "Argümanlar"},
    "approval.effect": {"en": "Effect", "tr": "Etki"},
    "approval.question": {"en": "Approve? [y/N] ", "tr": "Onaylıyor musunuz? [e/H] "},
    "approval.hint": {
        "en": "Approve? y: approve · n or Esc: reject",
        "tr": "Onaylıyor musunuz? e: onayla · h veya Esc: reddet",
    },
    "approval.approve": {"en": "Approve", "tr": "Onayla"},
    "approval.reject": {"en": "Reject", "tr": "Reddet"},
    # -- turn notices (shown to the user and kept in the history) --------------------------------
    "notice.turn_limit": {
        "en": "I reached the tool-call limit for this turn ({n} turns). I stopped; tell me if "
        "you want me to continue.",
        "tr": "Bu turda araç çağrısı sınırına ulaştım ({n} tur). Durdum; devam etmemi "
        "isterseniz söyleyin.",
    },
    "notice.model_error": {
        "en": "Model call failed: {detail}. Details are in the log.",
        "tr": "Model çağrısı başarısız oldu: {detail}. Ayrıntı günlükte.",
    },
    "notice.max_tokens": {
        "en": "The reply hit the length limit; say so if you want me to continue.",
        "tr": "Yanıt uzunluk sınırına takıldı; devam etmemi isterseniz söyleyin.",
    },
    "notice.total_tokens": {
        "en": "I reached the token budget for this turn. I stopped; tell me if you want me to "
        "continue.",
        "tr": "Bu turun token bütçesine ulaştım. Durdum; devam etmemi isterseniz söyleyin.",
    },
    "notice.cancelled": {"en": "Turn cancelled.", "tr": "Tur iptal edildi."},
    "notice.busy": {
        "en": "I am still answering the previous turn.",
        "tr": "Hâlâ önceki tura yanıt veriyorum.",
    },
    "notice.throttled": {
        "en": "Model is busy, retrying in {seconds} s.",
        "tr": "Model yoğun, {seconds} sn sonra tekrar deniyorum.",
    },
    "notice.overflow": {
        "en": "The conversation no longer fits the model's context window; start a new session "
        "with /new.",
        "tr": "Konuşma modelin bağlam penceresine sığmıyor; /new ile yeni bir oturum açın.",
    },
    "notice.interrupt_refused": {
        "en": "A tool asked for an interrupt this channel cannot answer; it was refused.",
        "tr": "Bir araç bu kanalın yanıtlayamadığı bir kesme istedi; reddedildi.",
    },
    "notice.previous_turn_unfinished": {
        "en": "The previous turn did not finish.",
        "tr": "Önceki tur tamamlanmadı.",
    },
    # -- TUI (consumed by tau-tui; kept here so both channels share one table) --------------------
    "tui.placeholder": {
        "en": "Type a message · /help · /quit",
        "tr": "Mesajınızı yazın · /help · /quit",
    },
    "tui.header.profile": {"en": "profile", "tr": "profil"},
    "tui.header.session": {"en": "session", "tr": "oturum"},
    "tui.pane.chat": {"en": "Chat", "tr": "Sohbet"},
    "tui.pane.events": {"en": "Events", "tr": "Olaylar"},
    "tui.user_label": {"en": "you", "tr": "sen"},
    "tui.tau_label": {"en": "tau", "tr": "tau"},
    "tui.welcome": {
        "en": "Welcome. Type a message, /help lists the commands.",
        "tr": "Hoş geldiniz. Bir mesaj yazın; /help komutları listeler.",
    },
    "tui.welcome.resumed": {
        "en": "Resumed session {session}{title}.",
        "tr": "{session}{title} oturumuna devam ediliyor.",
    },
    "tui.quit_hint": {
        "en": "Press Ctrl+Q or type /quit to leave.",
        "tr": "Çıkmak için Ctrl+Q'ya basın veya /quit yazın.",
    },
    "tui.busy": {
        "en": "tau is still answering; send again when it is done.",
        "tr": "tau hâlâ yanıtlıyor; bitince tekrar gönderin.",
    },
    "tui.unknown_command": {
        "en": "Unknown command: /{name}. Commands: {hint}",
        "tr": "Bilinmeyen komut: /{name}. Komutlar: {hint}",
    },
    "tui.tools.none": {"en": "No tools registered.", "tr": "Kayıtlı araç yok."},
    "tui.tools.header": {"en": "Tools ({n}):", "tr": "Araçlar ({n}):"},
    "tui.sessions.header": {"en": "Recent sessions:", "tr": "Son oturumlar:"},
    "tui.sessions.none": {
        "en": "No earlier session to resume.",
        "tr": "Devam edilecek önceki oturum yok.",
    },
    "tui.resume.notice": {
        "en": "Resuming session: {session}{title}",
        "tr": "Oturuma devam ediliyor: {session}{title}",
    },
    "tui.resume.none": {
        "en": "No session to resume; a new session was opened.",
        "tr": "Devam edilecek oturum yok; yeni bir oturum açıldı.",
    },
    "tui.resume.not_found": {
        "en": "Session not found: {session}.",
        "tr": "Oturum bulunamadı: {session}.",
    },
    "tui.session.new": {"en": "New session: {session}.", "tr": "Yeni oturum: {session}."},
    "tui.approval.title": {
        "en": "Approval needed (tier {tier})",
        "tr": "Onay gerekiyor (tier {tier})",
    },
    "tui.approval.tool": {"en": "Tool", "tr": "Araç"},
    "tui.approval.arguments": {"en": "Arguments", "tr": "Argümanlar"},
    "tui.approval.effect": {"en": "Effect", "tr": "Etki"},
    "tui.approval.hint": {
        "en": "Approve? y: approve · n or Esc: reject",
        "tr": "Onaylıyor musunuz? e: onayla · h veya Esc: reddet",
    },
    "tui.approval.approve": {"en": "Approve", "tr": "Onayla"},
    "tui.approval.reject": {"en": "Reject", "tr": "Reddet"},
    "tui.key.quit": {"en": "Quit", "tr": "Çık"},
    "tui.key.help": {"en": "Help", "tr": "Yardım"},
    "tui.key.cancel": {"en": "Cancel turn", "tr": "Turu iptal et"},
    "tui.key.new": {"en": "New session", "tr": "Yeni oturum"},
    "tui.key.sessions": {"en": "Sessions", "tr": "Oturumlar"},
    "tui.key.tools": {"en": "Tools", "tr": "Araçlar"},
    "tui.key.approve": {"en": "Approve", "tr": "Onayla"},
    "tui.key.reject": {"en": "Reject", "tr": "Reddet"},
    "tui.lang.switched": {"en": "UI language: {language}.", "tr": "Arayüz dili: {language}."},
    "tui.cancelled": {"en": "Turn cancelled.", "tr": "Tur iptal edildi."},
    "tui.unexpected_error": {
        "en": "Unexpected error: {detail}. Details are in the log.",
        "tr": "Beklenmeyen hata: {detail}. Ayrıntı günlükte.",
    },
    "tui.event.turn_limit": {"en": "turn limit: {n} turns", "tr": "tur sınırı: {n} tur"},
    "tui.event.error": {"en": "error", "tr": "hata"},
    "tui.event.approval": {"en": "approval", "tr": "onay"},
}


def t(key: str, language: str = DEFAULT_LANGUAGE, /, **kwargs: object) -> str:
    """The message ``key`` in ``language``, formatted with ``kwargs`` (``str.format``).

    An unknown key raises ``KeyError`` (a programming error, so tests catch it). A language
    that lacks the key, or an unknown language, falls back to English.
    """
    templates = MESSAGES[key]
    template = templates.get(language)
    if template is None:
        template = templates[DEFAULT_LANGUAGE]
    return template.format(**kwargs) if kwargs else template


def register_messages(mapping: Mapping[str, Mapping[str, str]]) -> None:
    """Add (or extend) message keys, e.g. from a plugin: ``{"mine.hello": {"en": ..., "tr": ...}}``.

    Every entry needs an English template; other languages are optional and fall back to it.
    """
    for key, templates in mapping.items():
        if DEFAULT_LANGUAGE not in templates and key not in MESSAGES:
            raise ValueError(f"message {key!r} needs an {DEFAULT_LANGUAGE!r} template")
        MESSAGES.setdefault(key, {}).update({str(k): str(v) for k, v in templates.items()})
