<!-- tr twin of reference/cli.md, translated 2026-09-30 -->

# CLI

Her `tau` alt komutu bir bileşendir: `tau-core`; `chat`, `components`, `doctor`, `hub`, `init`, `spend` ve `version` komutlarıyla gelir; `tau-tui` `tui` komutunu, `tau-guard` `guard` komutunu ([Sahip koruması](../guides/guard.md)), `tau-net` `net` komutunu, `tau-cloud` `cloud` komutunu (bkz. [tau ağına katıl](../guides/tau-network.md)), `tau-sub` da `sub` komutunu ekler. Kurulu herhangi bir dağıtım, `tau.commands` entry point grubu (Python paketlerinin eklenti kayıt noktası) üzerinden başka komutlar da ekleyebilir. Bu sayfa her birinin `--help` çıktısını aynen verir.

Bir depo checkout'unun (deponun yerel kopyası) içindeysen her komutun başına `uv run` ekle.

## `tau`

```text
Usage: tau [OPTIONS] COMMAND [ARGS]...

  tau — a personal smart-body agent.

  Subcommands come from plugins (the tau.commands entry point group).

Options:
  -h, --help      Show this help and exit.
  --profile NAME  Active profile, e.g. home | travel | sport (default:
                  TAU_PROFILE, else 'home').
  --home DIR      Configuration root: tau.toml, persona/, tools/ (default:
                  TAU_HOME).
  --lang LANG     UI language, en | tr (default: TAU_LANG, else [ui] in
                  tau.toml).
  -v, --verbose   Verbose log output.

Commands:
  chat        Chat with tau in the terminal.
  cloud       Cloud mode: sync config and persona with the spine, run the
              brain.
  components  List installed components and their state.
  doctor      Check the installation.
  guard       The owner guard (setup, verify, status, lock, log).
  hub         Run and manage tau as a long-lived service in the hub role.
  init        Create tau.toml and the persona files.
  net         Talk to other taus (identity, contacts, messages).
  spend       Show the spend per model role.
  sub         Specialists of your tau (/coach, /landing, ...).
  tui         Open tau in the Textual interface.
  version     Show the versions of the installed tau packages.
```

Üç global seçenek alt komuttan **önce** gelir: `tau --home ~/other --lang tr chat`. `--profile` ve `--lang`, çalıştırma boyunca `TAU_PROFILE` ve `TAU_LANG` olarak export edilir; böylece başka bir paketteki alt komut da onları görür. `-v`, yalnızca `WARNING` yerine `INFO` seviyesini de stderr'e gönderir.

## `tau init`

```text
Usage: tau init [OPTIONS]

  Set up a configuration root: tau.toml from the shipped template,
  persona/persona.md, persona/user.example.md, persona/user.md (from the
  example, unless it exists) and .env.example (the variable names). The
  provider is picked from the credentials present in the environment or
  <home>/.env (anthropic, openai, gemini, bedrock). Without any, tau init asks
  for a provider (anthropic, openai or gemini) and its key with hidden input,
  checks the key with one small request to the provider (--no-check skips it)
  and appends it to <home>/.env, which is kept at mode 0600; a key the
  provider refuses writes nothing. --yes asks nothing and falls back to the
  scripted 'fake' provider. Existing files are kept unless --force is given;
  user.md and .env.example are never overwritten.

Options:
  -h, --help       Show this help and exit.
  --home DIR       Configuration root to create (default: TAU_HOME, else
                   ~/.tau).
  --provider NAME  Provider for the brain and fast roles (default: the first
                   with credentials, else asked).
  --language LANG  UI language, en | tr (asked when not given, unless --yes).
  --profile NAME   Write TAU_PROFILE=NAME into <home>/.env (appended; an
                   existing value is kept).
  --no-check       Do not check a typed key with a request to the provider.
  -y, --yes        Ask nothing; use defaults for what is not given (no key).
  --force          Overwrite an existing tau.toml and persona.md.
```

