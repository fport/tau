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
    "command.compact": {
        "en": "summarize this session into a new one and continue there (the old one is kept)",
        "tr": "bu oturumu özetleyip yeni bir oturumda devam eder (eskisi saklanır)",
    },
    "command.clear": {
        "en": "clear the screen; the session continues",
        "tr": "ekranı temizler; oturum devam eder",
    },
    "command.status": {
        "en": "profile, session, model, context, tools, language, versions and hub",
        "tr": "profil, oturum, model, bağlam, araçlar, dil, sürümler ve hub",
    },
    "command.model": {
        "en": "show the model roles, or switch this session to one",
        "tr": "model rollerini gösterir ya da bu oturumu bir role geçirir",
    },
    "command.lang": {
        "en": "switch the UI language for this run",
        "tr": "bu çalıştırma için arayüz dilini değiştirir",
    },
    "command.settings": {
        "en": "show the settings, or change one (language, profile, model, set NAME)",
        "tr": "ayarları gösterir ya da birini değiştirir (language, profile, model, set AD)",
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
    # -- clear, compact, status, model -------------------------------------------------------------
    "clear.done": {
        "en": "Screen cleared; the session continues ({n} messages kept).",
        "tr": "Ekran temizlendi; oturum devam ediyor ({n} mesaj korundu).",
    },
    "compact.started": {"en": "Compacting {n} messages…", "tr": "{n} mesaj özetleniyor…"},
    "compact.done": {
        "en": "Compacted {n} messages into a summary. New session {session}; the previous "
        "session {previous} is kept.",
        "tr": "{n} mesaj bir özete indirildi. Yeni oturum {session}; önceki oturum {previous} "
        "saklandı.",
    },
    "compact.failed": {
        "en": "Compaction failed: {error}",
        "tr": "Özetleme başarısız oldu: {error}",
    },
    "compact.cancelled": {
        "en": "Compaction cancelled; the session continues.",
        "tr": "Özetleme iptal edildi; oturum devam ediyor.",
    },
    "status.profile": {"en": "Profile: {profile}", "tr": "Profil: {profile}"},
    "status.session": {
        "en": "Session: {session} · {title} · {n} messages stored · role {role}",
        "tr": "Oturum: {session} · {title} · {n} mesaj kayıtlı · rol {role}",
    },
    "status.model": {
        "en": "Model: {role} → {provider} · {model_id}",
        "tr": "Model: {role} → {provider} · {model_id}",
    },
    "status.model_fallback": {
        "en": "Model: {role} → {provider} (fallback; {primary} has no credentials) · {model_id}",
        "tr": "Model: {role} → {provider} (yedek; {primary} için kimlik bilgisi yok) · {model_id}",
    },
    "status.context": {
        "en": "Context: {mode}, window {window} · {n} messages in memory",
        "tr": "Bağlam: {mode}, pencere {window} · bellekte {n} mesaj",
    },
    "status.tools": {
        "en": "Tools: {n} registered · {approval} need approval (tier 2)",
        "tr": "Araçlar: {n} kayıtlı · {approval} onay ister (tier 2)",
    },
    "status.language": {"en": "UI language: {language}", "tr": "Arayüz dili: {language}"},
    "status.versions": {"en": "Versions: {versions}", "tr": "Sürümler: {versions}"},
    "status.hub": {"en": "Hub: {detail}", "tr": "Hub: {detail}"},
    "status.budget": {"en": "Budget: {detail}", "tr": "Bütçe: {detail}"},
    "model.current": {
        "en": "Model role: {role} ({provider})",
        "tr": "Model rolü: {role} ({provider})",
    },
    "model.roles_header": {"en": "Roles in tau.toml:", "tr": "tau.toml'daki roller:"},
    "model.fallback_note": {"en": "fallback {provider}", "tr": "yedek {provider}"},
    "model.current_mark": {"en": "current", "tr": "geçerli"},
    "model.unknown": {
        "en": "Unknown role: {role}. Roles: {roles}",
        "tr": "Bilinmeyen rol: {role}. Roller: {roles}",
    },
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
    # -- settings (the bootstrap config, tau_core.settings; shared by both channels) -------------
    "settings.header": {"en": "Settings · {home}", "tr": "Ayarlar · {home}"},
    "settings.roles_header": {"en": "Model roles:", "tr": "Model rolleri:"},
    "settings.cred.ok": {"en": "credentials ok", "tr": "kimlik bilgileri tamam"},
    "settings.cred.none": {"en": "no credentials needed", "tr": "kimlik bilgisi gerekmez"},
    "settings.cred.missing": {"en": "missing {names}", "tr": "eksik: {names}"},
    "settings.cred.fallback": {
        "en": "missing {names} · fallback {provider} in use",
        "tr": "eksik: {names} · yedek {provider} kullanılıyor",
    },
    "settings.cred.unavailable": {
        "en": "provider not available: {detail}",
        "tr": "sağlayıcı kullanılamıyor: {detail}",
    },
    "settings.interface": {
        "en": "UI language: {language} · profile: {profile}",
        "tr": "Arayüz dili: {language} · profil: {profile}",
    },
    "settings.agent": {
        "en": "Context: {mode}, window {window} · max_turns {turns} · max_total_tokens {tokens}",
        "tr": "Bağlam: {mode}, pencere {window} · max_turns {turns} · max_total_tokens {tokens}",
    },
    "settings.none": {"en": "none", "tr": "yok"},
    "settings.files_header": {"en": "Files:", "tr": "Dosyalar:"},
    "settings.file_present": {"en": "present", "tr": "var"},
    "settings.file_missing": {"en": "missing", "tr": "yok"},
    "settings.hint": {
        "en": "Change: /settings language en|tr · /settings profile NAME · /settings model ROLE "
        "PROVIDER MODEL_ID · /settings set NAME · /settings clear NAME. The TUI (`tau tui`) "
        "has an editor: /settings or F10. `tau init --force` rewrites tau.toml from the template.",
        "tr": "Değiştirmek için: /settings language en|tr · /settings profile AD · /settings model "
        "ROL SAĞLAYICI MODEL_ID · /settings set AD · /settings clear AD. TUI'de (`tau tui`) bir "
        "düzenleyici var: /settings ya da F10. `tau init --force` tau.toml'u şablondan yeniden "
        "yazar.",
    },
    "settings.usage": {
        "en": "Usage: /settings [language en|tr | profile NAME | model ROLE PROVIDER MODEL_ID | "
        "set NAME | clear NAME]",
        "tr": "Kullanım: /settings [language en|tr | profile AD | model ROL SAĞLAYICI MODEL_ID | "
        "set AD | clear AD]",
    },
    "settings.saved": {"en": "Settings saved.", "tr": "Ayarlar kaydedildi."},
    "settings.saved_reloaded": {
        "en": "Settings saved; model reloaded.",
        "tr": "Ayarlar kaydedildi; model yeniden yüklendi.",
    },
    "settings.saved_not_reloaded": {
        "en": "Settings saved, but the agent could not be rebuilt: {error}",
        "tr": "Ayarlar kaydedildi ama ajan yeniden kurulamadı: {error}",
    },
    "settings.invalid": {"en": "Not saved: {error}", "tr": "Kaydedilmedi: {error}"},
    "settings.credential_set": {
        "en": "{name} set in .env.",
        "tr": "{name} .env dosyasına yazıldı.",
    },
    "settings.credential_cleared": {
        "en": "{name} removed from .env.",
        "tr": "{name} .env dosyasından silindi.",
    },
    "settings.credential_absent": {
        "en": "{name} is not in .env.",
        "tr": "{name} .env dosyasında yok.",
    },
    "settings.credential_empty": {
        "en": "Nothing entered; {name} is unchanged.",
        "tr": "Bir şey girilmedi; {name} değişmedi.",
    },
    "settings.enter_value": {
        "en": "Value for {name} (not echoed): ",
        "tr": "{name} değeri (görünmez): ",
    },
    "settings.fallback_notice": {
        "en": "{role}: using the fallback provider {provider} ({primary} has no credentials). "
        "Add them in /settings.",
        "tr": "{role}: yedek sağlayıcı {provider} kullanılıyor ({primary} için kimlik bilgisi "
        "yok). /settings ile ekleyin.",
    },
    "settings.no_credentials": {
        "en": "Add credentials in /settings",
        "tr": "/settings ile kimlik bilgisi ekleyin",
    },
    "settings.no_provider": {
        "en": "Choose an available provider in /settings",
        "tr": "/settings ile kullanılabilir bir sağlayıcı seçin",
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
    # -- model budgets and failover (tau_core.budget, ADR 0011) ------------------------------------
    "notice.budget_exhausted": {
        "en": "The {role} budget is spent (${spend} of ${cap}) and resets at {reset}. To raise "
        "the cap, change it in tau.toml.",
        "tr": "{role} bütçesi doldu (${spend} / ${cap}); {reset} itibarıyla yenileniyor. Sınırı "
        "artırmak için tau.toml'da değiştirin.",
    },
    "notice.budget_exhausted_also": {
        "en": "The {role} budget is spent until {reset}, and {degrade}, which stands in for it, "
        "is spent too until {degrade_reset}.",
        "tr": "{role} bütçesi doldu ({reset} itibarıyla yenilenecek); yerine geçen {degrade} "
        "bütçesi de doldu ({degrade_reset} itibarıyla yenilenecek).",
    },
    "notice.budget_degraded": {
        "en": "The {role} budget is spent until {reset}; {degrade} answered instead.",
        "tr": "{role} bütçesi doldu ({reset} itibarıyla yenilenecek); bu yanıtı {degrade} verdi.",
    },
    "notice.failover": {
        "en": "{role} is not reachable right now; {failover} answered instead.",
        "tr": "{role} şu an ulaşılamıyor; bu yanıtı {failover} verdi.",
    },
    "budget.reset_unknown": {"en": "the end of its period", "tr": "dönem sonu"},
    # -- Telegram channel (tau_core.channels.telegram) -------------------------------------------
    "telegram.unavailable": {
        "en": "/{command} is not available on Telegram; use tau chat or the TUI on the hub.",
        "tr": "/{command} Telegram'da kullanılamaz; hub'da tau chat ya da TUI'yi kullan.",
    },
    "telegram.text_only": {
        "en": "I can only read text messages here for now.",
        "tr": "Burada şimdilik yalnızca metin mesajlarını okuyabiliyorum.",
    },
    "telegram.turn_failed": {
        "en": "The turn failed: {detail}. Details are in the hub log.",
        "tr": "Tur başarısız oldu: {detail}. Ayrıntı hub günlüğünde.",
    },
    "telegram.empty_reply": {
        "en": "(no reply)",
        "tr": "(yanıt yok)",
    },
    "telegram.approval.approved": {"en": "✓ Approved.", "tr": "✓ Onaylandı."},
    "telegram.approval.rejected": {"en": "✗ Rejected.", "tr": "✗ Reddedildi."},
    "telegram.approval.timeout": {
        "en": "⏱ No answer in time; not approved.",
        "tr": "⏱ Zamanında cevap gelmedi; onaylanmadı.",
    },
    "telegram.approval.cancelled": {
        "en": "The hub stopped before an answer; not approved.",
        "tr": "Hub cevaptan önce durdu; onaylanmadı.",
    },
    "telegram.approval.expired": {
        "en": "This request is no longer waiting for an answer.",
        "tr": "Bu istek artık cevap beklemiyor.",
    },
    # -- tau telegram pair / status (issue 172) ------------------------------------------------
    "telegram.pair.done": {
        "en": "Paired. From now on tau answers only this chat here. /help lists the commands.",
        "tr": "Eşleşme tamam. tau bundan sonra burada yalnızca bu sohbete yanıt verir. /help "
        "komutları listeler.",
    },
    "telegram.pair.token_prompt": {
        "en": "Bot token from @BotFather (hidden)",
        "tr": "@BotFather'dan aldığın bot token'ı (gizli)",
    },
    "telegram.pair.token_prompt_keep": {
        "en": "Bot token from @BotFather (hidden; Enter keeps the current one)",
        "tr": "@BotFather'dan aldığın bot token'ı (gizli; Enter mevcut olanı korur)",
    },
    "telegram.pair.no_token": {
        "en": "No token given. Create a bot with @BotFather (/newbot) and paste its token.",
        "tr": "Token girilmedi. @BotFather ile bir bot oluştur (/newbot) ve token'ını yapıştır.",
    },
    "telegram.pair.token_invalid": {
        "en": "That does not look like a bot token (digits, a colon, then letters and digits). "
        "Nothing was written.",
        "tr": "Bu bir bot token'ına benzemiyor (rakamlar, iki nokta, sonra harf ve rakamlar). "
        "Hiçbir şey yazılmadı.",
    },
    "telegram.pair.bad_json": {
        "en": '--json reads one JSON object on stdin, with the token under "token".',
        "tr": '--json stdin\'den tek bir JSON nesnesi okur; token "token" alanında olmalı.',
    },
    "telegram.pair.checking": {
        "en": "Checking the token with Telegram...",
        "tr": "Token Telegram'a soruluyor...",
    },
    "telegram.pair.token_refused": {
        "en": "Telegram refused the token ({detail}). Check it in @BotFather; nothing was written.",
        "tr": "Telegram token'ı reddetti ({detail}). @BotFather'da kontrol et; hiçbir şey "
        "yazılmadı.",
    },
    "telegram.pair.unreachable": {
        "en": "Telegram could not be reached ({detail}). Check the connection and try again; "
        "nothing was written.",
        "tr": "Telegram'a ulaşılamadı ({detail}). Bağlantıyı kontrol edip yeniden dene; hiçbir "
        "şey yazılmadı.",
    },
    "telegram.pair.token_ok": {
        "en": "Telegram knows the bot as @{bot}.",
        "tr": "Telegram botu @{bot} olarak tanıyor.",
    },
    "telegram.pair.token_written": {
        "en": "wrote {name} to {path} (mode 0600)",
        "tr": "{name}, {path} dosyasına yazıldı (izin 0600)",
    },
    "telegram.pair.token_kept": {
        "en": "kept  {name} in {path}",
        "tr": "{path} içindeki {name} korundu",
    },
    "telegram.pair.env_failed": {
        "en": "{name} could not be written to {path}: {reason}",
        "tr": "{name}, {path} dosyasına yazılamadı: {reason}",
    },
    "telegram.pair.env_shadowed": {
        "en": "Note: {name} is also set in this shell's environment. A hub started from this "
        "shell uses that value, not the one in .env.",
        "tr": "Not: {name} bu kabuğun ortamında da tanımlı. Bu kabuktan başlatılan bir hub "
        ".env'dekini değil, o değeri kullanır.",
    },
    "telegram.pair.instructions": {
        "en": "Open t.me/{bot} in Telegram and send: /start {code}",
        "tr": "Telegram'da t.me/{bot} adresini aç ve şunu gönder: /start {code}",
    },
    "telegram.pair.link": {
        "en": "Or in one tap: {link}",
        "tr": "Ya da tek dokunuşla: {link}",
    },
    "telegram.pair.valid": {
        "en": "The code works once, for {minutes} minutes (until {time}). Waiting for it; "
        "Ctrl-C cancels.",
        "tr": "Kod bir kez ve {minutes} dakika geçerli ({time} saatine kadar). Bekleniyor; "
        "Ctrl-C iptal eder.",
    },
    "telegram.pair.via_hub": {
        "en": "The running hub takes the code.",
        "tr": "Kodu çalışan hub alacak.",
    },
    "telegram.pair.via_cli": {
        "en": "The hub is not running, so this command polls Telegram itself until the code "
        "arrives.",
        "tr": "Hub çalışmıyor; bu komut kod gelene kadar Telegram'ı kendisi yoklayacak.",
    },
    "telegram.pair.conflict": {
        "en": "Another process is polling this bot (a hub elsewhere with the same token?); "
        "retrying.",
        "tr": "Bu botu başka bir süreç yokluyor (aynı token'la başka bir yerde çalışan bir "
        "hub?); yeniden deneniyor.",
    },
    "telegram.pair.hub_conflict": {
        "en": "The running hub polls Telegram but cannot take a pairing code (an older "
        "version?). Restart it (tau hub stop, then tau hub run) and run tau telegram pair again.",
        "tr": "Çalışan hub Telegram'ı yokluyor ama eşleşme kodu alamıyor (eski bir sürüm mü?). "
        "Yeniden başlat (tau hub stop, sonra tau hub run) ve tau telegram pair'i tekrar "
        "çalıştır.",
    },
    "telegram.pair.hub_mismatch": {
        "en": "The running hub did not take the pairing code ({reason}). Does it use another "
        "TAU_HOME or TAU_DATA_DIR? Nothing was paired.",
        "tr": "Çalışan hub eşleşme kodunu almadı ({reason}). Başka bir TAU_HOME ya da "
        "TAU_DATA_DIR mi kullanıyor? Eşleşme yapılmadı.",
    },
    "telegram.pair.hub_error": {
        "en": "The hub refused to reload its Telegram channel ({detail}); see its log.",
        "tr": "Hub Telegram kanalını yeniden yüklemeyi reddetti ({detail}); günlüğüne bak.",
    },
    "telegram.pair.paired": {
        "en": "Paired with {name}. tau answers only this chat on Telegram from now on.",
        "tr": "{name} ile eşleşildi. tau bundan sonra Telegram'da yalnızca bu sohbete yanıt verir.",
    },
    "telegram.pair.dropped": {
        "en": "Chats that were allowed before and are not any more: {n}.",
        "tr": "Daha önce izinli olup artık izinli olmayan sohbetler: {n}.",
    },
    "telegram.pair.start_hub": {
        "en": "Start the hub to talk to tau there: tau hub run (or tau hub install).",
        "tr": "Orada tau ile konuşmak için hub'ı başlat: tau hub run (ya da tau hub install).",
    },
    "telegram.pair.expired": {
        "en": "The code expired before it arrived. Run tau telegram pair again.",
        "tr": "Kod gelmeden süresi doldu. tau telegram pair'i yeniden çalıştır.",
    },
    "telegram.pair.void": {
        "en": "Too many wrong codes were sent, so this code no longer works. Run tau telegram "
        "pair again.",
        "tr": "Çok fazla yanlış kod gönderildi; bu kod artık çalışmıyor. tau telegram pair'i "
        "yeniden çalıştır.",
    },
    "telegram.pair.cancelled": {
        "en": "Pairing cancelled; the code no longer works.",
        "tr": "Eşleşme iptal edildi; kod artık çalışmıyor.",
    },
    "telegram.pair.locked": {
        "en": "A paired chat talks to tau without the guard, so pairing needs tau unlocked. "
        "Unlock it at the Mac (tau guard verify), then run tau telegram pair again.",
        "tr": "Eşleşen sohbet tau ile korumaya takılmadan konuşur; bu yüzden eşleşme için tau'nun "
        "kilidi açık olmalı. Mac'in başında kilidi aç (tau guard verify), sonra tau telegram "
        "pair'i yeniden çalıştır.",
    },
    "telegram.status.token_ok": {
        "en": "Bot token: set (@{bot})",
        "tr": "Bot token'ı: tanımlı (@{bot})",
    },
    "telegram.status.token_refused": {
        "en": "Bot token: set, but Telegram refused it ({detail})",
        "tr": "Bot token'ı: tanımlı ama Telegram reddetti ({detail})",
    },
    "telegram.status.token_unchecked": {
        "en": "Bot token: set (Telegram could not be reached: {detail})",
        "tr": "Bot token'ı: tanımlı (Telegram'a ulaşılamadı: {detail})",
    },
    "telegram.status.token_missing": {
        "en": "Bot token: not set (tau telegram pair sets it)",
        "tr": "Bot token'ı: tanımlı değil (tau telegram pair tanımlar)",
    },
    "telegram.status.paired": {
        "en": "Owner chat: paired ({n} allowed)",
        "tr": "Sahip sohbeti: eşleşmiş ({n} izinli)",
    },
    "telegram.status.unpaired": {
        "en": "Owner chat: not paired (tau telegram pair)",
        "tr": "Sahip sohbeti: eşleşmemiş (tau telegram pair)",
    },
    "telegram.status.pairing": {
        "en": "Pairing code: waiting until {time}",
        "tr": "Eşleşme kodu: {time} saatine kadar bekliyor",
    },
    "telegram.status.hub_off": {
        "en": "Hub: not running",
        "tr": "Hub: çalışmıyor",
    },
    "telegram.status.hub_none": {
        "en": "Hub: running, without a Telegram channel",
        "tr": "Hub: çalışıyor, Telegram kanalı yok",
    },
    "telegram.status.hub_idle": {
        "en": "Hub: running; the Telegram channel is idle ({reason})",
        "tr": "Hub: çalışıyor; Telegram kanalı boşta ({reason})",
    },
    "telegram.status.hub_state": {
        "en": "Hub: running; the Telegram channel is {state}",
        "tr": "Hub: çalışıyor; Telegram kanalı durumu: {state}",
    },
    "telegram.status.hub_polling": {
        "en": "Hub: running; polling as {bot}",
        "tr": "Hub: çalışıyor; {bot} olarak yokluyor",
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
    # -- tau init: the provider key (ADR 0013 §7) ---------------------------------------------
    "init.provider.none": {
        "en": "No model key was found in the environment or {path}. tau needs a key from one "
        "provider (`tau init --yes` sets up the scripted 'fake' provider without one).",
        "tr": "Ortamda ya da {path} içinde model anahtarı bulunamadı. tau'nun bir sağlayıcıdan "
        "anahtara ihtiyacı var (`tau init --yes` anahtarsız, senaryolu 'fake' sağlayıcıyı "
        "kurar).",
    },
    "init.provider.prompt": {"en": "Provider", "tr": "Sağlayıcı"},
    "init.key.prompt": {
        "en": "{name} (hidden; empty skips)",
        "tr": "{name} (gizli; boş bırakırsan atlanır)",
    },
    "init.key.checking": {
        "en": "Checking the key with one small request to {provider}...",
        "tr": "Anahtar {provider} sağlayıcısına tek bir küçük istekle deneniyor...",
    },
    "init.key.ok": {
        "en": "{provider} accepted the key.",
        "tr": "{provider} anahtarı kabul etti.",
    },
    "init.key.unchecked": {
        "en": "The key was not checked (--no-check).",
        "tr": "Anahtar denenmedi (--no-check).",
    },
    "init.key.refused": {
        "en": "{provider} refused the key (HTTP {status}). Check it and run tau init again; "
        "nothing was written.",
        "tr": "{provider} anahtarı reddetti (HTTP {status}). Anahtarı kontrol edip tau init'i "
        "yeniden çalıştır; hiçbir şey yazılmadı.",
    },
    "init.key.http": {
        "en": "{provider} answered the key check with HTTP {status}. Try again later or skip "
        "the check with --no-check; nothing was written.",
        "tr": "{provider} anahtar denemesine HTTP {status} ile yanıt verdi. Sonra yeniden dene "
        "ya da denemeyi --no-check ile atla; hiçbir şey yazılmadı.",
    },
    "init.key.unreachable": {
        "en": "{provider} could not be reached to check the key ({error}). Check the "
        "connection or skip the check with --no-check; nothing was written.",
        "tr": "Anahtarı denemek için {provider} sağlayıcısına ulaşılamadı ({error}). Bağlantıyı "
        "kontrol et ya da denemeyi --no-check ile atla; hiçbir şey yazılmadı.",
    },
    "init.key.invalid": {
        "en": "The key holds spaces, quotes or control characters; paste it again. Nothing "
        "was written.",
        "tr": "Anahtarda boşluk, tırnak ya da kontrol karakteri var; yeniden yapıştır. Hiçbir "
        "şey yazılmadı.",
    },
    "init.key.skipped": {
        "en": "No key given. Add {name} to {path} later; until then the {provider} roles "
        "cannot start.",
        "tr": "Anahtar girilmedi. {name} değerini sonra {path} dosyasına ekle; o zamana kadar "
        "{provider} rolleri başlayamaz.",
    },
    "init.key.written": {
        "en": "wrote {name} to {path} (mode 0600)",
        "tr": "{name}, {path} dosyasına yazıldı (izin 0600)",
    },
    "init.key.kept": {
        "en": "kept  {name} in {path} (it already has a value)",
        "tr": "{path} içindeki {name} korundu (zaten bir değeri var)",
    },
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
