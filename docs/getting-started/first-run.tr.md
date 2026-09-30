<!-- tr twin of getting-started/first-run.md, translated 2026-09-30 -->

# İlk çalıştırma

tau'yu kurmanın iki yolu var. Hızlısı arayüzün içinden: yapılandırması olmayan bir makinede `tau tui` bir kurulum ekranı açar, sonrasında da `/settings` (ya da F10) her şeyi düzenler. Diğeri dosyalar üzerinden: `tau init` onları yazar, sen `tau.toml` ve `.env` dosyalarını elle düzenlersin, `tau doctor` da kontrol eder. İkisi de aynı iki dosyada biter, yani bunları gönlünce karıştırabilirsin. Bu sayfa önce arayüzü, sonra dosyaları, ardından satır satır `tau doctor` çıktısını ve ilk konuşmayı gösterir.

## Arayüzde: `tau tui` { #in-the-interface-tau-tui }

```sh
tau tui
```

Hiçbir yerde (`TAU_HOME`, geçerli dizin, `~/.tau`) `tau.toml` yoksa sohbet yerine kurulum ekranı açılır:

```text
 ╭──────────────────────────────────────────────────────────────╮
 │ ◆ Welcome to tau · first run                                 │
 │                                                              │
 │ Nothing is configured yet. Pick a home directory, the model  │
 │ provider and the UI language; tau writes tau.toml and the    │
 │ persona files there.                                         │
 │                                                              │
 │ home directory  ~/.tau                                       │
 │ provider        anthropic · credentials found             ▼  │
 │ UI language     en                                        ▼  │
 │                           Create                             │
 │ tab fields · enter / ctrl+s / F2 create · esc quit           │
 ╰──────────────────────────────────────────────────────────────╯
```

- **home directory**, `tau.toml`, `.env` ve `persona/` dosyalarının gideceği yerdir; `TAU_HOME` ya da `tau --home` başka bir şey söylemedikçe `~/.tau`. İçinde zaten bir `tau.toml` bulunan dizin olduğu gibi kullanılır.
- **provider** (sağlayıcı), `tau init`'in yaptığı gibi ortamdan ve `<home>/.env` dosyasından algılanır: `ANTHROPIC_API_KEY` varsa `anthropic`, yoksa `OPENAI_API_KEY` varsa `openai`, yoksa `GEMINI_API_KEY` ya da `GOOGLE_API_KEY` varsa `gemini`, yoksa AWS kimlik bilgileri varsa `bedrock`, hiçbiri yoksa `fake` (anahtar gerekmez, senaryolu yanıtlar). İstersen değiştir.
- **UI language** (arayüz dili) değiştirdikçe ekranın etiketlerini de değiştirir.

**Create**, `tau init` ile aynı kodu çalıştırır, ardından sohbet yeni home dizininde açılır. Esc hiçbir şey yazmadan çıkar (çıkış kodu 2; eksik yapılandırmadaki ile aynı).

Yapılandırma var ama rolün sağlayıcısının kimlik bilgileri yoksa `tau tui` yine de açılır: ayarlar ekranı **Credentials** bölümünde, eksik değişkenler `◆ needed` ile işaretlenmiş hâlde gelir, yazma alanı *Add credentials in /settings* der ve bir kaydetme sağlayıcıya anahtarını verdiği anda sohbet başlar. Fallback sağlayıcısıyla (birincil sağlayıcının kimlik bilgisi yokken devreye giren yedek sağlayıcı; tanımladıysan) çalışan bir rol, tek satırlık bir bildirimle duyurulur (`brain: using the fallback provider anthropic (bedrock has no credentials). Add them in /settings.`).

`/settings` (Türkçe takma adı `/ayarlar`) ya da F10 aynı düzenleyiciyi istediğin zaman açar:

```text
 τ tau  home · 20260929-120000-abcd                                  brain · en
 ╭────────────────────────────────────────────────────────────────────────────╮
 │ ◆ Settings                                                                 │
 │                                                                            │
 │ Model roles        brain                                                   │
 │ Credentials        provider     anthropic                              ▼   │
 │ Interface          model id     claude-sonnet-5                            │
 │ Agent              max tokens   4096                                       │
 │ Doctor             fallback     (none)                                 ▼   │
 │ Files              fallback id                                             │
 │                    ✓ credentials ok                                        │
 │                                                                            │
 │                    fast                                                    │
 │                    …                                                       │
 │ ↑↓ section · tab fields · ctrl+s / F2 save · esc close                     │
 ╰────────────────────────────────────────────────────────────────────────────╯
```

| Bölüm | Neyi düzenlersin |
|---|---|
| Model roles | Rol başına: sağlayıcı (kurulu her sağlayıcı; sonraki bir issue'nun yapacağı planlanmış bir sağlayıcı bir notta listelenir ve seçilemez), model id, max tokens, isteğe bağlı bir fallback sağlayıcısı ve model id'si, ve rolün kimlik bilgisi durumu (`credentials ok`, `missing ANTHROPIC_API_KEY`, `missing … · fallback anthropic in use`, `no credentials needed`). Bir rolün `budget` ve `failover` değerleri yalnızca `tau.toml` içinde düzenlenir. |
| Credentials | Yapılandırılmış sağlayıcıların ihtiyaç duyduğu her değişken, sonra diğer her sağlayıcınınkiler, sonra `.env.example` ve `.env` içindeki her ad. Her satır `set · sk-…abcd` ya da `not set` der; değişkeni kabuğun ayarlıyorsa `(from the environment; .env does not override it)` der. Anahtarlar, token'lar, secret'lar ve parolalar gizli bir girişle alınır; `TAU_OLLAMA_URL` ya da `TAU_PROFILE` gibi düz ayarlar görünür bir girişle. **clear** bir değeri kaldırır. Değerler yazdıktan sonra bir daha asla gösterilmez. |
| Interface | Arayüz dili (`en`/`tr`, kaydedince uygulanır) ve profil (`.env` içindeki `TAU_PROFILE`). |
| Agent | Dosyadaki kurallarla aynı şekilde `context`, `window_size`, `max_turns`, `max_total_tokens`. |
| Doctor | `✓`, `◆`, `✗` ve `▸` simgeleriyle `tau doctor` kontrolleri. |
| Files | `tau.toml`, `.env`, `.env.example`, `persona/persona.md` ve `persona/user.md` yolları, var olanlar için bir işaretle; persona dosyaları kendi editöründe düzenlenir ve bir sonraki turdan önce yeniden okunur. |

`ctrl+s` (mosh üzerinde `ctrl+s` akış denetimi tarafından yutulabildiği için F2) doğrular ve kaydeder: yapılandırmanın reddedeceği bir değer durum satırında bildirilir ve hiçbir şey yazılmaz; geçerli bir kaydetme `tau.toml` dosyasını yorumları bozulmadan ve `.env` dosyasını `0600` moduyla yazar, ardından bir rol, bir ajan seçeneği, bir kimlik bilgisi ya da profil değiştiyse ajanı aynı oturum üzerinde yeniden kurar (`Settings saved; model reloaded.`). Esc kaydetmeden kapatır. Burada hiçbir şey bir kimlik bilgisi değerini asla açık hâlde yazdırmaz, loglamaz ya da saklamaz.

## Dosyalarda: `tau init`

Arayüzün yaptığı her şey terminalde de yapılabilir; `tau chat`'in de daha küçük bir `/settings` komutu var (bkz. [tau ile konuş](talk.md)). Dosyaları `tau init` yazar:

```sh
tau init
```

Seçenek verilmezse sihirbaz:

1. Yapılandırma kökünü belirler (`TAU_HOME`, yoksa `~/.tau`).
2. Ortamda ve `<root>/.env` içinde model kimlik bilgilerini arar. Bulursa o sağlayıcıyı kullanır ve anahtar hakkında bir şey sormaz.
3. Arayüz dilini sorar: `en` ya da `tr`. Bundan sonraki sorular o dildedir.
4. Hiçbir yerde kimlik bilgisi yoksa sağlayıcıyı (`anthropic`, `openai` ya da `gemini`) ve onun anahtarını sorar; anahtar gizli yazılır. Anahtarı sağlayıcıya tek bir küçük istekle dener: ücretsiz olan model listesi; anahtar yalnızca bir istek başlığında gider. Sağlayıcının reddettiği bir anahtar ya da yanıt alamayan bir deneme, `tau init`'i hiçbir şey yazılmadan durdurur. Boş bırakılan anahtar bu adımı atlar.
5. `tau.toml`, `persona/persona.md`, `persona/user.example.md`, `persona/user.md` ve `.env.example` dosyalarını yazar, ardından anahtarı `<root>/.env` dosyasının sonuna ekler. Dosya `0600` izniyle oluşturulur ya da bu izne çekilir; diğer satırları olduğu gibi kalır, orada zaten ayarlı bir anahtar korunur.

Kimlik bilgisi olmayan bir makinede ilk çalıştırma şöyle görünür (anahtar asla gösterilmez):

```text
UI language (en, tr) [en]: tr
Ortamda ya da <root>/.env içinde model anahtarı bulunamadı. tau'nun bir sağlayıcıdan anahtara ihtiyacı var (`tau init --yes` anahtarsız, senaryolu 'fake' sağlayıcıyı kurar).
Sağlayıcı (anthropic, openai, gemini) [anthropic]: openai
OPENAI_API_KEY (gizli; boş bırakırsan atlanır):
Anahtar openai sağlayıcısına tek bir küçük istekle deneniyor...
openai anahtarı kabul etti.
wrote <root>/tau.toml
wrote <root>/persona/persona.md
wrote <root>/persona/user.example.md
wrote <root>/persona/user.md
wrote <root>/.env.example
OPENAI_API_KEY, <root>/.env dosyasına yazıldı (izin 0600)
Configuration root: <root> (UI language: tr).
Next: edit persona/user.md, then run `tau doctor` and `tau chat`.
```

Her seçimin bir bayrağı var, böylece bir betik onu soru sormadan çalıştırabilir:

```sh
tau init --home ~/.tau --provider anthropic --language en --profile home --yes
```

| Seçenek | Etkisi |
|---|---|
| `--home DIR` | Oluşturulacak kök. Varsayılan: `TAU_HOME`, yoksa `~/.tau`. |
| `--provider NAME` | `brain` ve `fast` rolleri için sağlayıcı: `anthropic`, `openai`, `gemini`, `bedrock` ya da `fake`. Varsayılan: bu sırayla, kimlik bilgisi olan ilki. Yalnızca `brain` ve `fast` rollerinin `provider` ve `model_id` değerleri değişir; bütçeler ve `local` (Ollama; ulaşılamazsa `fast`'e failover yapar) geldiği gibi kalır. |
| `--language LANG` | Arayüz dili, `en` ya da `tr`. Verilmezse sorulur, `--yes` varsa sorulmaz. |
| `--profile NAME` | `<root>/.env` içinde ayarlı değilse oraya `TAU_PROFILE=NAME` ekler. |
| `--no-check` | Yazılan anahtarı sağlayıcıya bir istekle deneme (örneğin internete erişimi olmayan bir makinede). |
| `-y`, `--yes` | Hiçbir şey sorma; verilmeyen her şey için varsayılanları kullan. Anahtar sorulmaz; hiç kimlik bilgisi yoksa roller `fake` kullanır. |
| `--force` | Mevcut bir `tau.toml` ve `persona.md` dosyasının üzerine yaz. `user.md` ve `.env.example` asla ezilmez. |

`--provider anthropic`, `openai` ya da `gemini` verilir ve onun anahtarı yoksa `tau init` anahtarı da sorar (`--yes` yoksa). `bedrock` ve `fake` hiç sormaz: Bedrock'un kimlik bilgileri `.env` dosyasına elle girilir.

Hiçbir yerde kimlik bilgisi yokken `tau init --yes` şöyle biter (yollar kısaltılmıştır):

```text
Provider: fake. No model credentials were found in the environment or <root>/.env, so both roles use the scripted 'fake' provider. Add ANTHROPIC_API_KEY, OPENAI_API_KEY or GEMINI_API_KEY to <root>/.env (names are in <root>/.env.example) and run `tau init --force`, run `tau init --force` without --yes to type a key, or edit tau.toml.
wrote <root>/tau.toml
wrote <root>/persona/persona.md
wrote <root>/persona/user.example.md
wrote <root>/persona/user.md
wrote <root>/.env.example
Configuration root: <root> (UI language: en).
Next: edit persona/user.md, then run `tau doctor` and `tau chat`.
```

## Kimlik bilgisi olmadan dene

`fake` sağlayıcısı, `tau-core` ile gelen senaryolu bir modeldir. Anahtar gerektirmez, ağa hiç dokunmaz ve her şeye `Okay.` diye yanıt verir. Test paketi de böyle çalışır; REPL'i, TUI'yi, slash komutlarını, oturumları ve onay akışını görmek için yeterlidir.

```sh
tau init --provider fake --yes
tau chat
```

tau'ya herhangi bir şey sor, sonra `/tools`, `/status` ve `/sessions` komutlarını dene. Gerçek yanıtlar istediğinde kimlik bilgilerini ekle ve aşağıdan devam et.

## `.env` içinde kimlik bilgileri

tau kimlik bilgilerini ortamdan ve `<root>/.env` dosyasından okur. Kabuğunda zaten ayarlı olan bir değişken kazanır; dosya onu asla ezmez. `.env` senindir ve hiçbir deponun içine girmez; yanındaki `.env.example` yalnızca adları listeler.

Sağlayıcının anahtarını `.env` dosyasına koy, sonra rolleri ona göre `tau init --force` ile yeniden yazdır (`.env` dosyasında artık ne varsa ona bakarak bu sırayla Anthropic, OpenAI, Gemini, Bedrock seçer), TUI'de `/settings` içindeki **Model roles** bölümünü aç ya da `tau.toml` dosyasını elle düzenle:

=== "Anthropic"

    Gelen `tau.toml` dosyasının sağlayıcısı: `brain` Claude Sonnet 5, `fast` Claude Haiku 4.5.

    ```sh
    ANTHROPIC_API_KEY=sk-ant-...
    # Only for a key that is not scoped to a workspace (Console → Settings → Workspaces):
    # ANTHROPIC_WORKSPACE_ID=wrksp_...
    ```

=== "OpenAI"

    `brain` `gpt-6.1-sol`, `fast` `gpt-6-luna` olur. Bir roldeki `params.base_url` onu bunun yerine OpenAI uyumlu herhangi bir API'ye yönlendirir.

    ```sh
    OPENAI_API_KEY=sk-...
    ```

=== "Google Gemini"

    `brain` `gemini-3.5-flash`, `fast` `gemini-3.1-flash-lite` olur.

    ```sh
    GEMINI_API_KEY=...        # GOOGLE_API_KEY works too
    ```

=== "Amazon Bedrock (isteğe bağlı)"

    `AWS_REGION` ve üç kimlik bilgisi biçiminden biri:

    ```sh
    AWS_REGION=eu-central-1
    AWS_PROFILE=tau
    # or
    # AWS_ACCESS_KEY_ID=AKIAXXXXXXXXXXXXXXXX
    # AWS_SECRET_ACCESS_KEY=...
    # or
    # AWS_BEARER_TOKEN_BEDROCK=...
    ```

```sh
tau init --force          # picks anthropic > openai > gemini > bedrock from what .env now holds, else asks
tau doctor
```

Sağlayıcı hangisi olursa olsun `tau.toml` **bütçelerini** korur: `brain` ayda 15 $ harcayabilir, sonra işi `fast`'e devreder; `fast` ise günde 1 $. tau her yanıtı fiyatlandırır ve bütçeleri kendisi uygular; `tau spend` her rolün nerede durduğunu gösterir. **`local`** rolü bu makinedeki Ollama üzerinde kalır ve anahtar gerektirmez: kullanmak için [Ollama](https://ollama.com)'yı kur ve `ollama pull qwen3.5:9b` çalıştır; o zamana kadar onun yerine `fast` yanıt verir. Son savunma hattı olarak sağlayıcının konsolunda da aylık bir harcama sınırı belirle. Hepsini [Modeller ve bütçeler](../guides/models-and-budgets.md) anlatıyor.

Bir oturumun içinde `/settings set ANTHROPIC_API_KEY` (terminal) değeri ekrana yansıtmadan ister ve `.env` dosyasına yazar; TUI'nin **Credentials** bölümü de aynısını gizli bir girişle yapar.

Bir rolün kullanılabilir kimlik bilgisi yoksa `tau chat` başlamadan, çıkış kodu 2 ve eksik değişkenleri adlandıran bir mesajla durur; `tau tui` ise bunun yerine ayarlar ekranında açılır (bkz. yukarısı):

```text
Missing model credentials for role 'brain' (anthropic). Add these variables to .env: ANTHROPIC_API_KEY
Example names are in .env.example.
```

## Senin bilgilerin: `persona/user.md`

`persona/user.md`, tau'nun senin hakkında bildikleridir: sana nasıl hitap edeceği, adın, şehrin, çalışma saatlerin, tercihlerin. Uydurma örnekten oluşturulur ve asla ezilmez. O olmadan ya da boşken tau sana resmî hitap eder ve senin hakkında hiçbir şey bilmez.

Onu herhangi bir editörde düzenle. Değişiklik bir sonraki model çağrısında uygulanır; yeniden başlatılacak bir şey yok. Dosyadaki HTML yorumları senin için notlardır ve modele asla ulaşmaz.

!!! warning "Uyarı"
    `user.md` yaşam verisidir. Onu yapılandırma kökünde ve kontrol etmediğin herhangi bir deponun ya da eşitleme klasörünün dışında tut. [Yedekleme rehberi](../guides/backups.md) onu nasıl güvenle kopyalayacağını anlatıyor.

## Satır satır `tau doctor`

```sh
tau doctor
```

Bir checkout'ta (deponun yerel kopyası), `.env` içinde `ANTHROPIC_API_KEY` varken ama henüz bir `user.md` yazmadan önceki ilk çalıştırma:

```text
ok   config: <root>/tau.toml loaded
ok   role brain: provider 'anthropic', credentials present
ok   role fast: provider 'anthropic', credentials present
ok   role local: provider 'ollama', needs no credentials
ok   budget: brain $0.00 of $15.00 this month (resets 01.10.2026 00:00); fast $0.00 of $1.00 today (resets 01.10.2026 00:00)
ok   sessions: backend 'file' opens under ~/.local/share/tau/sessions
ok   persona: <root>/persona/persona.md present and non-empty
warn persona: <root>/persona/user.md is missing: tau addresses you formally and knows nothing about you (start from persona/user.example.md)
ok   .env: every name in .env is listed in .env.example
ok   components: every component loads
info hub: hub is not running (nothing answers on http://127.0.0.1:7877/health)
info telegram: not configured (TELEGRAM_BOT_TOKEN is not set)
12 checks: 9 ok, 1 warnings, 0 failed
```

Anahtar olmadan iki Anthropic rolü başarısız olur ve çıkış kodu 1'dir:

```text
fail role brain: provider 'anthropic' is missing ANTHROPIC_API_KEY (names are in .env.example)
fail role fast: provider 'anthropic' is missing ANTHROPIC_API_KEY (names are in .env.example)
ok   role local: provider 'ollama', needs no credentials
```

Ollama kurulu olmasa bile `role local` `ok` olur: `tau doctor` asla bir model çağırmaz ve Ollama'ya ulaşılamadığı sürece `local`'in failover'ı olan `fast` yanıt verir.

| Kontrol | Neyi doğrular | Ne zaman başarısız olur |
|---|---|---|
| `config` | `tau.toml` ayrıştırılabilir ve her sağlayıcı ve arka uç adı biliniyor. Bilinmeyen üst düzey tablolar bir uyarıdır. | Eksik ya da geçersiz bir dosya: `fail`, ve başka hiçbir kontrol çalışmaz. |
| `role <name>` | Her rolün sağlayıcısı var ve bir istemci kurmadan kimlik bilgilerine sahip. `warn`, fallback'in kullanılacağı, sağlayıcının planlanmış olduğu (sonraki bir issue onu yapacak) ya da rolün bir `budget` değeri olduğu ama modelinin fiyatı olmadığı, yani çağrılarının 0 $ sayılacağı anlamına gelir. | Birincil ya da fallback için kimlik bilgisi yok: `fail`, eksik adlarla birlikte. |
| `budget` | `tau.toml` içinde en az bir bütçe varsa: bütçeli her rolün kendi dönemindeki harcamasını, `TAU_DATA_DIR` altındaki defterden (ledger), sınırıyla karşılaştırır (`/status` ve `tau spend` ile aynı metin). | Defter okunamıyor: `fail`. |
| `sessions` | `[sessions] backend` açılıyor. `file` için dizini adlandırır. | Arka uç kendi deposunu açamıyor. |
| `persona` (iki kez) | `persona.md` var ve boş değil; `user.md` var. | Eksik ya da boş bir `persona.md` `fail`'dir; eksik bir `user.md` yalnızca `warn`. |
| `.env` | `.env` içindeki her ad `.env.example` içinde listeleniyor; böylece bir değişken adındaki yazım hatası yakalanır. `.env` yoksa `info`. | Asla; bilinmeyen adlar `warn`'dır. Susturmak için kendi adlarını `.env.example` dosyasına ekle. |
| `components` | Her `tau.*` entry point'i (eklenti kayıt noktası) yükleniyor. | Bozuk bir bileşen: dağıtım ve hatası yazdırılır. |
| `hub` | `http://127.0.0.1:<control_port>/health` adresinde bir hub (servis olarak çalışan tau) yanıt veriyor mu. Yalnızca bilgi amaçlı. | Asla. Bir şey hatayla yanıt verirse `warn`. |
| `telegram` | [Telegram](../guides/telegram.md) kanalı yapılandırılmış mı ve hub çalışıyorsa poller'ın durumu (`polling as @bot`, yeniden deniyor, durdu). Token yoksa `info`. | Bot API'nin reddettiği bir token: `fail`. Boş ya da geçersiz bir `TELEGRAM_ALLOWED_CHAT_IDS` ya da yeniden denemeyi sürdüren bir poller: `warn`. |

Çıkış kodu 1, en az bir `fail` olduğu anlamına gelir. `tau doctor --json` aynı kontrolleri betikler için JSON olarak yazdırır.

!!! tip "İpucu"
    `tau doctor` asla bir model başlatmaz, bir sağlayıcıya ağ bağlantısı açmaz ya da açtığı oturum dizini dışında hiçbir şey yazmaz. Yalnızca hub'a nasıl olduğunu sorar ve harcama defterini okur. İstediğin kadar sık çalıştır.

## İlk konuşman

```sh
tau chat
```

Açılış satırı profili ve yeni oturum id'sini söyler. Bir mesaj yaz; yanıt `tau>` altında akar. Araç çağrıları soluk, girintili satırlar olarak görünür:

```text
you> what time is it?
  ⚙ current_time (tier 0)
  ✓ current_time: 29.09.2026 17:38:26, Tuesday (Europe/Istanbul)
tau> It is 17:38 on Tuesday, 29 September.
```

tau tier-2 bir araç (fiziksel dünyada eylemde bulunan ve her zaman onay isteyen izin seviyesindeki bir araç) kullanmak istediğinde durur ve sorar. Gelen `demo_physical_action` aracı tam olarak bunu göstermek için var:

```text
⚠️  Approval needed (tier 2)
  Tool: demo_physical_action
  Arguments: {"action": "turn on the desk lamp"}
  Effect: Demo: simulates a physical action; no real device moves.
  Approve? [y/N]
```

`y`, `yes`, `e` ya da `evet` onaylar. Enter ve Ctrl-D dahil başka her şey reddeder; tau reddi okur ve sana kısaca söyler. Hiçbir şey asla kendiliğinden onaylanmaz. Kurallar [Tier'lar ve onaylar](../reference/tiers.md) sayfasında.

Her oturum ilk mesajdan itibaren diskte. `/sessions` onları listeler, `/resume` sonuncusunu sürdürür, `/quit` çıkar. Sıradaki: [Yapılandırma](configure.md) ve [tau ile konuş](talk.md).
