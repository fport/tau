<!-- tr twin of reference/guard.md, translated 2026-09-30 -->

# Sahip koruması referansı

Sahip korumasının okuduğu, yazdığı ve yanıtladığı her şey: `[component.guard]` anahtarları, `tau guard` komutları, durumlar ve nedenler, imzalı istek şemasıyla `/guard/*` route'ları, denetim kaydı ve `TAU_DATA_DIR/guard/` altındaki dosyalar. Kurulum ve günlük kullanım [koruma rehberinde](../guides/guard.md); karar [ADR 0008](../adr/0008-owner-guard.md).

Kod nerede:

- **`tau_core.guard`** (tau-core) `Guard` protokolüne, değer tiplerine, neden listelerine, `HubGuard`'a (kanalların hub istemcisi), `LockedGuard`'a ve `resolve_guard`'a sahiptir. Hiçbir kanal süreci OpenCV ya da pyobjc içe aktarmaz.
- **`tau_guard`** (`tau-guard` dağıtımı) `guard` hub servisi (`tau.hub_services`), `python -m tau_guard.worker` worker'ı ve `tau guard` komutudur (`tau.commands`).

## Koruma ne zaman etkindir { #when-the-guard-is-active }

| Koşul | Sonuç |
|---|---|
| `TAU_DATA_DIR/guard/enrolled` işareti yok ve `[component.guard] enabled` `true` değil | **kapalı**: koruma yok, hiçbir şey kilitlenmez; `/status` `guard: {state: "off"}` bildirir |
| işaret var **ya da** `enabled = true` | **etkin**: korunan kanallar sahibin Mac'in başında doğrulanmasını ister |
| macOS dışında bir platformda etkin | kalıcı olarak kilitli, neden `unsupported_platform` |
| `enabled` bool değil ya da `[component.guard]` bilinmeyen bir anahtar içeriyor | kalıcı olarak kilitli (`tau doctor` sorunu söyler); `enable = true` gibi bir yazım hatası asla "kapalı" demek değildir |
| `enabled = true` ama kayıt yok | kilitli, neden `not_enrolled` |
| bilinen bir anahtar aralık dışında ya da yanlış tipte | `unavailable`, neden `config`, her sorun hub log'unda; asla daha zayıf bir değere düşülmez |

İşaret durduğu sürece `enabled = false` yok sayılır ve `tau doctor` bunu söyler. Tek kapatma yolu `tau guard forget`'tir.

## `[component.guard]`

Her anahtar isteğe bağlıdır.

```toml
[component.guard]
enabled = true                         # or the enrollment marker
max_unlock_hours = 8
idle_lock_minutes = 10
recheck_after_idle_minutes = 3
presence_recheck_minutes = 30
verify_timeout_seconds = 15
unlock_threshold = 0.50
step_up_threshold = 0.55
step_up_challenge_fresh_seconds = 120
unlock_liveness = "challenge"
step_up = "face"
unlock_fallback = "touch_id"
camera = "builtin"
```

