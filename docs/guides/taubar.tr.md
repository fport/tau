<!-- tr twin of guides/taubar.md, translated 2026-10-01 -->

# tau uygulaması (macOS)

tau'nun Mac uygulaması, adı **tau**: menü çubuğunda bir **τ**, hub'ın (tau'nun bu Mac'te
çalıştırdığı servis) gözetmeni ve `tau tui` çalıştıran sohbet pencereleri. Mac'i senin seçtiğin
şekilde uyanık tutar, oturum açılışında başlar ve kendini günceller. Daha önceki iki uygulamanın
yerini aldı: TauBar (bu sayfanın eskiden anlattığı menü çubuğu uygulaması) ve tau Desktop (sohbet
pencereleri); böylece izinleri tek bir uygulama tutar
([ADR 0014](https://github.com/fport/tau/blob/main/docs/adr/0014-one-installer-and-onboarding.md)).
Kaynak kod ve eksiksiz referans (imzalama, sürümler, dosyalar, geliştirme)
[`apps/tau/README.md`](https://github.com/fport/tau/blob/main/apps/tau/README.md) içinde.

τ'ya sol tıklayınca aşağıdaki panel açılır; sağ tık aynı öğeleri sade bir menü olarak gösterir.
Panel açık ve koyu moda uyar, başka bir yere tıklayınca ya da Esc'e basınca kapanır.

```text
Hub                                      [ on]
(τ)  Up 2 h 5 min
     pid 1234 · started by the app
(➤)  Telegram
     polling as @your_bot
(!)  Last crash
     none
(▣)  Guard                (yalnızca hub sahip korumasını çalıştırırken)
     unlocked
     Lock now
──────────────────────────────────────────────
Sleep
( )  Normal
(●)  Keep awake on AC power
( )  Keep awake with the lid closed    Set up…
──────────────────────────────────────────────
New Chat Window                             ⌘N
──────────────────────────────────────────────
Launch at login                          [ on]
Open Hub Log
Open App Log
Settings…                                   ⌘,
Check for Updates…
──────────────────────────────────────────────
Quit tau                                    ⌘Q
```

## Kur { #install }

### Bir sürümden { #from-a-release }

1. Son sürüm olan [`tau.dmg`](https://tau.getporti.com/download/tau.dmg) dosyasını indir
   ([indirme sayfası](https://tau.getporti.com/tr/download) da aynı dosyaya bağlanır), aç ve
   **tau**'yu **Applications** klasörüne sürükle.
2. tau'yu aç. İlk seferde macOS, tau'yu kötü amaçlı yazılım için denetleyemediğini söyler:
   uygulama imzalıdır ama Apple tarafından noter onayından (notarisation) geçirilmemiştir.
   **System Settings → Privacy & Security** bölmesini aç, en altlarda tau ile ilgili satırı bul,
   **Open Anyway**'e tıkla ve onayla. macOS 14 ve öncesinde tau.app'e sağ tıklayıp **Open**
   demek de aynı işi görür. Bu, güncellemelerden sonra değil, kurulum başına bir kez olur.
3. tau ayarlar penceresini açar. **How tau starts the hub** altında tau checkout'unu seç
   (**Use a tau checkout…**), sonra **Run the hub** ve **Launch at login** kutularını işaretle.

### Checkout'tan { #from-the-checkout }

macOS 13 veya daha yenisine, Rust'a (`rustup`), [Bun](https://bun.sh)'a ve Xcode komut satırı
araçlarına ihtiyacın var.

```sh
cd apps/tau
bun install
bun run tauri build
cp -R src-tauri/target/release/bundle/macos/tau.app /Applications/
open -a tau
```

Bu derleme ad hoc imzalanır; bu, onu derleyen Mac için yeterlidir. İlk açılışta tau'nun ayarlar
penceresi açılır; sonrasında uygulama menü çubuğunda yaşar.

!!! note "Menü çubuğunda τ yok mu?"
    Çentikli bir MacBook'ta macOS, çentiğin yanına sığmayan menü çubuğu simgelerini gizler ve
    ilk gizlenenler en yenileridir. tau'yu yeniden aç (Spotlight, Finder ya da `open -a tau`):
    bir pencere görünür; bir sohbet penceresi açıkken menü çubuğunda **Settings…** ve **Quit tau**
    içeren kendi tau menüsü de vardır. Aynı anda yalnızca bir tau çalışır: ikinci bir açılış işi
    çalışana devreder ve kapanır. Başka menü çubuğu uygulamalarından çıkarak ya da bazılarını
    **System Settings → Menu Bar → Allow in the Menu Bar** altında kapatarak yer aç. Hidden Bar
    gibi bir menü çubuğu yöneticisi, ayırıcısının solundaki her şeyi gizler: onu genişlet ve
    τ'yu Cmd ile sürükleyerek ayırıcının sağına taşı.

Ardından **Launch at login** anahtarını aç ve `infra/remote/setup.sh` komutunu bir kez çalıştır:
tau `/Applications` içindeyken bu komut
[uzaktan erişim kurulumundaki](phone-tailscale-termius.md) `com.tau.keepawake` agent'ını
kaldırır, çünkü aynı işi tau yapar. `infra/remote/doctor.sh` ikisini de kabul eder.

### TauBar ya da tau Desktop'tan geçiş { #coming-from-taubar-or-tau-desktop }

tau'nun kendi paket kimliği (bundle id, `com.tau.app`) var, yani eski uygulamaların yerine
kendiliğinden geçmez:

1. TauBar'dan (**Quit TauBar** çalıştırdığı hub'ı durdurur) ve tau Desktop'tan çık.
2. TauBar'ı System Settings → General → Login Items'tan kaldır; `TauBar.app` ve
   `tau Desktop.app` uygulamalarını Applications'tan sil.
3. tau'yu aç. İlk açılışı TauBar'ın ayarlarını (uyku modu, **Run the hub**, hub'ın nasıl
   başlatıldığı) ve tau Desktop'ın klasörünü devralır; eski dosyaları değiştirmez.
4. **Launch at login** kutusunu yeniden işaretle.
5. macOS kamerayı bir kez daha, bu sefer tau için ister: bir izin tek bir uygulamaya aittir ve
   tau yeni bir uygulamadır.

## İlk açılış { #first-launch }

TauBar ile tau Desktop'ın birleştiği tau uygulaması ([ADR 0014](../adr/0014-one-installer-and-onboarding.md)),
ilk açılışında bir **kurulum sihirbazı** açar. Menüsündeki, panelindeki, ayarlar penceresindeki
ve boş bir sohbet penceresindeki **Set up tau…** onu yeniden açar; özellikleri sonra eklemek ya
da çıkarmak için de bunu kullanırsın. Sihirbaz, terminaldeki `tau setup` ile aynı motoru
[JSON protokolü](../reference/setup.md#the-json-protocol) üzerinden çalıştırır; iki yol da aynı
tau'ya varır. Adımlar soldadır ve her adım atlanabilir.

1. **Dil:** sihirbaz ve tau'nun orada söylediği her şey için İngilizce ya da Türkçe.
2. **tau'yu kur:** sihirbaz önce tau'yu arar: uygulamanın hub ayarları, bir kaynak kopyasının
   `.venv`'i, bir `uv tool install tau-core` (`uv tool dir`, `UV_TOOL_DIR`,
   `~/.local/share/uv/tools`) ya da bir `tau` komutu. Bulduğunu hub'a ve sohbet pencerelerine
   gösterir. tau yoksa onu ev klasörüne [uv](https://docs.astral.sh/uv/) ile kurar
   (`uv tool install tau-core --with tau-tui`); uv de yoksa önce bunu söyler, sonra Astral'ın
   resmî kurulum betiğini [tek satırlık kurucunun](../reference/setup.md#the-installer) yaptığı
   gibi indirip çalıştırır. Hiçbir adım yönetici parolası istemez.
3. **Model anahtarı:** sağlayıcıyı seç ve anahtarı gizli bir alana yapıştır. tau anahtarı küçük
   bir istekle kontrol eder ve yalnızca senin okuyabildiğin `.env` dosyasında saklar; reddedilen
   bir anahtar orada gösterilir ve hiçbir şey yazılmaz. Henüz anahtarın yok mu? Hazır cevaplı
   `fake` sağlayıcıyla etrafa bakabilirsin.
4. **Hakkında** (isteğe bağlı): adın, tau'nun sana nasıl hitap edeceği, konuştuğun diller.
5. **Özellikler:** tau'nun bu Mac'te ne yapacağı; zaten açık olanlar ve bir özelliğin neden
   olmadığı da görünür. Uygulama seçtiklerinin paketlerini kurar.
6. **İzinler:** yalnızca özelliklerinin ihtiyaç duydukları, her biri bir cümlelik gerekçesiyle:
   sahip koruması için kamera, uygulama için bildirimler. **Allow…** macOS'un kendi sorusunu tau
   adına gösterir; uygulama hiçbir izni kendi kendine vermez, **Open System Settings** de önceki
   bir cevabı değiştirir.
7. **Özellik adımları:** her özelliğin adımları, canlı olarak. Sahip korumasının kaydı
   sihirbazın kendi terminalinde çalışır, bu yüzden macOS kamerayı tau için sorar. Telegram bot
   token'ını ister ve botuna göndereceğin kodu bağlantısıyla gösterir. Omurga (spine)
   Cloudflare'in token sayfasını açar ve token'ı alır. Uzaktan erişim kontrollerini ve yalnızca
   senin Terminal'de çalıştıracağın tek komutu gösterir (`sudo` ile parolanı orada ister): kopyala,
   çalıştır, sonra **Done, check again**. Uygulama onu asla çalıştırmaz. Oturum açılınca başlatma,
   uygulamanın hub'ı çalıştırması ve oturum açılınca açılması demektir.
8. **Özet:** açık olanlar, `tau doctor` kontrolleri, **Open a chat window** ve **Start the hub**.

## Sohbet pencereleri { #chat-windows }

**New Chat Window** (⌘N; panelde, menüde ve ayarlar penceresinde) gerçek `tau tui`'yi çalıştıran
bir pencere açar; TUI'nin yaptığı her şey orada da çalışır, sahip korumasının kilit ekranı
dahil. Bir sohbet penceresi açıkken tau'nun Dock simgesi ve kendi menü çubuğu olur; sonuncusunu
kapatmak onu yeniden yalnızca menü çubuğuna döndürür.

Bir sohbet penceresi checkout'un kendi `.venv/bin/python -m tau_core tui` komutunu çalıştırır.
Checkout'u, tau onunla açıldıysa `TAU_HOME`'dan, yoksa daha önce seçilen klasörden alır; ilk
seferde hub'ın checkout'unu (**Use This Folder**) ya da bir klasör seçiciyi önerir ve klasörü
kullanmadan önce `python -m tau_core version` ile denetler. `TAU_DATA_DIR`'ı ve hub portunu,
hub'ın da TUI'nin de okuduğu checkout'taki `.env` ve `tau.toml` içinde tut.

Tuşlar: ⌘N yeni bir pencere, ⌘W birini kapatır (TUI, ctrl+q ile kapandığı gibi kapanır), ⌘C/⌘V
kopyala ve yapıştır, Option ile sürüklemek metin seçer, ⌘ ile tıklamak bir bağlantıyı açar.
ctrl ve Option dahil diğer her tuş TUI'ye gider. ⌘Q tau'dan çıkar ve tau hub'ı çalıştırıyorsa
önce sorar, çünkü hub da onunla durur; tau'yu çalışır tutmak için bunun yerine sohbet
pencerelerini kapat.

## Hub'ı çalıştır { #run-the-hub }

**Run the hub** anahtarını aç; tau bu Mac'te hub'ın gözetmeni olur. macOS'ta varsayılan budur
([alternatifi](hub-service.md#macos-alternative-launchd-user-agent) bir launchd agent'ıdır):

- `tau hub run` komutunu kendi alt süreci olarak başlatır ve kontrol API'si yanıt verir vermez
  `Hub: up …` gösterir;
- bir çökme ya da `kill -9` bir saniye sonra yeniden başlatılır (başarısız olmaya devam ettikçe
  beklemeler uzar) ve yeni hub çökmeyi bildirir;
- `tau hub stop` hub'ı durmuş hâlde bırakır; anahtarı kapatmak onu durdurur; tau'dan çıkmak onun
  başlattığı hub'ı durdurur;
- asla ikinci bir hub başlatmaz: elle, launchd ile ya da TauBar ile başlatılmış bir hub
  gösterilir (`started outside the app`, `run by launchd`) ve kendi hâline bırakılır.

tau'nun tau-core kurulu Python'a ve `TAU_HOME` değerine ihtiyacı var. İlk açılışta bunları
TauBar'dan ya da kurulu bir `com.tau.hub` launchd agent'ından devralır; yoksa ayarlar penceresini
aç, **How tau starts the hub** → **Use a tau checkout…** yolunu izle. Hub'ı launchd'den devralmak
için checkout içinde `uv run tau hub uninstall` çalıştır ve **Run the hub** anahtarını aç. Veri
dizini, port ve ortam alanları dahil ayrıntılar:
[tau'yu servis olarak çalıştır](hub-service.md#macos-taubar-default).

## Sahip koruması ve kamera { #owner-guard-and-the-camera }

Hub sahip korumasını (owner guard) çalıştırdığında
([ADR 0008](https://github.com/fport/tau/blob/main/docs/adr/0008-owner-guard.md)) panelde bir
**Guard** satırı (`locked`, `unlocked`, `unavailable (camera denied)`), sağ tık menüsünde de bir
koruma satırı (`Guard: locked`) görünür; ikisinin altında da **Lock now** vardır. Bu, hub'dan
imzalı bir istekle kilitlenmesini ister; tau kilidi asla açmaz. Koruma yoksa ikisi de gizlidir.
Korumanın kurulumu, günlük kullanımı ve "kilitli kaldım" adımları [Sahip koruması](guard.md)
rehberinde.

Hub tau'nun alt süreci olduğu için macOS kamerayı tau adına ister ("tau would like to access the
camera"); tau bunun için kullanım açıklamalarını ve kamera ile mikrofon yetkilerini
(entitlements) taşır. Bir sohbet penceresindeki `tau tui` de tau'nun alt sürecidir; bu yüzden
bir sohbet penceresindeki `tau guard setup` tau'nun iznini kullanır. Hub kameranın
reddedildiğini bildirdiğinde **Grant camera access…** System Settings → Privacy & Security →
Camera bölmesini açar. Hiçbir pencerenin sayfası kamerayı ya da mikrofonu kendisi kullanamaz:
her webview izin isteği reddedilir.

İzin güncellemelerden sonra da kalır, çünkü her sürüm aynı sertifikayla imzalanır. macOS bir
izni bir uygulamanın *designated requirement*'ı için saklar: imzadaki, hangi kodun "bu uygulama"
olduğunu söyleyen kural. Tek bir sertifikayla bu kural derlemeyi değil sertifikayı adlandırır ve
her güncelleme onu karşılar. Checkout'tan bir derleme ad hoc imzalanır, yani her yeniden derleme
macOS için yeni bir uygulamadır ve izni yeniden sorar;
[README](https://github.com/fport/tau/blob/main/apps/tau/README.md#why-a-stable-identity-keeps-the-camera-permission)
imzalamayı ve sürüm kimliğini kendi derlemelerinde nasıl kullanacağını anlatır. macOS'un
yeniden sormasını istersen `tccutil reset Camera com.tau.app` çalıştır ve hub'ı tau'dan yeniden
başlat (**Run the hub** işaretini kaldırıp yeniden koy).

## Uyku modları { #sleep-modes }

| Mod | Etkisi |
|---|---|
| Normal | Mac her zamanki gibi uyur. |
| **Keep awake on AC power** (varsayılan) | Fişe takılıyken sistem uykusu yok, `caffeinate -s` gibi: bir IOKit `PreventSystemSleep` assertion'ı, root gerekmez. Pilde ya da kapak kapalıyken Mac yine uyur. |
| Keep awake with the lid closed | Kapak kapalıyken de uyanık kalır (`pmset -a disablesleep 1`). Bir kerelik bir sudoers kuralı gerektirir. |

Seçim yeniden başlatmalardan sonra korunur. `pmset -g assertions` ile kontrol et
(`… (tau-app): … PreventSystemSleep named: "tau keeps the Mac awake"` gibi bir satır); kapak
kapalı mod için de `pmset -g` (`SleepDisabled 1`). **tau'dan çıkmak normal uykuyu geri getirir.**

### Kapak kapalı modu kur { #set-up-the-lid-closed-mode }

Kullanıcına tam olarak `/usr/bin/pmset -a disablesleep 0` ve `… 1` komutlarına izin veren, başka
hiçbir şeye izin vermeyen bir sudoers kuralı var olana kadar mod "needs setup" gösterir.
Checkout içinden, kendi terminalinde:

```sh
apps/tau/sudoers/install-sudoers.sh --print   # show and check the rule, install nothing
apps/tau/sudoers/install-sudoers.sh           # install it (sudo asks for your password)
```

tau bunu beş saniye içinde fark eder. TauBar için kurulmuş bir kural çalışmaya devam eder.
Yeniden kaldırmak için (bu önce uykuyu yeniden etkinleştirir):

```sh
apps/tau/sudoers/uninstall-sudoers.sh
```

Uyumayan kapalı bir MacBook yine de ısınır: bu modu fişe takılıyken, açık havada kullan.

## Oturum açılışında başlat { #launch-at-login }

**Launch at login** anahtarı tau'yu bir launchd agent'ı üzerinden değil, `SMAppService`
üzerinden kaydeder (System Settings → General → Login Items → Open at Login): bazı Mac'lerde
launchd, kullanıcı agent'larının otomatik başlatılmasını süresiz olarak bekletir (bkz.
[tau'yu servis olarak çalıştır](hub-service.md#macos-taubar-default)). Login item uygulamanın
mevcut konumunu gösterir; bu yüzden tau onu yalnızca `/Applications` (ya da `~/Applications`)
içinden çalışırken açar, aksi hâlde bunu söyler. **Run the hub** açıkken hub da oturum
açılışında bu yolla başlar.

## Güncellemeler { #updates }

Bir sürüm derlemesi, açıldıktan bir dakika sonra ve sonra günde bir kez tau.getporti.com'a
tau'nun son sürümünü sorar (`https://tau.getporti.com/download/latest.json`) ve daha yeni bir
sürümü önerir; sen tıklamadan hiçbir şey kurulmaz. **Check for
Updates…** hemen sorar. Kurulum uygulamayı değiştirip yeniden açar: sohbet pencereleri kapanır ve
hub yeni sürümle yeniden başlar. Güncelleme kurulmadan önce tau'nun kendi imza anahtarıyla
denetlenir. Ayarlar penceresindeki **Look for an update once a day** günlük denetimi kapatır; bir
denetim tau.getporti.com'a olağan istekten başka bir şey göndermez.
