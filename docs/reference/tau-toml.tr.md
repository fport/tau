<!-- tr twin of reference/tau-toml.md, translated 2026-09-30 -->

# tau.toml

`tau.toml`, tau'nun statik yapılandırmasıdır; başlangıçta `tau_core.config.Config` tarafından bir kez okunur. Yapılandırma kökünde (`TAU_HOME`) durur; `tau init` onu, deponun kendi dosyasıyla aynı olan ve paketle gelen bir şablondan yazar. Bu sayfa her tabloyu ve anahtarı türü ve varsayılan değeriyle listeler.

Her yerde geçerli kurallar:

- tau'nun okuduğu üst düzey tablolar: `models`, `agent`, `sessions`, `hub`, `ui`, `components`, `component`. Başka her üst düzey tablo bir kez loglanır ve yok sayılır, asla hata sayılmaz (`[model]` gibi bir yazım hatası `tau doctor` çıktısında uyarı olarak görünür).
- Bir rol tablosunun, bir `[models.prices]` tablosunun ve `[components]` tablosunun içinde bilinmeyen bir anahtar **hatadır**; böylece yanlış yazılmış bir anahtar bir aracı sessizce açık bırakamaz.
- Sağlayıcı ve arka uç adları yükleme sırasında yalnızca adlarına göre doğrulanır; bir rol kullanılana kadar hiçbir şey içe aktarılmaz.
- Secret'lar (gizli değerler) asla buraya girmez. Kimlik bilgileri ortamdan ya da `.env` dosyasından gelir.

## `[models.roles.<role>]`

Her rol için bir tablo. Gelen dosya `brain`, `fast` ve `local` rollerini tanımlar; her ad kullanılabilir ve `tau chat --role` ya da `/model` onu seçebilir. Roller, sağlayıcılar ve bütçeler [Modeller ve bütçeler](../guides/models-and-budgets.md) sayfasında anlatılıyor.

