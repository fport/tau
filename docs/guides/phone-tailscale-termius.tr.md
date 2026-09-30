<!-- tr twin of guides/phone-tailscale-termius.md, translated 2026-10-01 -->

# Telefondan tau'ya ulaş (Tailscale + Termius)

Hedef şu: telefonda Termius'u aç, hub'daki (tau'nun çalıştığı, sana ait makine) bir tmux oturumuna düş, `tau tui` çalıştır ve telefon kilitlendiğinde ya da ağ değiştiğinde o oturum yaşamaya devam etsin. İnternete hiçbir şey açılmaz: telefon ve hub bir Tailscale özel ağı üzerinden konuşur, SSH yalnızca anahtar kabul eder ve yalnızca o ağdan kabul eder, mosh da dolaşım (roaming) sırasında bağlantıyı korur.

```text
Phone (Termius) ──▶ Tailscale ──▶ OpenSSH on the hub ──▶ mosh ──▶ tmux ──▶ tau tui
```

| Parça | Görevi |
|---|---|
| **Tailscale** | Port açmadan telefonu ve hub'ı aynı özel ağa (bir *tailnet*'e) koyar. |
| **OpenSSH** (macOS Remote Login) | Yalnızca anahtarla, yalnızca senin kullanıcın olarak, yalnızca tailnet'ten giriş. |
| **mosh** | Bağlantı ağ değişikliklerinden ve kilitli telefondan sağ çıkar. |
| **tmux** | Bağlantı koptuğunda oturum ve içinde çalışan her şey çalışmaya devam eder. |
| **keep-awake agent'ı** | Mac fişe takılıyken uyumaz (`caffeinate -s`). [tau uygulaması](taubar.md) kurulduktan sonra `setup.sh` onu kaldırır ve işi uygulama yapar. |

