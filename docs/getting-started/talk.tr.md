<!-- tr twin of getting-started/talk.md, translated 2026-09-30 -->

# tau ile konuş

Bugün terminalde iki kanal çalışıyor. `tau chat` satır tabanlı bir REPL'dir: tek bir istem, akan yanıtlar, araç satırları, stdin üzerinden onaylar. `tau tui` eksiksiz bir Textual arayüzüdür: markdown yanıtlar, araç kartları, canlı bir olaylar bölmesi, bir oturum seçici ve modal bir onay penceresi. İkisi aynı slash komutlarını, aynı oturum deposunu ve aynı tier kapısını (araçların izin seviyesine göre onay isteyen denetim) paylaşır; yani birinde başlayıp diğerinde `/resume` ile sürdürebilirsin.

| | `tau chat` | `tau tui` |
|---|---|---|
| En uygun olduğu yer | betikler, yavaş bağlantılar, hızlı bir soru | günlük kullanım, telefon, uzun oturumlar |
| Yanıtlar | akan düz metin | akan markdown |
| Araç çağrıları | soluk satırlar | tier, onay, süre ve sonuç içeren kartlar |
| Onaylar | stdin'de `Approve? [y/N]` | **Approve** / **Reject** içeren modal pencere |
| Ajan olayları | yalnızca log dosyasında | canlı bölme, `/resume` ile yeniden oynatılır |
| Bir turu iptal etme | Ctrl-C | Esc |
| Çıkış | `/quit`, Ctrl-D | `/quit`, Ctrl+Q |
| TTY gerekir mi | hayır | evet |

İkisi de aynı yapılandırmayı okur ve yapılandırma bozuksa ya da bir `--resume ID` bilinmiyorsa, hiçbir şey açılmadan çıkış kodu 2 ile durur. Eksik kimlik bilgileri `tau chat`'i aynı şekilde durdurur; `tau tui` ise bunun yerine ayarlar ekranında açılır, hiç yapılandırma yoksa da bir kurulum ekranı açar ([İlk çalıştırma](first-run.md#in-the-interface-tau-tui)).

## `tau chat`

```sh
tau chat                      # new session on the brain role
tau chat --resume             # continue the most recent earlier session
tau chat --resume ID          # continue that session
tau chat --session ID         # start with this session id
tau chat --role fast          # pin a role for the whole run
tau --lang tr chat            # Turkish chrome
```

```text
tau ready. Profile: home, session: 20260929-173826-f949. Commands: /help, /tools, /sessions, /resume, /new, /session, /compact, /clear, /status, /model, /lang, /settings, /quit (Ctrl-D also quits).
you> Merhaba tau
tau> Merhaba. Nasıl yardımcı olabilirim?
you> /session
Session: 20260929-173826-f949
Title: Merhaba tau
Messages: 2
Store: file (~/.local/share/tau/sessions)
```

REPL bir seferde tek bir iş yapar: bir komut asla bir turla çakışmaz. Bir tur sırasında Ctrl-C, turu bir sonraki güvenli noktada iptal eder ve `Interrupted.` yazdırır; istemdeyken Ctrl-C çıkar.

### Terminalde onaylar

Tier-2 bir çağrı (her zaman onay isteyen izin seviyesi) turu durdurur ve stdin üzerinden sorar:

```text
⚠️  Approval needed (tier 2)
  Tool: demo_physical_action
  Arguments: {"action": "turn on the desk lamp"}
  Effect: Demo: simulates a physical action; no real device moves.
  Approve? [y/N]
```

- `y`, `yes`, `e` ya da `evet` onaylar; arayüz dili hangisi olursa olsun.
- Başka her şey reddeder: `n`, Enter, Ctrl-D, bir yazım hatası.
- Terminalde zaman aşımı yoktur; istem seni bekler.
- Bir ret turu bitirmez. Model araç sonucu olarak `The user did not approve this action` okur ve yanıt verir.

## Slash komutları

