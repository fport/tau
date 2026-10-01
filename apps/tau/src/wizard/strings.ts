// The setup wizard's own words, in English and Turkish: a small message table for the wizard's
// chrome only (the app-wide one is roadmap 086). Feature labels, descriptions, step labels and
// tau's messages come from `tau --lang <en|tr> setup …` already localized. English is the
// source; a key missing in Turkish fails the type check.

import type { Lang } from "./api";

const en = {
  "app.title": "Set up tau",
  "app.subtitle": "tau on this Mac, step by step",

  "step.language": "Language",
  "step.install": "Install tau",
  "step.key": "Model key",
  "step.about": "About you",
  "step.features": "Features",
  "step.permissions": "Permissions",
  "step.setup": "Feature steps",
  "step.summary": "Summary",

  "mark.done": "done",
  "mark.skipped": "skipped",
  "mark.failed": "needs a look",

  "nav.back": "Back",
  "nav.next": "Next",
  "nav.skip": "Skip",
  "nav.continue": "Continue",
  "nav.cancel": "Cancel",
  "nav.retry": "Try again",
  "nav.busy": "A step is running. Wait for it, or cancel it.",

  "common.output": "Output",
  "common.copy": "Copy",
  "common.copied": "Copied",
  "common.open": "Open",
  "common.loading": "Loading…",
  "common.needs_tau": "Install tau first (the Install tau step); this step needs it.",
  "common.exit": "It ended with exit code {code}.",
  "common.cancelled": "Cancelled.",
  "common.timed_out": "It took too long and was stopped.",

  "language.title": "Welcome to tau",
  "language.body":
    "Choose the language of this setup and of tau's menus. tau itself answers in whichever language you write to it.",
  "language.en": "English",
  "language.tr": "Türkçe",

  "install.title": "Install tau",
  "install.looking": "Looking for tau on this Mac…",
  "install.found": "Found {version}",
  "install.python": "Python",
  "install.home": "Configuration (TAU_HOME)",
  "install.via": "Found through",
  "install.kind.settings": "tau's hub settings",
  "install.kind.checkout": "a tau checkout",
  "install.kind.uv_tool": "uv tool install",
  "install.kind.command": "the tau command",
  "install.saved":
    "tau's settings now point at it: the hub and the chat windows run this tau.",
  "install.rejected": "Also looked at",
  "install.missing":
    "tau is not installed yet. The app installs it with uv, a package manager for Python (uv tool install tau-core --with tau-tui). It needs no administrator password and stays in your home folder.",
  "install.tau": "Install tau",
  "install.no_uv":
    "tau is installed with uv, a package manager for Python by Astral. uv is not on this Mac yet. The app can download Astral's official installer from {url} and run it: it puts uv into ~/.local/bin and may add that folder to your shell's PATH. No administrator password, nothing outside your home folder.",
  "install.uv": "Install uv",
  "install.uv_docs": "About uv",
  "install.too_old":
    "This tau ({version}) is older than the setup wizard: it has no tau setup command yet.",
  "install.upgrade": "Update tau",
  "install.upgrade_checkout":
    "This tau runs from a checkout: update it there (git pull, then uv sync --all-packages), then come back to this step.",
  "install.status_failed": "tau setup could not report its state.",
  "install.recheck": "Look again",
  "install.version": "Version {version} (TAU_INSTALL_VERSION)",
  "install.running": "Installing…",

  "key.title": "Model key",
  "key.body":
    "tau thinks with a language model from a provider you choose, paid with your own key. tau checks the key with one small request, then keeps it in {home}/.env, which only you can read. It never appears on a command line or in a log.",
  "key.configured":
    "tau is configured already ({home}/tau.toml exists). To change the model or its key, edit tau.toml and .env, or run tau init in a terminal.",
  "key.provider": "Provider",
  "key.provider.anthropic": "Anthropic (Claude)",
  "key.provider.openai": "OpenAI",
  "key.provider.gemini": "Google Gemini",
  "key.provider.bedrock": "Amazon Bedrock",
  "key.provider.fake": "No key yet: try tau with scripted replies",
  "key.bedrock": "Bedrock uses the AWS credentials of this Mac (aws configure); tau asks for no key.",
  "key.fake":
    "tau answers with a few fixed replies, so you can look around. Run Set up tau… again when you have a key.",
  "key.key": "API key",
  "key.get": "Get a key",
  "key.save": "Check and save",
  "key.saving": "Checking the key…",
  "key.saved": "Saved. tau is configured.",

  "about.title": "About you",
  "about.body":
    "Optional. tau keeps this in persona/user.md on this Mac and reads it in every conversation with you (never in a conversation with another tau).",
  "about.configured": "persona/user.md already holds facts about you; tau keeps it as it is.",
  "about.name": "Your name",
  "about.address": "How tau should address you",
  "about.languages": "Your languages (for example: Turkish, English)",
  "about.save": "Save",
  "about.saved": "Saved.",

  "features.title": "Features",
  "features.body":
    "Choose what tau should do on this Mac. You can add or remove features later: open Set up tau… again.",
  "features.state.done": "on",
  "features.state.installed": "installed",
  "features.state.missing": "not installed",
  "features.state.available": "",
  "features.state.unavailable": "not on this Mac",
  "features.advanced": "Advanced",
  "features.needs": "Asks for: {permissions}",
  "features.requires": "Also turns on: {features}",
  "features.this_app": "This app: you are using it.",
  "features.autostart":
    "This app runs the hub and opens when you log in, so the hub's camera works for the guard.",
  "features.install": "Install and continue",
  "features.installing": "Installing the packages…",
  "features.installed": "Installed: {packages}.",
  "features.nothing": "Nothing to install.",
  "features.checkout":
    "This tau runs from a checkout, so the app cannot add packages to it. Install them there (uv sync --all-packages), then open Set up tau… again. The rest goes on with what is installed.",
  "features.docs": "Guide",

  "permissions.title": "Permissions",
  "permissions.body":
    "Only what the features you chose need. macOS asks once; you can change your answer later in System Settings.",
  "permissions.none": "The features you chose need no permissions.",
  "permissions.why.camera":
    "The owner guard checks that it is you at the Mac. The camera is on only during a check, a few seconds at a time, and nothing is recorded.",
  "permissions.why.notifications":
    "So tau can tell you when something needs you, such as an approval.",
  "permissions.why.microphone": "So tau can hear your voice commands.",
  "permissions.for": "For: {features}",
  "permissions.access.granted": "Allowed",
  "permissions.access.denied": "Not allowed",
  "permissions.access.restricted": "Blocked by a profile on this Mac",
  "permissions.access.not_determined": "Not asked yet",
  "permissions.access.unsupported": "Only in the installed tau.app",
  "permissions.allow": "Allow…",
  "permissions.asking": "macOS is asking…",
  "permissions.settings": "Open System Settings",
  "permissions.fix.camera":
    "To change it: System Settings → Privacy & Security → Camera, switch tau on.",
  "permissions.fix.microphone":
    "To change it: System Settings → Privacy & Security → Microphone, switch tau on.",
  "permissions.fix.notifications":
    "To change it: System Settings → Notifications → tau, switch Allow notifications on.",

  "setup.title": "Feature steps",
  "setup.body":
    "Each chosen feature's steps, one after the other. A step can be skipped, and a failed step does not stop the others.",
  "setup.none": "The features you chose have no steps to run.",
  "setup.optional": "optional",
  "setup.run": "Set up",
  "setup.run_again": "Run again",
  "setup.skip_feature": "Skip this feature",
  "setup.status.pending": "waiting",
  "setup.status.running": "running",
  "setup.status.checking": "checking",
  "setup.status.done": "done",
  "setup.status.failed": "failed",
  "setup.status.skipped": "skipped",
  "setup.status.info": "note",
  "setup.status.needs_ui": "needs you",
  "setup.outcome.done": "on",
  "setup.outcome.partial": "partly set up",
  "setup.outcome.failed": "failed",
  "setup.outcome.skipped": "skipped",
  "setup.this_app": "This app is installed; nothing to do.",
  "setup.autostart.do": "Run the hub in this app and open it at login",
  "setup.autostart.done": "The app runs the hub and opens at login.",
  "setup.checks": "Checks",
  "setup.terminal.intro": "This step needs you at the Mac. It runs below; follow what it asks.",
  "setup.terminal.start": "Start",
  "setup.terminal.finished": "Finished.",
  "setup.terminal.failed": "It did not finish (exit code {code}).",
  "setup.guard.intro":
    "Enroll your face: macOS asks for Touch ID or your password, then for the camera in tau's name. A dark window shows what to do: look at the camera, then turn left, right, up and down. Sit in normal light, about an arm's length away.",
  "setup.continue": "Continue with the next steps",
  "setup.done_check": "Done, check again",
  "setup.skip_step": "Skip this step",
  "setup.action.run": "Run this in Terminal:",
  "setup.action.sudo":
    "It asks for your Mac password there. The app never runs sudo or anything with administrator rights.",
  "setup.action.changes": "What it changes",
  "setup.action.script": "The script",
  "setup.phone.title": "Your phone: Termius",
  "setup.phone.host": "Host",
  "setup.phone.ip": "IP address",
  "setup.phone.user": "User",
  "setup.phone.port": "Port",
  "setup.phone.mosh": "mosh",
  "setup.phone.startup": "Startup command",
  "setup.phone.keys": "Keys",

  "telegram.intro":
    "1. In Telegram, open @BotFather, send /newbot and follow it. 2. Paste the bot token it gives you here. 3. Send your bot the code tau shows.",
  "telegram.botfather": "Open @BotFather",
  "telegram.token": "Bot token",
  "telegram.keep": "Leave it empty to keep the token tau has.",
  "telegram.pair": "Pair",
  "telegram.bot": "Bot @{bot}",
  "telegram.code": "Send this code to your bot within 10 minutes:",
  "telegram.open": "Open in Telegram",
  "telegram.waiting": "Waiting for your message…",
  "telegram.paired": "Paired with {name}.",

  "spine.intro":
    "The spine is your tau's mailbox on Cloudflare, in your own account (the free plan is enough). The deploy needs no Node.js.",
  "spine.deploy": "Deploy the spine",
  "spine.need_token":
    "tau needs a Cloudflare API token with these permissions. The page below has them filled in: create the token there, then paste it here.",
  "spine.open": "Open Cloudflare",
  "spine.token": "Cloudflare API token",
  "spine.account": "Which Cloudflare account?",
  "spine.done": "Your spine runs at {url}.",
  "spine.unhealthy": "It does not answer yet; a new address can take a few minutes.",

  "summary.title": "Summary",
  "summary.body": "What is on now. Open Set up tau… from the menu at any time to change it.",
  "summary.key": "Model key",
  "summary.key.set": "set",
  "summary.key.skipped": "skipped",
  "summary.about": "About you",
  "summary.chosen": "not chosen",
  "summary.chat": "Open a chat window",
  "summary.hub": "Start the hub",
  "summary.hub_started": "The hub is starting.",
  "summary.hub_not_ready": "The hub needs tau installed first.",
  "summary.settings": "Settings",
  "summary.doctor": "Checks (tau doctor)",
  "summary.doctor_run": "Run the checks",
} as const;

