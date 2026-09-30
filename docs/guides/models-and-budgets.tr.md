<!-- tr twin of guides/models-and-budgets.md, translated 2026-09-30 -->

# Modeller ve bütçeler

tau'nun kodu hiçbir zaman bir modelin adını vermez. Bir **rol** ister (`brain`, `fast`, `local`), hangi sağlayıcının ve model id'sinin o rolü karşılayacağını da `tau.toml` söyler. tau sağlayıcıyı `.env` içindeki kendi anahtarınla doğrudan çağırır ya da Ollama üzerinden yerel bir model kullanır; yanında çalıştırman gereken hiçbir şey yok. Maliyetleri de kendisi tutar: her yanıtın token kullanımı fiyatlandırılır ve hub'daki (tau'nun çalıştığı, sana ait makine) küçük bir harcama defterine (ledger) yazılır; **bütçesi** olan bir rol de gün, hafta ya da ay için belirlenen üst sınırında durur.

Karar [ADR 0011](../adr/0011-budgets-in-tau-no-litellm.md)'de. Bu rehber işin kullanıcı tarafı: bir sağlayıcı seç, üç rolü anla, üst sınırları ayarla, harcamayı gör ve bir bütçe bittiğinde ya da bir modele ulaşılamadığında ne olacağını bil.

```text
brain, fast ──► Anthropic, OpenAI or Gemini API    (your key from .env)
local       ──► Ollama, this machine or the Mac over the tailnet
                  └─ not reachable ──► fast answers instead   (failover)

every answer ──► priced (prices.toml) ──► TAU_DATA_DIR/spend.sqlite3
before a call: budget spent? ──► degrade_to answers, or tau says when it resets
```

## Sağlayıcılar ve anahtarları

| Sağlayıcı | Kimlik bilgileri (`.env` içinde) | Notlar |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | Bir workspace'e bağlı olmayan bir anahtar ayrıca `ANTHROPIC_WORKSPACE_ID` ister (Console → Settings → Workspaces); o olmadan API 400 döner. `params.base_url` başka bir API taban URL'si ayarlar. Rolün `cache` tablosuna uyar. |
| `openai` | `OPENAI_API_KEY` | `params.base_url` onu OpenAI uyumlu herhangi bir API'ye yönlendirir. Rolün `max_tokens` değeri, güncel OpenAI modellerinin beklediği `max_completion_tokens` olarak gönderilir. |
| `gemini` | `GEMINI_API_KEY` ya da `GOOGLE_API_KEY` | Strands'in `GeminiModel` sınıfı (`google-genai` SDK'sı) üzerinden Google Gemini. `max_tokens`, `max_output_tokens` olarak gönderilir. |
| `ollama` | yok | Yerel bir model. Sunucu, rolün `params.base_url` değeridir; o yoksa `TAU_OLLAMA_URL`, o da yoksa `http://127.0.0.1:11434` (`/v1` olmadan; tau onu kendisi ekler). Hızlı başarısız olur: 3 saniyelik bağlantı zaman aşımı ve yeniden deneme yok. Ücretsiz. |
| `bedrock` | `AWS_REGION` + `AWS_PROFILE`, ya da `AWS_REGION` + `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`, ya da `AWS_REGION` + `AWS_BEARER_TOKEN_BEDROCK` | İsteğe bağlı. Model id'leri `global.` önekli Converse biçimini kullanır. Roldeki bir `region`, `AWS_REGION` ihtiyacını ortadan kaldırır. `cache`'e uyar. |
| `fake` | yok | Testlerin senaryolu modeli: `Okay.` ya da rolün `params.replies` değeriyle yanıt verir. Ücretsiz. |

`params.api_key_env`, `anthropic`, `openai` ya da `gemini` anahtarı için başka bir değişken adı belirtir; örneğin yan yana iki OpenAI uyumlu sağlayıcı:

```toml
[models.roles.fast]
provider = "openai"
model_id = "my-model"
params = { base_url = "https://llm.example.com/v1", api_key_env = "EXAMPLE_LLM_KEY" }
```

