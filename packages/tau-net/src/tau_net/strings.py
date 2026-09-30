"""The ``tau net`` message keys, registered into ``tau_core.i18n`` at import.

What ``tau net`` prints goes through ``t(key, language)`` with the UI language of the
configuration (``[ui] language``, ``TAU_LANG``, ``tau --lang``). Error lines are the English
text of the exception, like every error raised before a channel exists. The keys must not
collide with tau-core's table, because ``register_messages`` overrides silently; the assertion
at import keeps that honest.
"""

from __future__ import annotations

from tau_core.i18n import MESSAGES, register_messages

NET_MESSAGES: dict[str, dict[str, str]] = {
    # -- init ----------------------------------------------------------------------------------
    "net.init.created": {
        "en": "Created the network identity at {path}.",
        "tr": "Ağ kimliği {path} içinde oluşturuldu.",
    },
    "net.init.kept": {
        "en": "An identity already exists at {path}; it was kept.",
        "tr": "{path} içinde bir kimlik zaten var; korundu.",
    },
    "net.init.env": {
        "en": "The identity comes from TAU_NET_IDENTITY; no file was written.",
        "tr": "Kimlik TAU_NET_IDENTITY değişkeninden geliyor; dosya yazılmadı.",
    },
    "net.init.name_saved": {
        "en": "Card name set to {name} in {path}.",
        "tr": "Kart adı {path} içinde {name} olarak ayarlandı.",
    },
    "net.init.next": {"en": "Next steps:", "tr": "Sonraki adımlar:"},
    "net.init.step_env": {
        "en": "1. Put TAU_SPINE_URL and TAU_SPINE_TOKEN in .env (the names are in .env.example).",
        "tr": "1. TAU_SPINE_URL ve TAU_SPINE_TOKEN değerlerini .env dosyasına yaz "
        "(adlar .env.example içinde).",
    },
    "net.init.step_note": {
        "en": "2. Write what other taus may know about you in persona/{note} "
        "(start from persona/net.example.md).",
        "tr": "2. Diğer tau'ların senin hakkında bilebileceklerini persona/{note} dosyasına yaz "
        "(persona/net.example.md ile başla).",
    },
    "net.init.step_publish": {
        "en": "3. Run `tau net publish`, or start the hub: it publishes the card itself.",
        "tr": "3. `tau net publish` çalıştır ya da hub'ı başlat: kartı kendisi yayımlar.",
    },
    # -- keys and status -----------------------------------------------------------------------
    "net.keys.sign": {"en": "sign_key  {key}", "tr": "sign_key  {key}"},
    "net.keys.box": {"en": "box_key   {key}", "tr": "box_key   {key}"},
    "net.status.name": {"en": "name:     {name}", "tr": "ad:       {name}"},
    "net.status.identity": {"en": "identity: {source}", "tr": "kimlik:   {source}"},
    "net.status.identity_missing": {
        "en": "identity: none (run `tau net init`)",
        "tr": "kimlik:   yok (`tau net init` çalıştır)",
    },
    "net.status.spine_missing": {
        "en": "spine:    not configured (TAU_SPINE_URL and TAU_SPINE_TOKEN in .env)",
        "tr": "spine:    ayarlı değil (.env içinde TAU_SPINE_URL ve TAU_SPINE_TOKEN)",
    },
    "net.status.spine": {
        "en": "spine:    {url}: address {address}, mode {mode}, {mailbox} waiting in the mailbox",
        "tr": "spine:    {url}: adres {address}, mod {mode}, posta kutusunda {mailbox} zarf",
    },
    "net.status.spine_error": {
        "en": "spine:    {url}: {error}",
        "tr": "spine:    {url}: {error}",
    },
    "net.status.card_matches": {
        "en": "card:     published, matches this identity",
        "tr": "kart:     yayımlandı, bu kimlikle uyuşuyor",
    },
    "net.status.card_differs": {
        "en": "card:     published but different (run `tau net publish`)",
        "tr": "kart:     yayımlandı ama farklı (`tau net publish` çalıştır)",
    },
    "net.status.card_missing": {
        "en": "card:     not published (run `tau net publish`)",
        "tr": "kart:     yayımlanmadı (`tau net publish` çalıştır)",
    },
    "net.status.contacts": {
        "en": "contacts: {accepted} accepted, {pending_in} asking you, {pending_out} waiting, "
        "{blocked} blocked",
        "tr": "kişiler:  {accepted} kabul edildi, {pending_in} seni bekliyor, "
        "{pending_out} yanıt bekleniyor, {blocked} engelli",
    },
    "net.status.store": {"en": "store:    {store}", "tr": "depo:     {store}"},
    "net.status.doctor": {"en": "check:    {status} {detail}", "tr": "kontrol:  {status} {detail}"},
    # -- card ----------------------------------------------------------------------------------
    "net.card.local": {
        "en": "The spine has no card yet; `tau net publish` would send:",
        "tr": "Spine'da henüz kart yok; `tau net publish` şunu gönderir:",
    },
    "net.publish.done": {
        "en": "Published the card of {address} as {name}.",
        "tr": "{address} kartı {name} adıyla yayımlandı.",
    },
    # -- contacts ------------------------------------------------------------------------------
    "net.contacts.none": {
        "en": "No contacts yet. Add one with `tau net add <address>`.",
        "tr": "Henüz kişi yok. `tau net add <adres>` ile ekle.",
    },
    "net.contacts.note": {"en": "    note: {note}", "tr": "    not: {note}"},
    "net.state.pending_in": {"en": "asks you", "tr": "seni istiyor"},
    "net.state.pending_out": {"en": "waiting", "tr": "bekleniyor"},
    "net.state.accepted": {"en": "contact", "tr": "kişi"},
    "net.state.blocked": {"en": "blocked", "tr": "engelli"},
    "net.add.sent": {
        "en": "Sent a contact request to {address}. It becomes a contact once they accept.",
        "tr": "{address} adresine kişi isteği gönderildi. Kabul edince kişi olur.",
    },
    "net.add.accepted": {
        "en": "{address} had asked already: it is a contact now.",
        "tr": "{address} zaten istemişti: artık kişi.",
    },
    "net.accept.done": {"en": "{address} is a contact now.", "tr": "{address} artık kişi."},
    "net.block.done": {
        "en": "Blocked {address}: nothing from it is read or answered.",
        "tr": "{address} engellendi: ondan gelen hiçbir şey okunmaz ve yanıtlanmaz.",
    },
    "net.remove.done": {"en": "Removed {address}.", "tr": "{address} kaldırıldı."},
    "net.remove.none": {
        "en": "{address} was not a contact.",
        "tr": "{address} zaten kişi değildi.",
    },
    "net.send.done": {
        "en": "Sent to {address} ({status}).",
        "tr": "{address} adresine gönderildi ({status}).",
    },
    # -- log and poll --------------------------------------------------------------------------
    "net.log.empty": {"en": "The network log is empty.", "tr": "Ağ günlüğü boş."},
    "net.poll.done": {
        "en": "{handled} handled, {dropped} dropped, {replied} replied.",
        "tr": "{handled} işlendi, {dropped} düşürüldü, {replied} yanıtlandı.",
    },
}

_collisions = set(NET_MESSAGES) & set(MESSAGES)
assert not _collisions, f"tau-net message keys collide with tau-core: {sorted(_collisions)}"

register_messages(NET_MESSAGES)