`--provider`; `anthropic`, `openai`, `gemini`, `bedrock` ya da `fake` değerlerini kabul eder. Yazdığı model id'leri paketle birlikte gelen bir tablodan gelir; böylece tau-core'un Python kodu hiçbir modelin adını anmaz. `--provider` verilmezse `ANTHROPIC_API_KEY` ayarlıysa `anthropic` seçilir, sonra `openai` (`OPENAI_API_KEY`), sonra `gemini` (`GEMINI_API_KEY` ya da `GOOGLE_API_KEY`), sonra `bedrock` (AWS kimlik bilgileri). Hiçbiri yoksa `--yes` `fake` seçer; `--yes` yoksa sorar.

- Yalnızca `brain` ve `fast` rollerinin `provider` ve `model_id` değerlerini yeniden yazar; `anthropic` şablonu geldiği gibi yazar.
- `budget` tabloları kalır (tau onları her sağlayıcı için uygular) ve `local` Ollama'da kalır (`qwen3.5:9b`, `failover = "fast"`).

```text
Provider: anthropic. ANTHROPIC_API_KEY was found in the environment or ~/.tau/.env. tau.toml caps brain and fast with budgets tau enforces itself (`tau spend` shows them), and local uses Ollama on this machine, falling back to fast when it is not running.
```

**Sağlayıcı anahtarı** ([ADR 0013](../adr/0013-hosted-taus-handles-and-public-pages.md) §7). Kimlik bilgisi olmayan bir makinede etkileşimli çalıştırma önce arayüz dilini, sonra sağlayıcıyı (`anthropic`, `openai` ya da `gemini`; varsayılan `anthropic`) ve onun anahtarını gizli girişle sorar. Anahtarı olmayan bir `--provider anthropic|openai|gemini` yalnızca anahtarı sorar.

- Anahtar, sağlayıcının model listesine tek bir `GET` ile denenir; anahtar URL'de değil, bir istek başlığında gider ve yönlendirmeler izlenmez. `--no-check` denemeyi atlar.
- Reddedilen bir anahtar (`401`/`403`), başka bir durum kodu ya da yanıtsızlık stderr'de açıklanır; hiçbir şey yazılmaz ve çıkış kodu 1'dir.
- Anahtar `<home>/.env` dosyasına `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` ya da `GEMINI_API_KEY` olarak yazılır: yeni dosya `0600` izniyle oluşturulur; var olan dosya `0600` iznine çekilir ve satır, diğerlerine dokunulmadan sona eklenir. Zaten değeri olan bir ad korunur.
- Boş bırakılan anahtar atlanır: `tau.toml` o sağlayıcı için yazılır ve bir not, sonra eklenecek değişkenin adını verir.
- Sorular ve notlar seçilen arayüz dilini izler (mesaj tablosunun `init.*` anahtarları); anahtar asla çıktıda, argv'de ya da bir logda görünmez.

Başarıda çıkış kodu 0'dır; var olan her dosyayı olduğu gibi bıraktığında da.

## `tau doctor`

```text
Usage: tau doctor [OPTIONS]

  Check the installation: tau.toml, each role's provider and credentials (no
  model client is built), the session store, the persona files, .env against
  .env.example, component load errors, [components] names nothing provides and
  whether a hub answers on the control API. Exit 1 when a check fails.

Options:
  -h, --help  Show this help and exit.
  --json      Print the checks as JSON.
```

Her kontrol satırı `ok`, `warn`, `info` ya da `fail` ile başlar, ardından kontrolün adı ve bir ayrıntı gelir. Çıkış kodu yalnızca `fail` durumunda 1'dir. `--json`, `{"ok": bool, "checks": [{"name", "status", "detail"}, …]}` yazdırır. Kök, global `--home` seçeneğidir: `tau --home DIR doctor`. Her satırın anlamı için bkz. [İlk çalıştırma](../getting-started/first-run.md).

