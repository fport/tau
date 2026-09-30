"""The ``tau guard`` message keys (``guard.cli.*``), registered into ``tau_core.i18n`` at import.

They cover ``status``, ``lock`` and ``log`` (issue 111), ``setup``, ``enroll``, ``verify``,
``forget`` and ``doctor`` (issue 112), and the LocalAuthentication prompt texts
(``guard.cli.la.*``) that the hub and the CLI put into a worker request. :data:`WINDOW_MESSAGES`
holds the guard window's lines (``guard.window.*``, issue 126), which the hub and the CLI also
put into a worker request (the worker never imports tau-core), and ``tau guard window``'s
(``guard.cli.window.*``).

tau-core's own guard keys (``guard.state.*``, ``guard.verdict.*``, ``guard.lock_trigger.*``,
``guard.start_hub``) are used as they are. The keys below are new and must not collide with
tau-core's table, because ``register_messages`` overrides silently; the assertion at import
keeps that honest. Help texts and error lines stay English.
"""

from __future__ import annotations

import tau_core.guard  # noqa: F401  (registers tau-core's guard keys before the check)
from tau_core.i18n import MESSAGES, register_messages

CLI_MESSAGES: dict[str, dict[str, str]] = {
    # -- tau guard status ----------------------------------------------------------------------
    "guard.cli.off": {
        "en": "The guard is off (no enrollment marker, and [component.guard] enabled is not true).",
        "tr": "Koruma kapalı (kayıt işareti yok ve [component.guard] enabled true değil).",
    },
    "guard.cli.no_hub": {
        "en": "No hub runs, so guarded channels stay locked. {hint}",
        "tr": "Çalışan hub yok, bu yüzden korunan kanallar kilitli kalır. {hint}",
    },
    "guard.cli.hub_off": {
        "en": "The running hub has no active guard service; guarded channels stay locked. "
        "Restart the hub.",
        "tr": "Çalışan hub'da etkin koruma servisi yok; korunan kanallar kilitli kalır. "
        "Hub'ı yeniden başlat.",
    },
    "guard.cli.hub_error": {
        "en": "The hub did not answer as expected: {error}",
        "tr": "Hub beklendiği gibi yanıt vermedi: {error}",
    },
    "guard.cli.state": {"en": "Guard: {state}", "tr": "Koruma: {state}"},
    "guard.cli.reason": {"en": "  Reason: {reason}", "tr": "  Neden: {reason}"},
    "guard.cli.trigger": {"en": "  Why: {trigger}", "tr": "  Kilit nedeni: {trigger}"},
    "guard.cli.method": {"en": "  Unlocked with: {method}", "tr": "  Açan yöntem: {method}"},
    "guard.cli.since": {"en": "  Unlocked since: {when}", "tr": "  Açılış zamanı: {when}"},
    "guard.cli.expires": {
        "en": "  Locks at the latest: {when}",
        "tr": "  En geç kilitlenme: {when}",
    },
    "guard.cli.face_seen": {"en": "  Face last seen: {when}", "tr": "  Yüz son görülme: {when}"},
    "guard.cli.failures": {
        "en": "  Failed attempts since the last unlock: {count}",
        "tr": "  Son açılıştan beri başarısız deneme: {count}",
    },
    "guard.cli.fallback": {
        "en": "  Touch ID fallback: offered ({mode})",
        "tr": "  Touch ID yedeği: sunuluyor ({mode})",
    },
    "guard.cli.cooldown": {
        "en": "  Too many failed attempts; checks resume at {when}",
        "tr": "  Çok fazla başarısız deneme; kontroller {when} itibarıyla yeniden başlar",
    },
    "guard.cli.enrolled": {"en": "  Face enrolled: {value}", "tr": "  Kayıtlı yüz: {value}"},
    "guard.cli.attempt": {"en": "  Check running: {step}", "tr": "  Süren kontrol: {step}"},
    "guard.cli.screen_unknown": {
        "en": "  The screen lock cannot be read (no GUI session); an unlock lasts at most "
        "idle_lock_minutes.",
        "tr": "  Ekran kilidi okunamıyor (grafik oturum yok); bir açılış en fazla "
        "idle_lock_minutes sürer.",
    },
    "guard.cli.yes": {"en": "yes", "tr": "evet"},
    "guard.cli.no": {"en": "no", "tr": "hayır"},
    # -- tau guard lock ------------------------------------------------------------------------
    "guard.cli.locked": {"en": "tau is locked.", "tr": "tau kilitlendi."},
    "guard.cli.lock_no_hub": {
        "en": "No hub runs; guarded channels are locked anyway.",
        "tr": "Çalışan hub yok; korunan kanallar zaten kilitli.",
    },
    "guard.cli.lock_failed": {
        "en": "The hub did not confirm the lock: {error}",
        "tr": "Hub kilidi doğrulamadı: {error}",
    },
    # -- tau guard log -------------------------------------------------------------------------
    "guard.cli.log.empty": {
        "en": "The guard's audit log has no entries.",
        "tr": "Korumanın denetim günlüğünde kayıt yok.",
    },
    "guard.cli.log.ok": {"en": "ok", "tr": "tamam"},
    "guard.cli.log.failed": {"en": "failed", "tr": "başarısız"},
    "guard.cli.log.event.verify": {"en": "unlock check", "tr": "açma kontrolü"},
    "guard.cli.log.event.step_up": {"en": "step-up", "tr": "ek doğrulama"},
    "guard.cli.log.event.recheck": {"en": "presence recheck", "tr": "varlık yoklaması"},
    "guard.cli.log.event.lock": {"en": "lock", "tr": "kilit"},
    "guard.cli.log.event.unlock": {"en": "unlocked", "tr": "kilit açıldı"},
    "guard.cli.log.event.enroll": {"en": "enrollment", "tr": "kayıt"},
    "guard.cli.log.event.forget": {"en": "forget", "tr": "silme"},
    "guard.cli.log.event.cooldown": {"en": "cooldown", "tr": "bekleme"},
    "guard.cli.log.event.camera_open": {"en": "camera opened", "tr": "kamera açıldı"},
    "guard.cli.log.event.touch_id": {"en": "Touch ID", "tr": "Touch ID"},
    # -- LocalAuthentication prompt texts (macOS shows "<app> is trying to <text>.") -------------
    "guard.cli.la.enroll": {
        "en": "enroll your face for the tau guard",
        "tr": "tau koruması için yüzünü kaydetmek",
    },
    "guard.cli.la.forget": {
        "en": "remove your face from the tau guard",
        "tr": "yüzünü tau korumasından silmek",
    },
    "guard.cli.la.unlock": {"en": "unlock tau", "tr": "tau'nun kilidini açmak"},
    "guard.cli.la.recheck": {
        "en": "confirm that you are still at tau",
        "tr": "hâlâ tau'nun başında olduğunu doğrulamak",
    },
    "guard.cli.la.step_up": {
        "en": "confirm that tau may run {tool}",
        "tr": "tau'nun {tool} çalıştırabileceğini onaylamak",
    },
    # -- shared by setup, enroll, verify, forget ------------------------------------------------
    "guard.cli.unsupported": {
        "en": "The face guard works only on macOS.",
        "tr": "Yüz koruması yalnızca macOS'ta çalışır.",
    },
    "guard.cli.ssh_refused": {
        "en": "This runs only at the Mac, not in a session over SSH: the macOS prompt and the "
        "camera are on the Mac.",
        "tr": "Bu yalnızca Mac'in başında çalışır, SSH oturumunda değil: macOS isteği ve kamera "
        "Mac'te.",
    },
    "guard.cli.no_model": {
        "en": "The face model is not installed. Run `tau guard setup` (offline: "
        "`tau guard setup --model-file PATH`).",
        "tr": "Yüz modeli kurulu değil. `tau guard setup` çalıştır (çevrimdışı: "
        "`tau guard setup --model-file PATH`).",
    },
    "guard.cli.via_hub": {
        "en": "The hub runs this (any macOS prompt appears on the Mac's screen).",
        "tr": "Bunu hub çalıştırıyor (macOS istekleri Mac'in ekranında çıkar).",
    },
    "guard.cli.local": {
        "en": "No hub with an active guard runs; using a local worker.",
        "tr": "Etkin korumalı çalışan hub yok; yerel bir işçi kullanılıyor.",
    },
    "guard.cli.worker_failed": {
        "en": "The guard worker failed: {error}. Details are in {log}.",
        "tr": "Koruma işçisi başarısız oldu: {error}. Ayrıntılar {log} içinde.",
    },
    # -- the face model ------------------------------------------------------------------------
    "guard.cli.model.present": {
        "en": "Face model: installed and verified.",
        "tr": "Yüz modeli: kurulu ve doğrulandı.",
    },
    "guard.cli.model.downloading": {
        "en": "Downloading the face model (SFace, about 39 MB) from opencv_zoo…",
        "tr": "Yüz modeli indiriliyor (SFace, yaklaşık 39 MB, opencv_zoo'dan)…",
    },
    "guard.cli.model.copying": {
        "en": "Installing the face model from {path}…",
        "tr": "Yüz modeli {path} dosyasından kuruluyor…",
    },
    "guard.cli.model.installed": {
        "en": "Face model installed; its sha256 matches the pinned one.",
        "tr": "Yüz modeli kuruldu; sha256 değeri sabitlenmiş olanla eşleşiyor.",
    },
    "guard.cli.model.checksum": {
        "en": "The face model's sha256 does not match: expected {expected}, got {actual}. The "
        "file was not kept.",
        "tr": "Yüz modelinin sha256 değeri eşleşmiyor: beklenen {expected}, gelen {actual}. "
        "Dosya saklanmadı.",
    },
    "guard.cli.model.failed": {
        "en": "The face model could not be installed: {error}",
        "tr": "Yüz modeli kurulamadı: {error}",
    },
    # -- tau guard setup -----------------------------------------------------------------------
    "guard.cli.setup.start": {
        "en": "Setting up the face guard. Frames, the template and the key stay on this Mac.",
        "tr": "Yüz koruması kuruluyor. Kareler, şablon ve anahtar bu Mac'te kalır.",
    },
    "guard.cli.setup.enroll": {
        "en": "Enroll your face: macOS asks for Touch ID or your password first.",
        "tr": "Yüzünü kaydet: macOS önce Touch ID ya da parolanı ister.",
    },
    "guard.cli.setup.verify": {
        "en": "Now one check, with the head-turn challenge.",
        "tr": "Şimdi baş çevirme sınamasıyla bir kontrol.",
    },
    "guard.cli.setup.verify_failed": {
        "en": "The check did not pass. The enrollment is kept and the guard is active; try "
        "`tau guard verify --explain`, enroll again with `tau guard enroll`, or turn it off with "
        "`tau guard forget`.",
        "tr": "Kontrol geçmedi. Kayıt duruyor ve koruma etkin; `tau guard verify --explain` dene, "
        "`tau guard enroll` ile yeniden kaydol ya da `tau guard forget` ile kapat.",
    },
    "guard.cli.setup.enabled": {
        "en": "Wrote [component.guard] enabled = true to {path}.",
        "tr": "{path} dosyasına [component.guard] enabled = true yazıldı.",
    },
    "guard.cli.setup.restart": {
        "en": "Restart the hub and any open tau chat, tau tui or tau Desktop window: one that "
        "started before now stays unguarded until its next start.",
        "tr": "Hub'ı ve açık tau chat, tau tui ya da tau Desktop pencerelerini yeniden başlat: "
        "bundan önce açılan bir pencere bir sonraki açılışına kadar korumasız kalır.",
    },
    "guard.cli.setup.hub_camera": {
        "en": "The enrollment used this terminal's camera permission. The app that runs the hub "
        "(TauBar, or the terminal running `tau hub run`) needs its own: macOS asks for it at the "
        "first unlock after the restart; allow it.",
        "tr": "Kayıt bu terminalin kamera iznini kullandı. Hub'ı çalıştıran uygulamanın (TauBar "
        "ya da `tau hub run` çalıştıran terminal) kendi iznine ihtiyacı var: macOS bunu yeniden "
        "başlatmadan sonraki ilk kilit açmada sorar; izin ver.",
    },
    "guard.cli.setup.remote": {
        "en": "While you are away from the Mac, remote tau tui and tau chat (over SSH or mosh) "
        "and tau ask stay locked.",
        "tr": "Mac'in başında değilken uzaktan tau tui ve tau chat (SSH ya da mosh üzerinden) ve "
        "tau ask kilitli kalır.",
    },
    "guard.cli.setup.done": {
        "en": "The face guard is set up.",
        "tr": "Yüz koruması kuruldu.",
    },
    # -- tau guard enroll ----------------------------------------------------------------------
    "guard.cli.enroll.start": {
        "en": "Follow the prompts: look at the camera, turn left, turn right, up, down. It takes "
        "about 15 seconds.",
        "tr": "Yönergeleri izle: kameraya bak, sola dön, sağa dön, yukarı, aşağı. Yaklaşık 15 "
        "saniye sürer.",
    },
    "guard.cli.enroll.local_auth": {
        "en": "Confirm in the macOS prompt: Touch ID, or your Mac password where the prompt "
        "offers it.",
        "tr": "macOS isteminde onayla: Touch ID ile ya da istem sunuyorsa Mac parolanla.",
    },
    # -- Touch ID refusals of enroll and forget (issue 114) -------------------------------------
    "guard.cli.touch_id.touch_id_failed": {
        "en": "Touch ID accepts only the fingerprints that were enrolled on this Mac when you "
        "set up the guard; `tau guard doctor` says whether they changed.",
        "tr": "Touch ID yalnızca korumayı kurduğunda bu Mac'te kayıtlı olan parmak izlerini "
        "kabul eder; değişip değişmediklerini `tau guard doctor` söyler.",
    },
    "guard.cli.touch_id.touch_id_unavailable": {
        "en": "This Mac has Touch ID, but it cannot be used now (the lid is closed, the Touch ID "
        "keyboard is not connected, or it is locked after failed tries). Open the lid or unlock "
        "the Mac with its password once, then try again.",
        "tr": "Bu Mac'te Touch ID var ama şu an kullanılamıyor (kapak kapalı, Touch ID klavyesi "
        "bağlı değil ya da başarısız denemelerden sonra kilitlendi). Kapağı aç ya da Mac'in "
        "kilidini bir kez parolayla aç, sonra yeniden dene.",
    },
    "guard.cli.enroll.add": {
        "en": "Adding samples under the current light to your face template.",
        "tr": "Yüz şablonuna şimdiki ışıkta örnekler ekleniyor.",
    },
    "guard.cli.enroll.done_first": {
        "en": "Your face is enrolled.",
        "tr": "Yüzün kaydedildi.",
    },
    "guard.cli.enroll.done_again": {
        "en": "Your face is enrolled again; the old template is replaced.",
        "tr": "Yüzün yeniden kaydedildi; eski şablonun yerini aldı.",
    },
    "guard.cli.enroll.done_add": {
        "en": "Samples added to your face template.",
        "tr": "Yüz şablonuna örnekler eklendi.",
    },
    "guard.cli.enroll.failed": {
        "en": "The enrollment did not finish: {reason}",
        "tr": "Kayıt tamamlanmadı: {reason}",
    },
    "guard.cli.enroll.reason.timeout": {
        "en": "tau needs ten good frames and a clear turn to each side. Try again in even light, "
        "about an arm's length from the camera.",
        "tr": "tau'nun on iyi kareye ve her iki yana belirgin bir dönüşe ihtiyacı var. Dengeli "
        "ışıkta, kameradan yaklaşık bir kol boyu uzakta yeniden dene.",
    },
    "guard.cli.enroll.reason.no_match": {
        "en": "the samples do not agree (another face in view, or uneven light). Try again with "
        "only you in view.",
        "tr": "örnekler birbiriyle uyuşmuyor (görüntüde başka bir yüz ya da dengesiz ışık). "
        "Görüntüde yalnızca sen varken yeniden dene.",
    },
    # -- tau guard verify ----------------------------------------------------------------------
    "guard.cli.verify.local": {
        "en": "Checking in a local worker; this unlocks nothing.",
        "tr": "Yerel bir işçide kontrol ediliyor; bu hiçbir şeyin kilidini açmaz.",
    },
    "guard.cli.verify.passed": {"en": "Verified.", "tr": "Doğrulandı."},
    "guard.cli.verify.passed_detail": {
        "en": "Verified ({liveness}), score {score}.",
        "tr": "Doğrulandı ({liveness}), puan {score}.",
    },
    "guard.cli.verify.failed": {"en": "Not verified: {reason}", "tr": "Doğrulanmadı: {reason}"},
    "guard.cli.verify.liveness.challenge": {
        "en": "head-turn challenge",
        "tr": "baş çevirme sınaması",
    },
    "guard.cli.verify.liveness.passive": {"en": "passive match", "tr": "pasif eşleşme"},
    "guard.cli.verify.explain_row": {
        "en": "{t}  {phase}  faces={faces} det={score} eyes={iod} light={brightness} "
        "sharp={sharpness} yaw={yaw} match={similarity}{hint}",
        "tr": "{t}  {phase}  yüz={faces} algı={score} göz={iod} ışık={brightness} "
        "netlik={sharpness} yaw={yaw} eşleşme={similarity}{hint}",
    },
    "guard.cli.verify.phase.look": {"en": "look     ", "tr": "bakış    "},
    "guard.cli.verify.phase.challenge": {"en": "challenge", "tr": "sınama   "},
    "guard.cli.verify.phase.after": {"en": "after    ", "tr": "sonra    "},
    "guard.cli.verify.nothing_saved": {
        "en": "No frame was saved.",
        "tr": "Hiçbir kare kaydedilmedi.",
    },
    # -- tau guard forget ----------------------------------------------------------------------
    "guard.cli.forget.start": {
        "en": "Removing your face template, the enrollment marker and the Keychain key. macOS "
        "asks for Touch ID or your password.",
        "tr": "Yüz şablonun, kayıt işareti ve Anahtar Zinciri anahtarı siliniyor. macOS Touch ID "
        "ya da parolanı ister.",
    },
    "guard.cli.forget.done": {
        "en": "Removed. The face guard is off.",
        "tr": "Silindi. Yüz koruması kapalı.",
    },
    "guard.cli.forget.nothing": {
        "en": "There was nothing to remove. The face guard is off.",
        "tr": "Silinecek bir şey yoktu. Yüz koruması kapalı.",
    },
    "guard.cli.forget.disabled": {
        "en": "Wrote [component.guard] enabled = false to {path}.",
        "tr": "{path} dosyasına [component.guard] enabled = false yazıldı.",
    },
    "guard.cli.forget.restart": {
        "en": "Restart the hub and any open tau chat, tau tui or tau Desktop window; until then "
        "they answer that no face is enrolled.",
        "tr": "Hub'ı ve açık tau chat, tau tui ya da tau Desktop pencerelerini yeniden başlat; o "
        "zamana kadar kayıtlı yüz olmadığını söylerler.",
    },
    "guard.cli.forget.failed": {
        "en": "Nothing was removed: {reason}",
        "tr": "Hiçbir şey silinmedi: {reason}",
    },
    "guard.cli.forget.key_left": {
        "en": "Your face template and the enrollment marker are removed and the face guard is "
        "off, but the Keychain did not let tau remove the key. Run `tau guard forget` again at "
        "the Mac (allow Keychain access if macOS asks) to remove it.",
        "tr": "Yüz şablonun ve kayıt işareti silindi, yüz koruması kapalı; ama Anahtar Zinciri "
        "anahtarın silinmesine izin vermedi. Silmek için `tau guard forget` komutunu Mac'in "
        "başında yeniden çalıştır (macOS sorarsa Anahtar Zinciri erişimine izin ver).",
    },
    # -- tau guard doctor ----------------------------------------------------------------------
    "guard.cli.doctor.platform_ok": {"en": "macOS", "tr": "macOS"},
    "guard.cli.doctor.platform_bad": {
        "en": "{platform}; the face guard works only on macOS",
        "tr": "{platform}; yüz koruması yalnızca macOS'ta çalışır",
    },
    "guard.cli.doctor.opencv_ok": {
        "en": "{version}; its camera order was checked for this series",
        "tr": "{version}; kamera sırası bu seri için denetlendi",
    },
    "guard.cli.doctor.opencv_unverified": {
        "en": "{version}; the camera order was checked for {verified} only",
        "tr": "{version}; kamera sırası yalnızca {verified} için denetlendi",
    },
    "guard.cli.doctor.model_ok": {
        "en": "{name}: sha256 {sha} matches",
        "tr": "{name}: sha256 {sha} eşleşiyor",
    },
    "guard.cli.doctor.model_changed": {
        "en": "made with the model {enrolled}, this tau expects {expected}; run `tau guard "
        "enroll` again",
        "tr": "{enrolled} modeliyle yapılmış, bu tau {expected} bekliyor; `tau guard enroll` "
        "komutunu yeniden çalıştır",
    },
    "guard.cli.doctor.model_missing": {
        "en": "{name}: not installed; run `tau guard setup`",
        "tr": "{name}: kurulu değil; `tau guard setup` çalıştır",
    },
    "guard.cli.doctor.model_mismatch": {
        "en": "{name}: the file does not match the pinned sha256 {sha}; run `tau guard setup` "
        "again",
        "tr": "{name}: dosya sabitlenmiş sha256 {sha} ile eşleşmiyor; `tau guard setup` "
        "komutunu yeniden çalıştır",
    },
    "guard.cli.doctor.enrolled": {
        "en": "{enrollment}, made {created}",
        "tr": "{enrollment}, oluşturma {created}",
    },
    "guard.cli.doctor.not_enrolled": {
        "en": "none; run `tau guard setup`",
        "tr": "yok; `tau guard setup` çalıştır",
    },
    "guard.cli.doctor.template_ok": {"en": "decrypts", "tr": "çözülebiliyor"},
    "guard.cli.doctor.keychain_ok": {"en": "readable", "tr": "okunabiliyor"},
    "guard.cli.doctor.keychain_missing": {"en": "no key", "tr": "anahtar yok"},
    "guard.cli.doctor.keychain_unavailable": {
        "en": "could not be read in time; if macOS asked for Keychain access (it does after a "
        "Python upgrade), run `tau guard doctor` at the Mac and allow it",
        "tr": "zamanında okunamadı; macOS Anahtar Zinciri erişimi sorduysa (Python "
        "güncellemesinden sonra sorar), `tau guard doctor` komutunu Mac'in başında çalıştır ve "
        "izin ver",
    },
    "guard.cli.doctor.keychain_invalid": {
        "en": "the item tau-guard / template-key-v1 is not a tau-guard key; `tau guard forget` "
        "removes it",
        "tr": "tau-guard / template-key-v1 öğesi bir tau-guard anahtarı değil; `tau guard "
        "forget` onu siler",
    },
    "guard.cli.doctor.modes": {
        "en": "unlock_liveness = {liveness}, step_up = {step_up}, unlock_fallback = {fallback}, "
        "thresholds {unlock} / {strict}",
        "tr": "unlock_liveness = {liveness}, step_up = {step_up}, unlock_fallback = {fallback}, "
        "eşikler {unlock} / {strict}",
    },
    "guard.cli.doctor.liveness_none": {
        "en": "unlock_liveness = none: a photo held up to the camera can unlock tau",
        "tr": "unlock_liveness = none: kameraya tutulan bir fotoğraf tau'nun kilidini açabilir",
    },
    "guard.cli.doctor.camera_ok": {
        "en": "{name}; {others} other camera(s) ignored",
        "tr": "{name}; {others} başka kamera yok sayıldı",
    },
    "guard.cli.doctor.camera_not_builtin": {
        "en": "{name} (camera = {camera}) is not the Mac's built-in camera; only the built-in "
        "camera keeps a virtual camera's injected frames out",
        "tr": "{name} (camera = {camera}) Mac'in yerleşik kamerası değil; sanal bir kameranın "
        "enjekte ettiği kareleri yalnızca yerleşik kamera dışarıda tutar",
    },
    "guard.cli.doctor.camera_missing": {
        "en": "no camera matches camera = {camera}",
        "tr": "camera = {camera} ile eşleşen kamera yok",
    },
    "guard.cli.doctor.permission": {
        "en": "{app}: {status}",
        "tr": "{app}: {status}",
    },
    "guard.cli.doctor.tcc.0": {"en": "not decided yet", "tr": "henüz karar verilmedi"},
    "guard.cli.doctor.tcc.1": {"en": "restricted", "tr": "kısıtlı"},
    "guard.cli.doctor.tcc.2": {"en": "denied", "tr": "reddedildi"},
    "guard.cli.doctor.tcc.3": {"en": "allowed", "tr": "izin verildi"},
    "guard.cli.doctor.tcc.unknown": {"en": "unknown", "tr": "bilinmiyor"},
    "guard.cli.doctor.hub_camera": {
        "en": "the hub runs under {app}; its last camera answer: {camera}",
        "tr": "hub {app} altında çalışıyor; son kamera yanıtı: {camera}",
    },
    "guard.cli.doctor.hub_none": {
        "en": "no hub runs; the app that starts it (TauBar, or the terminal running "
        "`tau hub run`) needs the camera permission",
        "tr": "çalışan hub yok; onu başlatan uygulamanın (TauBar ya da `tau hub run` çalıştıran "
        "terminal) kamera iznine ihtiyacı var",
    },
    "guard.cli.doctor.touch_id_ok": {
        "en": "available; re-enrollment, forget and the Touch ID fallback use it",
        "tr": "kullanılabilir; yeniden kayıt, silme ve Touch ID yedeği onu kullanır",
    },
    "guard.cli.doctor.touch_id_unavailable": {
        "en": "this Mac has Touch ID, but it cannot be used now: {why}",
        "tr": "bu Mac'te Touch ID var ama şu an kullanılamıyor: {why}",
    },
    "guard.cli.doctor.why.clamshell": {
        "en": "the lid is closed, so the built-in sensor is off",
        "tr": "kapak kapalı, bu yüzden yerleşik sensör kapalı",
    },
    "guard.cli.doctor.why.lockout": {
        "en": "it is locked after failed tries; unlock the Mac with its password once",
        "tr": "başarısız denemelerden sonra kilitlendi; Mac'in kilidini bir kez parolayla aç",
    },
    "guard.cli.doctor.why.disconnected": {
        "en": "the Touch ID keyboard is not connected",
        "tr": "Touch ID klavyesi bağlı değil",
    },
    "guard.cli.doctor.why.not_available": {
        "en": "macOS says it is not available",
        "tr": "macOS kullanılamadığını söylüyor",
    },
    "guard.cli.doctor.why.no_passcode": {
        "en": "the Mac has no login password",
        "tr": "Mac'in giriş parolası yok",
    },
    "guard.cli.doctor.why.error": {
        "en": "LocalAuthentication did not answer; worker.log has the details",
        "tr": "LocalAuthentication yanıt vermedi; ayrıntılar worker.log'da",
    },
    "guard.cli.doctor.touch_id_none": {
        "en": "this Mac has no Touch ID (or no enrolled finger); enrollment and forget use the "
        "Mac password",
        "tr": "bu Mac'te Touch ID yok (ya da kayıtlı parmak yok); kayıt ve silme Mac parolasını "
        "kullanır",
    },
    "guard.cli.doctor.touch_id_none_needed": {
        "en": "this Mac has no Touch ID (or no enrolled finger), but unlock_fallback or step_up "
        "asks for it; use unlock_fallback = touch_id_or_password or none, and step_up = face",
        "tr": "bu Mac'te Touch ID yok (ya da kayıtlı parmak yok) ama unlock_fallback ya da "
        "step_up onu istiyor; unlock_fallback = touch_id_or_password ya da none ve step_up = "
        "face kullan",
    },
    "guard.cli.doctor.touch_id_unknown": {
        "en": "could not be checked (the worker self-test did not say)",
        "tr": "denetlenemedi (işçinin öz sınaması bildirmedi)",
    },
    "guard.cli.doctor.clamshell_closed": {
        "en": "the lid is closed: the built-in camera and Touch ID are off; "
        "unlock_fallback = touch_id_or_password takes the Mac password then",
        "tr": "kapak kapalı: yerleşik kamera ve Touch ID kapalı; unlock_fallback = "
        "touch_id_or_password o zaman Mac parolasını kabul eder",
    },
    "guard.cli.doctor.clamshell_open": {"en": "the lid is open", "tr": "kapak açık"},
    "guard.cli.doctor.clamshell_unknown": {
        "en": "no lid, or its state cannot be read",
        "tr": "kapak yok ya da durumu okunamıyor",
    },
    "guard.cli.doctor.pin_ok": {
        "en": "the Touch ID fingerprints are the ones pinned at enrollment",
        "tr": "Touch ID parmak izleri kayıtta sabitlenenlerle aynı",
    },
    "guard.cli.doctor.pin_changed": {
        "en": "the Touch ID fingerprints changed since the enrollment (a finger was added or "
        "removed, or none is left), so Touch ID is refused for the fallback, the step-up, "
        "re-enrollment and forget, and the Mac password never replaces it. To start over, "
        "remove the template key (`security delete-generic-password -s tau-guard -a "
        "template-key-v1`), then run `tau guard setup` at the Mac.",
        "tr": "Touch ID parmak izleri kayıttan beri değişti (bir parmak eklendi ya da silindi "
        "ya da hiç kalmadı), bu yüzden Touch ID yedek, adım yükseltme, yeniden kayıt ve silme "
        "için reddedilir ve Mac parolası onun yerini tutmaz. Baştan başlamak için şablon "
        "anahtarını sil (`security delete-generic-password -s tau-guard -a template-key-v1`), "
        "sonra Mac'in başında `tau guard setup` çalıştır.",
    },
    "guard.cli.doctor.pin_unreadable": {
        "en": "the enrollment cannot be read, so Touch ID cannot compare the fingerprints it "
        "pinned, and re-enrollment and forget are refused. To start over, remove the template "
        "key (`security delete-generic-password -s tau-guard -a template-key-v1`), then run "
        "`tau guard setup` at the Mac.",
        "tr": "kayıt okunamıyor, bu yüzden Touch ID sabitlediği parmak izlerini "
        "karşılaştıramıyor; yeniden kayıt ve silme reddedilir. Baştan başlamak için şablon "
        "anahtarını sil (`security delete-generic-password -s tau-guard -a template-key-v1`), "
        "sonra Mac'in başında `tau guard setup` çalıştır.",
    },
    "guard.cli.doctor.pin_not_pinned": {
        "en": "the enrollment pinned no Touch ID fingerprints (set up without Touch ID, or "
        "before issue 114), so Touch ID only is refused; `tau guard enroll --add` with Touch ID "
        "available pins them",
        "tr": "kayıt Touch ID parmak izi sabitlemedi (Touch ID olmadan ya da 114'ten önce "
        "kuruldu), bu yüzden yalnızca Touch ID reddedilir; Touch ID kullanılabilirken `tau "
        "guard enroll --add` onları sabitler",
    },
    "guard.cli.doctor.pin_unknown": {
        "en": "cannot be compared now (no readable enrollment, or Touch ID is not available)",
        "tr": "şu an karşılaştırılamıyor (okunabilir kayıt yok ya da Touch ID kullanılamıyor)",
    },
    "guard.cli.doctor.step_up_none": {
        "en": "step_up = none: a tier-2 call on a guarded channel runs after the approval alone, "
        "with no fresh check (only for a client whose own tau.toml says step_up = none too; a "
        "client that leaves step_up out uses face)",
        "tr": "step_up = none: korunan bir kanalda 2. katman bir çağrı yalnızca onayla, taze "
        "kontrol olmadan çalışır (yalnızca kendi tau.toml'u da step_up = none diyen bir istemci "
        "için; step_up yazmayan bir istemci face kullanır)",
    },
    "guard.cli.doctor.failures": {
        "en": "{count} in the last 24 h",
        "tr": "son 24 saatte {count}",
    },
    "guard.cli.doctor.selftest_failed": {
        "en": "the worker self-test did not run: {error}",
        "tr": "işçinin öz sınaması çalışmadı: {error}",
    },
}

