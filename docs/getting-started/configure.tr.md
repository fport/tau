<!-- tr twin of getting-started/configure.md, translated 2026-09-30 -->

# Yapılandırma

tau'yu iki dosya yapılandırır. `tau.toml` durağan veridir: hangi modelin hangi role hizmet ettiği, bir turun ne kadar sürebileceği, oturumların nereye gittiği. `.env` kimlik bilgilerini ve kökleri seçen birkaç ortam değişkenini tutar. Bu sayfa ikisini de adım adım anlatır; [tau.toml referansı](../reference/tau-toml.md) ve [ortam değişkenleri referansı](../reference/environment.md) her anahtarı listeler.

!!! note "Config ile Settings farkı"
    tau, başlangıçta bir kez okunan bu iki dosya için **config** (yapılandırma) sözcüğünü kullanır; TUI'nin `/settings` ekranı ve terminalin `/settings` komutu onları yerinde düzenler. **Settings** (ayarlar) ise tau çalışırken değişecek çalışma zamanı değerleridir (ambient mod, saklama süresi, bildirim tercihleri). Bunlar `TAU_DATA_DIR` altındaki bir dosyada yaşar ve çalışırken yeniden yüklenir; yol haritası issue 019'da planlanıyorlar ve bu sayfanın konusu değiller.

## Arayüzden düzenle

