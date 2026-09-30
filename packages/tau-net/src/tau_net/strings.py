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
    "net.name.saved": {
        "en": "Card name set to {name} in the network profile ({store}).",
        "tr": "Kart adı ağ profilinde {name} olarak ayarlandı ({store}).",
    },
    "net.name.publish": {
        "en": "Publish it with `tau net publish`; the hub also publishes it when it starts.",
        "tr": "`tau net publish` ile yayımla; hub da başlarken yayımlar.",
    },
    "net.init.next": {"en": "Next steps:", "tr": "Sonraki adımlar:"},
    "net.init.step_env": {
        "en": "- Give your tau an address: `tau net spine init DIR` and `tau net spine deploy DIR` "
        "(they write TAU_SPINE_URL and TAU_SPINE_TOKEN into .env).",
        "tr": "- Tau'na bir adres ver: `tau net spine init DIR` ve `tau net spine deploy DIR` "
        "(TAU_SPINE_URL ve TAU_SPINE_TOKEN değerlerini .env dosyasına yazarlar).",
    },
    "net.init.step_note": {
        "en": "- Write what other taus may know about you in persona/{note}.",
        "tr": "- Diğer tau'ların senin hakkında bilebileceklerini persona/{note} dosyasına yaz.",
    },
    "net.init.note_written": {
        "en": "Created {path}: your public note for other taus, empty until you fill it in.",
        "tr": "{path} oluşturuldu: diğer tau'lar için herkese açık notun, doldurana kadar boş.",
    },
    "net.init.step_publish": {
        "en": "- Run `tau net publish`, or start the hub: it publishes the card itself.",
        "tr": "- `tau net publish` çalıştır ya da hub'ı başlat: kartı kendisi yayımlar.",
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
    # -- the universe --------------------------------------------------------------------------
    "net.universe.joined": {
        "en": "Joined the universe {universe}: {url}",
        "tr": "{universe} evrenine katıldın: {url}",
    },
    "net.universe.reported": {
        "en": "Report sent. Listed contacts: {links}; visible links: {visible} "
        "(a link shows once both taus report each other).",
        "tr": "Rapor gönderildi. Listelenen kişiler: {links}; görünür bağlantılar: {visible} "
        "(bir bağlantı iki tau da birbirini bildirince görünür).",
    },
    "net.universe.reported_off": {
        "en": "Report sent without links (links are off).",
        "tr": "Rapor bağlantısız gönderildi (bağlantılar kapalı).",
    },
    "net.universe.subs": {
        "en": "Public sub-taus listed: {subs}.",
        "tr": "Listelenen açık sub-tau'lar: {subs}.",
    },
    "net.universe.left": {
        "en": "Left the universe {universe}: this tau and its links are no longer listed.",
        "tr": "{universe} evreninden ayrıldın: bu tau ve bağlantıları artık listelenmiyor.",
    },
    "net.universe.left_unlisted": {
        "en": "This tau was not listed in {universe}; universe_join is off now.",
        "tr": "Bu tau {universe} evreninde listelenmiyordu; universe_join artık kapalı.",
    },
    "net.universe.status.off": {
        "en": 'universe: off ([component.net] universe = "")',
        "tr": 'evren:    kapalı ([component.net] universe = "")',
    },
    "net.universe.status.host": {"en": "universe: {universe}", "tr": "evren:    {universe}"},
    "net.universe.status.joined": {
        "en": "joined:   yes, the hub reports every {minutes} min",
        "tr": "katılım:  evet, hub her {minutes} dakikada bir raporlar",
    },
    "net.universe.status.not_joined": {
        "en": "joined:   no (`tau net universe join` lists this tau)",
        "tr": "katılım:  hayır (`tau net universe join` bu tau'yu listeler)",
    },
    "net.universe.status.links_on": {
        "en": "links:    on (mutual links with listed contacts are reported)",
        "tr": "bağlar:   açık (listelenen kişilerle karşılıklı bağlantılar raporlanır)",
    },
    "net.universe.status.links_off": {
        "en": "links:    off (no contacts are reported)",
        "tr": "bağlar:   kapalı (hiçbir kişi raporlanmaz)",
    },
    "net.universe.status.owner": {"en": "owner:    {owner}", "tr": "sahip:    {owner}"},
    "net.universe.status.about": {"en": "about:    {about}", "tr": "hakkında: {about}"},
    "net.universe.status.unlisted": {
        "en": "listed:   no",
        "tr": "listede:  hayır",
    },
    "net.universe.status.online": {
        "en": "listed:   yes, online, last report {when}",
        "tr": "listede:  evet, çevrimiçi, son rapor {when}",
    },
    "net.universe.status.offline": {
        "en": "listed:   yes, offline, last report {when}",
        "tr": "listede:  evet, çevrimdışı, son rapor {when}",
    },
    "net.universe.status.url": {"en": "page:     {url}", "tr": "sayfa:    {url}"},
    "net.universe.status.no_links": {
        "en": "visible:  no links yet (a link shows once both taus report each other)",
        "tr": "görünür:  henüz bağlantı yok (iki tau da birbirini bildirince görünür)",
    },
    "net.universe.status.link": {
        "en": "visible:  {peer}, messages: {messages}",
        "tr": "görünür:  {peer}, mesaj: {messages}",
    },
    "net.universe.status.sub": {
        "en": "sub-tau:  /{name}: {about}",
        "tr": "sub-tau:  /{name}: {about}",
    },
    "net.universe.status.sub_web": {
        "en": "sub-tau:  /{name} (web page, {visits} visitor turns today): {about}",
        "tr": "sub-tau:  /{name} (web sayfası, bugün {visits} ziyaretçi turu): {about}",
    },
    "net.universe.status.handle": {
        "en": "handle:   @{handle}  {url}",
        "tr": "tanıtıcı: @{handle}  {url}",
    },
    "net.universe.status.no_handle": {
        "en": "handle:   none yet (`tau net universe claim` proves one with GitHub)",
        "tr": "tanıtıcı: henüz yok (`tau net universe claim` GitHub ile bir tane kanıtlar)",
    },
    "net.universe.claim.link": {
        "en": "Open this link within an hour and sign in with GitHub there; {universe} then "
        "binds your GitHub login as the handle of {address}:",
        "tr": "Bu bağlantıyı bir saat içinde aç ve orada GitHub ile giriş yap; {universe} "
        "GitHub kullanıcı adını {address} için tanıtıcı olarak bağlar:",
    },
    "net.universe.claim.private": {
        "en": "The link is a signed claim for this tau: whoever opens it with their GitHub "
        "account could take the handle for it, so do not share it.",
        "tr": "Bağlantı bu tau için imzalı bir talep: onu kendi GitHub hesabıyla açan herkes "
        "tanıtıcıyı alabilir, o yüzden paylaşma.",
    },
    "net.universe.claim.not_joined": {
        "en": "This tau is not in the universe yet; the handle shows once you run `tau net "
        "universe join`.",
        "tr": "Bu tau henüz evrende değil; tanıtıcı `tau net universe join` çalıştırınca görünür.",
    },
}

_collisions = set(NET_MESSAGES) & set(MESSAGES)
assert not _collisions, f"tau-net message keys collide with tau-core: {sorted(_collisions)}"

register_messages(NET_MESSAGES)