Bir rolün bütçesi varsa doctor, her rolün harcama defterindeki (ledger) harcamasını içeren bir `budget` satırı ekler (`ok   budget: brain $0.00 of $15.00 this month (resets 01.10.2026 00:00); fast $0.00 of $1.00 today (resets 01.10.2026 00:00)`); defter okunamıyorsa bir `fail` ekler. Bütçesi olan ama modelinin fiyatı olmayan bir rol, kendi rol satırında bir `warn` alır (`has a budget, but model 'my-model' has no price, so its calls count as $0; add [models.prices."my-model"] to tau.toml`).

## `tau components`

```text
Usage: tau components [OPTIONS]

  List every component tau can see: tools, commands, providers, session
  backends, context sources and hub services, with their distribution,
  version, whether [components] enables them and any load error.

Options:
  -h, --help  Show this help and exit.
  --json      Print the listing as JSON.
```

Her entry point grubu için bir blok, her bileşen için bir satır: ad, dağıtım ve sürüm, `enabled` ya da `disabled` ve bir not (araçlar için `tier N`, sağlayıcılar için `in use: brain, fast` ya da `available`, oturum arka ucu için `in use`, komutlar için `tau <name>`, varsa bir yükleme hatası). Eksiksiz bir liste için bkz. [Bileşenler ve eklentiler](components.md).

## `tau chat`

```text
Usage: tau chat [OPTIONS]

  Chat with tau in the terminal.

Options:
  -h, --help     Show this help and exit.
  --role ROLE    Model role to use (default: brain, or the role a resumed
                 session remembers from /model).
  --resume [ID]  Resume an earlier session (same as /resume).
  --session ID   Start with this session id.
```

- Tek başına `--resume`, mesaj içeren en son önceki oturumu sürdürür; `--resume ID` o oturumu sürdürür.
- `--session ID`, o id'ye sahip bir oturumu açar (ya da oluşturur); id'ler düz adlar olmalı (harfler, rakamlar, `.`, `_`, `-`).
- `--role`, rolü bütün çalıştırma boyunca sabitler ve sürdürülen bir oturumun hatırladığı role üstün gelir.
- Kimlik bilgileri eksikse, yapılandırma geçersizse ya da oturum açılamıyorsa komut, istem görünmeden önce 2 çıkış koduyla biter. Ctrl-D ve `/quit` 0 ile çıkar.
- [Sahip koruması](../guides/guard.md) etkinken `tau chat` ekranı ve kaydırma geçmişini temizler, `locked> ` istemiyle açılır; Enter bir yüz kontrolü başlatır. Kontrol geçene kadar yalnızca `/help`, `/lang`, `/guard` ve `/quit` çalışır.

## `tau tui`

```text
Usage: tau tui [OPTIONS]

  Open tau in the Textual interface.

Options:
  -h, --help      Show this help and exit.
  --profile NAME  Active profile (default: TAU_PROFILE, else 'home').
  --resume [ID]   Resume an earlier session (the most recent one when ID is
                  omitted).
```

Buradaki `--profile`, global seçenekle aynı ayardır; ikisinden birini kullanabilirsin. Bozuk bir yapılandırma ya da bilinmeyen bir oturum id'si, arayüz açılmadan önce komutu düz İngilizce bir mesajla ve 2 çıkış koduyla bitirir. Hiç `tau.toml` yoksa önce kurulum ekranı açılır ve bir tane oluşturur (`tau init` ile aynı kod; oradaki Esc de 2 çıkış kodudur). Bir rolünün kimlik bilgileri olmayan bir yapılandırmayla arayüz ayarlar ekranında açılır ve bir anahtar kaydedilince sohbet başlar ([İlk çalıştırma](../getting-started/first-run.md#in-the-interface-tau-tui)). Çalıştığı sürece loglar yalnızca `<TAU_DATA_DIR>/logs/tau.log` dosyasına gider.