`/` ile başlayan bir satır bir komuttur. Onu kanal işler; model onu asla görmez. On üç standart ad İngilizcedir; Türkçe takma adlar (`/devam`, `/çık`, `/özet`, `/ayarlar`, …) çalışmaya devam eder ama asla gösterilmez.

| Komut | Ne yapar |
|---|---|
| `/help` | komutları tek satırlık yardımlarıyla listeler |
| `/tools` | kayıtlı araçlar, tier'ları ve açıklamalarıyla |
| `/sessions` | en son 10 önceki oturum, numaralı |
| `/resume`, `/resume n`, `/resume id` | en son önceki oturumu, son listedeki n'inciyi ya da bir id'yi sürdürür |
| `/new` | yeni bir oturum başlatır; mevcut oturum kayıtta kalır |
| `/session` | mevcut oturumun id'si, başlığı, mesaj sayısı ve deposu |
| `/compact [focus]` | bu oturumu kendi modeliyle özetler ve özetle başlatılmış yeni bir oturumda devam eder; eskisi saklanır |
| `/clear` | ekranı temizler; oturum ve ajan devam eder |
| `/status` | profil, oturum, model, bağlam, araçlar, arayüz dili, sürümler, hub (servis olarak çalışan tau) ve bütçe varsa harcama |
| `/model [role]` | `tau.toml` içindeki rolleri listeler ya da bu oturumu birine geçirir; `/resume` bunu hatırlar |
| `/lang en`, `/lang tr` | bu çalıştırma için arayüz dilini değiştirir |
| `/settings [key value]` | ayarları gösterir (roller, kimlik bilgisi durumu, dil, profil, bağlam, dosyalar); terminalde `/settings language tr`, `/settings profile NAME`, `/settings model ROLE PROVIDER MODEL_ID`, `/settings set NAME` (gizli istem) ve `/settings clear NAME` birini değiştirir; TUI'de ayarlar ekranını açar |
| `/quit` | çıkar; `/exit` bir takma addır |

```text
you> /status
Profile: home
Session: 20260929-173826-f949 · Merhaba tau · 2 messages stored · role brain
Model: brain → anthropic · claude-sonnet-5
Context: sliding, window 60 · 2 messages in memory
Tools: 2 registered · 1 need approval (tier 2)
UI language: en
Versions: tau-core 0.3.1 · tau-tui 0.3.1
Hub: hub is not running (nothing answers on http://127.0.0.1:7877/health)
Budget: brain $0.42 of $15.00 this month (resets 01.10.2026 00:00); fast $0.03 of $1.00 today (resets 01.10.2026 00:00)
```

`/status` her rol için modeli ve fallback'in (birincil sağlayıcının kimlik bilgisi yokken kullanılan yedek sağlayıcı) kullanılıp kullanılmadığını söyler, asla bir anahtarı değil; son satırı, bütçeli her rolün harcamasını sınırıyla karşılaştırır ([Modeller ve bütçeler](../guides/models-and-budgets.md)). [Slash komutları referansında](../reference/slash-commands.md) takma adlar ve her bildirimin tam ifadesi var.

## `tau tui`

```sh
tau tui                       # new session
tau tui --resume              # continue the most recent earlier session
tau tui --resume ID
tau tui --profile travel
tau --home /path/to/root --lang tr tui
```

Arayüz, üstte bir satır ve altta en fazla dört satırlık kontrol öğesinden oluşur; böylece telefonda mosh üzerinden 80x24 kullanılabilir kalır. Başlık profili, oturum id'sini, rolü, araç sayısını ve arayüz dilini gösterir; yazma alanı bir satırdan beş satıra büyüyen yuvarlak köşeli bir kutudur; ipucu çubuğu da o anda önemli olan tuşları söyler.