Anahtarlar `tau.toml` içine değil, `<TAU_HOME>/.env` dosyasına girer (dosyayı `0600` modunda tut); adlar `.env.example` içinde. `tau chat` içindeki `/settings set NAME` ve TUI'nin **Credentials** bölümü, gizli bir istemle onları senin yerine yazar. Eksik bir anahtar, `tau chat`'i değişkenin adını söyleyerek durdurur; `tau doctor` ise hiçbir şey başlatmadan bunu bildirir. [Ortam değişkenleri referansı](../reference/environment.md#model-credentials) her değişkeni listeler.

## `tau init` ile kur

`tau init`, anahtarını ortamda ya da `<home>/.env` içinde bulduğu ilk sağlayıcıyı seçer: önce Anthropic, sonra OpenAI, sonra Gemini, sonra Bedrock; hiçbiri yoksa kimlik bilgisi gerektirmeyen `fake`. `--provider anthropic|openai|gemini|bedrock|fake` ile birini kendin seçersin.

```sh
tau init
```

```text
Provider: anthropic. ANTHROPIC_API_KEY was found in the environment or ~/.tau/.env. tau.toml caps brain and fast with budgets tau enforces itself (`tau spend` shows them), and local uses Ollama on this machine, falling back to fast when it is not running.
```

Hazır gelen `tau.toml` dosyasını yazar ve `brain` ile `fast` rollerinin yalnızca `provider` ve `model_id` değerlerini, tau-core ile gelen bir tablodaki (`templates/models.toml`) id'lerle yeniden yazar:

| Sağlayıcı | `brain` | `fast` |
|---|---|---|
| `anthropic` | `claude-sonnet-5` | `claude-haiku-4-5` |
| `openai` | `gpt-6.1-sol` | `gpt-6-luna` |
| `gemini` | `gemini-3.5-flash` | `gemini-3.1-flash-lite` |
| `bedrock` | `global.anthropic.claude-sonnet-5` | `global.anthropic.claude-haiku-4-5` |
| `fake` | `fake-brain` | `fake-fast` |

Bütçe tabloları olduğu gibi kalır (tau onları her sağlayıcı için uygular), `local` da Ollama'da kalır. Sağlayıcıları karıştırmak için, örneğin `brain` Anthropic'te ve `fast` Gemini'de, rol tablolarını elle düzenle, `tau chat` içinde `/settings model fast gemini gemini-3.1-flash-lite` kullan ya da TUI'nin ayarlar ekranındaki **Model roles** bölümünü kullan. Var olan bir köke bir anahtar ekledikten sonra `tau init --force`, `tau.toml` dosyasını ona göre yeniden yazar; `--force` ayrıca `persona/persona.md` dosyasını da yeniden yazar, o yüzden o dosyayı değiştirdiysen rolleri elle düzenle.

## Roller

| Rol | Hazır gelen model | Ne için kullanılır | Bütçe | Yanıt veremediğinde |
|---|---|---|---|---|
| `brain` | Anthropic `claude-sonnet-5`, `max_tokens = 4096` | konuşma ve planlama; `tau chat` ve `tau tui` onunla başlar | ayda 15 $ | bittiğinde: ayın 1'ine kadar `fast` yanıt verir |
| `fast` | Anthropic `claude-haiku-4-5`, `max_tokens = 1024` | ön eleme ve özetler; `/model fast` | günde 1 $ | bittiğinde: tau ne zaman sıfırlanacağını söyler |
| `local` | Ollama `qwen3.5:9b`, `max_tokens = 1024` | makinelerinden hiç çıkmayan, cihaz üzerindeki yanıtlar | yok (ücretsiz) | ulaşılamadığında: `fast` yanıt verir |

Hazır gelen tablolar (dosyanın tamamı [tau.toml referansında](../reference/tau-toml.md#the-shipped-file)):

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

Üç ayar başka bir rolün devreye girmesini sağlar ve üçü aynı şey değildir:

| Ayar | Ne zaman | Ne zaman kontrol edilir |
|---|---|---|
| `budget.degrade_to = "<role>"` | rolün bütçesi bu dönem için bitti | her çağrıdan önce |
| `failover = "<role>"` | rolün modeline ulaşılamıyor | her çağrıda |
| `fallback = { provider, model_id, … }` | rolün sağlayıcısının kimlik bilgileri yok | bir kez, ajan kurulurken |

`degrade_to` (bütçesi biten rolün çağrılarını başka bir role bırakması, yani düşürme ya da degrade) ve `failover` (ulaşılamayan bir rolün çağrıyı başka bir role devretmesi), dosyada tanımlı başka bir rolü göstermeli ve rolden role izlendiklerinde başladıkları yere geri dönmemeli (`brain`'in `fast`'e düşürüldüğü, `fast`'in de failover ile `brain`'e geçtiği bir zincir reddedilir). Devreye giren rol sıradan bir roldür: kendi bütçesi ve failover'ı geçerlidir, harcaması da kendi adı altında sayılır.

## Bütçeler

Bütçe, `tau.toml` içinde rolün altındaki bir tablodur (satır içi `budget = { usd = 1, period = "day" }` da olur):

| Anahtar | Anlamı |
|---|---|
| `usd` | Dönem başına dolar, pozitif bir sayı. |
| `period` | `day`, `week` ya da `month`: Europe/Istanbul saatine göre takvim dönemleri. Gün gece yarısı, hafta pazartesi 00:00'da, ay ayın 1'inde 00:00'da sıfırlanır. |
| `degrade_to` | İsteğe bağlı. Bu bütçe bittiğinde sıfırlanana kadar yanıt veren başka bir rol. Vermezsen tau turu bitirir ve bütçenin ne zaman sıfırlanacağını söyler. |

tau bütçeyi şöyle tutar:

- Bütçeli bir rolün **her çağrısından önce** tau, rolün dönem başından beri harcadığını toplar. Üst sınırda ya da üstündeyse çağrı sağlayıcıya hiç ulaşmaz: ya `degrade_to` yanıt verir ya da tur tek bir cümleyle biter.
- **Her yanıttan sonra** tau, sağlayıcının bildirdiği token kullanımını fiyatlandırır ve deftere bir satır yazar. Kontrol çağrıdan önce yapıldığı için üst sınırdan önceki son yanıt, harcamayı sınırın birkaç sent üstüne çıkarabilir.
- **Hub başına bir defter.** `TAU_DATA_DIR/spend.sqlite3`, aynı veri dizinini kullanan her süreç tarafından paylaşılır: Telegram kanalıyla hub, `tau chat`, `tau tui`. Bütçe, hangi kanaldan gelirse gelsin her çağrıyı sayar. Defter her çağrının zamanını, rolünü, sağlayıcısını, model id'sini, token sayılarını ve dolar tutarını tutar, asla metin tutmaz ve `0600` moduyla oluşturulur.
- **Her sağlayıcı.** Bütçeler `anthropic`, `openai`, `gemini` ve `bedrock` üzerinde aynı çalışır; `ollama` ve `fake` çağrılarının maliyeti 0 $'dır.
- **Yalnızca `budget` ya da `failover` içeren roller ölçülür.** İkisi de olmayan bir rol defter olmadan çağrılır; `tau spend` onu `no budget (its calls are not counted)` olarak gösterir. Bir rolün harcamasını gerçekten sınırlamadan saymak için ona yüksek bir üst sınır ver.

**Bir üst sınırı değiştir:** `tau.toml` içindeki sayıyı düzenle ve tau'yu çalıştıran şeyi yeniden başlat. Çalışan bir hub, `tau chat` ya da `tau tui` dosyayı başlarken okur; o yüzden hub'ı yeniden başlat (`tau hub stop`, sonra yeniden başlat ya da TauBar'da **Run the hub** kutusunun işaretini kaldırıp yeniden işaretle) ve terminal kanallarını yeniden aç. `tau spend` ve `tau doctor` dosyayı her seferinde okur, dolayısıyla yeni sınırı hemen gösterir. Harcamanın kendisi bir değişiklikle asla sıfırlanmaz: yeni bir sınır, rolün bu dönem zaten harcadığına uygulanır.

## Bir bütçe bittiğinde

tau biten bir bütçeyi arayüz dilinde (`[ui] language = "tr"` ile Türkçe) tek bir cümleye çevirir, asla bir stack trace göstermez. Terminal, TUI ve Telegram aynı metni gösterir.

`degrade_to` varsa devreye giren rol yanıt verir ve yanıt bir bildirimle biter:

```text
The brain budget is spent until 01.10.2026 00:00; fast answered instead.
```

`degrade_to` yoksa tur, hiçbir çağrı yapılmadan biter:

```text
The brain budget is spent ($15.00 of $15.00) and resets at 01.10.2026 00:00. To raise the cap, change it in tau.toml.
```

Devreye giren rolün bütçesi de bittiğinde:

```text
The brain budget is spent until 01.10.2026 00:00, and fast, which stands in for it, is spent too until 01.10.2026 00:00.
```

Saatler Europe/Istanbul'a göredir. Hub logu (`<TAU_DATA_DIR>/logs/tau.log`), düşürülen (degrade edilen) her çağrıyı bir uyarı olarak kaydeder; örneğin `role brain: budget spent ($15.02 of $15.00, resets 2026-10-01T00:00:00+03:00); fast answers instead`.

## Failover ve local rolü

`failover = "<role>"`, modele **herhangi bir şey akmadan önce** ulaşılamadığında çağrıyı başka bir role devreder:

- bağlantı reddedildiğinde (Ollama çalışmıyor): hemen;
- hiçbir şey yanıt vermediğinde (uyuyan bir Mac, evden uzakta bir dizüstü): `ollama` sağlayıcısının 3 saniyelik bağlantı zaman aşımından sonra;
- sağlayıcı 5xx bir hatayla yanıt verdiğinde.

Hız sınırlaması (429) asla failover'a gitmez; Strands onu yeniden dener. Yanıt başladıktan sonraki bir hata da (devreye giren rol yarım bir yanıtı tekrarlardı) ya da Ollama'da olmayan bir model gibi başka herhangi bir ret de öyle. Bu durumda yanıt şununla biter:

```text
local is not reachable right now; fast answered instead.
```

hub logunda da `role local: ollama qwen3.5:9b is not reachable (…); fast answers instead` gibi bir uyarı bulunur. Uyuyan ya da uzakta olan bir Mac'teki hazır `local` rolüne yaklaşık 3 ila 6 saniye içinde `fast` yanıt verir. Her rolün bir failover'ı olabilir: `brain`'in `failover` değerini başka bir sağlayıcıdaki bir role yönlendirmek, `brain`'in sağlayıcısı çöktüğünde tau'nun o rolün bütçesi içinde yanıt vermeye devam etmesini sağlar.

### Ollama'yı kur { #set-up-ollama }

1. Mac'e [Ollama](https://ollama.com) kur ve modeli indir:

    ```sh
    ollama pull qwen3.5:9b
    ```

2. Önerilen yerel model `qwen3.5:9b`: Türkçede iyi yanıt verir. `params = { reasoning_effort = "none" }` ondan önce akıl yürütmek yerine hemen yanıt vermesini ister; böylece kısa bir yanıt yaklaşık iki saniye sürer. İndirdiğin başka herhangi bir model de çalışır: Ollama'daki adını `model_id` içine yaz.
3. **Hub Mac'teyse:** ayarlanacak bir şey yok; tau Ollama'ya `127.0.0.1:11434` üzerinden ulaşır.
4. **Hub başka bir yerdeyse** (bir [Raspberry Pi](raspberry-pi.md)): hub'ın `.env` dosyasına Mac'in adresini yaz,

    ```sh
    TAU_OLLAMA_URL=http://my-mac.tailXXXXXX.ts.net:11434
    ```

    ve Mac'teki Ollama'nın asla her arayüzü değil, yalnızca kendi tailnet adresini dinlemesini sağla: ona ulaşması gereken tek ağ tailnet'tir ([ADR 0006](../adr/0006-private-first-topology.md)). Ollama uygulaması için bu, `launchctl setenv OLLAMA_HOST 100.x.y.z:11434` ve uygulamanın yeniden başlatılması demek; bir terminaldeki `ollama serve` için ise `OLLAMA_HOST=100.x.y.z:11434 ollama serve`.

Ollama çağrıları ücretsizdir ve `local`'a giden bir prompt makinelerinden asla çıkmaz. Mac uzaktayken `local`'ın soruları `fast`'e gider ve `fast`'in bütçesinden düşer.

## Fiyatlar { #prices }

tau bir yanıtı, model id'sine göre anahtarlanmış, milyon token başına ABD doları tutan bir tabloyla fiyatlandırır. tau-core bir tane ile gelir (`templates/prices.toml`, sağlayıcıların 2026-09-30 tarihli fiyat sayfalarından):

| Model id | Girdi | Çıktı | Önbellek okuma | Önbellek yazma |
|---|---|---|---|---|
| `claude-sonnet-5`, `claude-sonnet-5-5`, `global.anthropic.claude-sonnet-5` | 2.00 | 10.00 | 0.20 | 2.50 |
| `claude-haiku-4-5`, `claude-haiku-4-5-20251001`, `global.anthropic.claude-haiku-4-5` | 1.00 | 5.00 | 0.10 | 1.25 |
| `claude-opus-5-5` | 4.00 | 20.00 | 0.20 | 5.00 |
| `gpt-6.1-sol` | 2.00 | 10.00 | 0.10 | – |
| `gpt-6-sol` | 2.00 | 10.00 | 0.20 | – |
| `gpt-6-luna` | 0.10 | 0.50 | 0.01 | – |
| `gemini-3.5-flash` | 1.50 | 9.00 | 0.15 | – |
| `gemini-3.1-flash-lite` | 0.25 | 1.50 | 0.025 | – |
| `gemini-2.5-pro` | 1.25 | 10.00 | 0.125 | – |

Tire, tablonun dışarıda bıraktığı bir fiyattır; onun yerine girdi fiyatı geçerli olur. `tau.toml` tabloyu model id'si başına genişletir ya da ezer:

```toml
[models.prices."my-model"]
input = 0.5            # $ per million input tokens (required)
output = 1.5           # $ per million output tokens (required)
cache_read = 0.05      # optional; defaults to input
cache_write = 0.625    # optional; defaults to input
```

- Aynı id için `tau.toml` içindeki fiyat, hazır gelen fiyata üstün gelir. Değerler dolardır, 0 ya da daha büyük; bilinmeyen bir anahtar hatadır.
- İki tabloda da olmayan bir model **fiyatsızdır**: çağrıları deftere maliyetsiz girer ve 0 $ sayılır, dolayısıyla onun üzerindeki bir bütçeye asla ulaşılmaz. `tau doctor`, fiyatsız bir model üzerindeki her bütçeli rol için uyarır; `tau spend` de fiyatsız çağrılarını sayar.
- Anthropic ve Bedrock önbellekten gelen token'ları girdi token'larından ayrı bildirir; OpenAI ve Gemini ise onları girdiye dahil eder. tau bunu hesaba katar; böylece önbellekteki bir token bir kez, kendi önbellek fiyatıyla fiyatlandırılır.
- Uzun bağlam ek ücretleri (200 bin token'ın üstü) modellenmez. Defter tau'nun tahminidir; gerçeği sağlayıcının faturası söyler.

## Harcamayı gör

**`tau spend`** her rolü bütçesiyle karşılaştırarak, defterden okuyup yazdırır (betikler için `--json`):

```text
  brain    anthropic $0.42 of $15.00 this month, resets 01.10.2026 00:00
  fast     anthropic $0.03 of $1.00 today, resets 01.10.2026 00:00
  local    ollama    $0.00 this month, no budget
```

Bütçesi biten bir rol `· SPENT` ile işaretlenir (düşürülüyorsa `, fast answers instead` ile birlikte), fiyatsız bir model üzerinde çağrıları olan bir rol de `· N calls without a price for <model id>` ile. JSON çıktısı [CLI referansında](../reference/cli.md#tau-spend).

Terminalde, TUI'de ya da Telegram'da **`/status`**, defterden o anda okunan aynı sayılarla biter:

```text
Budget: brain $0.42 of $15.00 this month (resets 01.10.2026 00:00); fast $0.03 of $1.00 today (resets 01.10.2026 00:00)
```

**Model** bu satırı sistem prompt'unda `## Now` altında `- Budget: …` olarak görür; böylece sana ne kadar kaldığını söyleyebilir (`budget` bağlam kaynağı; bir çağrıdan önce rol başına bir yerel sorgu, ağ yok). `tau.toml` içinde hiç bütçe yoksa satır `- Budget: unknown` olur.

**`tau doctor`** bunu `budget` satırı olarak yazdırır:

```text
ok   budget: brain $0.00 of $15.00 this month (resets 01.10.2026 00:00); fast $0.00 of $1.00 today (resets 01.10.2026 00:00)
```

**Hub** bunu kontrol API'sinde (yalnızca loopback) `GET /spend` olarak sunar. Bu route korumalıdır: istek hub'ın kontrol token'ıyla imzalanmalıdır ([ADR 0008](../adr/0008-owner-guard.md)), bu yüzden düz bir `curl` 403 alır. Açık `GET /status` aynı nesneyi `spend` altında taşır; tau-core'un `HubClient`'ı ise korumalı route'u senin yerine imzalar:

```sh
curl -s 127.0.0.1:7877/status | python3 -c 'import json, sys; print(json.dumps(json.load(sys.stdin)["spend"], indent=2))'
uv run python -c 'from tau_core import Config; from tau_core.hub import HubClient; print(HubClient(Config.load()).get("/spend", timeout=5))'
```

```json
{
  "roles": {
    "brain": {
      "provider": "anthropic",
      "model_id": "claude-sonnet-5",
      "spent_usd": 0.42,
      "cap_usd": 15.0,
      "period": "month",
      "since": "2026-09-01T00:00:00+03:00",
      "reset_at": "2026-10-01T00:00:00+03:00",
      "exhausted": false,
      "degrade_to": "fast",
      "unpriced_calls": 0,
      "metered": true
    }
  }
}
```

`tau.toml` içindeki her rolün bir girdisi vardır; bütçesi olmayan bir rolün `"cap_usd": null` değeri olur ve mevcut ay için raporlanır.

## Sağlayıcının kendi sınırı

Sağlayıcının konsolunda da aylık bir harcama sınırı ayarla (Anthropic Console'daki workspace sınırları ya da OpenAI veya Google'ın faturalama sınırları). Bu son savunma hattıdır: tau, aynı anahtarla tau dışında yapılan çağrıları göremez, bütçesi olmayan bir rol sayılmaz ve fiyat tablosu bir fiyat değişikliğinin gerisinde kalabilir.

## Sorun giderme

| Gördüğün | Yapılacak |
|---|---|
| `fail role brain: provider 'anthropic' is missing ANTHROPIC_API_KEY (names are in .env.example)` | Anahtarı `<TAU_HOME>/.env` dosyasına ekle (ya da `/settings set ANTHROPIC_API_KEY`), sonra tau'yu yeniden başlat. |
| `warn role brain: has a budget, but model 'my-model' has no price, so its calls count as $0; add [models.prices."my-model"] to tau.toml` | Yukarıda gösterilen fiyat tablosunu ekle. |
| Her `local` turunda `local is not reachable right now; fast answered instead.` | Ollama çalışmıyor ya da tau'nun baktığı yerde değil. Mac'te `curl http://127.0.0.1:11434/api/tags` (ya da hub'dan `TAU_OLLAMA_URL` adresi) modeli listelemeli; Ollama'yı başlat, `TAU_OLLAMA_URL` değerini ve Ollama'nın tailnet adresini dinlediğini kontrol et. |
| `local` üzerinde eksik bir modelden söz eden bir model hatası | `ollama pull qwen3.5:9b` ya da `model_id` içindeki ad. Ollama'da olmayan bir model failover'a gitmez. |
| Anthropic'ten, bir workspace'e bağlı olmayan bir anahtarla ilgili 400 | `ANTHROPIC_WORKSPACE_ID` ayarla. |
| `tau.toml` içindeki yeni bir sınır `tau spend` içinde görünüyor ama tau hâlâ eskisinde duruyor | Hub'ı yeniden başlat ve `tau chat` / `tau tui`'yi yeniden aç; `tau.toml` dosyasını başlarken okurlar. |
| `tau.toml: [models.roles.brain] 'budget' needs 'period', one of day, week, month.` | Eski bir dosyadan kalma `period = "1mo"` ya da `"1d"`: `"month"` ya da `"day"` yaz. |
| `tau.toml: [models.roles.brain] stand-ins loop: brain → fast → brain (budget.degrade_to and failover together).` | Zincir bitsin diye devreye giren iki rolden birini kaldır. |
| `warn .env: names in .env that .env.example does not list: …` | Artık kullanmadığın bir değişken: onu `.env` dosyasından sil ya da hâlâ gerekiyorsa adını `.env.example` dosyasına ekle. |
| Sağlayıcının konsolu `tau spend`'den fazlasını gösteriyor | Aynı anahtarla tau dışında yapılan çağrılar, bütçesi olmayan bir rol ya da değişmiş bir fiyat. Konsoldaki sınırı kontrol et. |