| Anahtar | Varsayılan | Aralık ya da değerler | Anlamı |
|---|---|---|---|
| `enabled` | `false` | bool | korumayı kayıt olmadan açar; `tau guard setup` `true`, `tau guard forget` `false` yazar |
| `max_unlock_hours` | `8` | 1–24 | UTC duvar saatine göre en uzun açık kalma süresi (tetikleyici `max_age`) |
| `idle_lock_minutes` | `10` | 1–240 | kilitleyen HID boşta kalma süresi (tetikleyici `idle`); ekran durumu bilinmezken açık kalma süresinin de üst sınırı |
| `recheck_after_idle_minutes` | `3` | 1–240 | son yüz eşleşmesinden bu yana boşta kalma; aşılınca kabul bir varlık yeniden kontrolü ister |
| `presence_recheck_minutes` | `30` | 1–1440 | son yüz eşleşmesinin yaşı; aşılınca kabul bir varlık yeniden kontrolü ister |
| `verify_timeout_seconds` | `15` | 5–60 | önden eşleşmenin sınırı; bu ne derse desin kamera en fazla 20 sn açık kalır |
| `unlock_threshold` | `0.50` | 0.45–0.95 | kilit açmak için bir karenin ihtiyaç duyduğu kosinüs benzerliği |
| `step_up_threshold` | `0.55` | 0.45–0.95 | step-up'lar ve varlık yeniden kontrolleri için aynısı |
| `step_up_challenge_fresh_seconds` | `120` | 0–600 | baş çevirme sınamasını geçen bir kontrolden sonraki bu süre içinde step-up pasif, katı bir eşleşmedir |
| `unlock_liveness` | `"challenge"` | `challenge`, `none` | `none` kilit açmadan baş çevirmeleri kaldırır; doctor uyarır, çünkü o zaman bir fotoğraf kilidi açabilir |
| `step_up` | `"face"` | `face`, `face_or_touch_id`, `touch_id`, `none` | tier-2 step-up'ın ne istediği; Touch ID issue 114'e kadar `touch_id_unavailable` yanıtını verir, bu yüzden `touch_id` o zamana kadar her step-up'ı başarısız kılar |
| `unlock_fallback` | `"touch_id"` | `touch_id`, `touch_id_or_password`, `none` | iki yüz başarısızlığından ya da bir `camera_*` kararından sonra sunulur (issue 114) |
| `camera` | `"builtin"` | `builtin` ya da bir kameranın AVFoundation uniqueID'si | `builtin`, `bltn` taşımasındaki `AVCaptureDeviceTypeBuiltInWideAngleCamera` tipindeki aygıtı seçer; bir id başka bir şeyi gösteriyorsa doctor uyarır |

