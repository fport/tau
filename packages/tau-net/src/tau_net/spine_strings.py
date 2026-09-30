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
    "net.spine.init.step_node": {
        "en": "1. Install Node.js 22 or newer (bun is optional) and log in to Cloudflare once: "
        "`bunx wrangler login`, or `npx wrangler login` without bun.",
        "tr": "1. Node.js 22 veya üstünü kur (bun isteğe bağlı) ve Cloudflare'e bir kez giriş "
        "yap: `bunx wrangler login`, bun yoksa `npx wrangler login`.",
    },
    "net.spine.init.step_deploy": {
        "en": "2. Deploy it: `tau net spine deploy {path}`.",
        "tr": "2. Dağıt: `tau net spine deploy {path}`.",
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