Betikler deponun [`infra/remote/`](https://github.com/fport/tau/tree/main/infra/remote) dizininde; macOS ve Linux için (Raspberry Pi hub dahil). `tau setup` seni bunlardan adım adım geçirir; ondan sonraki bölümler aynısını elle yapar.

## Rehberli yol: `tau setup` → Uzaktan erişim

```sh
tau setup              # kontrol listesinde "Uzaktan erişim"i işaretle
tau setup run remote   # ya da daha sonra istediğin zaman yalnızca bu özelliği
```

Üç denetimden geçer. Her biri ya kendiliğinden geçer ya da yalnızca senin yapabileceğin şeyi söyleyip bekler:

1. **Tailscale.** Tailscale CLI'yi bulur (`PATH` üzerinde ya da macOS'ta Tailscale.app'in içinde) ve `tailscale status --json` çıktısını okur: Tailscale'de oturum açık ve bağlıysa adım geçer, hub'ın MagicDNS adını ve 100.x adresini gösterir. Değilse Tailscale'in nasıl kurulacağını söyler ve istersen sayfayı açar (macOS: Mac App Store ya da tailscale.com/download), resmî kurulum betiğini senin çalıştırman için gösterir (Linux: `sudo` gerektirir) ya da nasıl oturum açılacağını söyler.
2. **SSH ve mosh.** `infra/remote/doctor.sh`'in denetlediklerini denetler: sshd 22 numaralı portta yanıt veriyor mu; tau'nun drop-in dosyası `/etc/ssh/sshd_config.d/010-tau.conf` parola ve keyboard-interactive girişi kapatıyor ve `AllowUsers`'ı tailnet'ten ve localhost'tan gelen sana sınırlıyor mu; localhost'ta parolayla giriş reddediliyor mu; mosh ve tmux kurulu mu (macOS'ta ayrıca `~/.zshenv` bloğu). Değilse **tek bir komut** ve neleri değiştirdiğini gösterir, sonra bekler:

    ```text
    → Bunu kendi terminalinde, sudo olmadan kendi kullanıcınla çalıştır: parolanı (sudo)
      yalnızca root gerektiren adımlar için sorar. tau onu hiçbir zaman çalıştırmaz.

          bash ~/.local/share/tau/remote/setup-all.sh

    Bitirince yeniden denetlemek için Enter'a bas ya da atla yaz:
    ```

    tau `sudo`'yu hiçbir zaman çalıştırmaz. Komutu başka bir terminal penceresinde çalıştır, geri gel ve Enter'a bas: yeniden denetler.
3. **Telefonun.** Termius'a girilecekleri canlı durumdan yazdırır: adres (`my-mac.tailXXXXXX.ts.net`), kullanıcı adın, port 22, Mosh açık ve `tau-attach` başlangıç komutu. `~/.ssh/authorized_keys` içinde bir anahtar olana kadar, Termius'un oluşturduğu anahtarı nasıl ekleyeceğini söyler (bölüm 2).

`tau remote status` bütün denetimleri istediğin zaman yeniden çalıştırır ve uzaktan erişim hazır olunca 0 ile çıkar. `tau remote tailscale`, `tau remote ssh` ve `tau remote phone` birer adımı çalıştırır. Değerler yalnızca yazdırılır, hiçbir dosyaya yazılmaz.

**Komut nereden geliyor.** Bir checkout'ta `infra/remote/setup-all.sh`'tir. Kurulu bir tau'nun checkout'u yoktur; bu yüzden tau-core `infra/remote`'un bir kopyasını taşır ve komutu göstermeden önce onu `~/.local/share/tau/remote/` altına (`TAU_DATA_DIR` içinde) yazar. İstersen önce orada oku. Yanındaki `config.local.env` makineye özgü ayarları tutar ve hiçbir zaman üzerine yazılmaz.

## 1. Hub'ı kur

=== "macOS"

    Tek komut iki kısmı da yapar; kendi terminalinde, normal kullanıcınla (sudo, root gereken yerde parolanı sorar):

    ```sh
    ./infra/remote/setup-all.sh      # setup.sh, then setup-sudo.sh
    ```

    Ya da iki kısmı tek tek. İlki sudo gerektirmez; ikincisi parolanı sorar:

    ```sh
    ./infra/remote/setup.sh          # tmux, mosh, ~/.tmux.conf, ~/.zshenv, tau-attach, keep-awake agent
    ./infra/remote/setup-sudo.sh     # Tailscale, sshd hardening, Remote Login
    ```

    Sonra giriş yap: Tailscale.app'i aç, **Privacy & Security** altında sistem uzantısına izin ver ve oturum aç.

    sudo kısmının `/etc/ssh/sshd_config.d/010-tau.conf` dosyasına yazdıkları:

    - parola ve keyboard-interactive (PAM) girişleri kapalı; yalnızca anahtarlar;
    - `AllowUsers`, senin kullanıcınla ve yalnızca tailnet'ten (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`) ve localhost'tan gelen bağlantılarla sınırlı;
    - agent yönlendirme kapalı; yalnızca yerel (`-L`) TCP yönlendirmeye izin var.

    macOS'ta sshd her arayüzü dinler, ama aynı kafe ağında olup 22 numaralı porta ulaşan biri bile `AllowUsers` tarafından durdurulur.

=== "Linux (Raspberry Pi)"

    Önce Tailscale, resmî betiğiyle; sonra oturum aç:

    ```sh
    curl -fsSL https://tailscale.com/install.sh | sh
    sudo tailscale up
    ```

    Sonra tek komut, normal kullanıcınla (sudo parolanı sorar):

    ```sh
    ./infra/remote/setup-all.sh      # runs setup-linux.sh
    ```

    `setup-linux.sh`, macOS'takiyle aynı drop-in dosyasını openssh-server, mosh ve tmux'u (apt-get, dnf ya da pacman ile) kurmadan **önce** yazar; böylece yeni bir SSH sunucusu sıkılaştırılmış başlar. `/etc/ssh/sshd_config`'in `sshd_config.d`'yi içerdiğini denetler, yapılandırmayı `sshd -t` ile dener ve başarısız olursa geri alır, `~/.tmux.conf` bloğunu ve `tau-attach`'ı ekler, SSH servisini etkinleştirip yeniden yükler. SSH üzerindeysen ve `~/.ssh/authorized_keys` içinde anahtar yoksa hiçbir şeyi değiştirmeden durur; böylece kendini dışarıda bırakamazsın.

    Elle yapmak istersen drop-in şu:

    ```sh
    sudo tee /etc/ssh/sshd_config.d/010-tau.conf >/dev/null <<'EOF'
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    PubkeyAuthentication yes
    AllowAgentForwarding no
    AllowTcpForwarding local
    AllowUsers you@100.64.0.0/10 you@fd7a:115c:a1e0::/48 you@127.0.0.1 you@::1
    EOF
    sudo systemctl restart ssh
    ```

    `you` yerine kendi kullanıcı adını yaz. İlk oturumu kapatmadan önce ikinci bir oturumdan dene.

## 2. Telefonu kur

1. Telefona **Tailscale**'i kur ve hub'la **aynı hesapla** giriş yap.
2. **Termius**'u kur.
3. Bir anahtar oluştur: Termius → **Keychain** → **+** → **Generate Key** → tür olarak **ED25519** → adını `iphone` koy. Anahtarı aç ve açık anahtarı kopyala.
4. Açık anahtarı hub'a ekle (sudo gerekmez). macOS'ta Universal Clipboard ile yapıştır:

    ```sh
    ./infra/remote/add-key.sh        # an installed tau: bash ~/.local/share/tau/remote/add-key.sh
    ```

    Ya da onu hub'daki `~/.ssh/authorized_keys` dosyasının sonuna kendin ekle (dosyaya `chmod 600`, dizine `chmod 700`).

5. Termius'ta host'u oluştur. `tau remote phone` bu değerleri canlı durumdan yazdırır:

    | Alan | Değer |
    |---|---|
    | Address | hub'ın MagicDNS adı, örneğin `my-mac.tailXXXXXX.ts.net` |
    | Username | hub'daki kullanıcı adın |
    | Key | `iphone` |
    | **Mosh** | açık |
    | **Startup Snippet** | `tau-attach` |

`tau-attach`, `setup.sh`'in `~/.local/bin` içine kurduğu minik bir betik: `tau` adlı tmux oturumuna bağlanır, gerekirse oturumu oluşturur. Startup snippet olarak onu kullanınca her bağlantı aynı oturuma düşer.

## 3. Zinciri kontrol et

```sh
tau remote status                # macOS and Linux
./infra/remote/doctor.sh         # macOS: also sleep and the firewall
```

`tau remote status` Tailscale'i, drop-in dosyasıyla sshd'yi, bir parolalı giriş denemesini, mosh'u, tmux'u ve telefonun anahtarını denetler, adresi yazdırır ve her şey yerindeyse 0 ile çıkar. `doctor.sh` macOS'ta aynılarını, ayrıca keep-awake agent'ını ve güvenlik duvarını denetler, MagicDNS adını ve tailnet IP'sini yazdırır. Termius'tan bağlan: hiçbir şey yazmadan tmux'a düşmelisin.

!!! warning "Kişisel değerler depoya girmez"
    Hostname'ler, tailnet adları, IP'ler ve anahtar parmak izleri kişiseldir. `.env.example` onları `TAU_MAC_MAGICDNS=my-mac.tailXXXXXX.ts.net`, `TAU_MAC_TAILNET_IP=100.x.y.z`, `TAU_MAC_SSH_HOST_KEY_FP=SHA256:...` gibi listeler. Gerçek değerleri gitignore'daki `.env` dosyana koy; doctor onları zaten canlı olarak yazdırır.

## 4. TUI'yi tmux içinde çalıştır

tmux oturumuna girdikten sonra:

```sh
cd /path/to/tau && uv run tau tui        # from a checkout
tau tui                                  # from a uv tool install
```

TUI'yi çalışır hâlde bırak. Telefonu kilitle, Wi-Fi'dan mobil veriye geç, geri gel: mosh yeniden bağlanır ve aynı ekran oradadır. mosh pes ederse (uzun bir çevrimdışı ara), Termius'ta yeniden bağlan; `tau-attach` oturumu, içinde TUI hâlâ çalışır şekilde geri getirir.

Aynı ekranı hub'ın kendi klavyesinden görmek için orada `tau-attach` çalıştır.

## 5. 50 sütunluk yerleşim

Bir telefon terminali yaklaşık 50 sütuna 24 satırdır. TUI'nin 60 sütunun altı için özel bir **phone** aralığı vardır:

```text
 τ tau · home                                  en
 › Salon lambası açık mı? Açıksa kapat.
 ○ set_light(room="salon", on=false)
   ⎿  tier 2 · running
 ✻ Running set_light…
 ❯
 esc cancel · ^j newline                     busy
```

- Başlık oturum id'sini göstermez; `/session` gösterir.
- Araç rozetleri sonuç satırına taşınır; yazma alanının (composer) çerçevesi yoktur.
- Yanıtlar düz metin olarak akar ve bir bölüm bittiğinde markdown'a dönüşür.
- Onay penceresi tam genişliktedir ve **Approve** / **Reject** butonları alt alta dizilir.
- 20 satırın altında ipucu satırı kaybolur ve yazma alanı iki satıra büyür.

Blok karakterleri kötü görünüyorsa ASCII bir sözcük dağarcığı ve çerçeveler için `TAU_TUI_ASCII=1 tau tui` ile başlat.

## 6. Telefon klavyesinde tuşlar

Termius, klavyenin üstünde **Esc**, **Tab**, **Ctrl**, ok tuşları ve fonksiyon tuşlarının bulunduğu ek bir tuş satırı gösterir. TUI bu yüzden her Ctrl kombinasyonunun yanına bir F tuşu bağlar:

| Tuş | Etkisi |
|---|---|
| F1 ya da `?` | yardım |
| F2 | oturum seçici (Enter sürdürür, `n` yeni, Esc kapatır) |
| F3 | `/tools` |
| F4 | olaylar görünümü (100 sütunun altında transkriptin yerini alır; Esc geri döner) |
| F6 | son turun araç kartlarını açar ya da kapatır |
| F7 / F8 | transkripti yukarı / aşağı kaydırır |
| F9 | en alta döner |
| Esc | çalışan turu iptal eder, menüyü kapatır, olaylar görünümünden çıkar |
| Ctrl-J (`^j`) | yazma alanında yeni satır |
| Ctrl-Q | TUI'den çıkar (tmux ve oturum kalır) |

`/` yazmak komut menüsünü açar; oklar seçer, Tab tamamlar, Enter çalıştırır.

## 7. Telefondan onaylar

Tier-2 bir çağrı (her zaman onay isteyen izin seviyesi) onay penceresini hangi ekran bağlıysa orada açar; böylece telefon, hub'ın klavyesinin göreceği pencerenin aynısını görür. `y` ya da `e` onaylar; `n`, `h` ya da Esc reddeder. Yarım saniyelik kurulma gecikmesi, o sırada yazmakta olduğun bir tuşun yanlışlıkla onay veremeyeceği anlamına gelir.

Başka hiçbir şey onay veremez. Burada güvenilen kanal tmux oturumudur: hub'da senin kullanıcınla çalışır ve ona yalnızca senin tailnet'inden gelen senin anahtarın bağlanabilir. Sessizlik asla onay değildir; telefon bir pencere açıkken kapanırsa bekleme iptal edildiğinde çağrı reddedilir.

## Sorun giderme

**`mosh-server not found`.** `./infra/remote/setup.sh` betiğini yeniden çalıştır. Etkileşimsiz SSH oturumları yalnızca `~/.zshenv` dosyasını okur; betik `PATH` girdisini de oraya koyar.

**Hub'a ulaşamıyorum.** Sırayla kontrol et: telefonda Tailscale açık mı, hub uykuda mı, `tau remote status` (ya da `doctor.sh`) ne diyor. Bir MacBook kapağı kapalıyken uyur; fişe tak ve kapağı açık bırak, harici bir ekranla kapalı kapak (clamshell) modunu kullan ya da tau uygulamasının "Keep awake with the lid closed" modunu seç (bir kerelik bir sudoers kuralı gerektirir, bkz. [tau uygulaması](taubar.md#set-up-the-lid-closed-mode)).

**TUI siyah beyaz.** mosh üzerinden Termius 24 bit renk kaçış dizilerini düşürür; 256 renk ise geçer. Bu yüzden `infra/remote/tmux/tau.tmux.conf`, `xterm-256color` istemcileri için truecolor'ı (`RGB`) zorlamaz; böylece tmux, TUI'nin renklerini telefon için 256 renklik paletle eşler. Kendi `~/.tmux.conf` dosyanda böyle bir ezme ayarladıysan onu kaldır, `Ctrl-b r` ile yeniden yükle ve Termius'ta yeniden bağlan (tmux bir istemcinin renklerine o bağlandığında karar verir). tmux dışında `TEXTUAL_COLOR_SYSTEM=256 uv run tau tui` tek bir çalıştırma için aynısını yapar.

**TUI, checkout'tan daha eski bir sürüm gösteriyor.** `uv tool install tau-core --with tau-tui`, kendi `tau`'sunu `~/.local/bin` içine koyar ve o, checkout'un içinde bile `PATH`'te önce gelir. Checkout içinde `uv run tau tui` çalıştır ya da aracı `uv tool upgrade tau-core` ile güncelle. Karşılama kartı çalışan sürümü gösterir.

**Claude Code SSH üzerinden yeniden giriş yapmamı istiyor.** macOS giriş anahtar zinciri (login keychain) bir SSH oturumunda kilitli görünebilir. Ya oturumda `security unlock-keychain ~/Library/Keychains/login.keychain-db` çalıştır ya da `claude setup-token` ile uzun ömürlü bir token oluştur ve onu, `~/.zshenv`'in yalnızca SSH oturumlarında yüklediği `~/.config/tau/remote.env` dosyasından export et. `GH_TOKEN` ve `CLOUDFLARE_API_TOKEN` da aynı dosyada durabilir.

**Telefon kayboldu.** O cihazın satırını hub'daki `~/.ssh/authorized_keys` dosyasından sil ve cihazı Tailscale yönetim konsolundan kaldır. İkisi de bir dakika sürer; bu sırayla yap.

**Geri alma.** macOS'ta: `sudo rm /etc/ssh/sshd_config.d/010-tau.conf`, `launchctl bootout gui/$(id -u)/com.tau.keepawake`, plist dosyasını ve `~/.local/bin/tau-attach` dosyasını sil, `~/.zshenv` ve `~/.tmux.conf` içinden `# >>> tau:remote >>>` bloklarını kaldır ve **System Settings → General → Sharing** altında Remote Login'i kapat.

## Bir iOS Kestirmesi'nden tek seferlik sorular

!!! info "Planlanan (yol haritası issue 073)"
    `tau ask "…"`, betikler ve iOS Kestirmeleri (Shortcuts) için tek seferlik bir komut olacak: Tailscale üzerinden bir SSH Kestirme eylemi `tau ask "what is on my desk?"` çalıştırır ve yanıtı gösterir. Aynı persona ve oturum deposuyla yanıt verir ve **tier-2 bir çağrıyı asla onaylamaz**: böyle bir çağrı, güvenilen bir kanala (TUI, tau uygulaması, web arayüzü ya da Telegram) yönlendirmeyle reddedilir. Komut henüz yok; tarif şöyle olacak:

    1. Kestirmeler → yeni Kestirme → **Dictate Text**.
    2. **Run Script Over SSH** ekle. Host: hub'ın MagicDNS adı (`my-mac.tailXXXXXX.ts.net`); kullanıcı: seninki; kimlik doğrulama: Kestirme'nin SSH anahtarı, Termius anahtarı gibi `authorized_keys` dosyasına eklenmiş. Betik: `tau ask "<Dictated Text>"`.
    3. Betiğin çıktısına **Speak Text** (ya da **Show Result**) ekle.
    4. Telefonda Tailscale açık olmalı; önkoşullar bu rehberdekilerin aynısı.

    `tau ask`, stdout bir terminal değilken ANSI içermeyen düz metin yazdırır, böylece **Speak Text** onu temiz okur; çıkış kodu 2, turun reddedildiği (tier-2 bir çağrı) ya da bir sınıra takıldığı anlamına gelir.