```text
 τ tau  home · 20260929-120000-abcd                                  brain · en
 › Salon lambası açık mı? Açıksa kapat.
 ● get_light_state(room="salon")                                  tier 0 · 38ms
   ⎿  {"on": true, "brightness": 80}
 ● set_light(room="salon", on=false)                  tier 2 · approved · 412ms
   ⎿  Light turned off
 τ Salon lambası kapatıldı.
   • Önceki durum: açık, %80 parlaklık
 ✓ Worked for 4s · 2 tool calls · ctrl+o expand
╭──────────────────────────────────────────────────────────────────────────────╮
│ ❯ Type a message…                                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
 ? shortcuts · / commands · ctrl+j newline                          ctrl+q quit
```

Simgeler, her biri tek hücre ve emoji yok: `›` sen · `τ` tau · `●` bitmiş araç çağrısı · `○` çalışıyor ya da onay bekliyor · `⎿` sonuç satırı · `✻` meşgul · `✓ ◆ ✗` tur altbilgisi (bitti / sana ihtiyaç var ya da sınır / hata) · `▸` bildirim · `❯` istem.

### Ekran boyutuna göre yerleşim

TUI, terminal boyutuna göre bir yerleşim seçer. Genişlik aralıkları: 60 sütunun altı **phone**, 60–99 **narrow**, 100–139 **wide**, 140 ve üstü **ultra**. Yükseklik aralıkları: 20 satırın altı **short**, **mid**, 30 ve üstü **tall**.

| Terminal | Ne elde edersin |
|---|---|
| 50x24 (phone, mosh üzerinden Termius) | Başlık oturum id'sini göstermez (`/session` gösterir), araç rozetleri sonuç satırına taşınır, yazma alanının çerçevesi yoktur, ipuçları `^j` diye yazılır, karşılama kartı 16 sütunluk işareti gösterir, yanıtlar düz metin olarak akar ve bölüm bittiğinde markdown'a dönüşür, onay penceresi tam genişliktedir ve butonları alt alta dizilir. |
| 80x24 (narrow) | Yukarıdaki yerleşim. `ctrl+e` ya da F4 aynı gövdede transkripti olay loguyla değiştirir; Esc geri döner. |
| 80x30 (narrow, tall) | Transkriptin altında 8 satırlık bir olaylar şeridi. |
| 100x30 (wide) | Olaylar bölmesi sağa yerleşir (34 sütun); `ctrl+e` onu gizler. |
| 160x45 (ultra) | Solda salt okunur bir oturum kenar çubuğu (28 sütun); bir satıra tıklamak onu sürdürür. Olaylar bölmesi 40 sütun. |
| 20 satırın altı (short) | İpucu satırı yok, karşılama işareti gizli, yazma alanı iki satıra büyür. |

### Tuşlar

| Tuş | Etkisi |
|---|---|
| Enter | gönderir ya da menüde vurgulanan satırı kabul eder |
| ctrl+j | yeni satır (terminal iletiyorsa shift+enter da) |
| Esc | menüyü kapatır · çalışan turu iptal eder · olaylar görünümünden çıkar · en alta geri kaydırır |
| ctrl+e / F4 | olaylar: sütunu (≥ 100 sütun) ya da görünümü (< 100 sütun) açıp kapatır |
| ctrl+r / F2 | oturum seçici (Enter sürdürür, `n` yeni, Esc kapatır) |
| ctrl+n | yeni oturum |
| ctrl+t / F3 | `/tools` |
| ctrl+o / F6 | son turun kartlarını açar ya da kapatır: JSON olarak argümanlar ve sonucun tamamı |
| PageUp / PageDown, F7 / F8 | transkripti kaydırır; katlanmış bir geçmişin en üstünde PageUp 20 eski turu yükler |
| F9 | en alta döner |
| F10 | ayarlar ekranı (`/settings`); içinde `ctrl+s` ya da F2 kaydeder, Esc kapatır |
| ↑ / ↓ | gönderilmiş istemleri geri çağırır; menü açıkken menüde gezinir |
| `?` ya da F1 | yardım (yalnızca boş bir yazma alanında) |
| ctrl+q | çıkar (ctrl+c bir seçimi kopyalar; seçim yoksa yalnızca nasıl çıkılacağını söyler) |