Dosyaları açmak zorunda değilsin. `tau tui` içinde `/settings` (takma adı `/ayarlar`) ya da F10 altı bölümlü bir düzenleyici açar: **Model roles**, **Credentials**, **Interface**, **Agent**, **Doctor** ve **Files**. `↑↓` bir bölüm seçer, Tab onun alanlarında gezinir, `ctrl+s` ya da F2 kaydeder, Esc kapatır. Bir kaydetme önce doğrulanır (hatalı bir değer, nedeni durum satırında yazılı hâlde pencerede kalır), `tau.toml` içindeki yorumları korur, `.env` dosyasını `0600` modunda tutar ve modeli etkileyen bir şey değiştiyse ajanı aynı oturum üzerinde yeniden kurar. Ekranı [İlk çalıştırma](first-run.md#in-the-interface-tau-tui) gösteriyor.

Sağlayıcı seçimi yalnızca hazır olan (kodu yazılmış) sağlayıcıları sunar. Planlanmış bir sağlayıcı (sonraki bir yol haritası issue'sunun yapacağı sağlayıcı; bugün hiç yok) bir notta listelenir ve seçilemez, çünkü onun üzerindeki bir rol başlayamaz; onu zaten adlandıran bir rol olduğu gibi bırakılır ve kaydedilmiş bir `tau.toml` bir gün `brain`'i onun üzerine koyarsa `tau tui` yine de açılır, ajansız ve Model roles bölümünde, böylece başka bir sağlayıcı seçebilirsin. Düzenleyici bir rolün sağlayıcısını ve model id'sini değiştirir ama `budget` ve `failover` değerlerine dokunmaz; onları dosyada düzenle ve tau'yu yeniden başlat (bkz. [Modeller ve bütçeler](../guides/models-and-budgets.md)). Bir kimlik bilgisi satırı, değerinin kabuk ortamından geldiğini de söyler: `.env` zaten ayarlı bir değişkeni asla ezmez, yani oraya kaydettiğin bir değer, kabuğunkini kaldırana kadar bir sonraki başlangıçta kullanılmaz.

`tau chat`'te bunun terminal biçimi var:

```text
you> /settings
Settings · ~/.tau
Model roles:
  brain  anthropic · claude-sonnet-5 · credentials ok
  fast   anthropic · claude-haiku-4-5 · credentials ok
  local  ollama · qwen3.5:9b · no credentials needed
UI language: en · profile: home
Context: sliding, window 60 · max_turns 12 · max_total_tokens none
Files:
  tau.toml            ~/.tau/tau.toml · present
  …
Change: /settings language en|tr · /settings profile NAME · /settings model ROLE PROVIDER MODEL_ID · /settings set NAME · /settings clear NAME. …
```

`/settings language tr`, `/settings profile travel` ve `/settings model brain anthropic claude-sonnet-5` değeri yazar ve yeniden yükler; `/settings set ANTHROPIC_API_KEY` değeri gizli bir istemle ister (hiçbir şey ekrana yansımaz), `/settings clear NAME` de onu kaldırır. İki kanalın arkasındaki Python API'si `tau_core.settings`'tir (bkz. tau-core README).

Bu sayfanın geri kalanı dosyaların kendisi.

## Model id'leri değil, roller

Kod asla bir modelin adını vermez. Bir **rol** ister, `tau.toml` da rolü bir sağlayıcıya ve bir model id'sine eşler. tau sağlayıcıyı doğrudan, `.env` içindeki anahtarınla (Anthropic, OpenAI ya da Google Gemini) ya da Ollama üzerinden yerel bir modelle çağırır ve rol başına bir **bütçeyi** kendisi uygular. Gelen dosya:

```toml
[models.roles.brain]
provider = "anthropic"                    # anthropic | openai | gemini | ollama | bedrock | fake
model_id = "claude-sonnet-5"
max_tokens = 4096

[models.roles.brain.budget]               # a hard cap tau enforces itself
usd = 15                                  # dollars per period
period = "month"                          # day | week | month; resets at midnight, on Monday, on the 1st
degrade_to = "fast"                       # once spent, this role answers until the reset; omit to stop and say so

[models.roles.fast]
provider = "anthropic"
model_id = "claude-haiku-4-5"
max_tokens = 1024

[models.roles.fast.budget]
usd = 1
period = "day"

[models.roles.local]
provider = "ollama"                       # Ollama on this machine; TAU_OLLAMA_URL points at another (the Mac over the tailnet)
model_id = "qwen3.5:9b"                   # answers well in Turkish; `ollama pull qwen3.5:9b`
max_tokens = 1024
params = { reasoning_effort = "none" }    # answer at once instead of reasoning first
failover = "fast"                         # answers while Ollama is not reachable (a sleeping or absent Mac)
```

- **`brain`** konuşma ve planlama modelidir (Claude Sonnet 5). Aksini söylemedikçe (`--role`, `/model`) `tau chat` ve `tau tui` onu kullanır.
- **`fast`** ön eleme ve özetler içindir (Claude Haiku 4.5). Bugün `/model fast` ile kullanılabilir; sonraki katmanlar onu hafıza çıkarımı için kullanır.
- **`local`**, Ollama üzerinden cihaz üzerinde çalışan bir modeldir (`qwen3.5:9b` önerilir). Ollama'ya ulaşılamadığında (çalışmıyorsa ya da Mac uyuyorsa) onun yerine **failover**'ı (ulaşılamayan rolün çağrıyı devrettiği yedek rol) olan `fast` yanıt verir ve yanıt bunu söyler.

`tau init` bu dosyayı anahtarını bulduğu sağlayıcı için yazar: Anthropic, OpenAI, Gemini ya da Bedrock; `brain` ve `fast` rollerinin `provider` ve `model_id` değerlerini yeniden yazar (örneğin OpenAI'da `gpt-6.1-sol` / `gpt-6-luna`, Gemini'de `gemini-3.5-flash` / `gemini-3.1-flash-lite`). Sağlayıcılar şunlar: `anthropic`, `openai` (`params.base_url` ile OpenAI uyumlu herhangi bir API de), `gemini`, `ollama`, isteğe bağlı bir `bedrock` ve senaryolu `fake`.

Bir **bütçe**, bir rolün ne kadar harcayabileceğini sınırlar: `period` başına `usd` (`day`, `week` ya da `month`; Europe/Istanbul saatine göre takvim dönemleri). tau her yanıtı fiyatlandırır, harcamayı `TAU_DATA_DIR` altındaki bir defterde (ledger) tutar ve bir bütçe tükendiğinde sıfırlanana kadar `degrade_to` rolü yanıt verir; böyle bir rol yoksa tau sana bütçenin ne zaman sıfırlanacağını söyler. `tau spend` her rolün nerede durduğunu gösterir. Sağlayıcılar, bütçeler, fiyatlar ve failover hakkındaki her şey tek bir rehberde: [Modeller ve bütçeler](../guides/models-and-budgets.md).

Bir rolün aynı anahtarlara sahip bir **`fallback`** tablosu olabilir. Fallback yalnızca birincil sağlayıcının kimlik bilgileri eksik olduğunda kullanılır; bu olduğunda `tau doctor` ve `/status` sana söyler. Gelen dosya hiç fallback tanımlamaz.

**Prompt önbelleği** isteğe bağlıdır ve rol başınadır. Anthropic ve Bedrock sağlayıcıları onu dikkate alır; `openai`, `gemini`, `ollama` ve `fake` yok sayar:

```toml
[models.roles.brain.cache]
strategy = "auto"                         # auto | anthropic
ttl = "1h"                                # optional: "5m", "1h"
# system_prompt_ttl = true               # bool or a TTL
# tools_ttl = "5m"
```

!!! tip "İpucu"
    Model id'leri veridir. Kodda değil, `tau.toml` içinde yaşarlar (Bedrock id'leri, bölgeler arası `global.` önekiyle Converse API biçimini kullanır; Ollama id'leri çektiğin adlardır). Yanlış bir id, bir yapılandırma hatası değil, ilk çağrıda bir model hatasıdır. tau-core'un fiyatını bilmediği bir model, bütçesi sayılabilmeden önce bir `[models.prices."<model_id>"]` tablosu ister ([tau.toml referansı](../reference/tau-toml.md#modelsprices)).

## `[agent]`: turlar, bağlam ve bütçe

```toml
[agent]
max_turns = 12                            # model calls per user turn (loop guard)
context = "sliding"                       # sliding | summarize
window_size = 60                          # sliding: messages kept; summarize: recent messages never summarized
# max_total_tokens = 200000               # optional per-turn token budget
```

- **`max_turns`**, mesajlarından birinin tetikleyebileceği model çağrısı sayısını sınırlar. tau bu sınıra ulaştığında son çağrının araçları yine çalışır, tau durur ve bunu söyler; devam edip etmeyeceğine sen karar verirsin.
- **`context`**, modelin uzun bir oturumdan neyi göreceğini seçer. `sliding` son `window_size` mesajı gönderir. `summarize` son `window_size` mesajı olduğu gibi, geri kalanını da bir özet olarak tutar. Oturum deposu her iki durumda da her mesajı saklar.
- **`max_total_tokens`**, isteğe bağlı, tur başına bir token (modelin metni ölçtüğü birim) bütçesidir. Ulaşıldığında tau turu bir bildirimle durdurur.

!!! warning "`context` değerini sonradan değiştirmek"
    Bir oturum, kaydedildiği bağlam modunu hatırlar. `sliding` değerini `summarize` yaptıktan sonra eski bir oturum `Session <id> was recorded with a different [agent] context setting; set it back to sliding or start a new session` diyerek açılmayı reddeder. Hiçbir şey kaybolmaz; değeri geri al ya da yeni bir oturumla başla. Ayrıntılar [Oturumlar ve sıkıştırma](../reference/sessions.md) sayfasında.

## `[sessions]`

```toml
[sessions]
backend = "file"                          # memory | file
```

`file`, `TAU_DATA_DIR/sessions/` altına oturum başına bir dizin yazar ve gelen dosyanın ayarladığı değer budur. `memory` oturumları süreç içinde tutar; testler ve atılacak çalıştırmalar içindir. Anahtar yoksa kod varsayılan olarak `memory` kullanır, o yüzden bu satırı koru.

## `[hub]`

```toml
[hub]
control_port = 7877
heartbeat_seconds = 5
```

Hub'ın (servis olarak çalışan, uzun ömürlü tau) kontrol API'si yalnızca `127.0.0.1:<control_port>` adresini dinler ve `GET /health`, `GET /status` ve `spend` servisinden gelen `GET /spend` (her rolün bütçe döneminde ne harcadığı, yerel defterden) isteklerine yanıt verir. `TAU_HUB_PORT` portu ezer. Heartbeat, çalışan hub'ın durum dosyasını ne sıklıkla yenilediğidir; `tau hub status` onu okur. Bkz. [tau'yu servis olarak çalıştır](../guides/hub-service.md).

## `[ui]`

```toml
[ui]
language = "en"                           # en | tr
```

**Arayüz dili**, arayüz öğelerinin dilidir: slash komutu yardımı, bildirimler, onay istemi, bölme başlıkları ve tuş ipuçları. tau'nun yanıt verdiği dil değildir; ona persona karar verir ve senin dilini yansıtır. `TAU_LANG` dosyayı ezer, `tau --lang tr …` tek bir çalıştırma için ikisini de ezer, `/lang en|tr` de onu bir oturumun içinde değiştirir.

## `[components]`: parçaları aç ya da kapat

tau'da takılıp çıkarılabilen her şey bir bileşendir; entry point'ler (Python paketlerinin eklenti kayıt noktaları) üzerinden bulunur ve `tau components` ile listelenir. `[components]` tablosu, hiçbir şeyi kaldırmadan araçları devre dışı bırakır, bağlam kaynaklarını ve hub servislerini seçer:

```toml
[components]
context = []                              # enabled tau.context sources; empty = every discovered one

[components.tools]
disabled = ["demo_physical_action", "dist:tau-example-tool"]   # tool names or dist:<distribution>

[components.hub]
services = []                             # enabled tau.hub_services; empty = every discovered one
```

- `tools.disabled` yalnızca araç kaldırabilir. Asla araç eklemez, bir araca tier (izin seviyesi) vermez ya da bir tier'ı değiştirmez.
- Bu tabloların içindeki bilinmeyen bir anahtar bir hatadır; böylece `disable` gibi bir yazım hatası bir aracı yanlışlıkla açık bırakamaz.
- Kurulu hiçbir bileşenin sağlamadığı bir ad, bir hata değil, bir `tau doctor` uyarısıdır.

Bir bileşenin kendi ayarları serbest bir `[component.<name>]` tablosuna girer:

```toml
[component.telegram]
chat_id_env = "TELEGRAM_CHAT_ID"
```

`tau.toml` içindeki başka herhangi bir üst düzey tablo bir kez loglanır ve yok sayılır. Resmin tamamı [Bileşenler ve eklentiler](../reference/components.md) sayfasında.

## Kökler ve kimlik: ortam

Dört değişken tau'nun nereden okuyup nereye yazacağına ve kim olduğuna karar verir. Onları kabuğunda ya da `<root>/.env` içinde ayarla; varsayılanlar tek kullanıcılı bir makineyi karşılar.

| Değişken | Varsayılan | Anlamı |
|---|---|---|
| `TAU_HOME` | içinde `tau.toml` varsa geçerli dizin, yoksa `~/.tau` | Yapılandırma kökü: `tau.toml`, `.env`, `persona/`, `tools/`. `tau --home DIR` onun önüne geçer. |
| `TAU_DATA_DIR` | `~/.local/share/tau` | Değişken durum: `sessions/`, `hub/`, `logs/`. Asla bir deponun içinde değil. |
| `TAU_PROFILE` | `home` | Etkin profil: `home`, `travel` ya da `sport`. `tau --profile NAME` onun önüne geçer. |
| `TAU_LANG` | `[ui] language` | Arayüz dili ezmesi, `en` ya da `tr`. `tau --lang` onun önüne geçer. |

Sonraki katmanlar için iki tane daha var: `TAU_ROLE` (`hub` ya da `node`, varsayılan `hub`; 5. katmandaki mesh onu kullanır) ve `TAU_HUB_PORT`.

```sh
# ~/.tau/.env
TAU_DATA_DIR=~/tau-data
TAU_PROFILE=home
ANTHROPIC_API_KEY=sk-ant-...
```

!!! note "Öncelik sırası, bir kez"
    Komut satırı seçeneği → ortam değişkeni → `.env` → `tau.toml` → yerleşik varsayılan. Kabuğunda zaten ayarlı bir değişkeni `.env` asla ezmez.

## Persona dosyaları

`persona/persona.md` tau'nun karakteridir ve yayımlanması güvenlidir. `persona/user.md` senin hakkındaki bilgilerdir ve özeldir. İkisi de değiştiklerinde, bir sonraki model çağrısından önce yeniden okunur; yani bir düzenleme yeniden başlatma gerektirmez. `persona.md` dosyasını boş bırakma: eksik ya da boş bir dosya `tau chat`'i başlangıçta bir `ConfigError` ile durdurur; tau çalışırken bozulan bir dosyanın ise son sağlam sürümü kullanılmaya devam eder.

## Bir değişiklikten sonra

```sh
tau doctor        # config, roles, credentials, persona, components
tau components    # what is discovered, enabled and in use
```

İkisi de bir model başlatmaz. Çalışan bir hub, `tau chat` ya da `tau tui`, `tau.toml` dosyasını başlarken okur; bu yüzden bir değişiklikten sonra, yeni bir `budget` da dahil, onları yeniden başlat. Çalışan bir oturumun içinde `/status` her rol için çözümlenmiş modeli, bağlam modunu ve penceresini, araç sayılarını ve bütçeli her rolün harcamasını sınırıyla birlikte gösterir; `/settings` dosyaların değerlerini gösterir ve onları değiştirmene izin verir, TUI'nin **Doctor** bölümü de `tau doctor` ile aynı kontrolleri çalıştırır.