export type Key = keyof typeof en;

const tr: Record<Key, string> = {
  "app.title": "tau'yu kur",
  "app.subtitle": "Bu Mac'te tau, adım adım",

  "step.language": "Dil",
  "step.install": "tau'yu kur",
  "step.key": "Model anahtarı",
  "step.about": "Hakkında",
  "step.features": "Özellikler",
  "step.permissions": "İzinler",
  "step.setup": "Özellik adımları",
  "step.summary": "Özet",

  "mark.done": "tamam",
  "mark.skipped": "atlandı",
  "mark.failed": "bakılmalı",

  "nav.back": "Geri",
  "nav.next": "İleri",
  "nav.skip": "Atla",
  "nav.continue": "Devam",
  "nav.cancel": "İptal",
  "nav.retry": "Tekrar dene",
  "nav.busy": "Bir adım çalışıyor. Bitmesini bekle ya da iptal et.",

  "common.output": "Çıktı",
  "common.copy": "Kopyala",
  "common.copied": "Kopyalandı",
  "common.open": "Aç",
  "common.loading": "Yükleniyor…",
  "common.needs_tau": "Önce tau'yu kur (tau'yu kur adımı); bu adımın ona ihtiyacı var.",
  "common.exit": "{code} çıkış koduyla bitti.",
  "common.cancelled": "İptal edildi.",
  "common.timed_out": "Çok uzun sürdü ve durduruldu.",

  "language.title": "tau'ya hoş geldin",
  "language.body":
    "Bu kurulumun ve tau'nun menülerinin dilini seç. tau, sen ona hangi dilde yazarsan o dilde cevap verir.",
  "language.en": "English",
  "language.tr": "Türkçe",

  "install.title": "tau'yu kur",
  "install.looking": "Bu Mac'te tau aranıyor…",
  "install.found": "{version} bulundu",
  "install.python": "Python",
  "install.home": "Yapılandırma (TAU_HOME)",
  "install.via": "Nereden bulundu",
  "install.kind.settings": "tau'nun hub ayarları",
  "install.kind.checkout": "bir tau kaynak kopyası (checkout)",
  "install.kind.uv_tool": "uv tool install",
  "install.kind.command": "tau komutu",
  "install.saved":
    "tau'nun ayarları artık onu gösteriyor: hub ve sohbet pencereleri bu tau'yu çalıştırır.",
  "install.rejected": "Ayrıca bakılanlar",
  "install.missing":
    "tau henüz kurulu değil. Uygulama onu Python paket yöneticisi uv ile kurar (uv tool install tau-core --with tau-tui). Yönetici parolası gerekmez, her şey ev klasöründe kalır.",
  "install.tau": "tau'yu kur",
  "install.no_uv":
    "tau, Astral'ın Python paket yöneticisi uv ile kurulur. uv bu Mac'te henüz yok. Uygulama Astral'ın resmî kurulum betiğini {url} adresinden indirip çalıştırabilir: uv'yi ~/.local/bin içine koyar ve bu klasörü kabuğunun PATH'ine ekleyebilir. Yönetici parolası gerekmez, ev klasörünün dışına hiçbir şey yazılmaz.",
  "install.uv": "uv'yi kur",
  "install.uv_docs": "uv hakkında",
  "install.too_old": "Bu tau ({version}) kurulum sihirbazından eski: henüz tau setup komutu yok.",
  "install.upgrade": "tau'yu güncelle",
  "install.upgrade_checkout":
    "Bu tau bir kaynak kopyasından çalışıyor: onu orada güncelle (git pull, ardından uv sync --all-packages), sonra bu adıma dön.",
  "install.status_failed": "tau setup durumunu bildiremedi.",
  "install.recheck": "Yeniden bak",
  "install.version": "Sürüm {version} (TAU_INSTALL_VERSION)",
  "install.running": "Kuruluyor…",

  "key.title": "Model anahtarı",
  "key.body":
    "tau, seçtiğin bir sağlayıcının dil modeliyle düşünür; ücreti kendi anahtarınla ödenir. tau anahtarı küçük bir istekle kontrol eder, sonra yalnızca senin okuyabildiğin {home}/.env dosyasında saklar. Anahtar hiçbir komut satırında ya da günlükte görünmez.",
  "key.configured":
    "tau zaten yapılandırılmış ({home}/tau.toml var). Modeli ya da anahtarını değiştirmek için tau.toml ve .env dosyalarını düzenle ya da bir terminalde tau init çalıştır.",
  "key.provider": "Sağlayıcı",
  "key.provider.anthropic": "Anthropic (Claude)",
  "key.provider.openai": "OpenAI",
  "key.provider.gemini": "Google Gemini",
  "key.provider.bedrock": "Amazon Bedrock",
  "key.provider.fake": "Henüz anahtar yok: tau'yu hazır cevaplarla dene",
  "key.bedrock":
    "Bedrock bu Mac'in AWS kimlik bilgilerini (aws configure) kullanır; tau anahtar istemez.",
  "key.fake":
    "tau birkaç sabit cevap verir, böylece etrafa bakabilirsin. Anahtarın olunca tau'yu kur… adımlarını yeniden aç.",
  "key.key": "API anahtarı",
  "key.get": "Anahtar al",
  "key.save": "Kontrol et ve kaydet",
  "key.saving": "Anahtar kontrol ediliyor…",
  "key.saved": "Kaydedildi. tau yapılandırıldı.",

  "about.title": "Hakkında",
  "about.body":
    "İsteğe bağlı. tau bunu bu Mac'te persona/user.md içinde tutar ve seninle her konuşmada okur (başka bir tau ile konuşurken asla).",
  "about.configured": "persona/user.md zaten senin hakkında bilgi içeriyor; tau onu olduğu gibi bırakır.",
  "about.name": "Adın",
  "about.address": "tau sana nasıl hitap etsin",
  "about.languages": "Konuştuğun diller (örneğin: Türkçe, İngilizce)",
  "about.save": "Kaydet",
  "about.saved": "Kaydedildi.",

  "features.title": "Özellikler",
  "features.body":
    "tau'nun bu Mac'te ne yapacağını seç. Özellikleri sonra ekleyip çıkarabilirsin: tau'yu kur… adımlarını yeniden aç.",
  "features.state.done": "açık",
  "features.state.installed": "kurulu",
  "features.state.missing": "kurulu değil",
  "features.state.available": "",
  "features.state.unavailable": "bu Mac'te yok",
  "features.advanced": "Gelişmiş",
  "features.needs": "İstediği izin: {permissions}",
  "features.requires": "Bunu da açar: {features}",
  "features.this_app": "Bu uygulama: şu an onu kullanıyorsun.",
  "features.autostart":
    "Bu uygulama hub'ı çalıştırır ve oturum açınca açılır; böylece hub'ın kamerası koruma için çalışır.",
  "features.install": "Kur ve devam et",
  "features.installing": "Paketler kuruluyor…",
  "features.installed": "Kuruldu: {packages}.",
  "features.nothing": "Kurulacak bir şey yok.",
  "features.checkout":
    "Bu tau bir kaynak kopyasından çalışıyor, bu yüzden uygulama ona paket ekleyemez. Paketleri orada kur (uv sync --all-packages), sonra tau'yu kur… adımlarını yeniden aç. Kalan adımlar kurulu olanlarla devam eder.",
  "features.docs": "Rehber",

  "permissions.title": "İzinler",
  "permissions.body":
    "Yalnızca seçtiğin özelliklerin ihtiyaç duydukları. macOS bir kez sorar; cevabını sonra Sistem Ayarları'ndan değiştirebilirsin.",
  "permissions.none": "Seçtiğin özelliklerin izne ihtiyacı yok.",
  "permissions.why.camera":
    "Sahip koruması, Mac'in başındakinin sen olduğunu kontrol eder. Kamera yalnızca kontrol sırasında, birkaç saniyeliğine açılır ve hiçbir şey kaydedilmez.",
  "permissions.why.notifications":
    "tau, bir onay gibi seni bekleyen bir şey olduğunda haber verebilsin diye.",
  "permissions.why.microphone": "tau sesli komutlarını duyabilsin diye.",
  "permissions.for": "Şunun için: {features}",
  "permissions.access.granted": "İzin verildi",
  "permissions.access.denied": "İzin verilmedi",
  "permissions.access.restricted": "Bu Mac'teki bir profil engelliyor",
  "permissions.access.not_determined": "Henüz sorulmadı",
  "permissions.access.unsupported": "Yalnızca kurulu tau.app'te",
  "permissions.allow": "İzin ver…",
  "permissions.asking": "macOS soruyor…",
  "permissions.settings": "Sistem Ayarları'nı aç",
  "permissions.fix.camera":
    "Değiştirmek için: Sistem Ayarları → Gizlilik ve Güvenlik → Kamera, tau'yu aç.",
  "permissions.fix.microphone":
    "Değiştirmek için: Sistem Ayarları → Gizlilik ve Güvenlik → Mikrofon, tau'yu aç.",
  "permissions.fix.notifications":
    "Değiştirmek için: Sistem Ayarları → Bildirimler → tau, Bildirimlere izin ver'i aç.",

  "setup.title": "Özellik adımları",
  "setup.body":
    "Seçtiğin her özelliğin adımları, sırayla. Bir adım atlanabilir; başarısız bir adım diğerlerini durdurmaz.",
  "setup.none": "Seçtiğin özelliklerin çalıştırılacak adımı yok.",
  "setup.optional": "isteğe bağlı",
  "setup.run": "Kur",
  "setup.run_again": "Tekrar çalıştır",
  "setup.skip_feature": "Bu özelliği atla",
  "setup.status.pending": "bekliyor",
  "setup.status.running": "çalışıyor",
  "setup.status.checking": "kontrol ediliyor",
  "setup.status.done": "tamam",
  "setup.status.failed": "başarısız",
  "setup.status.skipped": "atlandı",
  "setup.status.info": "not",
  "setup.status.needs_ui": "seni bekliyor",
  "setup.outcome.done": "açık",
  "setup.outcome.partial": "kısmen kuruldu",
  "setup.outcome.failed": "başarısız",
  "setup.outcome.skipped": "atlandı",
  "setup.this_app": "Bu uygulama kurulu; yapılacak bir şey yok.",
  "setup.autostart.do": "Hub'ı bu uygulamada çalıştır ve oturum açınca aç",
  "setup.autostart.done": "Uygulama hub'ı çalıştırıyor ve oturum açınca açılıyor.",
  "setup.checks": "Kontroller",
  "setup.terminal.intro":
    "Bu adım için Mac'in başında olman gerekiyor. Aşağıda çalışır; ne isterse onu yap.",
  "setup.terminal.start": "Başlat",
  "setup.terminal.finished": "Bitti.",
  "setup.terminal.failed": "Tamamlanmadı ({code} çıkış kodu).",
  "setup.guard.intro":
    "Yüzünü kaydet: macOS önce Touch ID ya da parolanı, sonra tau adına kamerayı sorar. Koyu bir pencere ne yapacağını gösterir: kameraya bak, sonra sola, sağa, yukarı ve aşağı dön. Normal ışıkta, kol boyu uzaklıkta otur.",
  "setup.continue": "Sonraki adımlarla devam et",
  "setup.done_check": "Tamam, tekrar kontrol et",
  "setup.skip_step": "Bu adımı atla",
  "setup.action.run": "Bunu Terminal'de çalıştır:",
  "setup.action.sudo":
    "Orada Mac parolanı ister. Uygulama asla sudo ya da yönetici yetkisiyle bir şey çalıştırmaz.",
  "setup.action.changes": "Neyi değiştirir",
  "setup.action.script": "Betik",
  "setup.phone.title": "Telefonun: Termius",
  "setup.phone.host": "Sunucu",
  "setup.phone.ip": "IP adresi",
  "setup.phone.user": "Kullanıcı",
  "setup.phone.port": "Port",
  "setup.phone.mosh": "mosh",
  "setup.phone.startup": "Başlangıç komutu",
  "setup.phone.keys": "Anahtarlar",

  "telegram.intro":
    "1. Telegram'da @BotFather'ı aç, /newbot gönder ve adımları izle. 2. Verdiği bot token'ını buraya yapıştır. 3. tau'nun gösterdiği kodu botuna gönder.",
  "telegram.botfather": "@BotFather'ı aç",
  "telegram.token": "Bot token'ı",
  "telegram.keep": "tau'daki token'ı korumak için boş bırak.",
  "telegram.pair": "Eşleştir",
  "telegram.bot": "Bot @{bot}",
  "telegram.code": "Bu kodu 10 dakika içinde botuna gönder:",
  "telegram.open": "Telegram'da aç",
  "telegram.waiting": "Mesajın bekleniyor…",
  "telegram.paired": "{name} ile eşleşti.",

  "spine.intro":
    "Omurga (spine), tau'nun Cloudflare'deki posta kutusudur; kendi hesabında çalışır (ücretsiz plan yeterli). Kurulum Node.js gerektirmez.",
  "spine.deploy": "Omurgayı kur",
  "spine.need_token":
    "tau'nun bu izinlere sahip bir Cloudflare API token'ına ihtiyacı var. Aşağıdaki sayfada izinler hazır: token'ı orada oluştur, sonra buraya yapıştır.",
  "spine.open": "Cloudflare'i aç",
  "spine.token": "Cloudflare API token'ı",
  "spine.account": "Hangi Cloudflare hesabı?",
  "spine.done": "Omurgan {url} adresinde çalışıyor.",
  "spine.unhealthy": "Henüz cevap vermiyor; yeni bir adresin hazır olması birkaç dakika sürebilir.",

  "summary.title": "Özet",
  "summary.body": "Şu an açık olanlar. Değiştirmek için menüden istediğin zaman tau'yu kur… seç.",
  "summary.key": "Model anahtarı",
  "summary.key.set": "ayarlandı",
  "summary.key.skipped": "atlandı",
  "summary.about": "Hakkında",
  "summary.chosen": "seçilmedi",
  "summary.chat": "Sohbet penceresi aç",
  "summary.hub": "Hub'ı başlat",
  "summary.hub_started": "Hub başlıyor.",
  "summary.hub_not_ready": "Hub için önce tau'nun kurulu olması gerekiyor.",
  "summary.settings": "Ayarlar",
  "summary.doctor": "Kontroller (tau doctor)",
  "summary.doctor_run": "Kontrolleri çalıştır",
};

const TABLE: Record<Lang, Record<Key, string>> = { en, tr };

export type T = (key: Key, vars?: Record<string, string | number>) => string;

/** The wizard's words in `lang`, with `{name}` placeholders filled from `vars`. */
export function strings(lang: Lang): T {
  const table = TABLE[lang] ?? en;
  return (key, vars) => {
    const text = table[key] ?? en[key];
    if (!vars) return text;
    return text.replace(/\{(\w+)\}/g, (whole, name: string) =>
      name in vars ? String(vars[name]) : whole,
    );
  };
}

/** The language to start in: Turkish when the system says so, else English. */
export function guessLang(languages: readonly string[]): Lang {
  return languages.some((l) => l.toLowerCase().startsWith("tr")) ? "tr" : "en";
}

export const KEYS = Object.keys(en) as Key[];
export const TABLES = TABLE;
