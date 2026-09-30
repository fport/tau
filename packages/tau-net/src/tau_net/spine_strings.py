"""The ``tau net spine`` message keys, registered into ``tau_core.i18n`` at import.

Kept apart from :mod:`tau_net.strings` so the spine kit stays one self-contained piece;
the rules are the same: every key in both languages with the same fields, no collision with
tau-core's table or with the rest of tau-net's.
"""

from __future__ import annotations

from tau_core.i18n import MESSAGES, register_messages

from tau_net.strings import NET_MESSAGES

SPINE_MESSAGES: dict[str, dict[str, str]] = {
    # -- init ----------------------------------------------------------------------------------
    "net.spine.init.done": {
        "en": "Wrote the spine project (kit {version}) to {path}.",
        "tr": "Spine projesi (kit {version}) {path} içine yazıldı.",
    },
    "net.spine.init.address": {
        "en": "Address: {address}, with a custom-domain route (the zone must be on your "
        "Cloudflare account).",
        "tr": "Adres: {address}, özel alan adı yönlendirmesiyle (alan adı Cloudflare "
        "hesabında olmalı).",
    },
    "net.spine.init.workers_dev_address": {
        "en": "Address: {address} (the workers.dev address Cloudflare gives the Worker).",
        "tr": "Adres: {address} (Cloudflare'in Worker'a verdiği workers.dev adresi).",
    },
    "net.spine.init.no_address": {
        "en": "Address: tau-spine.<your-subdomain>.workers.dev, known after the first deploy.",
        "tr": "Adres: tau-spine.<alt-alan-adın>.workers.dev, ilk dağıtımdan sonra belli olur.",
    },
    "net.spine.next": {"en": "Next steps:", "tr": "Sonraki adımlar:"},
    "net.spine.init.step_deploy": {
        "en": "1. Deploy it: `tau net spine deploy {path}`. It asks for a Cloudflare API token "
        "and shows the link that creates one; no Node.js needed.",
        "tr": "1. Dağıt: `tau net spine deploy {path}`. Bir Cloudflare API token'ı ister ve onu "
        "oluşturan bağlantıyı gösterir; Node.js gerekmez.",
    },
    "net.spine.init.step_wrangler": {
        "en": "   Or with Wrangler (Node.js 22 or newer): `bunx wrangler login` (`npx wrangler "
        "login` without bun), then `tau net spine deploy {path} --wrangler`.",
        "tr": "   Ya da Wrangler ile (Node.js 22 veya üstü): `bunx wrangler login` (bun yoksa "
        "`npx wrangler login`), sonra `tau net spine deploy {path} --wrangler`.",
    },
    # -- deploy --------------------------------------------------------------------------------
    "net.spine.deploy.run": {"en": "$ {command}", "tr": "$ {command}"},
    "net.spine.deploy.logged_in": {
        "en": "Wrangler is logged in to Cloudflare.",
        "tr": "Wrangler Cloudflare'e giriş yapmış.",
    },
    "net.spine.deploy.token_created": {
        "en": "Generated a new TAU_SPINE_TOKEN in {path}.",
        "tr": "{path} içinde yeni bir TAU_SPINE_TOKEN oluşturuldu.",
    },
    "net.spine.deploy.token_kept": {
        "en": "Using the TAU_SPINE_TOKEN in {path}.",
        "tr": "{path} içindeki TAU_SPINE_TOKEN kullanılıyor.",
    },
    "net.spine.deploy.token_env": {
        "en": "Note: TAU_SPINE_TOKEN is also set in the environment with another value, and "
        "the environment wins over .env; unset it or make it match.",
        "tr": "Not: TAU_SPINE_TOKEN ortamda da başka bir değerle tanımlı ve ortam .env'e "
        "üstün gelir; kaldır ya da eşitle.",
    },
    "net.spine.deploy.secret_set": {
        "en": "Set the Worker's HUB_TOKEN secret to TAU_SPINE_TOKEN.",
        "tr": "Worker'ın HUB_TOKEN sırrı TAU_SPINE_TOKEN olarak ayarlandı.",
    },
    "net.spine.deploy.url_saved": {
        "en": "Wrote TAU_SPINE_URL={url} to {path}.",
        "tr": "TAU_SPINE_URL={url} {path} içine yazıldı.",
    },
    "net.spine.deploy.done": {
        "en": "The spine is deployed at {url}.",
        "tr": "Spine {url} adresinde yayında.",
    },
    # -- deploy through the Cloudflare API ---------------------------------------------------
    "net.spine.api.token_needed": {
        "en": "The deploy needs a Cloudflare API token with these permissions:",
        "tr": "Dağıtım şu izinlere sahip bir Cloudflare API token'ı istiyor:",
    },
    "net.spine.api.token_scope": {"en": "  - {scope}", "tr": "  - {scope}"},
    "net.spine.api.token_link": {
        "en": "Create it on this page, which opens with the permissions filled in (Continue "
        "to summary, then Create Token):",
        "tr": "Bu sayfada oluştur; izinler dolu açılır (Continue to summary, sonra Create Token):",
    },
    "net.spine.api.link": {"en": "  {link}", "tr": "  {link}"},
    "net.spine.api.token_prompt": {
        "en": "Paste the token (it is not shown)",
        "tr": "Token'ı yapıştır (görünmez)",
    },
    "net.spine.api.token_ok": {
        "en": "Cloudflare accepted the API token.",
        "tr": "Cloudflare API token'ını kabul etti.",
    },
    "net.spine.api.token_env": {
        "en": "Using CLOUDFLARE_API_TOKEN from the environment.",
        "tr": "Ortamdaki CLOUDFLARE_API_TOKEN kullanılıyor.",
    },
    "net.spine.api.token_dotenv": {
        "en": "Using CLOUDFLARE_API_TOKEN from {path}.",
        "tr": "{path} içindeki CLOUDFLARE_API_TOKEN kullanılıyor.",
    },
    "net.spine.api.token_saved": {
        "en": "Saved CLOUDFLARE_API_TOKEN in {path}.",
        "tr": "CLOUDFLARE_API_TOKEN {path} içine kaydedildi.",
    },
    "net.spine.api.accounts": {
        "en": "The token reaches {count} Cloudflare accounts:",
        "tr": "Token {count} Cloudflare hesabına erişiyor:",
    },
    "net.spine.api.account_item": {"en": "  {n}. {name} ({id})", "tr": "  {n}. {name} ({id})"},
    "net.spine.api.account_prompt": {
        "en": "Deploy to which one (number)",
        "tr": "Hangisine dağıtılsın (numara)",
    },
    "net.spine.api.account": {
        "en": "Cloudflare account: {name} ({id}).",
        "tr": "Cloudflare hesabı: {name} ({id}).",
    },
    "net.spine.api.account_id": {
        "en": "Cloudflare account: {id}.",
        "tr": "Cloudflare hesabı: {id}.",
    },
    "net.spine.api.kv_kept": {
        "en": "KV namespace for {binding}: {id}, the one the Worker already uses.",
        "tr": "{binding} için KV namespace: {id}, Worker'ın zaten kullandığı.",
    },
    "net.spine.api.kv_found": {
        "en": "KV namespace for {binding}: {title} ({id}), already in the account.",
        "tr": "{binding} için KV namespace: {title} ({id}), hesapta zaten var.",
    },
    "net.spine.api.kv_created": {
        "en": "Created the KV namespace {title} ({id}) for {binding}.",
        "tr": "{binding} için {title} ({id}) KV namespace'i oluşturuldu.",
    },
    "net.spine.api.address_saved": {
        "en": "Wrote the address {address} and its custom-domain route into {path}.",
        "tr": "{address} adresi ve özel alan adı yönlendirmesi {path} içine yazıldı.",
    },
    "net.spine.api.recorded": {
        "en": "Recorded the account and the KV namespace ids in {path}.",
        "tr": "Hesap ve KV namespace kimlikleri {path} içine kaydedildi.",
    },
    "net.spine.api.migrations": {
        "en": "Durable Object migrations: {count} step(s), up to {tag}.",
        "tr": "Durable Object geçişleri: {count} adım, {tag} etiketine kadar.",
    },
    "net.spine.api.migrations_current": {
        "en": "Durable Object migrations: already at {tag}.",
        "tr": "Durable Object geçişleri: zaten {tag} etiketinde.",
    },
    "net.spine.api.migrations_unknown": {
        "en": "Note: the deployed Worker has the migration tag {tag}, which {path} does not "
        "list; sending every migration, as Wrangler does.",
        "tr": "Not: yayındaki Worker'ın geçiş etiketi {tag}, {path} bunu listelemiyor; Wrangler "
        "gibi bütün geçişler gönderiliyor.",
    },
    "net.spine.api.uploaded": {
        "en": "Uploaded the Worker {name} ({size} KiB).",
        "tr": "{name} Worker'ı yüklendi ({size} KiB).",
    },
    "net.spine.api.crons": {
        "en": "Cron triggers: {crons}.",
        "tr": "Cron tetikleyicileri: {crons}.",
    },
    "net.spine.api.workers_dev": {
        "en": "The workers.dev address is on: {host}.",
        "tr": "workers.dev adresi açık: {host}.",
    },
    "net.spine.api.workers_dev_off": {
        "en": "The workers.dev address is off; the custom domain serves the spine.",
        "tr": "workers.dev adresi kapalı; spine'ı özel alan adı sunuyor.",
    },
    "net.spine.api.domain": {
        "en": "Attached the custom domain {host}.",
        "tr": "{host} özel alan adı bağlandı.",
    },
    "net.spine.api.health_ok": {
        "en": "The spine answers at {url} (version {version}) and accepts TAU_SPINE_TOKEN.",
        "tr": "Spine {url} adresinde yanıt veriyor (sürüm {version}) ve TAU_SPINE_TOKEN'ı "
        "kabul ediyor.",
    },
    "net.spine.api.health_later": {
        "en": "The spine does not answer at {url} yet ({error}); a new address can take a few "
        "minutes. `tau net status` checks it again.",
        "tr": "Spine {url} adresinde henüz yanıt vermiyor ({error}); yeni bir adres birkaç "
        "dakika sürebilir. `tau net status` yeniden kontrol eder.",
    },
    "net.spine.deploy.step_init": {
        "en": "1. `tau net init --name \"Alice's tau\"`: the identity and the card's name.",
        "tr": '1. `tau net init --name "Alice\'s tau"`: kimlik ve kartın adı.',
    },
    "net.spine.deploy.step_publish": {
        "en": "2. `tau net publish`: the card on the spine.",
        "tr": "2. `tau net publish`: kart spine'da.",
    },
    "net.spine.deploy.step_status": {
        "en": "3. `tau net status`: check that everything answers.",
        "tr": "3. `tau net status`: her şeyin yanıt verdiğini kontrol et.",
    },
}

# tau_net.strings registered NET_MESSAGES on import, so MESSAGES covers both tables here.
_collisions = set(SPINE_MESSAGES) & (set(MESSAGES) | set(NET_MESSAGES))
assert not _collisions, f"tau-net spine message keys collide: {sorted(_collisions)}"

register_messages(SPINE_MESSAGES)
