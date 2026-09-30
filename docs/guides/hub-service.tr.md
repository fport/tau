<!-- tr twin of guides/hub-service.md, translated 2026-09-30 -->

# tau'yu servis olarak çalıştır

`tau hub run`, tau'yu **hub** rolünde (tau'nun çalıştığı, sana ait tek makine) uzun ömürlü bir süreç olarak çalıştırır. Tek örnek kilidini tutar, bir heartbeat'i (canlılık sinyali) tazeler, loopback üzerinde küçük bir kontrol API'si sunar ve etkin her hub servisini başlatır (Telegram, ses ve mesh'in hepsi hub servisi olacak). Bir gözetmen (supervisor) altında çalışırken bir çökmeden sonra geri gelir, temiz bir durdurmadan sonra ise kapalı kalır: macOS'ta bu gözetmen [tau uygulaması](taubar.md) (varsayılan) ya da bir launchd agent'ı, Linux'ta ise bir systemd kullanıcı birimidir.

Bugün hub'ın kendine ait bir kanalı yok: `tau chat` ve `tau tui` ajanlarını kendi süreçlerinin içinde kurar ve çalışan bir hub olsa da olmasa da çalışır. Altyapının yerinde olmasını, çökme raporlarını ve hub'ın ayakta olduğunu söyleyen `/status` satırını istiyorsan servisi şimdi kur; ona ihtiyaç duyan hub servisleri sonraki katmanlarla geliyor.

## Ön planda

```sh
tau hub run
```

```text
tau hub is running (pid 12345, profile home). Control API: http://127.0.0.1:7877
To stop: Ctrl-C or `tau hub stop`
```

- Makine başına yalnızca bir hub çalışır. İkinci bir `tau hub run`, `tau hub is already running (pid N)…` mesajıyla 1 koduyla çıkar.
- Her `[hub] heartbeat_seconds` sürede (varsayılan 5) `<TAU_DATA_DIR>/hub/state.json` dosyasını tazeler.
- SIGTERM ya da SIGINT onu temiz bir şekilde durdurur ve `stopped_at` yazar.
- `stopped_at` içermeyen bir `state.json` bulan başlangıç bir çökme raporu kaydeder ve `The previous hub did not stop cleanly: …` yazdırır.

## Durum ve durdurma

```sh
tau hub status
tau hub status --json
tau hub stop
tau hub stop --timeout 30
```

Hiçbir şey çalışmıyorken `tau hub status`:

```text
tau hub is not running.
  Last crash: none
  launchd: not installed (to install: tau hub install)
```

Çalışırken pid'i, çalışma süresini, heartbeat'in yaşını, sürümü, rolü, profili, son çökmeyi ve launchd durumunu gösterir. `--json` ayrıca yapılandırmanın neye çözümlendiğini de taşır (`control_port`, `data_dir`, `hub_dir`, `lock`); tau uygulaması, çalıştırdığı hub'ın kilidini ve kontrol API'sini bu yolla bulur. `tau hub stop` SIGTERM gönderir ve `--timeout` saniyeye kadar bekler (varsayılan 15); bu, launchd ve systemd'nin çökme **saymadığı** temiz durdurmadır.

## Kontrol API'si

Hub yalnızca `127.0.0.1:<control_port>` adresini dinler (varsayılan 7877; `TAU_HUB_PORT` bunu ezer) ve JSON konuşur:

| Rota | Erişim | Yanıt |
|---|---|---|
| `GET /health` | açık | `{"ok": true, "pid": …, "uptime_s": …}` |
| `GET /status` | açık | rol, profil, sürüm, `started_at`, `heartbeat_at`, `uptime_s`, `last_crash`, `approvals_pending`, `nodes`, artı hub servislerinin eklediği anahtarlar: `spend` (`/spend` ile aynı nesne), sahip korumasıyla `guard: {state, enrolled, available, reason}` |
| `GET /spend` | korumalı | her model rolünün bütçe dönemindeki harcaması, üst sınırıyla yan yana; her istekte yerel harcama defterinden (ledger, `TAU_DATA_DIR/spend.sqlite3`) okunur (`spend` hub servisi); bkz. [Modeller ve bütçeler](models-and-budgets.md) |
| `/guard/*` | korumalı | [sahip korumasının](guard.md) durumu, kabulü, kontrolleri ve kilidi; yalnızca koruma etkinken ([referans](../reference/guard.md#guard)) |

Loopback olmayan bir `Host` başlığı taşıyan istek 403 alır; böylece API'ye yanlışlıkla bir tünel ya da proxy üzerinden ulaşılamaz. `tau doctor` ve bir oturumdaki `/status`, yalnızca bilgi amaçlı olarak `/health` adresini bir saniyelik zaman aşımıyla yoklar.

**`/health` ve `/status` dışındaki her route korumalıdır** ([ADR 0008](../adr/0008-owner-guard.md)). Hub her başlangıçta `TAU_DATA_DIR/hub/control.token` dosyasına (mod `0600`) yeni bir token yazar. İstemci her korumalı isteği onunla imzalar (`X-Tau-Nonce`, `X-Tau-Auth`), token'ın kendisi asla yolculuk etmez ve hub yanıtını imzalar (`X-Tau-Proof`); `Origin` başlığı taşıyan istek reddedilir, böylece hiçbir web sayfası bu route'ları çağıramaz. Şema [koruma referansında](../reference/guard.md#signed-requests). Düz bir `curl` orada 403 alır; açık route'ları curl ile, korumalı olanları ise imzalayıp denetleyen tau-core'un `HubClient`'ı ile oku:

```sh
curl -s 127.0.0.1:7877/health
curl -s 127.0.0.1:7877/status | python3 -c 'import json, sys; print(json.dumps(json.load(sys.stdin)["spend"], indent=2))'
uv run python -c 'from tau_core import Config; from tau_core.hub import HubClient; print(HubClient(Config.load()).get("/spend", timeout=5))'
```

## macOS: tau uygulaması (varsayılan) { #macos-taubar-default }

tau'nun Mac uygulaması, [tau uygulaması](taubar.md) hub'ı kendisi çalıştırır. Menüsünde (ya da ayarlar penceresinde) **Run the hub** kutusunu işaretle, uygulama da şunları yapsın:

- `<python> -m tau_core hub run` komutunu kendi alt süreci olarak, `TAU_HOME` içinde; `TAU_HOME`, `TAU_ROLE=hub`, sade bir `PATH` ve ayarlarının eklediği diğer her şeyle (`TAU_DATA_DIR`, `TAU_HUB_PORT`, ek ortam değişkenleri) başlatır;
- temiz olmayan bir çıkıştan (bir çökme, bir `kill -9`, başarısız bir başlangıç) sonra onu 1 sn sonra, başarısız olmaya devam ettikçe 2, 4 … en fazla 60 sn sonra yeniden başlatır; bir çalıştırma bir dakika sürdüğünde yeniden 1 sn'ye döner;
- kendisinin istemediği temiz bir çıkıştan (`tau hub stop`) sonra onu durmuş hâlde bırakır: sen yeniden işaretleyene ya da uygulama yeniden başlayana kadar anahtar kapalı görünür, tıpkı launchd agent'ının bir sonraki girişe kadar beklemesi gibi;
- anahtarın işaretini kaldırdığında ya da uygulamadan çıktığında onu SIGTERM ile durdurur (15 sn sonra, uygulama çıkarken ise 10 sn sonra hâlâ durmamışsa SIGKILL);
- asla ikinci bir hub başlatmaz. Her başlatmadan önce `tau hub status --json` komutunun çözümlediği veri dizininin hub kilidini yoklar. Kendi başlatmadığı bir hub menüde gösterilir (`started outside the app` ya da `run by launchd`) ve kendi hâline bırakılır; bu durumda anahtarın işaretini kaldırmak sana onu nasıl durduracağını söyler. Yüklenmiş bir `com.tau.hub` launchd agent'ı aynı veri dizinine sahipken uygulama hub'ı launchd'ye bırakır.

Menü, kontrol API'sinden gelen üç satır gösterir: `Hub: up 2 h 5 min · pid 1234`, Telegram poller'ı (`Telegram: polling as @your_bot`) ve son çökme. **Launch at login**, oturum açtığında uygulamayı, onunla birlikte de hub'ı başlatır.

Uygulamanın hangi Python'u ve hangi `TAU_HOME` değerini kullanacağını bilmesi gerekir. İlk açılışta bunları TauBar'dan (yerini aldığı uygulama) devralır ya da kurulu bir `com.tau.hub` launchd agent'ından kopyalar; yoksa ayarlar penceresinde checkout'u (deponun yerel kopyası) seç (**Use a tau checkout…**, `<checkout>/.venv/bin/python` yolunu ve `TAU_HOME` olarak checkout'u doldurur). Hub'ın stdout ve stderr çıktıları `<TAU_DATA_DIR>/hub/logs/app.{out,err}.log` dosyalarına, logu her zamanki gibi `<TAU_DATA_DIR>/logs/tau.log` dosyasına gider (menü → **Open Hub Log**); uygulamanın kendi logu da her başlatmayı, çıkışı ve yeniden başlatmayı kaydeder.

launchd agent'ından tau uygulamasına geçmek için:

```sh
cd /path/to/tau
uv run tau hub uninstall     # the launchd hub stops; the tau app may now run it
```

sonra **Run the hub** kutusunu işaretle. (Anahtar zaten açıksa uygulama, launchd hub'ı gider gitmez kendi hub'ını başlatır.)

Varsayılan neden launchd değil de uygulama: bunun üzerinde geliştirildiği Mac'te (macOS 26.3.1) launchd, oturumdaki kullanıcı agent'larının her otomatik başlatmasını bekletti: `RunAtLoad`, bir `kill -9` sonrasında `KeepAlive` ve hatta `StartInterval` hiç tetiklenmedi, yalnızca `launchctl kickstart` işe yaradı (yol haritası issue 057 ve 052). Görebildiğin bir uygulamanın içindeki gözetmen buna bağımlı değildir.

## macOS alternatifi: launchd kullanıcı agent'ı { #macos-alternative-launchd-user-agent }

tau uygulaması bir seçenek değilse bunu kullan (GUI uygulaması istemiyorsan ya da launchd'nin otomatik başlatmalarının çalıştığı bir Mac'teysen). Kurulumdan sonra hub'ın gerçekten çalıştığını kontrol et (`tau hub status`); bazı Mac'lerde launchd agent'ı yükler ama hiç başlatmaz (yukarıya bak), `launchctl kickstart gui/$UID/com.tau.hub` ise onu elle başlatır.

Oturum açmış kullanıcının bir Terminal'inden çalıştır. `gui/<uid>` launchd alanı bir GUI oturumu gerektirir, dolayısıyla GUI oturumu olmayan bir SSH oturumu onu bootstrap edemez.

```sh
cd /path/to/tau
uv run tau hub install
uv run tau hub status
```

```text
launchd agent installed: ~/Library/LaunchAgents/com.tau.hub.plist
  The hub starts at login; after a crash or a kill it is restarted within a few
  seconds. It is not restarted after a clean stop (tau hub stop).
  launchd logs: ~/.local/share/tau/hub/logs
  For the status: tau hub status
```

`tau hub install` şunları yapar:

- plist'i paket şablonundan **bu makinenin mutlak yollarıyla** oluşturur: sanal ortamın Python'u, `TAU_HOME`, `TAU_DATA_DIR`, `TAU_ROLE=hub` ve sade bir `PATH`;
- log dizinini oluşturur;
- yüklü bir agent varsa onu boot out eder ve taze plist'i bootstrap eder (`launchctl bootstrap gui/$UID`); yani idempotenttir, tekrar tekrar çalıştırmak güvenlidir.

plist `RunAtLoad` (kurulumda ve her girişte başlat), `KeepAlive = {SuccessfulExit: false}` ve `ThrottleInterval 3` ayarlar: bir çökme ya da `kill -9` hub'ı yaklaşık üç saniye içinde geri getirir; `tau hub stop` ise onu durmuş hâlde tutar.

```sh
tau hub stop                                    # stop without a relaunch
launchctl kickstart gui/$UID/com.tau.hub        # start it again (or: tau hub install)
tau hub uninstall                               # launchctl bootout + delete the plist
```

Loglar: stdout ve stderr `<TAU_DATA_DIR>/hub/logs/launchd.{out,err}.log` içinde, ayrıntılar `<TAU_DATA_DIR>/logs/tau.log` içinde.

!!! warning "Checkout'u taşıdıktan ya da `.venv`'i yeniden oluşturduktan sonra"
    plist, venv'in Python'unu mutlak yoluyla gösterir. Depoyu taşıdıktan, sanal ortamı yeniden oluşturduktan ya da Python'u yükselttikten sonra `tau hub install` komutunu yeniden çalıştır; yoksa launchd hub'ı başlatamaz.

Kendi kendini iyileştirmeyi bir kez elle kontrol et (aynı kontrol tau uygulaması için de geçerli):

```sh
curl -s 127.0.0.1:7877/health                  # note the pid
kill -9 <pid>
sleep 5; tau hub status        # a new pid, and "Last crash: … unexpected exit (no clean shutdown)"
```

!!! warning "`pkill -f` değil"
    `pkill -9 -f "tau_core hub run"`, testler için başka bir `TAU_DATA_DIR` ile çalıştırdığın hub dahil, makinedeki **her** hub'ı öldürür. `/health` ya da `tau hub status` komutunun bildirdiği pid'i öldür.

## Linux: systemd kullanıcı birimi

`tau hub systemd-unit`, bu makinenin yollarıyla oluşturulmuş bir birim (unit) yazdırır; `--python PATH` başka bir yorumlayıcı seçer.

```sh
cd /path/to/tau
mkdir -p ~/.config/systemd/user
uv run tau hub systemd-unit > ~/.config/systemd/user/tau-hub.service
systemctl --user daemon-reload
systemctl --user enable --now tau-hub
loginctl enable-linger "$USER"   # start at boot, without a login session
```

`RestartSec=3` ile birlikte `Restart=on-failure`, launchd'nin davranışını yansıtır: bir çökme ya da kill sonrasında yeniden başlatır, `tau hub stop` ya da `systemctl --user stop tau-hub` sonrasında yeniden başlatmaz. Loglar journal'a (`journalctl --user -u tau-hub -f`) ve `<TAU_DATA_DIR>/logs/tau.log` dosyasına gider.

Bir testin paket şablonlarıyla birebir aynı tuttuğu, oluşturulmuş örnek dosyalar [`infra/services/`](https://github.com/fport/tau/tree/main/infra/services) içinde. Onları elle kopyalama; yer tutucular (`/path/to/venv/bin/python`, `/path/to/tau`, `/path/to/tau-data`), yukarıdaki komutların yerine koyduğu değerlerdir.

## Hub dosyaları

Hub'ın tuttuğu her şey `<TAU_DATA_DIR>/hub/` altındadır:

| Dosya | Anlamı |
|---|---|
| `hub.lock` | `flock` tek örnek kilidi; çalışan hub'ın pid'ini tutar; asla silinmez |
| `state.json` | pid, `started_at`, `heartbeat_at`, sürüm, rol, profil, `last_crash`, `stopped_at` |
| `crash.json` | başarısız olan bir hub'ın kapanırken yazdığı neden; bir sonraki başlangıç onu tüketir |
| `crash_reports.jsonl` | bir sonraki başlangıcın fark ettiği her çökme, en eskisi önce |
| `last_crash.json` | en son çökme raporu (`tau hub status` ve `/status` bunu gösterir) |
| `logs/` | gözetmenin yakaladığı stdout ve stderr: `launchd.{out,err}.log` ya da `app.{out,err}.log` |

## Hub servisleri

Hub servisi; bir `name`, `async start(hub)` ve `async stop()` içeren ve `tau.hub_services` entry point grubu (Python paketlerinin eklenti kayıt noktası) üzerinden gelen bir bileşendir. `tau hub run` önce kontrol API'sini, ardından etkin her servisi sırayla başlatır; servisler ters sırayla durur. Kurulamayan ya da başlatılamayan bir servis loglanır ve atlanır; hub çalışmaya devam eder. `tau.toml` içindeki `[components.hub] services`, keşfedilen servislerden hangilerinin açık olacağını seçer (boş, hepsi demektir). Bkz. [Bileşenler ve eklentiler](../reference/components.md); bir servis yazmak için de [Eklenti yaz](../contributing/plugins.md).

## Makineyi uyanık tutmak

Uyuyan bir hub, düşünmeyen bir hub'dır. Bir MacBook'ta [tau uygulaması](taubar.md), Mac'i fişe takılıyken (varsayılan) ya da kapak kapalıyken bile uyanık tutar ve çıktığında normal uykuyu geri getirir. Uygulama olmadan, uzaktan erişim kurulumu `com.tau.keepawake` agent'ını kurar; bu, Mac'i fişe takılıyken uyanık tutmak için `caffeinate -s` çalıştıran bir launch agent'ıdır; bu durumda kapağın açık kalması (ya da harici bir ekranın bağlı olması) gerekir. Raspberry Pi'de böyle bir soru ortaya çıkmaz; Pi'nin uzun vadede doğal hub olmasının nedenlerinden biri de bu. Bkz. [Hub'ı Raspberry Pi'ye taşı](raspberry-pi.md).
