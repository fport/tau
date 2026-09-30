"""The ``tau setup`` message keys, registered into ``tau_core.i18n`` at import.

Kept apart from the main table like the guard's: every key in both languages with the same
fields, and no collision with the rest of the table. The feature catalog
(``templates/features.toml``) names its labels, descriptions, step labels, notes and input
labels by these keys; ``tau_core.setup.catalog`` refuses a key that is missing here.
"""

from __future__ import annotations

from tau_core.i18n import MESSAGES, register_messages

__all__ = ["SETUP_MESSAGES"]

SETUP_MESSAGES: dict[str, dict[str, str]] = {
    # -- the frame ---------------------------------------------------------------------------------
    "setup.language.prompt": {"en": "Language", "tr": "Dil"},
    "setup.title": {
        "en": "tau setup · tau-core {version} · {platform}",
        "tr": "tau kurulumu · tau-core {version} · {platform}",
    },
    "setup.home": {"en": "Configuration: {path}", "tr": "Yapılandırma: {path}"},
    "setup.home.missing": {
        "en": "Configuration: {path} (not created yet)",
        "tr": "Yapılandırma: {path} (henüz oluşturulmadı)",
    },
    "setup.platform.darwin": {"en": "macOS", "tr": "macOS"},
    "setup.platform.linux": {"en": "Linux", "tr": "Linux"},
    "setup.platform.other": {"en": "{platform}", "tr": "{platform}"},
    "setup.no_tty": {
        "en": "tau setup needs a terminal to ask its questions. Without one, run "
        "`tau setup --yes --features tui,sub` (the ids are in `tau setup status`).",
        "tr": "tau setup sorularını sormak için bir terminale ihtiyaç duyar. Terminal yoksa "
        "`tau setup --yes --features tui,sub` çalıştır (kimlikler `tau setup status` "
        "çıktısında).",
    },
    "setup.ssh": {
        "en": "You are connected over SSH: steps that need you at the Mac (the guard's "
        "enrollment) are skipped. Run tau setup at the Mac for them.",
        "tr": "SSH ile bağlısın: Mac'in başında olmanı gerektiren adımlar (korumanın yüz "
        "kaydı) atlanır. Onlar için tau setup'ı Mac'in başında çalıştır.",
    },
    # -- states ------------------------------------------------------------------------------------
    "setup.state.done": {"en": "set up", "tr": "kurulu"},
    "setup.state.installed": {"en": "installed, not set up", "tr": "yüklü, ayarlanmadı"},
    "setup.state.missing": {"en": "not installed", "tr": "yüklü değil"},
    "setup.state.available": {"en": "", "tr": ""},
    "setup.state.unavailable": {"en": "not on {platform}", "tr": "{platform} için yok"},
    "setup.state.advanced": {"en": "advanced", "tr": "ileri düzey"},
    # -- the checklist -----------------------------------------------------------------------------
    "setup.checklist.header": {
        "en": "Features ([x] chosen, ✓ already set up):",
        "tr": "Özellikler ([x] seçili, ✓ zaten kurulu):",
    },
    "setup.checklist.hint": {
        "en": 'Numbers toggle a feature (e.g. "3 5"), Enter goes on, q quits',
        "tr": 'Numaralar bir özelliği seçer ya da bırakır (ör. "3 5"), Enter devam eder, q çıkar',
    },
    "setup.checklist.invalid": {
        "en": "Not a feature number: {value}.",
        "tr": "Özellik numarası değil: {value}.",
    },
    "setup.checklist.done_already": {
        "en": "{label} is already set up. To remove it: tau setup --remove {id}",
        "tr": "{label} zaten kurulu. Kaldırmak için: tau setup --remove {id}",
    },
    "setup.checklist.unavailable": {"en": "{label}: {reason}", "tr": "{label}: {reason}"},
    "setup.checklist.requires": {
        "en": "{label} needs {required}; it is chosen too.",
        "tr": "{label} için {required} gerekiyor; o da seçildi.",
    },
    "setup.quit": {"en": "Nothing changed.", "tr": "Hiçbir şey değişmedi."},
    # -- yes/no questions (the accepted words are data too: no Turkish in code) -----------------
    "setup.confirm.hint_yes": {"en": "Y/n", "tr": "E/h"},
    "setup.confirm.hint_no": {"en": "y/N", "tr": "e/H"},
    "setup.confirm.yes_words": {"en": "y,yes", "tr": "e,evet,y,yes"},
    "setup.confirm.no_words": {"en": "n,no", "tr": "h,hayır,hayir,n,no"},
    "setup.confirm.invalid": {"en": "Answer y or n.", "tr": "e ya da h ile yanıtla."},
    # -- the plan and the install -----------------------------------------------------------------
    "setup.plan.install": {
        "en": "To install: {packages} (one `uv tool install`, pinned to tau-core {version})",
        "tr": "Yüklenecek: {packages} (tek bir `uv tool install`, tau-core {version} "
        "sürümüne sabit)",
    },
    "setup.plan.configure": {"en": "To set up: {features}", "tr": "Ayarlanacak: {features}"},
    "setup.plan.nothing": {
        "en": "Nothing new to install or set up.",
        "tr": "Yüklenecek ya da ayarlanacak yeni bir şey yok.",
    },
    "setup.plan.confirm": {"en": "Go on?", "tr": "Devam edilsin mi?"},
    "setup.install.running": {
        "en": "Installing with uv: {command}",
        "tr": "uv ile yükleniyor: {command}",
    },
    "setup.install.restarting": {
        "en": "Installed. tau setup goes on in the new environment.",
        "tr": "Yüklendi. tau setup yeni ortamda devam ediyor.",
    },
    "setup.install.failed": {
        "en": "The install failed (uv exit code {code}); the old environment is unchanged. "
        "Going on with what is installed.",
        "tr": "Yükleme başarısız oldu (uv çıkış kodu {code}); eski ortam değişmedi. Yüklü "
        "olanlarla devam ediliyor.",
    },
    "setup.install.not_uv_tool": {
        "en": "tau is not running from a `uv tool` install (a repository checkout or a "
        "virtualenv), so tau setup does not reinstall it. Install {packages} yourself, in a "
        "checkout with `uv sync --all-packages`, then run tau setup again. Going on with what "
        "is installed.",
        "tr": "tau bir `uv tool` kurulumundan çalışmıyor (bir depo kopyası ya da bir "
        "virtualenv), bu yüzden tau setup onu yeniden kurmaz. {packages} paketlerini kendin "
        "yükle, depo kopyasında `uv sync --all-packages` ile, sonra tau setup'ı yeniden "
        "çalıştır. Yüklü olanlarla devam ediliyor.",
    },
    "setup.install.uv_missing": {
        "en": "uv was not found on PATH, so nothing can be installed. Install uv "
        "(https://docs.astral.sh/uv/) or run the installer again.",
        "tr": "PATH üzerinde uv bulunamadı, bu yüzden hiçbir şey yüklenemiyor. uv'yi yükle "
        "(https://docs.astral.sh/uv/) ya da kurucuyu yeniden çalıştır.",
    },
    "setup.install.skipped": {
        "en": "--no-install: {packages} not installed; their features are skipped.",
        "tr": "--no-install: {packages} yüklenmedi; özellikleri atlanıyor.",
    },
    "setup.install.reexec_failed": {
        "en": "tau setup could not restart in the new environment ({error}). Run "
        "`tau setup` again to set up the new features.",
        "tr": "tau setup yeni ortamda yeniden başlayamadı ({error}). Yeni özellikleri "
        "ayarlamak için `tau setup` komutunu yeniden çalıştır.",
    },
    "setup.install.nothing": {
        "en": "Every package of these features is installed.",
        "tr": "Bu özelliklerin bütün paketleri yüklü.",
    },
    "setup.upgrade.running": {
        "en": "Upgrading tau-core and its packages to the latest release: {command}",
        "tr": "tau-core ve paketleri son sürüme yükseltiliyor: {command}",
    },
    "setup.resume.invalid": {
        "en": "The resume file {path} cannot be used ({reason}). Run `tau setup` again.",
        "tr": "Devam dosyası {path} kullanılamıyor ({reason}). `tau setup` komutunu yeniden "
        "çalıştır.",
    },
    # -- remove ------------------------------------------------------------------------------------
    "setup.remove.confirm": {
        "en": "Remove {label} ({package})? Its settings and data stay.",
        "tr": "{label} ({package}) kaldırılsın mı? Ayarları ve verileri kalır.",
    },
    "setup.remove.done": {"en": "Removed {package}.", "tr": "{package} kaldırıldı."},
    "setup.remove.no_package": {
        "en": "{label} has no package to remove.",
        "tr": "{label} için kaldırılacak bir paket yok.",
    },
    "setup.remove.not_installed": {
        "en": "{package} is not installed.",
        "tr": "{package} yüklü değil.",
    },
    "setup.remove.guard_enrolled": {
        "en": "The guard is enrolled: run `tau guard forget` at the Mac first, then remove it. "
        "Without tau-guard an enrolled hub would stay locked.",
        "tr": "Koruma kayıtlı: önce Mac'in başında `tau guard forget` çalıştır, sonra kaldır. "
        "tau-guard olmadan kayıtlı bir hub kilitli kalır.",
    },
    # -- running steps -----------------------------------------------------------------------------
    "setup.section": {"en": "── {label} ──", "tr": "── {label} ──"},
    "setup.step.ask": {
        "en": "{label}: run `tau {command}`?",
        "tr": "{label}: `tau {command}` çalıştırılsın mı?",
    },
    "setup.step.running": {"en": "▸ tau {command}", "tr": "▸ tau {command}"},
    "setup.step.done": {"en": "✓ {label}", "tr": "✓ {label}"},
    "setup.step.failed": {"en": "✗ {label}: {reason}", "tr": "✗ {label}: {reason}"},
    "setup.step.skipped": {"en": "– {label}: {reason}", "tr": "– {label}: {reason}"},
    "setup.skip.platform": {"en": "not on {platform}", "tr": "{platform} için yok"},
    "setup.skip.ssh": {
        "en": "at the Mac only, not over SSH; run `tau {command}` at the Mac",
        "tr": "yalnızca Mac'in başında, SSH üzerinden değil; `tau {command}` komutunu Mac'in "
        "başında çalıştır",
    },
    "setup.skip.missing_command": {
        "en": "`tau {command}` is not available in this version",
        "tr": "`tau {command}` bu sürümde yok",
    },
    "setup.skip.needs": {
        "en": "needs {programs} on PATH",
        "tr": "PATH üzerinde {programs} gerekiyor",
    },
    "setup.skip.declined": {"en": "skipped", "tr": "atlandı"},
    "setup.skip.optional": {
        "en": "optional; not run with --yes",
        "tr": "isteğe bağlı; --yes ile çalıştırılmaz",
    },
    "setup.skip.interactive": {
        "en": "needs you at the terminal; run `tau {command}` later",
        "tr": "terminalde senin olmanı gerektiriyor; sonra `tau {command}` çalıştır",
    },
    "setup.skip.no_input": {"en": "no {input} given", "tr": "{input} verilmedi"},
    "setup.skip.not_installed": {
        "en": "{package} is not installed",
        "tr": "{package} yüklü değil",
    },
    "setup.skip.configured": {"en": "already set up", "tr": "zaten kurulu"},
    "setup.skip.unavailable": {"en": "{reason}", "tr": "{reason}"},
    "setup.skip.interrupted": {"en": "interrupted", "tr": "kesildi"},
    "setup.fail.exit": {"en": "exit code {code}", "tr": "çıkış kodu {code}"},
    "setup.fail.start": {
        "en": "could not start: {error}",
        "tr": "başlatılamadı: {error}",
    },
    "setup.advisory": {
        "en": "reported problems (exit code {code}); the next steps fix the expected ones",
        "tr": "sorun bildirdi (çıkış kodu {code}); sonraki adımlar beklenenleri düzeltir",
    },
    "setup.input.prompt_default": {
        "en": "{label} (Enter keeps {default})",
        "tr": "{label} (Enter ile {default} kalır)",
    },
    "setup.input.prompt_optional": {
        "en": "{label} (Enter skips)",
        "tr": "{label} (Enter ile atlanır)",
    },
    "setup.input.secret": {
        "en": "{label} (hidden; Enter skips)",
        "tr": "{label} (gizli; Enter ile atlanır)",
    },
    "setup.input.saved": {
        "en": "wrote {name} to {path} (mode 0600)",
        "tr": "{name}, {path} dosyasına yazıldı (izin 0600)",
    },
    "setup.input.kept": {
        "en": "kept {name} in {path} (it already has a value)",
        "tr": "{path} içindeki {name} korundu (zaten bir değeri var)",
    },
    # -- the core steps ----------------------------------------------------------------------------
    "setup.core.init": {"en": "Model provider and key", "tr": "Model sağlayıcısı ve anahtar"},
    "setup.core.about": {"en": "About you", "tr": "Senin hakkında"},
    "setup.core.doctor": {"en": "Check the installation", "tr": "Kurulumu denetle"},
    "setup.about.intro": {
        "en": "Optional: tau keeps this in {path}, on this machine only. Enter skips a "
        "question; an empty name skips all of it.",
        "tr": "İsteğe bağlı: tau bunu yalnızca bu makinede, {path} içinde tutar. Enter bir "
        "soruyu atlar; boş bir ad hepsini atlar.",
    },
    "setup.about.name": {"en": "Your name", "tr": "Adın"},
    "setup.about.address": {
        "en": "How should tau address you (e.g. by first name, informal)",
        "tr": "tau sana nasıl hitap etsin (ör. adınla, samimi; ya da siz)",
    },
    "setup.about.languages": {
        "en": "Languages you speak (e.g. English, Turkish)",
        "tr": "Konuştuğun diller (ör. Türkçe, İngilizce)",
    },
    "setup.about.written": {"en": "wrote {path}", "tr": "{path} yazıldı"},
    "setup.about.kept": {
        "en": "{path} already holds your own facts; kept.",
        "tr": "{path} zaten senin bilgilerini içeriyor; korundu.",
    },
    "setup.about.skipped": {
        "en": "No name given; {path} is unchanged.",
        "tr": "Ad verilmedi; {path} değişmedi.",
    },
    "setup.doctor.problems": {
        "en": "tau doctor reports a failed check; see above.",
        "tr": "tau doctor başarısız bir denetim bildiriyor; yukarıya bak.",
    },
    # -- the summary ------------------------------------------------------------------------------
    "setup.summary.title": {"en": "Summary", "tr": "Özet"},
    "setup.summary.on": {"en": "on", "tr": "açık"},
    "setup.summary.skipped": {"en": "skipped", "tr": "atlandı"},
    "setup.summary.failed": {"en": "failed", "tr": "başarısız"},
    "setup.summary.partly": {"en": "partly set up", "tr": "kısmen kuruldu"},
    "setup.summary.next": {"en": "Next:", "tr": "Sırada:"},
    "setup.summary.next_chat": {
        "en": "tau chat      talk to tau in the terminal",
        "tr": "tau chat      terminalde tau ile konuş",
    },
    "setup.summary.next_tui": {
        "en": "tau tui       the full-screen interface",
        "tr": "tau tui       tam ekran arayüz",
    },
    "setup.summary.next_doctor": {
        "en": "tau doctor    check the installation again",
        "tr": "tau doctor    kurulumu yeniden denetle",
    },
    "setup.summary.next_app": {
        "en": "the tau app   {url}",
        "tr": "tau uygulaması {url}",
    },
    "setup.summary.rerun": {
        "en": "Run `tau setup` again any time to add a feature.",
        "tr": "Bir özellik eklemek için `tau setup` komutunu istediğin zaman yeniden çalıştır.",
    },
    "setup.summary.docs": {"en": "Docs: {url}", "tr": "Belgeler: {url}"},
    "setup.permission.camera": {"en": "camera", "tr": "kamera"},
    "setup.permission.notifications": {"en": "notifications", "tr": "bildirimler"},
    "setup.permission.microphone": {"en": "microphone", "tr": "mikrofon"},
    # -- JSON mode errors (the message field of an `error` event) ---------------------------------
    "setup.error.unknown_feature": {
        "en": "Unknown feature: {feature}. Known: {known}.",
        "tr": "Bilinmeyen özellik: {feature}. Bilinenler: {known}.",
    },
    "setup.error.unavailable": {
        "en": "{label} is not available on {platform}: {reason}",
        "tr": "{label} {platform} için yok: {reason}",
    },
    "setup.error.not_installed": {
        "en": "{package} is not installed; run `tau setup install --features {feature}` first.",
        "tr": "{package} yüklü değil; önce `tau setup install --features {feature}` çalıştır.",
    },
    "setup.error.bad_input": {
        "en": "The input on stdin is not usable: {detail}",
        "tr": "stdin'deki girdi kullanılamıyor: {detail}",
    },
    "setup.error.unknown_step": {
        "en": "{feature} has no step {step}.",
        "tr": "{feature} özelliğinde {step} adımı yok.",
    },
    "setup.error.bad_provider": {
        "en": "Unknown provider {provider}; tau setup takes a key for {known}.",
        "tr": "Bilinmeyen sağlayıcı {provider}; tau setup {known} için anahtar alır.",
    },
    # -- the features ------------------------------------------------------------------------------
    "setup.feature.tui": {"en": "Terminal UI", "tr": "Terminal arayüzü"},
    "setup.feature.tui.about": {
        "en": "tau tui: the full-screen interface with streamed replies and approvals",
        "tr": "tau tui: akan yanıtlar ve onaylarla tam ekran arayüz",
    },
    "setup.feature.app": {"en": "The tau app", "tr": "tau uygulaması"},
    "setup.feature.app.about": {
        "en": "the Mac app: menu bar, chat windows, the hub's supervisor",
        "tr": "Mac uygulaması: menü çubuğu, sohbet pencereleri, hub'ın gözetmeni",
    },
    "setup.feature.sub": {"en": "Sub-taus", "tr": "Alt-tau'lar"},
    "setup.feature.sub.about": {
        "en": "named specialists of your tau (/coach, /landing, ...)",
        "tr": "tau'nun adlı uzmanları (/coach, /landing, ...)",
    },
    "setup.feature.telegram": {"en": "Telegram", "tr": "Telegram"},
    "setup.feature.telegram.about": {
        "en": "talk to tau from your phone through your own bot",
        "tr": "kendi botun üzerinden telefondan tau ile konuş",
    },
    "setup.feature.remote": {"en": "Remote access", "tr": "Uzaktan erişim"},
    "setup.feature.remote.about": {
        "en": "reach this machine from your phone over Tailscale and SSH",
        "tr": "bu makineye telefondan Tailscale ve SSH ile ulaş",
    },
    "setup.feature.guard": {"en": "Owner guard", "tr": "Sahip koruması"},
    "setup.feature.guard.about": {
        "en": "tau answers only while you are at the Mac (face check, Touch ID)",
        "tr": "tau yalnızca sen Mac'in başındayken yanıt verir (yüz denetimi, Touch ID)",
    },
    "setup.feature.net": {"en": "The tau network", "tr": "tau ağı"},
    "setup.feature.net.about": {
        "en": "an address for your tau, contacts with other taus, the universe",
        "tr": "tau'na bir adres, başka tau'larla kişiler, evren",
    },
    "setup.feature.autostart": {"en": "Start at login", "tr": "Oturum açılınca başlat"},
    "setup.feature.autostart.about": {
        "en": "run the hub as a service that starts when you log in",
        "tr": "hub'ı oturum açtığında başlayan bir servis olarak çalıştır",
    },
    "setup.feature.cloud": {"en": "Cloud mode", "tr": "Bulut modu"},
    "setup.feature.cloud.about": {
        "en": "run tau in your own Cloudflare account (installs tau-cloud, then the guide)",
        "tr": "tau'yu kendi Cloudflare hesabında çalıştır (tau-cloud'u yükler, sonra rehber)",
    },
    "setup.unavailable.app": {
        "en": "the app is for macOS",
        "tr": "uygulama macOS içindir",
    },
    "setup.unavailable.guard": {
        "en": "macOS only: the guard uses the Mac's built-in camera and Touch ID",
        "tr": "yalnızca macOS: koruma Mac'in yerleşik kamerasını ve Touch ID'yi kullanır",
    },
    # -- the steps ---------------------------------------------------------------------------------
    "setup.step.app.download": {"en": "Download the app", "tr": "Uygulamayı indir"},
    "setup.note.app.download": {
        "en": "The tau app is not released yet. The download page says when it is; until "
        "then, the TauBar guide shows how to build the menu bar app.",
        "tr": "tau uygulaması henüz yayımlanmadı. İndirme sayfası ne zaman yayımlanacağını "
        "söyler; o zamana kadar TauBar rehberi menü çubuğu uygulamasının nasıl derleneceğini "
        "gösterir.",
    },
    "setup.step.sub.first": {"en": "Your first sub-tau", "tr": "İlk alt-tau'n"},
    "setup.note.sub.first": {
        "en": 'Create one when you like: tau sub new coach --describe "a patient running '
        'coach". Then /coach in tau tui, or tau sub chat coach.',
        "tr": 'İstediğinde bir tane oluştur: tau sub new coach --describe "sabırlı bir koşu '
        'koçu". Sonra tau tui içinde /coach ya da tau sub chat coach.',
    },
    "setup.step.telegram.pair": {"en": "Pair your bot", "tr": "Botunu eşleştir"},
    "setup.note.telegram.manual": {
        "en": "Pairing from tau setup comes with a later version. Until then: create a bot "
        "with @BotFather, then put TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_CHAT_IDS into "
        ".env as the Telegram guide shows.",
        "tr": "tau setup ile eşleştirme sonraki bir sürümle geliyor. O zamana kadar: "
        "@BotFather ile bir bot oluştur, sonra TELEGRAM_BOT_TOKEN ve TELEGRAM_ALLOWED_CHAT_IDS "
        "değerlerini Telegram rehberindeki gibi .env dosyasına yaz.",
    },
    "setup.step.remote.guide": {"en": "Tailscale and SSH", "tr": "Tailscale ve SSH"},
    "setup.note.remote.guide": {
        "en": "Guided remote access comes with a later version. Its SSH part needs sudo, "
        "which tau setup never runs: follow the guide to install Tailscale and run the one "
        "sudo command yourself.",
        "tr": "Rehberli uzaktan erişim sonraki bir sürümle geliyor. SSH kısmı sudo ister, "
        "tau setup ise sudo'yu hiç çalıştırmaz: Tailscale'i kurmak ve tek sudo komutunu "
        "kendin çalıştırmak için rehberi izle.",
    },
    "setup.step.guard.doctor": {
        "en": "Check the guard's prerequisites",
        "tr": "Korumanın ön koşullarını denetle",
    },
    "setup.step.guard.setup": {
        "en": "Enroll your face and switch the guard on",
        "tr": "Yüzünü kaydet ve korumayı aç",
    },
    "setup.step.guard.restart": {"en": "Restart the hub", "tr": "Hub'ı yeniden başlat"},
    "setup.note.guard.restart": {
        "en": "The guard starts with the next hub, locked: restart the hub (TauBar: untick "
        "and tick Run the hub; or tau hub stop, then tau hub run), then unlock once in "
        "tau tui.",
        "tr": "Koruma bir sonraki hub ile kilitli olarak başlar: hub'ı yeniden başlat "
        "(TauBar: Run the hub kutusunu kaldırıp yeniden işaretle; ya da tau hub stop, sonra "
        "tau hub run), sonra tau tui içinde bir kez kilidi aç.",
    },
    "setup.step.net.init": {
        "en": "Create your tau's network identity",
        "tr": "tau'nun ağ kimliğini oluştur",
    },
    "setup.step.net.spine": {"en": "Your spine", "tr": "Spine'ın"},
    "setup.note.net.spine": {
        "en": "Your tau's address is a spine, a small Worker in your own Cloudflare account "
        "(the free plan is enough). Deploying it today needs Node.js 22 or newer and one "
        "`npx wrangler login` in a browser; a version without Node is coming. You can skip "
        "the next two steps and deploy later.",
        "tr": "tau'nun adresi bir spine'dır: kendi Cloudflare hesabında küçük bir Worker "
        "(ücretsiz plan yeter). Bugün kurmak için Node.js 22 ya da daha yenisi ve tarayıcıda "
        "bir kez `npx wrangler login` gerekir; Node istemeyen bir sürüm geliyor. Sonraki iki "
        "adımı atlayıp daha sonra kurabilirsin.",
    },
    "setup.step.net.spine_init": {
        "en": "Write the spine project",
        "tr": "Spine projesini yaz",
    },
    "setup.step.net.spine_deploy": {
        "en": "Deploy the spine to Cloudflare",
        "tr": "Spine'ı Cloudflare'e kur",
    },
    "setup.needs.node": {
        "en": "Node.js was not found. Install Node.js 22 or newer (https://nodejs.org), run "
        "`npx wrangler login` once, then run tau setup again, or deploy later with "
        "tau net spine init and tau net spine deploy.",
        "tr": "Node.js bulunamadı. Node.js 22 ya da daha yenisini kur (https://nodejs.org), "
        "bir kez `npx wrangler login` çalıştır, sonra tau setup'ı yeniden çalıştır ya da daha "
        "sonra tau net spine init ve tau net spine deploy ile kur.",
    },
    "setup.step.net.universe": {
        "en": "List your tau in the universe",
        "tr": "tau'nu evrende listele",
    },
    "setup.step.net.claim": {
        "en": "Claim a handle (a GitHub sign-in link)",
        "tr": "Bir kullanıcı adı al (GitHub ile giriş bağlantısı)",
    },
    "setup.step.autostart.launchd": {
        "en": "Install the launchd agent",
        "tr": "launchd ajanını kur",
    },
    "setup.step.autostart.systemd": {
        "en": "A systemd user unit",
        "tr": "Bir systemd kullanıcı birimi",
    },
    "setup.note.autostart.systemd": {
        "en": "On Linux the hub runs as a systemd user unit, no sudo needed: mkdir -p "
        "~/.config/systemd/user && tau hub systemd-unit > "
        "~/.config/systemd/user/tau-hub.service && systemctl --user enable --now tau-hub",
        "tr": "Linux'ta hub bir systemd kullanıcı birimi olarak çalışır, sudo gerekmez: "
        "mkdir -p ~/.config/systemd/user && tau hub systemd-unit > "
        "~/.config/systemd/user/tau-hub.service && systemctl --user enable --now tau-hub",
    },
    "setup.step.cloud.guide": {"en": "The cloud mode guide", "tr": "Bulut modu rehberi"},
    "setup.note.cloud.guide": {
        "en": "tau-cloud is installed. Cloud mode moves your tau into your own Cloudflare "
        "account; the guide walks through it (tau cloud push when you are ready).",
        "tr": "tau-cloud yüklendi. Bulut modu tau'nu kendi Cloudflare hesabına taşır; rehber "
        "adım adım anlatır (hazır olduğunda tau cloud push).",
    },
    # -- inputs ------------------------------------------------------------------------------------
    "setup.input.net_name": {
        "en": "Display name on your card (e.g. Alice's tau)",
        "tr": "Kartındaki görünen ad (ör. Alice'in tau'su)",
    },
    "setup.input.spine_dir": {
        "en": "Directory for the spine project",
        "tr": "Spine projesinin dizini",
    },
    "setup.input.address": {
        "en": "Your tau's address, a domain on your Cloudflare account (Enter: workers.dev)",
        "tr": "tau'nun adresi, Cloudflare hesabındaki bir alan adı (Enter: workers.dev)",
    },
    "setup.input.owner": {
        "en": "Your name in the universe",
        "tr": "Evrendeki adın",
    },
    "setup.input.about": {
        "en": "One line about your tau",
        "tr": "tau'n hakkında bir satır",
    },
}

_collisions = set(SETUP_MESSAGES) & set(MESSAGES)
assert not _collisions, f"setup message keys collide with the table: {sorted(_collisions)}"
register_messages(SETUP_MESSAGES)
