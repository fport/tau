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
}

_collisions = set(TUI_MESSAGES) & set(MESSAGES)
assert not _collisions, f"tau-tui message keys collide with tau-core: {sorted(_collisions)}"

register_messages(TUI_MESSAGES)