[Sahip koruması](../guides/guard.md) etkinken arayüz, hiçbir oturum yüklenmeden önce opak bir kilit ekranıyla açılır; kurulum ve ayarlar ekranları bir yüz kontrolü geçene kadar açılmaz (Enter kontrolü başlatır, Esc iptal eder, ctrl+q çıkar). tau Desktop pencerelerinde bu komutun aynısını çalıştırır.

## `tau guard`

```text
Usage: tau guard [OPTIONS] COMMAND [ARGS]...

  The owner guard: face setup and checks, its state as the hub reports it,
  locking tau, the audit log.

Options:
  -h, --help  Show this help and exit.

Commands:
  doctor  Check everything the face guard depends on.
  enroll  Enroll your face again (behind Touch ID or your password).
  forget  Remove your face template, the marker and the Keychain key...
  lock    Lock tau now (every guarded channel, until you unlock at the Mac).
  log     Show the guard's audit log (checks, locks, cooldowns).
  setup   Set up the face guard at the Mac: the face model, your...
  status  Show the guard's state as the running hub reports it.
  verify  Run one face check with the head-turn challenge.
  window  Say whether the guard window can open here; --demo plays a...
```

`tau-guard` ekler, yalnızca macOS'ta çalışır (diğer platformlar yüz komutlarını reddeder). Kurulum, günlük kullanım ve kurtarma [Sahip koruması](../guides/guard.md) rehberinde; anahtarlar, route'lar, durumlar ve denetim kaydı [koruma referansında](guard.md).

