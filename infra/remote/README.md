# infra/remote — Uzaktan erişim

Telefon (Termius) → Tailscale → MacBook'ta OpenSSH → tmux → Claude Code.

| Parça | Görevi |
|---|---|
| **Tailscale** | Telefon ve Mac'i, port açmadan aynı özel ağa (tailnet) koyar |
| **OpenSSH** (macOS Remote Login) | Sadece anahtarla, sadece senin kullanıcınla, sadece tailnet'ten giriş |
| **mosh** | Ağ değişse ya da telefon kilitlense bile bağlantı kopmaz |
| **tmux** | Bağlantı kopsa bile oturum (ve içindeki Claude Code) çalışmaya devam eder |
| **com.tau.keepawake** | Şarjdayken Mac uyumaz (`caffeinate -s`). TauBar gelince bu görevi o devralacak |

## Kurulum

1. **tmux, mosh ve kullanıcı ayarları** (sudo gerekmez):
   ```sh
   ./infra/remote/setup.sh
   ```
2. **Tailscale, sshd ve Remote Login.** sudo şifre soracağı için bu adımı kendi terminalinde çalıştır:
   ```sh
   ./infra/remote/setup-sudo.sh
   ```
3. **Tailscale'e giriş:** Mac'te Tailscale.app'i aç, Gizlilik ve Güvenlik'te sistem uzantısına izin ver, sonra giriş yap. iPhone'a da Tailscale'i kur ve **aynı hesapla** giriş yap.
4. **Termius anahtarı:** Keychain → **+** → Generate Key → Type **ED25519** → isim olarak `iphone` ver → anahtarı açıp public key'i kopyala. Mac'te Universal Clipboard ile yapıştır:
   ```sh
   ./infra/remote/add-key.sh
   ```
5. **Termius host ayarları:**
   - Address: `doctor.sh`'ın yazdığı MagicDNS adı
   - Username: Mac kullanıcı adın
   - Key: `iphone`
   - **Mosh: açık**
   - **Startup Snippet:** `tau-attach`
6. **Kontrol:**
   ```sh
   ./infra/remote/doctor.sh
   ```

## Günlük kullanım

- **Termius'tan bağlandığında** doğrudan `tau` tmux oturumuna düşersin. `claude` yazarak başlarsın. Bağlantı koparsa yeniden bağlan, kaldığın yerden devam edersin.
- **Mac başındayken aynı oturuma** bağlanmak için `tau-attach` yeter. Telefondaki ile aynı ekranı görürsün.
- **Dev server'ı telefonda görmek** için sunucuyu `--host 0.0.0.0` ile başlat, Safari'de `http://<magicdns-adı>:3000` adresini aç. Bu trafik sadece tailnet içinde kalır.
- **tmux kısayolları:** Prefix `Ctrl-b`. Bölme için `|` ve `-`, ayarları yenilemek için `r`. Kaydırma parmakla yapılır.

## Sorun giderme

**`mosh-server not found`:** `./setup.sh` komutunu tekrar çalıştır. Etkileşimsiz SSH oturumları sadece `~/.zshenv` dosyasını okur.

**Claude Code SSH'ta tekrar giriş istiyor:** SSH oturumunda macOS login keychain'i kilitli görünebilir. İki çözüm var:

- Her oturumda kilidi aç (şifre sorar):
  ```sh
  security unlock-keychain ~/Library/Keychains/login.keychain-db
  ```
- Ya da kalıcı bir token oluştur:
  ```sh
  claude setup-token
  mkdir -p ~/.config/tau && chmod 700 ~/.config/tau
  printf 'export CLAUDE_CODE_OAUTH_TOKEN=%s\n' '<token>' > ~/.config/tau/remote.env
  chmod 600 ~/.config/tau/remote.env
  ```

`~/.zshenv` bu dosyayı **sadece SSH oturumlarında** yükler. `gh` için `GH_TOKEN`'ı, `wrangler` için de `CLOUDFLARE_API_TOKEN`'ı aynı dosyaya ekleyebilirsin.

**Mac'e ulaşamıyorum:** Sırayla kontrol et: iPhone'da Tailscale açık mı, Mac uyuyor mu, `doctor.sh` ne diyor. Kapak kapalıyken Mac uyur. Şarja takıp kapağı açık bırakabilir ya da harici ekranla clamshell modunda kullanabilirsin. "Kapak kapalıyken bile uyanık kal" modu TauBar ile gelecek.

## Güvenlik modeli

- **Sadece anahtarla giriş:** Şifre ve keyboard-interactive (PAM) girişleri kapalı.
- **Sadece senin kullanıcın, sadece tailnet ve localhost'tan:** `100.64.0.0/10`, `fd7a:115c:a1e0::/48`, `127.0.0.1` ve `::1`. macOS'ta sshd tüm arayüzlerde dinler, ama aynı kafedeki biri port 22'ye ulaşsa bile `AllowUsers` onu içeri almaz.
- **Kısıtlı yönlendirme:** Agent forwarding kapalı. TCP yönlendirmede sadece yerel (`-L`) açık.
- **Telefon kaybolursa:** O cihazın satırını `~/.ssh/authorized_keys`'ten sil, cihazı Tailscale admin panelinden kaldır.

## Ayarlar

Varsayılanlar `config.env` dosyasında. Makineye özel değişiklikleri `config.local.env` dosyasına yaz (gitignored). Örneğin uyku ajanını kapatmak için `TAU_KEEPAWAKE=0` yazıp `./setup.sh`'ı tekrar çalıştırırsın.

## Geri alma

```sh
sudo rm /etc/ssh/sshd_config.d/010-tau.conf
launchctl bootout gui/$(id -u)/com.tau.keepawake
rm ~/Library/LaunchAgents/com.tau.keepawake.plist ~/.local/bin/tau-attach
```

Bunlara ek olarak:
- `~/.zshenv` ve `~/.tmux.conf` içindeki `# >>> tau:remote >>>` bloklarını sil.
- Remote Login'i kapat: Sistem Ayarları → Genel → Paylaşma.