Boş bir yazma alanına `/` yazmak on üç komutun bulanık (fuzzy) bir menüsünü açar: `↑↓` seçer, Tab tamamlar, Enter çalıştırır, Esc kapatır. Tam yazılmış bir komut, menü hızlı bir tuş dizisine yetişememiş olsa bile yazıldığı gibi çalışır; böylece `/session` asla `/sessions` çalıştırmaz.

tau yanıt verirken yazma alanı metnini korur ve bir bildirim bunu söyler. `/new`, `/resume`, `/compact`, `/clear`, `/model <role>` ve `/settings` mevcut turu bekler; `/status` ve argümansız `/model` her an yanıt verir.

### TUI'de onaylar

Tier-2 bir çağrı sohbetin üzerinde yarı saydam bir pencere açar: araç, etkisi, düzgün biçimlendirilmiş JSON olarak argümanlar, **Approve** ve **Reject**.

- `y` ya da `e` onaylar; `n`, `h` ya da Esc reddeder. Odak **Reject** üzerinde başlar, yani Enter reddeder. Tab iki buton arasında gezinir.
- `y`/`e` ve **Approve**, pencere açıldıktan ancak yarım saniye sonra çalışır; bu sırada ipucunda `(arming…)` yazar. Sohbete yazmakta olduğun tuşlar yanlışlıkla onay veremez.
- Açık bir onay dışındaki her şey reddeder: başka bir yolla kapatılan bir pencere, iptal edilen bir bekleme, artık çalışmayan bir uygulama.
- Pencerenin arkasında araç kartında `○ set_light(…)` ve `⎿ ◆ waiting for your approval` yazar; yazma alanının çerçevesi ve başlıktaki `τ` Flare rengine döner.

### Terminal ayarları

| Ayar | Etkisi |
|---|---|
| `TAU_TUI_ASCII=1` | blok karakterleri olmayan terminaller için ASCII sözcük dağarcığı ve kutu çerçeveleri |
| `TAU_TUI_PLAIN_STREAM=1` | her yanıtı düz metin olarak akıtır ve markdown'ı bölüm başına bir kez ayrıştırır |
| `TEXTUAL_ANIMATIONS=none` | başlıkta hareket yok |
| `TEXTUAL_COLOR_SYSTEM` / `--ansi` | 16 renkli `tau-ansi` teması |

Canlı markdown akışı en az 60 sütun ister. TUI çalışırken ayrıntılar `<TAU_DATA_DIR>/logs/tau.log` dosyasına gider; sohbet bir traceback yerine kısa bir bildirim gösterir.

## Arayüz dili

```sh
tau --lang tr chat
tau --lang tr tui
```

`--lang`, arayüz öğelerinin dilini tek bir çalıştırma için ayarlar; `TAU_LANG` olarak export edilir, böylece TUI, terminal ve onların onay istemleri aynı dili kullanır. `/lang en` ya da `/lang tr` onu bir oturumun içinde değiştirir; `/settings language tr` (ya da TUI ayarlar ekranının **Interface** bölümü) onu kalıcı olarak `tau.toml` dosyasına yazar. Persona ise sen hangi dilde yazarsan o dilde yanıt vermeyi sürdürür.

## Her şey nereye gider

- Oturumlar: `<TAU_DATA_DIR>/sessions/<id>/`, her biri bir dizin, sonsuza dek saklanır. [Oturumlar ve sıkıştırma](../reference/sessions.md).
- Log: `<TAU_DATA_DIR>/logs/tau.log`, `INFO` ve üstü, traceback'lerle; tier-1 ve tier-2 araç çağrıları argümanları ve onaylarıyla birlikte.
- Başka hiçbir şey. Telemetri yok; [yedekleri](../guides/backups.md) kurmadıkça buluta kopya yok.
