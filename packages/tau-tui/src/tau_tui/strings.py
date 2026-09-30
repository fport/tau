"""The TUI's own message keys, registered into ``tau_core.i18n`` at import.

Shared keys (``command.*``, ``chat.*``, ``tools.*``, ``tier.*``, ``session.*``, ``lang.*``,
``approval.*`` and the ``tui.*`` keys tau-core already defines) are used as they are; the keys
below are new and must not collide with tau-core's table, because ``register_messages``
overrides silently. The assertion at import keeps that honest.
"""

from __future__ import annotations

from tau_core.i18n import MESSAGES, register_messages

TUI_MESSAGES: dict[str, dict[str, str]] = {
    # -- composer, busy verbs ------------------------------------------------------------------
    "tui.composer.placeholder": {"en": "Type a message…", "tr": "Bir mesaj yaz…"},
    "tui.busy.thinking": {"en": "Thinking…", "tr": "Düşünüyor…"},
    "tui.busy.running": {"en": "Running {tool}…", "tr": "{tool} çalışıyor…"},
    "tui.busy.approval": {"en": "Waiting for your approval…", "tr": "Onayın bekleniyor…"},
    "tui.busy.throttled": {
        "en": "Model is busy, retrying in {seconds} s…",
        "tr": "Model yoğun, {seconds} sn sonra tekrar…",
    },
    "tui.busy.cancelling": {"en": "Cancelling…", "tr": "İptal ediliyor…"},
    "tui.busy.summarizing": {"en": "Summarizing…", "tr": "Özetleniyor…"},
    "tui.busy_switch": {
        "en": "Wait for the current turn before switching sessions.",
        "tr": "Oturum değiştirmek için turun bitmesini bekle.",
    },
    "tui.busy_model": {
        "en": "Wait for the current turn before switching the model.",
        "tr": "Modeli değiştirmek için turun bitmesini bekle.",
    },
    "tui.busy_clear": {
        "en": "Wait for the current turn before clearing the screen.",
        "tr": "Ekranı temizlemek için turun bitmesini bekle.",
    },
    "tui.tool.waiting": {"en": "waiting for your approval", "tr": "onayın bekleniyor"},
    # -- turn footer -----------------------------------------------------------------------------
    "tui.turn.worked_for": {"en": "Worked for {s}", "tr": "{s} çalıştı"},
    "tui.turn.tools": {"en": "{n} tool calls", "tr": "{n} araç çağrısı"},
    "tui.turn.tools_one": {"en": "1 tool call", "tr": "1 araç çağrısı"},
    "tui.turn.expand_hint": {"en": "ctrl+o expand", "tr": "ctrl+o aç"},
    "tui.turn.collapse_hint": {"en": "ctrl+o collapse", "tr": "ctrl+o kapat"},
    "tui.turn.thought_for": {"en": "Thought for {s}", "tr": "{s} düşündü"},
    "tui.turn.thought": {"en": "Thought", "tr": "Düşündü"},
    "tui.turn.stop.limit_turns": {"en": "Turn limit", "tr": "Tur sınırı"},
    "tui.turn.stop.limit_total_tokens": {"en": "Token limit", "tr": "Token sınırı"},
    "tui.turn.stop.max_tokens": {"en": "Length limit", "tr": "Uzunluk sınırı"},
    "tui.turn.stop.cancelled": {"en": "Cancelled", "tr": "İptal edildi"},
    "tui.turn.stop.interrupt": {"en": "Interrupted", "tr": "Kesildi"},
    "tui.turn.stop.busy": {"en": "Busy", "tr": "Meşgul"},
    "tui.turn.stop.error": {"en": "Error", "tr": "Hata"},
    # -- welcome card ----------------------------------------------------------------------------
    "tui.welcome.tagline": {"en": "τ = 2π, one full turn.", "tr": "τ = 2π, tam bir tur."},
    "tui.welcome.profile": {"en": "profile", "tr": "profil"},
    "tui.welcome.session": {"en": "session", "tr": "oturum"},
    "tui.welcome.model": {"en": "model", "tr": "model"},
    "tui.welcome.tools": {"en": "tools", "tr": "araçlar"},
    "tui.welcome.tools_value": {
        "en": "{n} registered · {approval} need approval",
        "tr": "{n} kayıtlı · {approval} onay ister",
    },
    "tui.welcome.tip": {
        "en": "Type a message · / commands · ? keys",
        "tr": "Bir mesaj yaz · / komutlar · ? tuşlar",
    },
    "tui.welcome.tier_tip": {
        "en": "Tier-2 actions wait for your approval.",
        "tr": "Tier-2 eylemler onayını bekler.",
    },
    # -- events pane -----------------------------------------------------------------------------
    "tui.events.replayed": {
        "en": "· replayed {n} events ·",
        "tr": "· {n} olay yeniden oynatıldı ·",
    },
    "tui.events.live": {"en": "── live ──", "tr": "── canlı ──"},
    "tui.events.count": {"en": "Events · {n}", "tr": "Olaylar · {n}"},
    "tui.event.token_limit": {
        "en": "token limit: {n} tokens",
        "tr": "token sınırı: {n} token",
    },
    "tui.event.notice": {"en": "notice", "tr": "bildirim"},
    # -- sessions --------------------------------------------------------------------------------
    "tui.sessions.title": {"en": "Sessions", "tr": "Oturumlar"},
    "tui.sessions.hint": {
        "en": "enter resume · n new · esc close",
        "tr": "enter devam · n yeni · esc kapat",
    },
    "tui.sessions.sidebar_hint": {
        "en": "ctrl+r pick · ctrl+n new",
        "tr": "ctrl+r seç · ctrl+n yeni",
    },
    "tui.sessions.today": {"en": "today {time}", "tr": "bugün {time}"},
    "tui.sessions.yesterday": {"en": "yesterday", "tr": "dün"},
    "tui.sessions.msgs": {"en": "{n} msgs", "tr": "{n} mesaj"},
    "tui.fold": {
        "en": "… {n} earlier turns · PageUp at the top shows more",
        "tr": "… {n} önceki tur · en üstte PageUp daha fazlasını gösterir",
    },
    # -- hint bar --------------------------------------------------------------------------------
    "tui.hint.idle": {
        "en": "? shortcuts · / commands · ctrl+j newline",
        "tr": "? kısayollar · / komutlar · ctrl+j yeni satır",
    },
    "tui.hint.idle_phone": {
        "en": "? keys · / cmds · ^j newline",
        "tr": "? tuşlar · / komutlar · ^j yeni satır",
    },
    "tui.hint.busy": {"en": "esc cancel · ctrl+j newline", "tr": "esc iptal · ctrl+j yeni satır"},
    "tui.hint.busy_phone": {"en": "esc cancel · ^j newline", "tr": "esc iptal · ^j yeni satır"},
    "tui.hint.attention": {
        "en": "waiting for your approval · y approve · n reject",
        "tr": "onayın bekleniyor · y onayla · n reddet",
    },
    "tui.hint.menu": {
        "en": "↑↓ pick · tab complete · enter run · esc close",
        "tr": "↑↓ seç · tab tamamla · enter çalıştır · esc kapat",
    },
    "tui.hint.events": {"en": "esc chat · ctrl+j newline", "tr": "esc sohbet · ctrl+j yeni satır"},
    "tui.hint.events_phone": {"en": "esc chat · ^j newline", "tr": "esc sohbet · ^j yeni satır"},
    "tui.hint.quit": {"en": "ctrl+q quit", "tr": "ctrl+q çık"},
    "tui.hint.busy_word": {"en": "busy", "tr": "meşgul"},
    "tui.hint.approval_word": {"en": "approval", "tr": "onay"},
    "tui.hint.events_key": {"en": "ctrl+e events", "tr": "ctrl+e olaylar"},
    "tui.hint.events_key_phone": {"en": "F4 events", "tr": "F4 olaylar"},
    "tui.hint.chat_key": {"en": "F4 chat", "tr": "F4 sohbet"},
    "tui.header.events": {"en": "events", "tr": "olaylar"},
    # -- help card key descriptions (the rest come from tau-core's tui.key.* keys) --------------
    "tui.help.keys_header": {"en": "Keys:", "tr": "Tuşlar:"},
    "tui.key.send": {"en": "Send", "tr": "Gönder"},
    "tui.key.newline": {"en": "Newline", "tr": "Yeni satır"},
    "tui.key.events": {"en": "Events pane", "tr": "Olaylar bölmesi"},
    "tui.key.expand": {
        "en": "Expand or collapse the last turn's cards",
        "tr": "Son turun kartlarını aç/kapat",
    },
    "tui.key.scroll": {"en": "Scroll the transcript", "tr": "Dökümü kaydır"},
    "tui.key.bottom": {"en": "Back to the bottom", "tr": "En alta dön"},
    "tui.key.settings": {"en": "Settings", "tr": "Ayarlar"},
    "tui.busy_settings": {
        "en": "Wait for the current turn before opening the settings.",
        "tr": "Ayarları açmak için turun bitmesini bekle.",
    },
    # -- settings screen -------------------------------------------------------------------------
    "tui.settings.title": {"en": "Settings", "tr": "Ayarlar"},
    # Section and row labels must fit the phone band (section list 12–18, label column 12).
    "tui.settings.section.roles": {"en": "Model roles", "tr": "Roller"},
    "tui.settings.section.credentials": {"en": "Credentials", "tr": "Kimlikler"},
    "tui.settings.section.interface": {"en": "Interface", "tr": "Arayüz"},
    "tui.settings.section.agent": {"en": "Agent", "tr": "Ajan"},
    "tui.settings.section.doctor": {"en": "Doctor", "tr": "Doktor"},
    "tui.settings.section.files": {"en": "Files", "tr": "Dosyalar"},
    "tui.settings.hint": {
        "en": "↑↓ section · tab fields · ctrl+s / F2 save · esc close",
        "tr": "↑↓ bölüm · tab alanlar · ctrl+s / F2 kaydet · esc kapat",
    },
    "tui.settings.hint_phone": {
        "en": "↑↓ section · tab · ^s/F2 save · esc",
        "tr": "↑↓ bölüm · tab · ^s/F2 kaydet · esc",
    },
    "tui.settings.provider": {"en": "provider", "tr": "sağlayıcı"},
    "tui.settings.model_id": {"en": "model id", "tr": "model id"},
    "tui.settings.max_tokens": {"en": "max tokens", "tr": "token sınırı"},
    "tui.settings.fallback": {"en": "fallback", "tr": "yedek"},
    "tui.settings.fallback_model": {"en": "fallback id", "tr": "yedek id"},
    "tui.settings.no_fallback": {"en": "(none)", "tr": "(yok)"},
    "tui.settings.planned": {"en": "{provider} (planned)", "tr": "{provider} (planlı)"},
    "tui.settings.planned_note": {
        "en": "planned, not selectable yet: {providers}",
        "tr": "planlı, henüz seçilemez: {providers}",
    },
    "tui.settings.needed_by": {"en": "needed by {roles}", "tr": "{roles} için gerekli"},
    "tui.settings.needed": {"en": "needed", "tr": "gerekli"},
    "tui.settings.set": {"en": "set · {masked}", "tr": "ayarlı · {masked}"},
    "tui.settings.from_environment": {
        "en": "(from the environment; .env does not override it)",
        "tr": "(ortam değişkeninden; .env bunu geçersiz kılmaz)",
    },
    "tui.settings.not_set": {"en": "not set", "tr": "ayarlı değil"},
    "tui.settings.new_value": {"en": "new value (hidden)", "tr": "yeni değer (gizli)"},
    "tui.settings.new_value_plain": {"en": "new value", "tr": "yeni değer"},
    "tui.settings.clear": {"en": "clear", "tr": "sil"},
    "tui.settings.keep": {"en": "keep", "tr": "koru"},
    "tui.settings.will_clear": {"en": "will be removed", "tr": "silinecek"},
    "tui.settings.language": {"en": "UI language", "tr": "arayüz dili"},
    "tui.settings.profile": {"en": "profile", "tr": "profil"},
    "tui.settings.profile_note": {
        "en": "TAU_PROFILE in .env: home, travel, sport or your own name",
        "tr": ".env içinde TAU_PROFILE: home, travel, sport ya da kendi adınız",
    },
    "tui.settings.context": {"en": "context", "tr": "bağlam"},
    "tui.settings.window_size": {"en": "window size", "tr": "pencere"},
    "tui.settings.max_turns": {"en": "max turns", "tr": "azami tur"},
    "tui.settings.max_total_tokens": {"en": "token budget", "tr": "bütçe"},
    "tui.settings.agent_note": {
        "en": "per-turn limits; the budget may be empty (none)",
        "tr": "tur başına sınırlar; bütçe boş olabilir (yok)",
    },
    "tui.settings.number_expected": {
        "en": "{field}: enter a whole number",
        "tr": "{field}: tam sayı girin",
    },
    "tui.settings.fallback_needs_model": {
        "en": "{role}: the fallback needs a model id",
        "tr": "{role}: yedek için bir model kimliği gerekli",
    },
    "tui.settings.doctor_running": {"en": "Running the checks…", "tr": "Kontroller çalışıyor…"},
    "tui.settings.doctor_summary": {
        "en": "{n} checks: {ok} ok, {warn} warnings, {fail} failed",
        "tr": "{n} kontrol: {ok} tamam, {warn} uyarı, {fail} hata",
    },
    "tui.settings.files_hint": {
        "en": "Edit the persona files in any editor; tau re-reads them before the next turn.",
        "tr": "Persona dosyalarını herhangi bir düzenleyicide düzenleyin; tau bir sonraki "
        "turdan önce yeniden okur.",
    },
    # -- first-run setup screen ------------------------------------------------------------------
    "tui.setup.title": {
        "en": "Welcome to tau · first run",
        "tr": "tau'ya hoş geldiniz · ilk çalıştırma",
    },
    "tui.setup.intro": {
        "en": "Nothing is configured yet. Pick a home directory, the model provider and the UI "
        "language; tau writes tau.toml and the persona files there.",
        "tr": "Henüz bir yapılandırma yok. Bir ana dizin, model sağlayıcısı ve arayüz dili "
        "seçin; tau oraya tau.toml ve persona dosyalarını yazar.",
    },
    "tui.setup.home": {"en": "home directory", "tr": "ana dizin"},
    "tui.setup.provider": {"en": "provider", "tr": "sağlayıcı"},
    "tui.setup.language": {"en": "UI language", "tr": "arayüz dili"},
    "tui.setup.create": {"en": "Create", "tr": "Oluştur"},
    "tui.setup.hint": {
        "en": "tab fields · enter / ctrl+s / F2 create · esc quit",
        "tr": "tab alanlar · enter / ctrl+s / F2 oluştur · esc çık",
    },
    "tui.setup.hint_phone": {
        "en": "enter / ^s / F2 create · esc quit",
        "tr": "enter / ^s / F2 oluştur · esc çık",
    },
    "tui.setup.has_credentials": {
        "en": "{provider} · credentials found",
        "tr": "{provider} · kimlik bilgisi bulundu",
    },
    "tui.setup.no_credentials": {
        "en": "{provider} · no credentials found",
        "tr": "{provider} · kimlik bilgisi bulunamadı",
    },
    "tui.setup.fake_note": {
        "en": "fake · no credentials needed",
        "tr": "fake · kimlik bilgisi gerekmez",
    },
    "tui.setup.empty_home": {"en": "Enter a home directory.", "tr": "Bir ana dizin girin."},
    "tui.setup.failed": {"en": "Setup failed: {error}", "tr": "Kurulum başarısız: {error}"},
    # -- the owner guard (issue 113) -----------------------------------------------------------
    "tui.guard.title": {"en": "tau is locked", "tr": "tau kilitli"},
    "tui.guard.placeholder": {
        "en": "Enter unlocks · /help /lang /guard /quit",
        "tr": "Enter kilidi açar · /help /lang /guard /quit",
    },
    "tui.guard.hint": {
        "en": "enter unlock · esc cancel · ctrl+q quit",
        "tr": "enter kilidi aç · esc iptal · ctrl+q çık",
    },
    # the Touch ID fallback on the lock screen (issue 114); {key} is keys.TOUCH_ID_KEY
    "tui.guard.hint_fallback": {
        "en": "enter unlock · {key} Touch ID · esc cancel · ctrl+q quit",
        "tr": "enter kilidi aç · {key} Touch ID · esc iptal · ctrl+q çık",
    },
    "tui.guard.fallback_how": {"en": "press {key}", "tr": "{key} tuşuna bas"},
    "tui.busy.step_up": {"en": "Identity check: {step}", "tr": "Kimlik kontrolü: {step}"},
    "tui.turn.stop.locked": {"en": "Locked", "tr": "Kilitli"},
    "tui.key.lock": {"en": "lock tau", "tr": "tau'yu kilitle"},
    "tui.event.guard": {"en": "guard", "tr": "koruma"},
}

_collisions = set(TUI_MESSAGES) & set(MESSAGES)
assert not _collisions, f"tau-tui message keys collide with tau-core: {sorted(_collisions)}"

register_messages(TUI_MESSAGES)