| Anahtar | Tür | Varsayılan | Anlamı |
|---|---|---|---|
| `provider` | string | zorunlu | `anthropic`, `openai`, `gemini`, `ollama`, `bedrock`, `fake` ya da bir `tau.providers` bileşeninin adı. Her sağlayıcı doğrudan çağrılır. |
| `model_id` | string | zorunlu | Kod değil, veri: sağlayıcının model id'si (`claude-sonnet-5`, `gpt-6-luna`, `gemini-3.5-flash`); `ollama` için Ollama model adı (`qwen3.5:9b`). Bedrock id'leri `global.` önekli Converse biçimini kullanır. Id fiyatı da belirler (bkz. [`[models.prices]`](#modelsprices)). |
| `region` | string | yok | Bedrock bölgesi. Ayarlandığında bu rol için `AWS_REGION` artık gerekmez. |
| `max_tokens` | integer ≥ 1 | sağlayıcının varsayılanı (`anthropic`, `openai`, `gemini` ve `ollama` için 4096) | Çağrı başına çıktı token sınırı. `openai` bunu `max_completion_tokens`, `gemini` ise `max_output_tokens` olarak gönderir. |
| `params` | table | `{}` | Aşağıdaki tau'ya özgü anahtarlar dışında, sağlayıcının modeline ek parametreler olarak geçirilir. Gelen `local` rolü `reasoning_effort = "none"` ayarlar. |
| `fallback` | table | yok | Aynı anahtarlara sahip ikinci bir rol tablosu (iç içe fallback, `budget` ya da `failover` olmadan). Yalnızca birincil sağlayıcının kimlik bilgileri eksikken kullanılır. |
| `cache` | table | yok | Prompt önbelleği ayarları, aşağıya bak. |
| `budget` | table | yok | Rolün gün, hafta ya da ay başına tau'nun kendisinin uyguladığı kesin harcama sınırı; aşağıya bak. |
| `failover` | string | yok | Bu rolün modeline ulaşılamadığında yanıt veren başka bir rol; aşağıya bak. |

tau'nun kendisinin okuduğu (iletilmeyen) `params` anahtarları:

| Anahtar | Sağlayıcılar | Anlamı |
|---|---|---|
| `api_key_env` | anthropic, openai, gemini | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` ya da `GEMINI_API_KEY`/`GOOGLE_API_KEY` yerine anahtarı tutan değişken. |
| `base_url` | anthropic, openai, ollama | anthropic: alternatif bir API taban URL'si. openai: OpenAI uyumlu herhangi bir API. ollama: Ollama sunucusu; yoksa `TAU_OLLAMA_URL`, o da yoksa `http://127.0.0.1:11434`. `/v1` olmadan ver, tau onu kendisi ekler. |
| `workspace_id` | anthropic | `anthropic-workspace-id` olarak gönderilen workspace id'si; ortamdaki `ANTHROPIC_WORKSPACE_ID` de aynı işi yapar. |

`ollama` kimlik bilgisi gerektirmez. 3 saniyelik bir zaman aşımıyla bağlanır ve asla yeniden denemez; böylece Ollama ortada yokken bir rolün `failover`'ı saniyeler içinde yanıt verir.

### `[models.roles.<role>.budget]`

Rolün kesin harcama sınırı. tau bunu kendisi uygular: her yanıtın token kullanımı fiyatlandırılır ve `TAU_DATA_DIR` altındaki harcama defterine (ledger; `spend.sqlite3`) kaydedilir; her çağrıdan önce de rolün mevcut dönemdeki harcaması sınırla karşılaştırılır. Her sağlayıcı için aynı şekilde çalışır. Tablo da satır içi tablo da (`budget = { usd = 1, period = "day" }`) olur.

| Anahtar | Tür | Varsayılan | Anlamı |
|---|---|---|---|
| `usd` | number > 0 | zorunlu | Dönem başına dolar. |
| `period` | `"day"` \| `"week"` \| `"month"` | zorunlu | Europe/Istanbul saatine göre bir takvim dönemi: gün gece yarısı, hafta pazartesi 00:00'da, ay ayın 1'inde 00:00'da sıfırlanır. |
| `degrade_to` | string | yok | Bu dosyada tanımlı ve bu bütçe tükenince sıfırlanmaya kadar yanıt veren başka bir rol. Verilmezse tur biter ve kullanıcıya bütçenin ne zaman sıfırlanacağı söylenir. |

```toml
[models.roles.brain.budget]
usd = 15
period = "month"
degrade_to = "fast"
```

- `budget` bir `fallback` tablosunun içinde kullanılamaz; onu rolün kendisinde ayarla.
- Bir değişiklik tau başladığında geçerli olur: hub'ı yeniden başlat ve `tau chat` / `tau tui`'yi yeniden aç. `tau spend` ve `tau doctor` dosyayı her seferinde okur.
- Bütçesi olan ama modelinin fiyatı olmayan bir rol, çağrılarını $0 olarak sayar; `tau doctor` uyarır (`role brain: has a budget, but model 'my-model' has no price, so its calls count as $0; add [models.prices."my-model"] to tau.toml`).
- Yalnızca `budget` ya da `failover` sahibi roller ölçülür; `tau spend` diğerlerini `no budget (its calls are not counted)` olarak gösterir.
- Bütçe tükendiğinde kanal, arayüz dilinde, `The brain budget is spent until 01.10.2026 00:00; fast answered instead.` (`degrade_to` varsa) ya da `The brain budget is spent ($15.00 of $15.00) and resets at 01.10.2026 00:00. To raise the cap, change it in tau.toml.` (yoksa) gösterir.

### `failover`

`failover = "<role>"`, bu rolün modeline daha hiçbir şey akmadan ulaşılamadığında yanıt veren rolü belirtir: bağlantı reddedilir ya da zaman aşımına uğrar ya da sağlayıcı 5xx ile yanıt verir. Hız sınırlamaya (throttling) takılma Strands'in yeniden denemesine bırakılır. Kanal bu durumda `local is not reachable right now; fast answered instead.` gösterir, hub logu da bir uyarı yazar. Gelen `local` rolü (Ollama), `fast` rolüne failover yapar.

`budget.degrade_to` ve `failover`, ikisi de rolün kendisini değil, tanımlı başka bir rolü göstermeli; rolden role izlendiklerinde, tek başlarına ya da birlikte, döngüye girmemeliler: `brain` rolü `fast`'e düşerken (degrade) `fast` rolünün `brain`'e failover yapması reddedilir. Yerine geçen rol sıradan bir roldür: kendi bütçesi ve failover'ı geçerlidir ve harcaması kendi adı altında sayılır.

### `[models.roles.<role>.cache]`

Strands'in `CacheConfig` yapısına karşılık gelir. Anthropic ve Bedrock buna uyar; `openai`, `gemini`, `ollama` ve `fake` yok sayar.

| Anahtar | Tür | Varsayılan | Anlamı |
|---|---|---|---|
| `strategy` | `"auto"` \| `"anthropic"` | `"auto"` | Önbellek noktalarının nasıl yerleştirileceği. |
| `ttl` | string | sağlayıcının varsayılanı | Önbellek TTL'si, örneğin `"5m"`, `"1h"`. |
| `system_prompt_ttl` | bool ya da string | ayarsız | Sistem prompt'unu önbelleğe al (`true`) ya da kendi TTL'siyle al. |
| `tools_ttl` | bool ya da string | ayarsız | Araç tanımları için aynısı. |

```toml
[models.roles.brain]
provider = "anthropic"
model_id = "claude-sonnet-5"
max_tokens = 4096
cache = { strategy = "auto", ttl = "1h" }
```

## `[models.prices]`

Bir modelin maliyeti, milyon token başına ABD doları cinsinden, her model id'si için bir tablo. tau-core bir fiyat tablosuyla gelir (`templates/prices.toml`); buradaki tablolar onu genişletir ya da aynı id için ezer. Gelen dosyada hiç yoktur.

| Anahtar | Tür | Varsayılan | Anlamı |
|---|---|---|---|
| `input` | number ≥ 0 | zorunlu | Milyon girdi token'ı başına dolar. |
| `output` | number ≥ 0 | zorunlu | Milyon çıktı token'ı başına dolar. |
| `cache_read` | number ≥ 0 | `input` | Prompt önbelleğinden okunan milyon token başına dolar. |
| `cache_write` | number ≥ 0 | `input` | Prompt önbelleğine yazılan milyon token başına dolar. |

```toml
[models.prices."my-model"]
input = 0.5
output = 1.5
cache_read = 0.05
```

Model id'leri nokta ve iki nokta üst üste içerdiği için id tırnak içinde yazılır. `ollama` ve `fake` her zaman ücretsizdir. İki tabloda da olmayan bir model fiyatsızdır: çağrıları maliyetsiz kaydedilir. Gelen fiyatlar [Modeller ve bütçeler](../guides/models-and-budgets.md#prices) sayfasında listelenir.

## `[agent]`

| Anahtar | Tür | Varsayılan | Anlamı |
|---|---|---|---|
| `max_turns` | integer ≥ 1 | `12` | Kullanıcı turu başına model çağrısı (döngü koruması, Strands `Limits(turns=…)`). Sınırda son çağrının araçları yine çalışır; tau bir bildirimle durur. |
| `context` | `"sliding"` \| `"summarize"` | `"sliding"` | Modelin uzun bir oturumdan ne gördüğü. `sliding` son `window_size` mesajı gönderir; `summarize` son `window_size` mesajı olduğu gibi, geri kalanı özet olarak tutar. Depo her iki durumda da her şeyi saklar. Bir oturum, kaydedildiği modu hatırlar. |
| `window_size` | integer ≥ 1 | `60` | Tutulan (`sliding`) ya da asla özetlenmeyen (`summarize`) mesajlar. |
| `max_total_tokens` | integer ≥ 1 | ayarsız | İsteğe bağlı, tur başına token bütçesi (`Limits(total_tokens=…)`). |

SDK'nın `context_manager = "auto"` / `"agentic"` hazır ayarları bir `ConfigError` ile reddedilir: bunlar, tier kapısının (araçların izin seviyesi denetimi) reddedeceği, tier'sız SDK araçları kaydeder.

## `[sessions]`

| Anahtar | Tür | Varsayılan | Anlamı |
|---|---|---|---|
| `backend` | string | kodda `"memory"`; gelen dosya `"file"` ayarlar | `memory` (süreç içinde, testler için), `file` (`TAU_DATA_DIR/sessions/`) ya da bir `tau.sessions` bileşeninin adı. |

## `[hub]`

| Anahtar | Tür | Varsayılan | Anlamı |
|---|---|---|---|
| `control_port` | integer 1–65535 | `7877` | Loopback kontrol API'sinin portu. `TAU_HUB_PORT` bunu ezer. |
| `heartbeat_seconds` | integer ≥ 1 | `5` | Çalışan hub'ın (tau'nun çalıştığı makinedeki uzun ömürlü servis) `hub/state.json` dosyasını ne sıklıkla yenilediği. |

## `[ui]`

| Anahtar | Tür | Varsayılan | Anlamı |
|---|---|---|---|
| `language` | `"en"` \| `"tr"` | `"en"` | Terminalin ve TUI'nin arayüz dili. `TAU_LANG` bunu ezer; `tau --lang` ikisini de ezer; `/lang` tek bir çalıştırma için değiştirir. |

## `[components]`

Keşfedilen bileşenler için anahtarlar. Bu tabloların herhangi birindeki bilinmeyen anahtarlar hatadır.

| Anahtar | Tür | Varsayılan | Anlamı |
|---|---|---|---|
| `context` | string listesi | `[]` | Adıyla etkinleştirilen `tau.context` kaynakları. Boş, keşfedilen her biri demektir. |
| `tools.disabled` | string listesi | `[]` | Kapatılacak araçlar; araç adıyla ya da bir dağıtımın bütün araçları için `dist:<distribution>` ile. Yalnızca araç çıkarabilir. |
| `hub.services` | string listesi | `[]` | Adıyla etkinleştirilen `tau.hub_services`. Boş, keşfedilen her biri demektir. |

```toml
[components]
context = []

[components.tools]
disabled = ["demo_physical_action", "dist:tau-example-tool"]

[components.hub]
services = []
```

Kurulu hiçbir bileşenin sağlamadığı bir ad, `tau doctor` uyarısıdır. Açık bir listeyle çağrılan `build_agent(tools=[...])`, `tools.disabled` ayarını atlar.

## `[component.<name>]`

Bir bileşenin kendi ayarları için serbest tablolar; `Config.component("<name>")` tarafından yeni bir dict olarak döndürülür. tau içeriklerini doğrulamaz.

```toml
[component.telegram]
poll_timeout_seconds = 50    # Telegram long-poll timeout (default 50)
backoff_max_seconds = 60     # cap of the backoff after network errors (default 60)
approval_timeout_seconds = 300   # an unanswered tier-2 approval is a timeout (default 300)

[component.example]
nodes = ["mac", "arm"]
```

### `[component.guard]`

[Sahip korumasının](../guides/guard.md) tablosu "doğrulanmaz" kuralının tek istisnasıdır: tau-core bilinmeyen bir anahtarda ya da bool olmayan bir `enabled` değerinde korumayı kalıcı olarak kilitler (`enable = true` gibi bir yazım hatası asla "kapalı" anlamına gelmemeli); `tau-guard` da aralık dışı bir değerde korumayı `unavailable` yapar, asla daha zayıf bir değere düşmez. `tau guard setup` `enabled = true` yazar; kayıt işareti `TAU_DATA_DIR/guard/enrolled` durduğu sürece koruma `enabled` ne derse desin açıktır ve onu yalnızca `tau guard forget` kapatır.

| Anahtar | Varsayılan | Aralık ya da değerler |
|---|---|---|
| `enabled` | `false` | bool |
| `max_unlock_hours` | `8` | 1–24 |
| `idle_lock_minutes` | `10` | 1–240 |
| `recheck_after_idle_minutes` | `3` | 1–240 |
| `presence_recheck_minutes` | `30` | 1–1440 |
| `verify_timeout_seconds` | `15` | 5–60 |
| `unlock_threshold` | `0.50` | 0.45–0.95 |
| `step_up_threshold` | `0.55` | 0.45–0.95 |
| `step_up_challenge_fresh_seconds` | `120` | 0–600 |
| `unlock_liveness` | `"challenge"` | `challenge`, `none` |
| `step_up` | `"face"` | `face`, `face_or_touch_id`, `touch_id`, `none` |
| `unlock_fallback` | `"touch_id"` | `touch_id`, `touch_id_or_password`, `none` |
| `camera` | `"builtin"` | `builtin` ya da bir kameranın AVFoundation uniqueID'si |
| `window` | `true` | bool |

Her anahtarın ne yaptığı [koruma referansında](guard.md#componentguard).

## Gelen dosya { #the-shipped-file }

Bu, `tau init`'in birebir yazdığı şablondur; deponun kendi `tau.toml` dosyasına eşittir ve bir test ikisini aynı tutar.

```toml
# tau.toml — static configuration read by tau_core.config.Config.
# Role → provider + model id. Model ids are data; code never hardcodes them.
# Secrets never go here: credentials come from .env (see .env.example).
#
# Providers are called directly (ADR 0011). A budget caps what a role may spend per day, week or
# month (Europe/Istanbul); tau prices every answer and keeps the spend under TAU_DATA_DIR
# (`tau spend`). Prices come from tau-core's prices.toml; a model it does not know needs a
# [models.prices."<model_id>"] table (input, output, cache_read, cache_write in $ per 1M tokens).

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

# Optional per-role prompt caching (Anthropic and Bedrock; the other providers ignore it):
# [models.roles.brain.cache]
# strategy = "auto"                       # auto | anthropic; Strands CacheConfig(strategy=...)
# ttl = "1h"                              # optional cache TTL ("5m", "1h"); system_prompt_ttl / tools_ttl take a bool or a TTL

[agent]
max_turns = 12                            # per-turn loop guard, Strands Limits(turns=...)
context = "sliding"                       # sliding | summarize: what the model sees of a long session (the store keeps everything)
                                          # A session remembers this value; to resume it after a change, set it back or start a new session.
window_size = 60                          # sliding: messages kept; summarize: recent messages never summarized
# max_total_tokens = 200000               # optional per-turn token budget, Strands Limits(total_tokens=...)

[sessions]
backend = "file"                          # memory | file (under TAU_DATA_DIR/sessions); the store stays on the hub (ADR 0006)

[hub]
control_port = 7877
heartbeat_seconds = 5

[ui]
language = "en"                           # en | tr: chrome of the terminal and the TUI (commands, notices, approval prompt).
                                          # TAU_LANG or `tau --lang` override it; /lang switches it for one run.

# Components (see `tau components`): switch discovered parts on or off without uninstalling.
# Unknown keys in these tables are an error (a typo must not leave a tool switched on);
# a name nothing installed provides is a `tau doctor` warning.
# [components]
# context = []                            # enabled tau.context sources; empty = every discovered one
# [components.tools]
# disabled = ["demo_physical_action", "dist:tau-example-tool"]   # tool names or dist:<distribution>
# [components.hub]
# services = []                           # enabled tau.hub_services; empty = every discovered one
#
# Free tables for a component's own settings, read with Config.component("name"):
# [component.telegram]
# poll_timeout_seconds = 50
```

`tau init`, `anthropic` sağlayıcısı için onu değiştirmeden yazar. Başka bir sağlayıcı için yalnızca `brain` ve `fast` rollerinin `provider` ve `model_id` değerlerini, paketle gelen `models.toml` tablosundaki model id'leriyle yeniden yazar: `openai` için `gpt-6.1-sol` / `gpt-6-luna`, `gemini` için `gemini-3.5-flash` / `gemini-3.1-flash-lite`, `bedrock` için `global.anthropic.claude-sonnet-5` / `global.anthropic.claude-haiku-4-5`, `fake` için `fake-brain` / `fake-fast`. tau bütçeleri her sağlayıcı için uyguladığından bütçe tabloları kalır; `local` de failover'ıyla birlikte Ollama'da kalır.

## Karşılaşabileceğin hatalar { #errors-you-may-see }

Bütün `ConfigError` mesajları düz İngilizcedir, çünkü henüz hiçbir kanal yokken fırlatılırlar:

| Mesaj | Neden |
|---|---|
| `Configuration file not found: <path>. Set TAU_HOME or run from the repository root.` | çözümlenen kökte `tau.toml` yok |
| `tau.toml: [models.roles.brain] needs a 'provider'.` | zorunlu bir anahtar eksik |
| `tau.toml: [models.roles.brain] has unknown keys: model.` | bir rol tablosunun içinde yazım hatası |
| `tau.toml: unknown provider for role 'brain': 'x'. Valid values: …` | hiçbir dağıtımın bildirmediği bir sağlayıcı |
| `tau.toml: [models.roles.brain] 'budget' must be a table.` | tablo yerine `budget = 15` |
| `tau.toml: [models.roles.brain] 'budget' has unknown keys: cap.` | bütçenin içinde yazım hatası |
| `tau.toml: [models.roles.brain] 'budget' needs 'usd', a positive number of dollars.` | `usd` eksik, sıfır, negatif ya da sayı değil |
| `tau.toml: [models.roles.brain] 'budget' needs 'period', one of day, week, month.` | `period` eksik ya da başka bir biçimde, örneğin `"1mo"` |
| `tau.toml: [models.roles.brain] 'budget' 'degrade_to' must be the name of a role.` | `degrade_to` boş ya da string değil |
| `tau.toml: [models.roles.brain] 'budget.degrade_to' cannot name the role itself.` | `brain` üzerinde `degrade_to = "brain"` |
| `tau.toml: [models.roles.brain] 'budget.degrade_to' names 'cheap', which is not a defined role.` | `degrade_to`, dosyanın tanımlamadığı bir rolü gösteriyor |
| `tau.toml: [models.roles.brain] 'failover' must be the name of a role.` | `failover` boş ya da string değil |
| `tau.toml: [models.roles.brain] 'failover' cannot name the role itself.` | `brain` üzerinde `failover = "brain"` |
| `tau.toml: [models.roles.local] 'failover' names 'cheap', which is not a defined role.` | `failover`, dosyanın tanımlamadığı bir rolü gösteriyor |
| `tau.toml: [models.roles.brain] stand-ins loop: brain → fast → brain (budget.degrade_to and failover together).` | bir role geri dönen `degrade_to` ve `failover`; örneğin `brain` `fast`'e düşüyor ve `fast` `brain`'e failover yapıyor |
| `tau.toml: [models.roles.brain.fallback] cannot have a 'budget'; set it on the role.` | bir `fallback` tablosunun içinde bütçe (`failover` için de aynısı) |
| `tau.toml: [models.prices."my-model"] needs 'input' and 'output' (dollars per million tokens).` | `input` ya da `output` içermeyen bir fiyat tablosu |
| `tau.toml: [models.prices."my-model"] has unknown keys: cached.` | bir fiyat tablosunun içinde yazım hatası |
| `tau.toml: [models.prices."my-model"] 'input' must be a number of dollars, 0 or more.` | negatif ya da sayısal olmayan bir fiyat |
| `tau.toml: [agent] 'context' must be one of sliding, summarize, not 'auto'.` | bir SDK hazır ayarı ya da yazım hatası |
| `tau.toml: [components.tools] has unknown keys: disable.` | yanlış yazılmış bir anahtar |
| `TAU_LANG must be one of en, tr, not 'de'.` | desteklenmeyen bir dil |
| `Session <id> was recorded with a different [agent] context setting; set it back to sliding or start a new session` | `context` değiştirildikten sonra sürdürme |
