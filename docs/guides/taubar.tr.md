<!-- tr twin of guides/taubar.md, translated 2026-09-30 -->

# TauBar (macOS menü çubuğu)

TauBar, Mac hub'ı için tau'nun menü çubuğu uygulamasıdır: menü çubuğunda bir **τ**, Dock'ta
simge yok. Hub'ı (tau'nun çalıştığı makinedeki servis) çalıştırır ve gözetir, Mac'i senin
seçtiğin şekilde uyanık tutar ve oturum açılışında başlar. Kaynak kod ve eksiksiz referans
(imzalama, dosyalar, geliştirme)
[`apps/taubar/README.md`](https://github.com/fport/tau/blob/main/apps/taubar/README.md) içinde.

τ'ya sol tıklayınca aşağıdaki panel açılır; sağ tık aynı öğeleri sade bir menü olarak gösterir.
Panel açık ve koyu moda uyar, başka bir yere tıklayınca ya da Esc'e basınca kapanır.

```text
Hub                                      [ on]
(τ)  Up 2 h 5 min
     pid 1234 · started by TauBar
(➤)  Telegram
     polling as @your_bot
(!)  Last crash
     none
──────────────────────────────────────────────
Sleep
( )  Normal
(●)  Keep awake on AC power
( )  Keep awake with the lid closed    Set up…
──────────────────────────────────────────────
Launch at login                          [ on]
Open Hub Log
Open TauBar Log
Settings…                                   ⌘,
──────────────────────────────────────────────
Quit TauBar                                 ⌘Q
```

## Derle ve kur

macOS 13 veya daha yenisine, Rust'a (`rustup`), pnpm ile Node 20+'ya ve Xcode komut satırı
araçlarına ihtiyacın var.

```sh
cd apps/taubar
pnpm install
pnpm tauri build
cp -R src-tauri/target/release/bundle/macos/TauBar.app /Applications/
open -a TauBar
```

Derleme ad hoc imzalanır; bu, onu derleyen Mac için yeterlidir. İlk açılışta TauBar'ın
penceresi açılır; sonrasında uygulama menü çubuğunda yaşar.

!!! note "Menü çubuğunda τ yok mu?"
    Çentikli bir MacBook'ta macOS, çentiğin yanına sığmayan menü çubuğu simgelerini gizler ve
    ilk gizlenenler en yenileridir. TauBar'ı yeniden aç (Spotlight, Finder ya da `open -a TauBar`):
    penceresi bütün anahtarlarla ve bir Quit butonuyla görünür. Aynı anda yalnızca bir TauBar
    çalışır: ikinci bir açılış işi çalışana devreder ve kapanır. Başka menü çubuğu
    uygulamalarından çıkarak ya da bazılarını **System Settings → Menu Bar → Allow in the Menu Bar**
    altında kapatarak yer aç. Hidden Bar gibi bir menü çubuğu yöneticisi, ayırıcısının solundaki
    her şeyi gizler: onu genişlet ve τ'yu Cmd ile sürükleyerek ayırıcının sağına taşı.

Ardından **Launch at login** anahtarını aç ve `infra/remote/setup.sh` komutunu bir kez
çalıştır: TauBar `/Applications` içindeyken bu komut
[uzaktan erişim kurulumundaki](phone-tailscale-termius.md) `com.tau.keepawake` agent'ını
kaldırır, çünkü aynı işi TauBar yapar. `infra/remote/doctor.sh` ikisini de kabul eder.

## Hub'ı çalıştır

**Run the hub** anahtarını aç; TauBar bu Mac'te hub'ın gözetmeni olur. macOS'ta varsayılan
budur ([alternatifi](hub-service.md#macos-alternative-launchd-user-agent) bir launchd agent'ıdır):

- `tau hub run` komutunu kendi alt süreci olarak başlatır ve kontrol API'si yanıt verir vermez
  `Hub: up …` gösterir;
- bir çökme ya da `kill -9` bir saniye sonra yeniden başlatılır (başarısız olmaya devam ettikçe
  beklemeler uzar) ve yeni hub çökmeyi bildirir;
- `tau hub stop` hub'ı durmuş hâlde bırakır; anahtarı kapatmak onu durdurur; TauBar'dan
  çıkmak onun başlattığı hub'ı durdurur;
- asla ikinci bir hub başlatmaz: elle ya da launchd ile başlatılmış bir hub gösterilir
  (`started outside TauBar`, `run by launchd`) ve kendi hâline bırakılır.

TauBar'ın tau-core kurulu Python'a ve `TAU_HOME` değerine ihtiyacı var. İlk açılışta bunları
kurulu bir `com.tau.hub` launchd agent'ından kopyalar; yoksa penceresini aç, **How TauBar starts
the hub** → **Use a tau checkout…** yolunu izle. Hub'ı launchd'den devralmak için checkout
içinde `uv run tau hub uninstall` çalıştır ve **Run the hub** anahtarını aç. Veri dizini,
port ve ortam alanları dahil ayrıntılar: [tau'yu servis olarak çalıştır](hub-service.md#macos-taubar-default).

## Uyku modları

| Mod | Etkisi |
|---|---|
| Normal | Mac her zamanki gibi uyur. |
| **Keep awake on AC power** (varsayılan) | Fişe takılıyken sistem uykusu yok, `caffeinate -s` gibi: bir IOKit `PreventSystemSleep` assertion'ı, root gerekmez. Pilde ya da kapak kapalıyken Mac yine uyur. |
| Keep awake with the lid closed | Kapak kapalıyken de uyanık kalır (`pmset -a disablesleep 1`). Bir kerelik bir sudoers kuralı gerektirir. |

Seçim yeniden başlatmalardan sonra korunur. `pmset -g assertions` ile kontrol et
(`… (taubar): … PreventSystemSleep named: "TauBar keeps the Mac awake for tau"` gibi bir satır);
kapak kapalı mod için de `pmset -g` (`SleepDisabled 1`). **TauBar'dan çıkmak normal uykuyu geri
getirir.**

### Kapak kapalı modu kur { #set-up-the-lid-closed-mode }

Kullanıcına tam olarak `/usr/bin/pmset -a disablesleep 0` ve `… 1` komutlarına izin veren, başka
hiçbir şeye izin vermeyen bir sudoers kuralı var olana kadar mod "needs setup" gösterir.
Checkout içinden, kendi terminalinde:

```sh
apps/taubar/sudoers/install-sudoers.sh --print   # show and check the rule, install nothing
apps/taubar/sudoers/install-sudoers.sh           # install it (sudo asks for your password)
```

TauBar bunu beş saniye içinde fark eder. Yeniden kaldırmak için (bu önce uykuyu yeniden
etkinleştirir):

```sh
apps/taubar/sudoers/uninstall-sudoers.sh
```

Uyumayan kapalı bir MacBook yine de ısınır: bu modu fişe takılıyken, açık havada kullan.

## Oturum açılışında başlat

**Launch at login** anahtarı TauBar'ı bir launchd agent'ı üzerinden değil, `SMAppService`
üzerinden kaydeder (System Settings → General → Login Items → Open at Login): bazı Mac'lerde
launchd, kullanıcı agent'larının otomatik başlatılmasını süresiz olarak bekletir (bkz.
[tau'yu servis olarak çalıştır](hub-service.md#macos-taubar-default)). Login item uygulamanın
mevcut konumunu gösterir; bu yüzden TauBar onu yalnızca `/Applications` (ya da
`~/Applications`) içinden çalışırken açar, aksi hâlde bunu söyler. **Run the hub** açıkken
hub da oturum açılışında bu yolla başlar.
