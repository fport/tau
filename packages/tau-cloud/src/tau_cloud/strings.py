"""The ``tau cloud`` message keys, registered into ``tau_core.i18n`` at import.

What ``tau cloud`` prints goes through ``t(key, language)`` in the UI language (``tau --lang``,
``TAU_LANG``, ``[ui] language``). Error lines are plain English, like every error raised
before a channel exists. The keys must not collide with another table, because
``register_messages`` overrides silently; the assertion at import keeps that honest.
"""

from __future__ import annotations

from tau_core.i18n import MESSAGES, register_messages

CLOUD_MESSAGES: dict[str, dict[str, str]] = {
    # -- push ----------------------------------------------------------------------------------
    "cloud.push.plan": {
        "en": "These files go to the spine at {url}, in your own Cloudflare account: {files}",
        "tr": "Bu dosyalar kendi Cloudflare hesabındaki {url} spine'ına gider: {files}",
    },
    "cloud.push.confirm": {"en": "Upload them?", "tr": "Yüklensin mi?"},
    "cloud.push.user_warning": {
        "en": "persona/user.md holds what tau knows about you. If you upload it, it is stored "
        "in your own Cloudflare account (D1 and KV, under Cloudflare's encryption, not a key "
        "only you hold; ADR 0007).",
        "tr": "persona/user.md, tau'nun senin hakkında bildiklerini tutar. Yüklersen kendi "
        "Cloudflare hesabında saklanır (D1 ve KV, yalnızca senin tuttuğun bir anahtarla değil "
        "Cloudflare'in şifrelemesiyle; ADR 0007).",
    },
    "cloud.push.user_confirm": {
        "en": "Upload persona/user.md too?",
        "tr": "persona/user.md de yüklensin mi?",
    },
    "cloud.push.user_skipped": {
        "en": "persona/user.md was not uploaded. To upload it: tau cloud push --include-user",
        "tr": "persona/user.md yüklenmedi. Yüklemek için: tau cloud push --include-user",
    },
    "cloud.push.missing": {
        "en": "{name} does not exist here; the spine keeps its copy, if it has one.",
        "tr": "{name} burada yok; spine'da bir kopyası varsa o kalır.",
    },
    "cloud.push.cancelled": {"en": "Nothing was uploaded.", "tr": "Hiçbir şey yüklenmedi."},
    "cloud.push.uploaded": {
        "en": "Uploaded {name} ({size} bytes).",
        "tr": "{name} yüklendi ({size} bayt).",
    },
    "cloud.push.refused": {
        "en": "Skipped {name}: {reason}.",
        "tr": "{name} atlandı: {reason}.",
    },
    "cloud.refused.name": {
        "en": "only .md files with a plain name (letters, digits, '.', '_' and '-', starting "
        "with a letter or a digit) go to the spine",
        "tr": "spine'a yalnızca düz adlı .md dosyaları gider (harf, rakam, '.', '_' ve '-'; "
        "harf ya da rakamla başlar)",
    },
    "cloud.refused.not_file": {
        "en": "not a regular file",
        "tr": "normal bir dosya değil",
    },
    "cloud.refused.link": {
        "en": "a symbolic link, which could point outside persona/subs/",
        "tr": "persona/subs/ dışını gösterebilecek bir sembolik bağlantı",
    },
    "cloud.push.subs_kept": {
        "en": "persona/subs/ does not exist here; the spine keeps its {count} sub-tau files.",
        "tr": "persona/subs/ burada yok; spine'daki {count} sub-tau dosyası kalır.",
    },
    "cloud.push.plan_remove": {
        "en": "These sub-tau files are gone here and are removed from the spine: {files}",
        "tr": "Bu sub-tau dosyaları burada artık yok ve spine'dan silinir: {files}",
    },
    "cloud.push.removed": {
        "en": "Removed {name} from the spine.",
        "tr": "{name} spine'dan silindi.",
    },
    "cloud.push.done": {
        "en": "The brain reads these files when it starts, so they apply from its next start.",
        "tr": "Beyin bu dosyaları açılışta okur; bir sonraki açılışından itibaren geçerli olur.",
    },
    # -- pull ----------------------------------------------------------------------------------
    "cloud.pull.empty": {
        "en": "The spine holds no files yet. Upload them first: tau cloud push",
        "tr": "Spine'da henüz dosya yok. Önce yükle: tau cloud push",
    },
    "cloud.pull.refused": {
        "en": "Skipped {name}: not a name of the cloud-mode file set.",
        "tr": "{name} atlandı: bulut modu dosya kümesinde böyle bir ad yok.",
    },
    "cloud.pull.written": {"en": "Wrote {path}.", "tr": "{path} yazıldı."},
    "cloud.pull.unchanged": {
        "en": "{path} is already up to date.",
        "tr": "{path} zaten güncel.",
    },
    "cloud.pull.kept": {
        "en": "Kept {path}: it differs from the spine's copy.",
        "tr": "{path} korundu: spine'daki kopyadan farklı.",
    },
    "cloud.pull.force_hint": {
        "en": "To replace the local files with the spine's copies: tau cloud pull --force",
        "tr": "Yerel dosyaları spine'daki kopyalarla değiştirmek için: tau cloud pull --force",
    },
    # -- status --------------------------------------------------------------------------------
    "cloud.status.spine": {
        "en": "spine:  {url}: address {address}, mode {mode}, version {version}",
        "tr": "spine:  {url}: adres {address}, mod {mode}, sürüm {version}",
    },
    "cloud.status.not_cloud": {
        "en": "The spine runs in {mode} mode, so it keeps no files, sessions or brain. Deploy "
        "the cloud configuration first (pnpm run configure --cloud, then pnpm run "
        "deploy:cloud in cloud/spine; see the cloud-mode guide).",
        "tr": "Spine {mode} modunda çalışıyor; dosya, oturum ya da beyin tutmaz. Önce bulut "
        "yapılandırmasını yayına al (cloud/spine içinde pnpm run configure --cloud, sonra "
        "pnpm run deploy:cloud; bulut modu rehberine bak).",
    },
    "cloud.status.files": {"en": "files:", "tr": "dosyalar:"},
    "cloud.status.file": {
        "en": "  {name}  {size} bytes, updated {when}",
        "tr": "  {name}  {size} bayt, güncelleme {when}",
    },
    "cloud.status.files_none": {
        "en": "files:  none yet (tau cloud push)",
        "tr": "dosyalar:  henüz yok (tau cloud push)",
    },
    "cloud.status.brain_hub": {
        "en": "brain:  running (tau-cloud {version}); hub pid {pid}, up {uptime} s",
        "tr": "beyin:  çalışıyor (tau-cloud {version}); hub pid {pid}, {uptime} sn açık",
    },
    "cloud.status.brain_starting": {
        "en": "brain:  running (tau-cloud {version}); the hub is not answering yet",
        "tr": "beyin:  çalışıyor (tau-cloud {version}); hub henüz yanıt vermiyor",
    },
    "cloud.status.brain_down": {
        "en": "brain:  unavailable (not deployed, starting, or containers are off in local "
        "development)",
        "tr": "beyin:  ulaşılamıyor (yayında değil, açılıyor ya da yerel geliştirmede "
        "container'lar kapalı)",
    },
    # -- run -----------------------------------------------------------------------------------
    "cloud.run.pulled": {
        "en": "Pulled {count} files from {url} into {home}.",
        "tr": "{url} adresinden {count} dosya {home} içine alındı.",
    },
    "cloud.run.health": {
        "en": "Health endpoint: http://{host}:{port}/health",
        "tr": "Sağlık uç noktası: http://{host}:{port}/health",
    },
}

_collisions = set(CLOUD_MESSAGES) & set(MESSAGES)
assert not _collisions, f"tau-cloud message keys collide: {sorted(_collisions)}"

register_messages(CLOUD_MESSAGES)