| Komut | Ne yapar |
|---|---|
| `tau guard setup [--model-file FILE] [--no-window]` | SFace modelini kurar (indirir ve sabitlenmiş sha256 ile doğrular, ya da `FILE`'dan), yüzünü Touch ID ya da Mac parolanın arkasında kaydeder, bir kontrol çalıştırır ve `tau.toml`'a `[component.guard] enabled = true` yazar. Yalnızca Mac'in başında: SSH üzerinden reddedilir |
| `tau guard enroll [--add] [--no-window]` | Touch ID ya da Mac parolanın arkasında yeniden kaydeder; `--add` şablona başka bir ışıkta örnekler ekler. Yalnızca Mac'in başında |
| `tau guard verify [--explain] [--no-window]` | Baş çevirme sınamasıyla tek bir yüz kontrolü. Korumalı bir hub çalışıyorsa hub üzerinden (geçen kontrol tau'nun kilidini açar), yoksa yerel bir worker'da; `--explain` her zaman yerelde çalışır ve her karenin sayılarını yazar, hiçbir kareyi kaydetmez. Başarısızsa 1 ile çıkar |
| `tau guard forget` | Şablonu, kayıt işaretini ve Keychain anahtarını Touch ID ya da Mac parolanın arkasında siler ve `enabled = false` yazar. Keychain anahtarı tuttuysa 1 ile çıkar: yeniden çalıştır. Yalnızca Mac'in başında |
| `tau guard doctor` | Yüz korumasının dayandığı her şeyi denetler; hub'ın kamera iznini hangi uygulamanın tuttuğu da dahil. `fail` varsa 1 ile çıkar |
| `tau guard status [--json]` | Çalışan hub'ın bildirdiği durum. Etkin koruma yoksa `off`; hub çalışmıyorsa 0, hub hatasında 1 ile çıkar |
| `tau guard lock` | Korunan her kanalı hemen kilitler (tetikleyici `command`). SSH üzerinden de çalışır |
| `tau guard log [--since WHEN] [--json]` | Denetim kaydı; `WHEN` bir süre (`30m`, `2h`, `7d`) ya da ISO tarih veya saattir |
| `tau guard window [--demo]` | Koruma penceresinin açık olup olmadığını ve buradan açılıp açılamayacağını söyler; `--demo` içinde sentetik bir görüntüyle senaryolu bir kontrol oynatır (kamera yok; Esc kapatır) |

Bir kontrol sürerken worker [koruma penceresini](guard.md#the-guard-window) gösterir (`[component.guard] window`, varsayılan olarak açık); `--no-window` komutun kendi çalıştırdığı bir kontrol için onu kapalı tutar, hub üzerinden giden bir kontrol ise hub'ın ayarını izler.

`setup` ya da `forget` sonrasında hub'ı ve açık her `tau chat`, `tau tui` ya da tau Desktop penceresini yeniden başlat.

## `tau hub`

```text
Usage: tau hub [OPTIONS] COMMAND [ARGS]...

  Run and manage tau as a long-lived service in the hub role.

Options:
  -h, --help  Show this help and exit.

Commands:
  install       Install and start the launchd agent (macOS).
  run           Run the hub in the foreground.
  status        Show the hub's status and the reason of its last crash.
  stop          Stop the running hub (SIGTERM, clean shutdown).
  systemd-unit  Print the systemd unit file (for the RPi5 hub).
  uninstall     Remove the launchd agent (macOS).
```

### `tau hub run`

```text
Usage: tau hub run [OPTIONS]

  Run the hub in the foreground (launchd and systemd run this too).

Options:
  -h, --help  Show this help and exit.
```

Kilit tutuluyorsa `tau hub is already running (pid N)…` mesajıyla ve 1 çıkış koduyla biter. Ctrl-C ya da `tau hub stop` onu temiz biçimde durdurur.

### `tau hub status`

```text
Usage: tau hub status [OPTIONS]

  Show the hub's status and the reason of its last crash.

Options:
  -h, --help  Show this help and exit.
  --json      Print the status as JSON.
```

Hub'ın (tau'nun çalıştığı, sana ait makinedeki uzun ömürlü servis) çalışıp çalışmadığını (pid, çalışma süresi, heartbeat), son çökmeyi ve launchd durumunu yazdırır. Bir hub çalışsa da çalışmasa da çıkış kodu 0'dır.

### `tau hub stop`

```text
Usage: tau hub stop [OPTIONS]

  Stop the running hub (SIGTERM, clean shutdown).

Options:
  -h, --help         Show this help and exit.
  --timeout SECONDS  Wait at most this long for the hub to stop.  [default:
                     15.0]
```

Önce `Stop signal sent (pid N).`, sonra `tau hub stopped.` yazdırır; ya da stderr'e `tau hub did not stop within N s.` yazıp 1 çıkış koduyla biter.

### `tau hub install` / `tau hub uninstall`

```text
Usage: tau hub install [OPTIONS]

  Install and start the hub as a launchd user agent (macOS).

Options:
  -h, --help  Show this help and exit.
```

```text
Usage: tau hub uninstall [OPTIONS]

  Stop and remove the launchd user agent (macOS).

Options:
  -h, --help  Show this help and exit.
```

Yalnızca macOS; Linux'ta ikisi de bir mesaj yazdırır ve 1 çıkış koduyla biter. `install` idempotent'tir (tekrar çalıştırmak aynı sonucu verir) ve grafik arayüzlü bir oturum gerektirir. Bkz. [tau'yu servis olarak çalıştır](../guides/hub-service.md).

### `tau hub systemd-unit`

```text
Usage: tau hub systemd-unit [OPTIONS]

  Print the systemd unit file (for the RPi5 hub).

Options:
  -h, --help     Show this help and exit.
  --python PATH  The Python the service runs (default: the current
                 interpreter).
```

Unit dosyasını bu makinenin mutlak yollarıyla stdout'a yazdırır; çıktıyı `~/.config/systemd/user/tau-hub.service` dosyasına yönlendir.

## `tau spend`

```text
Usage: tau spend [OPTIONS]

  Show what every model role spent in its budget period (from the ledger under
  TAU_DATA_DIR) next to its budget in tau.toml.

Options:
  --json      Print the spend as JSON.
  -h, --help  Show this message and exit.
```

```text
  brain    anthropic $0.42 of $15.00 this month, resets 01.10.2026 00:00
  fast     anthropic $1.01 of $1.00 today, resets 01.10.2026 00:00 · SPENT
  local    ollama    $0.00 this month, no budget
```

Sütunlar: rol, sağlayıcı, rolün mevcut dönemde harcadığı, üst sınırı, dönem (`today`, `this week`, `this month`) ve bir sonraki sıfırlanma (Europe/Istanbul). `· SPENT`, üst sınırına ulaşmış bir rolü işaretler (`degrade_to` varsa `, fast answers instead` eklenir); `· N calls without a price for <model id>`, fiyatı olmayan bir modeldeki çağrıları sayar. Bütçesi olmayan bir rol `no budget (its calls are not counted)` gösterir; bir `failover` (ulaşılamayan rolün çağrısını başka bir role devretme) onu ölçülür hâle getirdiyse bu ayki harcamasını gösterir. `tau.toml` dosyasını ve `TAU_DATA_DIR/spend.sqlite3` defterini doğrudan okur; bu yüzden çalışan bir hub gerektirmez ve değişen bir üst sınırı hemen gösterir. Çıktı, `tau doctor` gibi düz İngilizcedir.

`--json`, rol başına bir nesne yazdırır; hub'ın `GET /spend` yanıtındaki nesnelerin aynısı, yalnızca `roles` sarmalayıcısı olmadan:

```json
{
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
```

Bkz. [Modeller ve bütçeler](../guides/models-and-budgets.md).

## `tau net`

```text
Usage: tau net [OPTIONS] COMMAND [ARGS]...

  The tau network: your tau's identity, card and contacts, and messages to
  other taus.

Options:
  -h, --help  Show this help and exit.

Commands:
  accept    Accept a contact request.
  add       Ask another tau to become a contact.
  block     Block an address.
  card      Print the card.
  contacts  List contacts.
  init      Create the network identity.
  log       Show the network log.
  name      Set the card's display name.
  poll      Handle queued envelopes once.
  publish   Publish the card.
  remove    Forget a contact.
  send      Send a message to a contact.
  spine     Set up and deploy your spine Worker.
  status    Show the network status.
  universe  Join or leave the tau universe.
```

`tau-net` tarafından eklenir. Spine (tau'nun ağdaki adresi ve posta kutusu olan Cloudflare Worker'ı) `TAU_SPINE_URL` ve `TAU_SPINE_TOKEN` değerlerinden, kimlik `TAU_DATA_DIR/net/identity.json` dosyasından ya da `TAU_NET_IDENTITY` değerinden, ayarlar da `[component.net]` tablosundan gelir. Kurulum [Kendi tau'nu kur](../getting-started/build-your-own-tau.md) ve [tau ağına katıl](../guides/tau-network.md) sayfalarında; protokoller [tau ağı referansında](tau-network.md) ve [tau evreni referansında](tau-universe.md).

| Komut | Ne yapar |
|---|---|
| `tau net init [--name NAME]` | Kimliği oluşturur (bir Ed25519 imza anahtarı ve bir X25519 kutu anahtarı); var olan bir kimliğin üzerine asla yazmaz. `--name`, kartın görünen adını `tau.toml` içinde değil, her zaman `TAU_DATA_DIR/net` altındaki ağ profilinde ayarlar |
| `tau net name NAME...` | Kartın görünen adını (1 ile 80 karakter arası) ağ profilinde ayarlar; `[component.net] name` değerine üstün gelir. `tau net publish` ile yayımla |
| `tau net status` | Kimlik, spine sağlığı, yayımlanan kartın eşleşip eşleşmediği, duruma göre kişiler (contact) ve ağ durumunun nerede saklandığı |
| `tau net card` / `tau net publish` | Sunulan kartı yazdırır / onu `PUT /hub/card` ile yayımlar (hub servisi de başlarken yayımlar) |
| `tau net contacts` | Kişiler ve bekleyen istekler |
| `tau net add ADDRESS [--note TEXT]` | Kartı alır, adresi bekleyen olarak hatırlar ve bir kişi isteği gönderir; karşı taraf zaten istemişse hemen kabul eder. `ADDRESS` bir host (`tau.example.com`) ya da barındırılan bir tau'dur (`tau.example.com/@alice`) |
| `tau net accept ADDRESS` | Bekleyen bir isteği kabul eder: anahtarları sabitler ve bir `contact_accept` gönderir |
| `tau net block ADDRESS` / `tau net remove ADDRESS` | O adresten gelen hiçbir şey artık okunmaz ya da yanıtlanmaz / kişiyi unutur (logu ve oturumu kalır) |
| `tau net send ADDRESS[/NAME] TEXT...` | Kabul edilmiş bir kişiye senin adınla bir mesaj gönderir (en fazla 8 000 karakter). `ADDRESS/NAME`, o tau'nun açık sub-tau'su `/NAME`'e yazar (`tau.example.com/coach`, `tau.example.com/@alice/coach`); yanıt `/NAME`'den gelir. Senin kendi komutun olduğu için onay gerekmez; ajanın `net_send` aracı ise tier 2'dir (her zaman onay isteyen izin seviyesi) |
| `tau net log [--address ADDRESS] [-n N]` | Ağ logu, en eskiden başlayarak (varsayılan 20 kayıt) |
| `tau net poll --once` | Spine'ın o anda tuttuğu her şeyi, ağ turları dahil, çalışan bir hub olmadan işler. Hub poll yaparken bunu çalıştırma |
| `tau net spine init DIR [--address HOST]` | `tau-net` içindeki kit'ten deploy edilmeye hazır bir spine projesini yeni ya da boş bir `DIR` dizinine yazar. `--address`, `ADDRESS` değerini ve özel alan adı (custom domain) rotasını ayarlar; o olmadan adres `tau-spine.<subdomain>.workers.dev` olur |
| `tau net spine deploy DIR [--address HOST]` | Oturumu kontrol ettikten sonra projeyi Wrangler ile deploy eder (yayına alır), Worker'ın `HUB_TOKEN` secret'ını hub'ın `.env` dosyasındaki `TAU_SPINE_TOKEN` değerine ayarlar (eksikse üretilir, stdin üzerinden geçirilir, asla yazdırılmaz) ve `TAU_SPINE_URL` değerini oraya yazar |
| `tau net universe join [--owner NAME] [--about TEXT] [--links \| --no-links]` | Bu tau'yu `[component.net] universe` evreninde (universe; varsayılan `tau.getporti.com`) listeler: profili yazar, gerekirse kartı yayımlar, imzalı bir katılma isteği ve bir rapor gönderir, tau'nun sayfasını yazdırır |
| `tau net universe status` / `tau net universe leave` | Profilin katılmış görünüp görünmediği ve evrenin bu tau'yu tanıtıcısı (handle), görünür bağlantıları ve açık sub-tau'larıyla (web sayfası olanlar bugünkü ziyaretçi turlarıyla) listeleyip listelemediği / imzalı bir ayrılma isteği gönderir, hub'ın raporlarını durdurur ve evrenin sabitlenmiş anahtarlarını unutur; böylece ziyaret gelmez |
| `tau net universe claim` | Bu tau'nun imzaladığı, bir saat geçerli bir talep olan `https://<universe>/claim#…` bağlantısını yazdırır. Bağlantıyı aç ve orada GitHub ile giriş yap: evren GitHub kullanıcı adını bu tau'nun tanıtıcısı (`/@login`) olarak bağlar. Gerekirse önce kartı yayımlar; hiçbir şey göndermez. Bağlantıyı paylaşma |

## `tau cloud`

```text
Usage: tau cloud [OPTIONS] COMMAND [ARGS]...

  Cloud mode: your tau's hub runs as a container in your own Cloudflare
  account and keeps sessions, config and persona in the spine (ADR 0007).

Options:
  -h, --help  Show this help and exit.

Commands:
  pull    Download tau.toml and the persona files from the spine.
  push    Upload tau.toml and the persona files to the spine.
  run     Run the hub as the brain container (entrypoint).
  status  Show the spine, its files and the brain.
```

`tau-cloud` tarafından eklenir; kurulum [tau'yu Cloudflare'de çalıştır](../guides/cloud-mode.md) sayfasında. Her alt komut `TAU_SPINE_URL` ve `TAU_SPINE_TOKEN` gerektirir.

| Komut | Ne yapar |
|---|---|
| `tau cloud push [--include-user] [-y]` | `tau.toml`, `persona/persona.md`, `persona/net.md` ve sub-tau dosyalarını (`persona/subs/*.md`, düz adlı olanlar; o dizindeki başka girdiler, alt dizinler ve sembolik bağlantılar atlanır ve adları yazılır) yükler. `persona/subs/` varsa, burada artık olmayan sub-tau dosyaları spine'dan silinir. `persona/user.md` yalnızca `--include-user` ile ya da kendi sorusuna "evet" denirse yüklenir; `.env` asla yüklenmez |
| `tau cloud pull [--force]` | Aynı dosyaları `TAU_HOME` içine indirir; farklı olan yerel bir dosya `--force` verilmedikçe korunur, yerelde hiçbir şey silinmez ve dosya kümesi dışında listelenen bir ad atlanır |
| `tau cloud status` | Spine'ın sağlığı ve modu, tuttuğu dosyalar, brain Container'ının (Cloudflare'de çalışan konteyner) `/health` durumu |
| `tau cloud run` | Konteynerin giriş noktası: dosyaları (sub-tau dosyaları dahil) çeker, `[sessions] backend` ve `[component.net] store` değerlerini `spine` yapar, `0.0.0.0:8080` üzerinde `GET /health` sunar (`TAU_CLOUD_HEALTH_HOST`/`_PORT` bunu ezer) ve SIGTERM gelene kadar hub'ı çalıştırır. `tau.toml` dosyasını kendisinin yazmadığı bir `TAU_HOME` dizinini reddeder |

## `tau version`

```text
Usage: tau version [OPTIONS]

  Show the versions of the installed tau packages.

Options:
  -h, --help  Show this help and exit.
```

```text
tau-core 0.3.1
tau-tui 0.3.1
```

Kurulu her `tau-*` dağıtımı için bir satır. Hiçbir sağlayıcı SDK'sını içe aktarmaz; bu yüzden bozuk bir kurulumda da güvenle çalıştırılabilir.

## Çıkış kodları { #exit-codes }

| Kod | Anlamı |
|---|---|
| 0 | başarı; `tau doctor` için hiç `fail` yok |
| 1 | `tau doctor` ya da `tau guard doctor` başarısız bir kontrol buldu; `tau hub run` çalışan bir hub buldu; bir hub komutu işini yapamadı; bir `tau guard` kontrolü, kaydı ya da silmesi başarılı olmadı |
| 2 | `tau chat` / `tau tui`: hiçbir şey açılmadan önce eksik kimlik bilgileri, geçersiz yapılandırma ya da bilinmeyen oturum; macOS dışındaki bir platformda ya da SSH üzerinden `tau guard` yüz komutları; ayrıca Click'in kendi kullanım hataları |
| 130 | `tau chat`, bir onay istemi hâlâ stdin'i beklerken Ctrl-C ile bırakıldı |

## Ortam { #environment }

Her komut `TAU_HOME`, `TAU_DATA_DIR`, `TAU_PROFILE`, `TAU_ROLE`, `TAU_HUB_PORT` ve `TAU_LANG` değerlerine uyar ve `<TAU_HOME>/.env` dosyasını, zaten ayarlı değişkenleri ezmeden okur. Kanallar ayrıca rollerinin model kimlik bilgilerini ve `TAU_OLLAMA_URL` değerini okur; `tau spend` ve bütçeler `TAU_DATA_DIR` altındaki harcama defterini kullanır. Bkz. [Ortam değişkenleri](environment.md).