Bir istemci her kontrolde kendi `step_up` ve `unlock_liveness` değerlerini gönderir; hub kendi değeriyle istemcininkinden daha katı olanı uygular (en katıdan başlayarak: `face` ya da `touch_id`, sonra `face_or_touch_id`, sonra `none`; `challenge`, `none`'dan önce).

## `tau guard`

| Komut | Ne yapar | Nerede çalışır |
|---|---|---|
| `tau guard setup [--model-file FILE]` | SFace'i kurar (sha256 ile sabitlenmiş indirme ya da `FILE`), kaydeder, bir kontrol çalıştırır, `[component.guard] enabled = true` yazar | yalnızca Mac'in başında (macOS, `SSH_CONNECTION` yok); korumalı bir hub çalışıyorsa hub üzerinden, yoksa yerel bir worker'da |
| `tau guard enroll [--add]` | Touch ID ya da Mac parolasının arkasında yeniden kaydeder; `--add` şablona örnekler ekler (başka ışık) | yalnızca Mac'in başında |
| `tau guard verify [--explain[=all]]` | baş çevirme sınamasıyla tek kontrol; `--explain` onu yerel bir worker'da çalıştırır, her istemi vurgulu bir satır olarak (`>>> TURN YOUR HEAD LEFT <<<`) ve her üç kareden birinin sayılarını yazar (`=all`: her kare): ekrandaki istem, baş yaw'ı, önden taban çizgisine göre dönüş ve eğim (derece), landmark'ların uyum hatası, göz mesafesi, dedektör puanı, parlaklık, netlik, benzerlik. Hiçbir kare kaydedilmez. Sınamayı geçemeyen yerel bir kontrol, geçilemeyen canlılık kuralını söyler. Başarısızsa 1 ile çıkar | macOS (başka yerde 2 ile çıkar); korumalı bir hub çalışıyorsa hub üzerinden, böylece geçen kontrol tau'nun kilidini açar, yoksa yerel bir worker'da |
| `tau guard forget` | Touch ID ya da Mac parolasının arkasında şablonu, işareti ve Keychain anahtarını siler ve `enabled = false` yazar; Keychain anahtarı tuttuysa 1 ile çıkar (yeniden çalıştır) | yalnızca Mac'in başında, her zaman yerel bir worker'da |
| `tau guard doctor` | platformu, worker'ı, OpenCV'yi, YuNet ve SFace dosyalarını, kaydı, şablonu, baş çevirme kalibrasyonunu (derece olarak ölçülmüş mü, yoksa derecelerden önceki bir kaydın varsayılanı mı), Keychain'i, modları, canlılığı, kamerayı, terminalin kamera iznini, başarısızlıkları ve hub'ın kamera iznini tutan uygulamayı denetler; `fail` varsa 1 ile çıkar | her yerde |
| `tau guard status [--json]` | çalışan hub'ın bildirdiği durum (`GET /guard/status`); etkin koruma yoksa `off` yazar; hub çalışmıyorsa 0, hub hatasında 1 ile çıkar | her yerde |
| `tau guard lock` | korunan her kanalı kilitler (`POST /guard/lock`, tetikleyici `command`) | her yerde; SSH üzerinden de |
| `tau guard log [--since WHEN] [--json]` | denetim kaydı; `WHEN` bir süre (`30m`, `2h`, `7d`) ya da ISO tarih veya saattir | her yerde |

`setup` ya da `forget` sonrasında hub'ı ve açık her `tau chat`, `tau tui` ya da tau Desktop penceresini yeniden başlat. `--help` metinleri [CLI referansında](cli.md#tau-guard).

## Durumlar { #states }

| Durum | Anlamı |
|---|---|
| `off` | etkin koruma yok |
| `locked` | korunan kanallar her turu reddeder; nedenini `lock_trigger` söyler |
| `verifying` | bir kilit açma sürüyor; eşzamanlı kilit açmalar ona katılır (aynı deneme, aynı karar) |
| `unlocked` | kabul edilir; `since`, `expires_at`, `face_seen_at` ve `method` ayarlıdır |
| `unavailable` | koruma karar veremiyor (hub yok, bozuk yapılandırma, duran refleks döngüsü); `locked` gibi reddeder |

Durumun yanında hub şunları tutar: `step_up_active`, `failures` (son kilit açmadan bu yana sayılan başarısızlıklar), `cooldown_until`, `seq` (her değişiklikte büyür), `face_seen_at`, son yüzden bu yana HID boşta kalma süresi, `screen` (`locked`, `unlocked` ya da `unknown`) ve `camera` (`ok`, `denied`, `not_determined`, `unavailable`).

### Kilit tetikleyicileri { #lock-triggers }

`command`, `idle`, `screen_lock`, `sleep` (iki tik arasında duvar saati ile monoton saat arasında 30 sn'den fazla kayma), `max_age`, `hub_stop`, `telegram`, `step_up_failed`, `startup`.

Refleks denetimleri (azami süre, uyku, boşta kalma, ekran kilidi) her kabulde ve her step-up'ta satır içinde ve her 2 sn'de bir döngüde çalışır. Döngünün son tiki 6 sn'den eskiyse kabul `unavailable` ile reddeder. Ne model, ne bulut, ne mesh gerektirirler. Her kilit süren bir denemeyi iptal eder ve kamerayı bırakır; korunan kanallarda süren turu da iptal eder ve bekleyen bir onayı reddeder.

### Geçişler { #transitions }

| Olay | Nereden | Nereye / etkisi |
|---|---|---|
| hub başlangıcı | – | `locked` (tetikleyici `startup`) |
| kilit açma isteği | `locked`, `unlocked` | `verifying` |
| kilit açma başarılı | `verifying` | `unlocked`; `face_seen_at` = şimdi; başarısızlıklar kanal onları bildirdikten sonra sıfırlanır |
| kilit açma başarısız | `verifying` | önceki durum; sayılan bir neden başarısızlık sayacını ilerletir |
| step-up isteği | `unlocked` | `step_up_active` ile `unlocked` kalır; süren bir kontrolün arkasında bekler |
| step-up isteği | `locked` ya da `locked`'dan süren bir kilit açma | reddedilir (`locked`); kamera asla açılmaz |
| step-up başarılı | – | `face_seen_at` = şimdi; `since` ve `expires_at` değişmez |
| `no_match`, `spoof` ya da `multiple_faces` ile başarısız step-up ya da yeniden kontrol | `unlocked` | `locked` (tetikleyici `step_up_failed`) |
| yeniden kontrol başarılı | `unlocked` | `face_seen_at` = şimdi; son yüzden bu yana boşta kalma = 0 |
| herhangi bir kilit tetikleyicisi | herhangi | `locked`; süren bir deneme `cancelled` olarak, bir baş çevirme istemi ekrandaysa `spoof` olarak biter |

### Başarısızlıklar ve bekleme süresi { #failures-and-cooldown }

`no_match`, `spoof` ve `multiple_faces` kilit açma, yeniden kontrol ve step-up için aynı şekilde sayılan başarısızlıklardır. 10 dakika içinde üçü 30 sn'lik bir bekleme süresi başlatır; sonraki her sayılan başarısızlık onu ikiye katlar, en fazla 15 dakikaya kadar. Bir eşleşme ya da 10 sessiz dakika katlamayı sıfırlar. Bekleme süresinde bir kontrol `retry_after` (saniye) ile `cooldown` yanıtını verir. Sayım ve bekleme süresi hub yeniden başlasa da korunur (`failures.json`).

## Nedenler { #reasons }

### Kabul (`POST /guard/admit`, `Admission.reason`)

| Neden | Anlamı |
|---|---|
| `ok` | kabul edildi |
| `locked` | reddedildi: koruma kilitli |
| `recheck` | pasif bir varlık kontrolünden sonra kabul: kanal `unlock(kind="recheck")` çalıştırır ve saklanan istemi yeniden gönderir |
| `not_enrolled` | etkin ama kayıt yok |
| `cooldown` | bekleme süresinde reddedildi |
| `unavailable` | koruma karar veremiyor (hub yok, kötü yanıt, eskimiş refleks döngüsü, 3 sn zaman aşımı) |
| `unsupported_platform` | macOS değil |
| `error` | bilinmeyen bir değer dahil başka her şey |

Reddedilen bir tur bir bildirim ve `TurnEnd("locked")` üretir: geçmişe hiçbir şey eklenmez, hiçbir model çağrılmaz, onarım turu gelmez. `TauAgent.ask()` `GuardLocked(reason)` yükseltir.

### Kararlar (`GuardVerdict.reason`, bir denemenin `reason`'ı)

| Neden | Anlamı | Sayılır |
|---|---|---|
| `match` | doğrulandı; `method` `face` (ya da issue 114 ile `touch_id`) | – |
| `no_match` | kaliteli bir kare şablonla eşleşmedi | evet |
| `no_face` | hiç yüz görülmedi | hayır |
| `multiple_faces` | sayılacak kadar büyük ikinci bir yüz | evet |
| `spoof` | baş çevirme sınaması başarısız; denetim kaydındaki `liveness` kuralı söyler (aşağıya bak) | evet |
| `timeout` | kontrolün süresi doldu | hayır |
| `cancelled` | çağıran ya da bir kilit tarafından iptal edildi | hayır |
| `too_dark`, `face_too_small` | kareler kalite eşiklerini hiç geçmedi (canlı ipuçları olarak da) | hayır |
| `camera_busy`, `camera_unavailable` | kamerayı başka bir uygulama tutuyor ya da tek bir yerleşik kamera bulunamadı | hayır |
| `camera_denied`, `permission_pending` | hub'ı çalıştıran uygulamanın kamera izni yok ya da macOS istemi hâlâ açık | hayır |
| `not_enrolled`, `template_invalid`, `model_changed` | şablon yok, okunamıyor (ya da kayıt id'si işaretinkiyle aynı değil), yüz modeli değişti | hayır |
| `key_unavailable` | Keychain anahtarı okunamadı | hayır |
| `cooldown` | bekleme süresinde reddedildi; `retry_after` ayarlı | – |
| `locked` | kilitliyken bir step-up | – |
| `touch_id_unavailable`, `touch_id_failed` | Touch ID yok (kapalı kapak, sensör yok, 114'e kadar) ya da doğrulamadı | hayır |
| `unsupported_platform`, `unavailable`, `busy`, `error` | macOS değil; hub yok ya da kötü yanıt; başka bir kontrol sürüyor; başka her şey | hayır |

### Baş çevirme sınaması { #head-turn-challenge }

Başın yaw'ı `cv2.solvePnP`'den gelir: YuNet'in beş landmark'ı, odak uzaklığı kare genişliğine eşit bir kameranın gördüğü genel bir 3B başa oturtulur. Her şey denemenin önden karelerinin medyan yaw'ına göre derece cinsindendir; bu yüzden biraz yanda oturmak da çalışır.

| | |
|---|---|
| adımlar | kilit açma için 2, step-up için 3; rastgele sol ya da sağ |
| her istemden önceki duraklama | rastgele 0,3–0,9 sn |
| adım başına süre | istemden itibaren 4 sn |
| dönüş | istenen yöne en az `max(12°, 0,5 × kalibre edilmiş dönüş)` |
| tutma | rastgele 0,3–0,6 sn; tutulurken dönüş 3° sarkabilir |
| geri dönüş | önden yaw'ın 6° yakınına ya da onun ötesine |
| sayılan kareler | landmark'lar başa 0,10 göz mesafesi içinde uyar (önden uyum daha büyükse onun 1,5 katı); 3 karelik kayan medyan |

Kayıt, sola dönüşün işaretini ve sahibin her iki yana aralığını kalibre eder. Derecelerden önce (issue 127) yapılmış bir kayıt çalışmaya devam eder: işareti kalır ve her yöne 12°'lik bir dönüş istenir; `tau guard enroll` sahibin kendi aralığını ölçer.

### Canlılık kuralları (`spoof`'un `liveness`'i) { #liveness-rules }

| Kural | Ne zaman |
|---|---|
| `overshoot_before_target` | dönüş tutulmadan önce ters yöne 8° ya da daha fazla |
| `oscillation` | tek adımda 3'ten fazla yön değişimi (her biri 6°) |
| `moved_between_prompts` | ekranda istem yokken önden yaw'dan 10°'den fazla (bir geri dönüş salınımının öbür yanında 20°) |
| `no_turn` | dönüş zamanında hedefine ulaşmadı |
| `too_slow` | dönüş hedefine ulaştı ama zamanında tutulmadı |
| `no_return` | baş zamanında geri dönmedi |
| `face_lost` | yüz 0,2 sn'den uzun kayboldu ya da kutusu sıçradı |
| `step_identity` | bir dönüşün çevresinde merkeze yakın kareler sahiple eşleşmedi |
| `abandoned` | bir baş çevirme istemi ekrandayken iptal edildi ya da kilitlendi |

Dikey eksen etrafında döndürülen düz bir fotoğraf 50°'ye kadar döndürülürken en fazla yaklaşık 10° okunur (boyutlar, oturuş yerleri ve 15°'lik bir eğim boyunca; kameraya tam karşıdan bakarken birkaç derece) ve daha fazla döndürülünce landmark'ları bir başa uymaz olur. Bir baş açının tamamını okur.

### İlerleme adımları { #progress-steps }

`starting`, `look`, `turn_left`, `turn_right`, `center`, `touch_id`, `done`, kayıt için de `look_up`, `look_down`, `turn_more`. Bir ilerleme olayı `step`, `seq`, `deadline` (UTC, adımın zaman aşımına uğradığı an) ve `hint` (canlı ipucu olarak kullanılan bir karar nedeni, örneğin `too_dark`) taşır.

## Kanallar { #channels }

| | Korunan: kabul ve step-up | Başka yolla tanınan: `guard=None` |
|---|---|---|
| **Güvenilen** (tier 2 onaylayabilir) | TUI (yerel, SSH ya da mosh, tau Desktop, bir web sekmesi), `tau chat` | Telegram (chat-id izin listesi, doğrudan yoklanır) |
| **Güvenilmeyen** (asla onaylamaz) | `tau ask`, ses (ileride) | ağ turları (`net`: araç yok, onaylar reddedilir) |

Varsayılan `build_agent(guard=DISCOVER)`'dır: hiçbir şey geçmeyen bir çağıran, bir koruma etkinse korunur; bu yüzden bilinmeyen ve gelecekteki kanallar (MCP sunucusu, devreden turun koruması altında `ask_sub` ile çalışan sub-tau'lar) korunan sütuna düşer. Yalnızca `TelegramService` ve tau-net'in ağ turları `guard=None` geçer; `packages/*/src` içindeki başka her `guard=None` bir repo kuralı testini başarısız kılar. Hiçbir bayrak, değişken ya da yapılandırma anahtarı bir kanal seçmez.

Kilitliyken yalnızca `/help`, `/lang`, `/guard` ve `/quit` çalışır (`ALLOWED_WHILE_LOCKED`).

## Tier kapısı { #the-tier-gate }

`TierGate(guard=…, client_id=…)`; `packages/*/src` içindeki her `TierGate(` çağrısı `guard=`'ı açıkça geçmek zorundadır.

- **Tier-1 ya da tier-2 bir çağrıdan önce** kabul yeniden çalışır. Bir ret çağrıyı onaylayıcıya sormadan reddeder; model `tau was locked before the user answered.` okur ve `tool_call` olayı onay olarak `locked` kaydeder.
- **Tier-2 bir çağrıda `APPROVED` sonrasında** kabul bir kez daha çalışır (pencere açıkken gelen bir kilit çağrıyı aynı şekilde reddeder), sonra `step_up`. İlerlemesi `guard` ajan olaylarına dönüşür (`{"action": "challenge", "step", "hint", "deadline", "request_id"}`). `True` dışındaki her şey kararı `REJECTED`'e çevirir; model `The guard could not confirm the user's identity.` okur ve `approval` olayı `step_up: passed | failed` kaydeder.
- **Muaf çağrılar** (rutinler) iki denetime de ulaşmaz.

Hiçbir yol korumadan `APPROVED` üretmez.

## Kontrol route'ları { #control-routes }

Hub'ın kontrol API'si yalnızca `127.0.0.1:<control_port>` adresini dinler. **Yalnızca `GET /health` ve `GET /status` açıktır.** Diğer her route korumalıdır: `GET /spend`, altı `/guard/*` route'u ve bir hub servisinin eklediği her route (`ControlApi.add_route(..., open=False)` varsayılandır).

### İmzalı istekler { #signed-requests }

Hub her başlangıçta `TAU_DATA_DIR/hub/control.token` dosyasına yeni bir token yazar (32 rastgele bayt, urlsafe, mod `0600`, `0700` bir dizinde) ve temiz bir durdurmada onu siler. Token asla yolculuk etmez:

| Başlık | Değer |
|---|---|
| `X-Tau-Nonce` | her istekte yeni, en fazla 128 karakter |
| `X-Tau-Auth` | `hex(HMAC-SHA256(token, "req" \| nonce \| METHOD \| path))` |
| `X-Tau-Proof` (yanıt) | `hex(HMAC-SHA256(token, "resp" \| nonce \| METHOD \| path \| status \| body))` |

Alanlar düz bir `|` baytıyla birleştirilir, yöntem büyük harftir ve yolda sorgu dizesi yoktur. `req` ve `resp` alanları, bir isteğin auth değerinin kanıt olarak geçmesini engeller.

Hub korumalı bir isteği şu durumlarda 403 JSON ile reddeder: token dosyası yok, boş ya da artık bu hub'ın token'ını tutmuyor; nonce ya da `X-Tau-Auth` eksik ya da yanlış (bir başlıkta ham token asla kabul edilmez); herhangi bir `Origin` başlığı var; bir POST'un medya tipi `application/json` değil. İstemci `X-Tau-Proof`'u denetlemek zorundadır: sert bir hub çıkışından sonra herhangi bir yerel süreç boş portu tutabilir ve gerçek hub'ı bir işgalciden yalnızca kanıt ayırır.

`tau_core.hub.HubClient` bunların hepsini yapar: yalnızca loopback, proxy yok, yönlendirme yok, token her istekte ve bir 403'ten sonra bir kez daha okunur, kanıt denetlenir:

```sh
uv run python -c 'from tau_core import Config; from tau_core.hub import HubClient; print(HubClient(Config.load()).get("/spend", timeout=5))'
```

Açık `/status` yalnızca `guard: {state, enrolled, available, reason}` taşır; diğer yerel hesaplara sahibin ne zaman ayrıldığını söyleyecek zaman damgaları yoktur.

### `/guard/*` { #guard }

Bir route hub'dan yalnızca bakmasını isteyebilir. Hiçbir route bir karar, bir puan, bir görüntü ya da bir embedding kabul etmez. `channel` alanları denetim etiketidir ve politikayı asla değiştirmez. Route'lar yalnızca koruma etkinken vardır; aksi hâlde 404 yanıtını verirler.

| Route | Gövde ya da sorgu | Yanıt |
|---|---|---|
| `GET /guard/status` | `?since=<seq>&wait=<0..25>[&attempt=<id>]` (long poll) | her `GuardStatus` alanı, artı `enrollment`, `screen`, `step_up_active` ve `attempt` |
| `POST /guard/admit` | `{channel, session_id, client_id}` | `{allowed, reason, enrollment, state}`; refleks denetimleri satır içinde değerlendirilir |
| `POST /guard/verify` | `{channel, client_id, kind: "unlock" \| "recheck" \| "step_up", request_id?, tool?, policy?}` | `202 {attempt, seq}` (süren bir kilit açmaya katılır); `409 {reason}` (`locked`, `busy`, `not_enrolled`, `unavailable`) ya da `429 {reason: "cooldown", retry_after}` ile reddedilir |
| `POST /guard/cancel` | `{client_id, attempt?}` | `{ok}` |
| `POST /guard/lock` | `{channel, client_id, trigger}` | `{state: "locked"}`, idempotent |
| `POST /guard/enroll` | `{client_id, add?}` | `202 {attempt, seq}`; önce LocalAuthentication |

Bilinmeyen bir anahtar, eksik bir zorunlu anahtar ya da yanlış bir tip içeren gövde `400 {reason: "error", error}` alır.

Bir **deneme** `{id, kind, step, seq, deadline, hint, done, ok, reason, method, retry_after}` biçimindedir. `attempt=<id>` ile `GET /guard/status` o denemenin kaydını kuyrukta, sürmekte ya da bitmiş olsun döndürür; id bilinmiyor ya da süresi dolmuşsa `null`. Bitmiş bir kayıt en az 60 sn tutulur. Yalnızca `ok: true`, `reason: "match"`, bir `method`, `state: "unlocked"` ve yerel işaretin `enrollment` id'sine sahip bitmiş bir deneme başarıdır; `HubGuard` eksik bir kanıt dahil diğer her şeyi kilitli sayar.

## Denetim kaydı { #audit-log }

`TAU_DATA_DIR/guard/audit.jsonl`, satır başına bir JSON nesnesi, mod `0600`, 1 MiB'de döndürülür, 3 dosya tutulur (`audit.jsonl`, `.1`, `.2`). `tau guard log` onu okur.

```json
{"v": 1, "at": "2026-09-30T08:12:03+00:00", "event": "verify", "channel": "tui", "client_id": "3f9a1c0b7e2d4a61", "trigger": null, "ok": true, "reason": "match", "score": 0.71, "liveness": "challenge", "duration_ms": 2380}
```

| Anahtar | Her zaman | Anlamı |
|---|---|---|
| `v` | evet | şema sürümü, `1` |
| `at` | evet | UTC, saniyeli ISO 8601 |
| `event` | evet | `verify`, `step_up`, `recheck`, `lock`, `unlock`, `enroll`, `forget`, `cooldown`, `camera_open`, `touch_id` |
| `channel`, `client_id`, `trigger` | evet | denetim etiketleri (geçerli değilse `null`); `client_id` süreç başına rastgeledir; `trigger`, `lock` için bir kilit tetikleyicisidir |
| `ok`, `reason` | evet | sonuç ve karar nedeni |
| `duration_ms` | evet | ne kadar sürdüğü |
| `score` | hayır | benzerlik puanı, 2 ondalığa yuvarlanmış |
| `liveness` | hayır | bir yüz eşleşmesinde `challenge` ya da `passive`; bir `spoof`'ta geçilemeyen canlılık kuralı |
| `request_id`, `tool` | hayır | bir step-up'ın ait olduğu tier-2 çağrı |

Bir kayıt asla bir embedding, bir kare ya da başka bir insan hakkında bir şey tutmaz. Dizeler 128 karaktere kesilir ve yazdırılamayan karakterler `?` olur; böylece bir çağıranın etiketi kaydı yazdıran terminali yönlendiremez. Hub log'u hiçbir karar ve puan almaz.

## Dosyalar { #files }

`TAU_DATA_DIR/guard/` altında, mod `0700`, yedeklere girmez ve `tau cloud push` asla göndermez:

| Dosya | Nedir |
|---|---|
| `enrolled` | herkese açık işaret, JSON `{"v": 1, "enrollment": "<id>", "model": "<sha256>", "created": "<iso>"}`; biyometrik hiçbir şey yok. Durduğu sürece koruma etkindir |
| `owner.face.v1.bin` | şablon, `0600`, atomik yazılır: ilişkili veri olarak `b"tau-guard/v1\|" + model_sha256` ile `b"TAUG1" \| nonce(12) \| AES-GCM(payload)`. Yük, yeniden normalleştirilmiş ortalama embedding'i, örnekleri ve baş çevirme kalibrasyonunu tutar |
| `models/face_recognition_sface_2021dec.onnx` | SFace; `tau guard setup` kurar, her yüklemede sha256 ile denetlenir |
| `audit.jsonl` (+ `.1`, `.2`) | denetim kaydı |
| `failures.json` | başarısızlık sayısı ve bekleme süresi, `0600` |
| `worker.log` | worker'ın stderr'i, `0600`, 1 MiB'yi geçince döndürülür; asla bir kare ya da embedding içermez |

Başka yerlerde:

- **Şablon anahtarı**, 256 bit, macOS Keychain'de: servis `tau-guard`, hesap `template-key-v1`, her zaman keyring'in macOS arka ucu üzerinden. Onu yalnızca worker okur.
- **YuNet** (`face_detection_yunet_2023mar.onnx`, MIT) lisansıyla birlikte `tau-guard` wheel'inin içinde gelir.
- **Kontrol token'ı**, `TAU_DATA_DIR/hub/control.token`.

## Modeller ve emeği geçenler { #models-and-credits }

| Model | Lisans | Boyut | Nasıl gelir |
|---|---|---|---|
| YuNet 2023mar (yüz algılama, beş nokta) | MIT, © 2020 Shiqi Yu | 232 KB | wheel'in içinde |
| SFace 2021dec (128 boyutlu yüz embedding'leri) | Apache-2.0 (OpenCV Zoo) | 38,7 MB | `tau guard setup`, opencv_zoo'dan `47534e2` commit'inde, ya da `--model-file` |

Yığın yalnızca `opencv-python-headless` ve `numpy` gerektirir; macOS'ta ayrıca `keyring` ile pyobjc AVFoundation, Quartz ve LocalAuthentication framework'leri.
