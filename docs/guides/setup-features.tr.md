<!-- tr twin of guides/setup-features.md, translated 2026-10-01 -->

# Kurulum özellikleri

`tau setup` ve Mac uygulamasının kurulum sihirbazı aynı özellik listesini sunar. Bu sayfa her birini tek tek anlatır: ne olduğunu, neyi kurduğunu, nerede çalıştığını, istediği macOS izinlerini, adımlarını ve sonradan nasıl eklenip kaldırılacağını. Sihirbazın arkasındaki karar [ADR 0014](../adr/0014-one-installer-and-onboarding.md). Kataloğun şeması ve uygulamanın konuştuğu JSON protokolü [`tau setup` başvurusunda](../reference/setup.md).

## İki giriş kapısı { #two-ways-in }

- **Mac uygulaması.** `tau.dmg` dosyasını [tau.getporti.com/tr/download](https://tau.getporti.com/tr/download) adresinden indir. İlk açılışta sihirbaz açılır; menüdeki **Set up tau…** onu yeniden açar ([uygulama rehberi](taubar.md#first-launch)).
- **Terminal**, macOS'ta, Linux'ta ve Raspberry Pi'de:

    ```sh
    curl -fsSL https://tau.getporti.com/install.sh | sh
    ```

    Eksikse uv'yi, sonra tau'yu kurar ve `tau setup`'ı başlatır ([Kurulum](../getting-started/install.md)).

İkisi de aynı kontrol listesini gösterir ve aynı adımları çalıştırır. Zaten kurulu bir özellik `✓` ile işaretlenir ve bir daha sorulmaz.

## Bir bakışta { #at-a-glance }

| Özellik | id | Ne kurar | Platformlar | Varsayılan olarak açık | macOS'tan istediği | Senden istediği |
|---|---|---|---|---|---|---|
| [Terminal arayüzü](#terminal-ui) | `tui` | `tau-tui` | macOS, Linux | evet | – | – |
| [tau uygulaması](#the-tau-app) | `app` | uygulamanın kendisi, indirme sayfasından | macOS | hayır | bildirimler | indirme |
| [Sub-tau'lar](#sub-taus) | `sub` | `tau-sub` | macOS, Linux | evet | – | – |
| [Telegram](#telegram) | `telegram` | hiçbir şey (tau-core'da) | macOS, Linux | hayır | – | bir bot token'ı, sonra telefonda `/start` |
| [Uzaktan erişim](#remote-access) | `remote` | hiçbir şey (tau-core'da) | macOS, Linux | hayır | – | Tailscale girişi, tek bir `sudo` komutu, telefonunun anahtarı |
| [Sahip koruması](#owner-guard) | `guard` | `tau-guard` | macOS | hayır | kamera | yüzün, Mac'in başında |
| [tau ağı](#the-tau-network) | `net` | `tau-net` | macOS, Linux | hayır | – | bir ad; spine için bir Cloudflare API token'ı |
| [Oturum açılınca başlat](#start-at-login) | `autostart` | hiçbir şey | macOS, Linux | macOS'ta | – | – |
| [Bulut modu](#cloud-mode) | `cloud` | `tau-cloud` (ve `tau-net`) | macOS, Linux | hayır | – | bulut modu rehberi |

Özelliklerden önce kurulum kendi iki adımını çalıştırır: henüz yapılandırma yoksa `tau init` (dil, model sağlayıcın ve gizli bir istemde anahtarı) ve `persona/user.md` için kısa bir "senin hakkında" (adın, tau'nun sana nasıl hitap edeceği, dillerin). Bunlardan sonra `tau doctor` çalışır.

## Kurulum nasıl davranır { #how-setup-behaves }

- **Tek kurulum.** Seçilen özelliklerin paketleri, çalışan tau-core'un sürümüne sabitlenmiş tek bir `uv tool install` ile kurulur; kurulum sonra yeni ortamda devam eder ([ayrıntılar](../reference/setup.md#installing-and-the-re-execution)).
- **Her adım önce sorar** ve atlanabilir. Başarısız olan bir adım bildirilir, diğerleri devam eder.
- **Asla `sudo` yok.** Bir şey yönetici parolası gerektirdiğinde kurulum o tek komutu neyi değiştirdiğiyle birlikte gösterir ve sen onu kendi terminalinde çalıştırırken bekler. Onu ne tau ne de uygulama çalıştırır.
- **Gizliler gizli kalır.** Anahtarlar ve token'lar gizli istemlere (uygulamada gizli alanlara) yazılır ve `0600` izniyle `<TAU_HOME>/.env` dosyasına kaydedilir. Hiçbir zaman bir komut satırında görünmezler.
- **Yalnızca Mac'in başında.** Korumanın yüz kaydı SSH üzerinden çalışmayı reddeder. Onun için kurulumu Mac'in başında çalıştır.
- **İsteğe bağlı.** Sen seçmedikçe hiçbir şey Telegram'ı, uzaktan erişimi, korumayı ya da ağı açmaz. Tier 2 değişmez: fiziksel dünyadaki bir eylem ya da senin adına başka bir tau'ya giden bir mesaj hâlâ senin onayını bekler.

### Sonradan özellik eklemek { #adding-a-feature-later }

```sh
tau setup                  # kontrol listesi: istediğini işaretle
tau setup run telegram     # tek bir özelliğin adımları, kurulu olsa bile
tau setup status           # her özellik, id'si ve durumu
```

Uygulamada: menüde, panelde ya da ayarlar penceresinde **Set up tau…**.

### Bir özelliği kaldırmak { #removing-a-feature }

```sh
tau setup --remove sub
```

`--remove`, bir onaydan sonra özelliğin paketini aynı sabitlenmiş `uv tool install` ile kaldırır. Ayarlar ve veriler kalır. Paketi olmayan bir özellik (Telegram, uzaktan erişim, oturum açılınca başlatma, uygulama) elle kapatılır; aşağıdaki her bölüm nasıl yapılacağını söyler.

## Terminal arayüzü { #terminal-ui }

Tam ekran arayüz `tau tui`: akan yanıtlar, araç kartları, bir pencerede onaylar ve oturum listesi. [tau ile konuş](../getting-started/talk.md) onu `tau chat` ile karşılaştırır.

- **Kurar:** tau-core ile birlikte yayımlanan ve onun sürümüne sabitlenen `tau-tui`. Tek satırlık kurucu onu her zaman içerir.
- **Platformlar:** macOS ve Linux. Varsayılan olarak açık.
- **Adımlar:** yok.
- **Kaldır:** `tau setup --remove tui`. `tau chat` kalır.

## tau uygulaması { #the-tau-app }

Mac uygulaması: menü çubuğunda bir **τ**, hub'ın gözetmeni, `tau tui` çalıştıran sohbet pencereleri, uyku modları, oturum açılınca başlatma ve bu sihirbazın kendi kopyası. Bkz. [uygulama rehberi](taubar.md).

- **Kurar:** uv üzerinden hiçbir şey. Adım, `tau.dmg` dosyasının bulunduğu [indirme sayfasını](https://tau.getporti.com/tr/download) gösterir (macOS 13 ve sonrası, Apple silicon ve Intel). Uygulama henüz Apple'ın noter onayından geçmedi; bu yüzden macOS onu açmadan önce bir kez sorar. İndirme sayfası onu açmanın iki yolunu gösterir.
- **Platformlar:** macOS. Terminalde varsayılan olarak kapalı; uygulamada zaten oradadır.
- **İzinler:** bildirimler. Uygulama, çalıştırdığı bir hub için kamera iznini de tutar; [sahip koruması](#owner-guard) buna ihtiyaç duyar.
- **Kurulu sayılır:** `tau.app`, `/Applications` ya da `~/Applications` içindeyse.
- **Kaldır:** **Launch at login** işaretini kaldır, tau'dan çık (başlattığı hub'ı durdurur) ve `tau.app`'i Çöp Sepeti'ne taşı.

## Sub-tau'lar { #sub-taus }

tau'nun adı olan, her biri kendi karakterine sahip uzmanları: bir koşu koçu, bir aşçı, bir öğretmen. Bkz. [Web sayfalı açık sub-tau'lar](public-sub-taus.md) ve [ADR 0012](../adr/0012-sub-taus.md).

- **Kurar:** `tau-sub`.
- **Platformlar:** macOS ve Linux. Varsayılan olarak açık.
- **Adımlar:** istediğinde ilkini nasıl yapacağına dair bir not:

    ```sh
    tau sub new coach --describe "sabırlı bir koşu koçu"
    tau sub chat coach          # ya da tau tui içinde /coach
    ```

- **Kaldır:** `tau setup --remove sub`. Sub-tau'ların dosyaları yapılandırmanda kalır.

## Telegram { #telegram }

Kendi botun üzerinden telefondan tau ile konuş. Hub Telegram'ı kendisi yoklar; arada sunucu yoktur ve hiçbir port açılmaz. Bkz. [Telegram](telegram.md).

- **Kurar:** hiçbir şey; kanal tau-core'un parçası.
- **Platformlar:** macOS ve Linux.
- **Adımlar:** senden bir şeyler isteyen tek bir adım, `tau telegram pair`:
    1. [@BotFather](https://t.me/botfather) ile bir bot oluştur (`/newbot`) ve token'ını kopyala.
    2. Token'ı gizli isteme (uygulamada gizli bir alana) yapıştır. tau onu Telegram'a doğrulatır ve `.env` dosyasına `TELEGRAM_BOT_TOKEN` olarak yazar.
    3. tau tek kullanımlık bir kod ve bir `t.me` bağlantısı gösterir. Bağlantıyı telefonunda aç ve **Başlat**'a bas ya da bota `/start <kod>` gönder. Kodu gönderen sohbet tau'nun yanıt verdiği tek sohbet olur (`TELEGRAM_ALLOWED_CHAT_IDS`); yani aranacak bir chat id yok.
- **Kurulu sayılır:** iki değer de ortamda ya da `.env` içindeyse. Çalışan bir hub eşleşmeyi hemen alır; yoksa hub'ı başlat.
- **Kaldır:** `<TAU_HOME>/.env` içindeki iki `TELEGRAM_…` satırını sil ve hub'ı yeniden başlat. Botun kendisini BotFather'da `/deletebot` siler.

## Uzaktan erişim { #remote-access }

Bu makineye telefonundan ulaş: Tailscale ikisini tek bir özel ağa koyar, SSH yalnızca o ağdan ve yalnızca anahtarla giriş kabul eder, mosh ve tmux da oturumu kilitli bir telefona rağmen ayakta tutar. Bkz. [Telefondan tau'ya ulaş](phone-tailscale-termius.md).

- **Kurar:** uv üzerinden hiçbir şey. tau-core kurulum betiklerini yanında taşır ve bir komut göstermeden önce onları `~/.local/share/tau/remote/` altına yazar.
- **Platformlar:** macOS ve Linux (Raspberry Pi dahil).
- **Adımlar:** üç denetim. Her biri ya kendiliğinden geçer ya da yalnızca senin yapabileceğin şeyi söyleyip bekler; **Enter** (uygulamada **Done, check again**) yeniden denetler, `skip` atlayıp devam eder:
    1. **Tailscale.** Kur ve giriş yap. macOS'ta adım, istersen indirme sayfasını açar; Linux'ta senin çalıştırman için Tailscale'in resmî kurulum komutunu gösterir.
    2. **SSH ve mosh.** Eksik bir şey varsa **tek bir komut** ve neyi değiştirdiğini gösterir:

        ```sh
        bash ~/.local/share/tau/remote/setup-all.sh
        ```

        Onu kendi terminalinde, kendi kullanıcınla çalıştır: parolanı (`sudo`) yalnızca root gerektiren kısımlar için sorar. tau onu asla çalıştırmaz.

    3. **Telefonun.** Termius'a girilecek değerler (adres, kullanıcı adın, port 22, mosh açık) ve Termius'un ürettiği anahtarı nasıl ekleyeceğin.
- **Kurulu sayılır:** `tau remote status` 0 ile çıkıyorsa.
- **Kaldır:** telefon rehberindeki [Sorun giderme](phone-tailscale-termius.md#sorun-giderme) bölümünde anlatılan geri alma adımları: SSH ek dosyası, uyanık tutma ajanı, kabuk blokları ve Uzaktan Giriş.

## Sahip koruması { #owner-guard }

tau yalnızca sen Mac'in başındayken yanıt verir: TUI ve `tau chat` kilitli açılır, bir yüz denetimiyle açılır, yedek olarak Touch ID vardır; tier-2 bir eylem de senin onayından sonra bir denetim daha ister. Bkz. [Sahip koruması](guard.md) ve [ADR 0008](../adr/0008-owner-guard.md).

- **Kurar:** tau-core ile birlikte yayımlanan ve onun sürümüne sabitlenen `tau-guard`. Yüz modeli (yaklaşık 40 MB) kurulum adımı tarafından bir kez indirilir.
- **Platformlar:** yalnızca macOS. Mac'in yerleşik kamerasını ve Touch ID'yi kullanır.
- **İzinler:** kamera. Uygulamada sihirbaz bu izni ister; böylece izin hub'ı çalıştıran tau.app'e ait olur.
- **Adımlar:**
    1. `tau guard doctor` ön koşulları denetler. Kurulumdan önce sorun bildirmesi beklenir; sonraki adım onları giderir.
    2. `tau guard setup` yüzünü Touch ID ya da Mac parolanın arkasında kaydeder. **Mac'in başında olmalısın:** SSH üzerinden reddedilir. Uygulamada sihirbazın kendi terminalinde çalışır.
    3. Hub'ı yeniden başlat: koruma bir sonraki hub ile kilitli başlar. `tau tui` içinde bir kez kilidi aç.
- **Kurulu sayılır:** yüzün kayıtlıysa.
- **Kaldır:** önce Mac'in başında `tau guard forget` çalıştır, sonra `tau setup --remove guard`. Kayıtlıyken kurulum paketi kaldırmayı reddeder; çünkü tau-guard'ı olmayan ama kaydı duran bir hub kilitli kalırdı.

## tau ağı { #the-tau-network }

tau'na bir adres, başka tau'larla kişiler, imzalı ve mühürlü mesajlar ve istersen herkese açık evrende bir yer. Bkz. [tau ağına katıl](tau-network.md).

- **Kurar:** `tau-net`.
- **Platformlar:** macOS ve Linux.
- **Adımlar:**
    1. `tau net init` tau'nun ağ kimliğini oluşturur. Kartındaki görünen adı sorar.
    2. **Spine** hakkında bir not: tau'nun adresi kendi Cloudflare hesabında küçük bir Worker'dır ve ücretsiz plan yeterlidir. Sonraki iki adım isteğe bağlıdır; sonra da kurabilirsin.
    3. `tau net spine init` spine projesini yazar (varsayılan `~/tau-spine`); Cloudflare'de bir alan adın varsa adresinle, yoksa bir `workers.dev` adresiyle.
    4. `tau net spine deploy` onu Cloudflare API'si üzerinden kurar. **Senden bir token:** tau, Cloudflare'in token sayfasını izinleri doldurulmuş olarak açar; sen token'ı oluşturup gizli isteme yapıştırırsın, o da `.env` dosyasına `CLOUDFLARE_API_TOKEN` olarak kaydedilir. Node.js ya da Wrangler gerekmez.
    5. `tau net universe join` tau'nu evrende listeler (isteğe bağlı; adın ve tau'n hakkında bir satır).
    6. `tau net universe claim` tau'n için bir kullanıcı adı alan bir GitHub giriş bağlantısı yazar (isteğe bağlı).
- **Kurulu sayılır:** kimlik varsa.
- **Kaldır:** `tau net universe leave` tau'nu evrenden çıkarır. `tau setup --remove net` paketi kaldırır; kimliğin ve kişilerin veri dizininde kalır, böylece sonraki bir kurulum onları yeniden bulur.

## Oturum açılınca başlat { #start-at-login }

Hub, sen oturum açınca başlayan ve bir çökmeden sonra geri gelen bir servis olur. Bkz. [tau'yu servis olarak çalıştır](hub-service.md).

- **Kurar:** hiçbir şey.
- **Platformlar:** macOS ve Linux. macOS'ta varsayılan olarak açık.
- **Adımlar:**
    - **macOS, terminalde:** `tau hub install`, bir launchd kullanıcı ajanı.
    - **macOS, uygulamada:** hub'ı uygulamanın kendisi çalıştırır ve uygulama oturum açılınca açılır. Kamerayı koruma için yalnızca uygulamanın çalıştırdığı bir hub kullanabilir.
    - **Linux:** bir systemd kullanıcı birimi, `sudo` gerekmez:

        ```sh
        mkdir -p ~/.config/systemd/user
        tau hub systemd-unit > ~/.config/systemd/user/tau-hub.service
        systemctl --user enable --now tau-hub
        ```

- **Kaldır:** macOS'ta `tau hub uninstall` (ya da uygulamada **Launch at login** işaretini kaldır); Linux'ta `systemctl --user disable --now tau-hub` ve birim dosyasını sil.

## Bulut modu { #cloud-mode }

İleri düzey: hub'ın kendisi, sürekli açık bir makinesi olmayan sahipler için kendi Cloudflare hesabındaki bir container'da çalışır. Workers Paid ve Docker gerektirir. Bkz. [tau'yu Cloudflare'de çalıştır](cloud-mode.md).

- **Kurar:** `tau-cloud` ve onunla birlikte `tau-net`.
- **Platformlar:** macOS ve Linux. Kontrol listesinde ileri düzey olarak işaretlidir.
- **Adımlar:** rehberi gösteren bir not; hazır olduğunda sıra `tau cloud push`'a gelir.
- **Kaldır:** `tau setup --remove cloud`. Hesap tarafını [Yerel moda geri dönmek](cloud-mode.md#yerel-moda-geri-donmek) anlatır.