WINDOW_MESSAGES: dict[str, dict[str, str]] = {
    # -- the guard window (issue 126): uppercase HUD lines, written out in each language
    # (Python's upper() turns a Turkish "i" into "I", not "İ") ---------------------------------
    "guard.window.purpose.unlock": {"en": "UNLOCK", "tr": "KİLİT AÇMA"},
    "guard.window.purpose.recheck": {"en": "PRESENCE CHECK", "tr": "VARLIK KONTROLÜ"},
    "guard.window.purpose.step_up": {"en": "STEP-UP · {tool}", "tr": "EK DOĞRULAMA · {tool}"},
    "guard.window.purpose.enroll": {"en": "ENROLLMENT", "tr": "YÜZ KAYDI"},
    "guard.window.purpose.check": {"en": "FACE CHECK", "tr": "YÜZ KONTROLÜ"},
    "guard.window.step.starting": {"en": "STARTING CAMERA", "tr": "KAMERA AÇILIYOR"},
    "guard.window.step.look": {"en": "LOOK AT THE CAMERA", "tr": "KAMERAYA BAK"},
    "guard.window.step.turn_left": {"en": "TURN LEFT", "tr": "SOLA ÇEVİR"},
    "guard.window.step.turn_right": {"en": "TURN RIGHT", "tr": "SAĞA ÇEVİR"},
    "guard.window.step.center": {"en": "BACK TO CENTER", "tr": "ORTAYA DÖN"},
    "guard.window.step.touch_id": {"en": "TOUCH THE SENSOR", "tr": "SENSÖRE DOKUN"},
    "guard.window.step.look_up": {"en": "TILT UP", "tr": "YUKARI KALDIR"},
    "guard.window.step.look_down": {"en": "TILT DOWN", "tr": "AŞAĞI İNDİR"},
    "guard.window.step.turn_more": {"en": "TURN FURTHER", "tr": "BİRAZ DAHA ÇEVİR"},
    "guard.window.hint.too_dark": {
        "en": "TOO DARK · FIND MORE LIGHT",
        "tr": "ÇOK KARANLIK · IŞIĞI ARTIR",
    },
    "guard.window.hint.face_too_small": {"en": "MOVE CLOSER", "tr": "YAKLAŞ"},
    "guard.window.hint.multiple_faces": {"en": "ONE FACE ONLY", "tr": "YALNIZCA BİR YÜZ"},
    "guard.window.hint.no_face": {"en": "NO FACE IN VIEW", "tr": "YÜZ GÖRÜNMÜYOR"},
    "guard.window.samples": {"en": "{count}/{needed} SAMPLES", "tr": "{count}/{needed} ÖRNEK"},
    "guard.window.touch_id": {
        "en": "CONFIRM IN THE MACOS PROMPT",
        "tr": "MACOS PENCERESİNDE ONAYLA",
    },
    "guard.window.result.unlock": {"en": "UNLOCKED", "tr": "KİLİT AÇILDI"},
    "guard.window.result.recheck": {"en": "PRESENCE CONFIRMED", "tr": "VARLIK DOĞRULANDI"},
    "guard.window.result.step_up": {"en": "CONFIRMED", "tr": "ONAYLANDI"},
    "guard.window.result.enroll": {"en": "ENROLLED", "tr": "KAYDEDİLDİ"},
    "guard.window.result.check": {"en": "VERIFIED", "tr": "DOĞRULANDI"},
    "guard.window.result.failed": {"en": "NOT VERIFIED", "tr": "DOĞRULANAMADI"},
    "guard.window.result.enroll_failed": {"en": "ENROLLMENT FAILED", "tr": "KAYIT BAŞARISIZ"},
    "guard.window.cancel": {"en": "ESC · CANCEL", "tr": "ESC · İPTAL"},
    "guard.window.privacy": {
        "en": "MIRROR VIEW · NOTHING IS SAVED",
        "tr": "AYNA GÖRÜNTÜSÜ · HİÇBİR ŞEY KAYDEDİLMEZ",
    },
    # -- tau guard window, --no-window -------------------------------------------------------
    "guard.cli.window.state": {"en": "Guard window: {state}", "tr": "Koruma penceresi: {state}"},
    "guard.cli.window.on": {"en": "on", "tr": "açık"},
    "guard.cli.window.off": {
        "en": "off ([component.guard] window = false)",
        "tr": "kapalı ([component.guard] window = false)",
    },
    "guard.cli.window.headless": {
        "en": "  Checks started from here run without it: {why}",
        "tr": "  Buradan başlayan kontroller pencere olmadan çalışır: {why}",
    },
    "guard.cli.window.why.ssh": {
        "en": "this session came in over SSH",
        "tr": "bu oturum SSH üzerinden açıldı",
    },
    "guard.cli.window.why.platform": {
        "en": "the window works only on macOS",
        "tr": "pencere yalnızca macOS'ta çalışır",
    },
    "guard.cli.window.why.disabled": {
        "en": "TAU_GUARD_WINDOW=0 is set",
        "tr": "TAU_GUARD_WINDOW=0 ayarlı",
    },
    "guard.cli.window.why.no_gui_session": {
        "en": "there is no GUI session (no window server)",
        "tr": "grafik oturum yok (pencere sunucusu yok)",
    },
    "guard.cli.window.why.pyobjc_missing": {
        "en": "pyobjc's AppKit cannot be imported",
        "tr": "pyobjc'nin AppKit modülü içe aktarılamıyor",
    },
    "guard.cli.window.hub": {
        "en": "  The hub's checks follow the hub's own tau.toml and session.",
        "tr": "  Hub'ın kontrolleri hub'ın kendi tau.toml'unu ve oturumunu izler.",
    },
    "guard.cli.window.demo_hint": {
        "en": "Run `tau guard window --demo` to see it without the camera.",
        "tr": "Kamera olmadan görmek için `tau guard window --demo` çalıştır.",
    },
    "guard.cli.window.demo_start": {
        "en": "Playing a scripted check in the guard window (no camera; Esc closes it)…",
        "tr": "Koruma penceresinde senaryolu bir kontrol oynatılıyor (kamera yok; Esc kapatır)…",
    },
    "guard.cli.window.demo_failed": {
        "en": "The guard window did not open: {why}",
        "tr": "Koruma penceresi açılmadı: {why}",
    },
    "guard.cli.window.demo_saved": {
        "en": "Snapshots written to {path}",
        "tr": "Anlık görüntüler {path} içine yazıldı",
    },
    "guard.cli.window.through_hub": {
        "en": "  --no-window applies to checks this command runs itself; this one runs in the hub, "
        "whose [component.guard] window decides.",
        "tr": "  --no-window yalnızca bu komutun kendi çalıştırdığı kontrollere uygulanır; bu "
        "kontrol hub'da çalışıyor ve orada [component.guard] window karar verir.",
    },
}

_collisions = (set(CLI_MESSAGES) | set(WINDOW_MESSAGES)) & set(MESSAGES)
assert not _collisions, f"tau-guard message keys collide with tau-core: {sorted(_collisions)}"
assert not set(CLI_MESSAGES) & set(WINDOW_MESSAGES)

register_messages(CLI_MESSAGES)
register_messages(WINDOW_MESSAGES)
