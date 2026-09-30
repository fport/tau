<!-- tr twin of guides/private-deployment.md, translated 2026-09-30 -->

# Özel dağıtım (Cloudflare Tunnel + Access)

Bu rehber tau'nun tarayıcı arayüzü için ön kapıyı hazırlar: her cihazdan ulaşılabilen tek bir hostname; kimliğin kenarda (edge, yani Cloudflare'in ağında) doğrulanır ve hub'da (tau'nun çalıştığı, sana ait makine) dışarıdan gelen bağlantılara açık hiçbir port olmaz. İki seçenek var. **A** alan adı gerektirmez ve Tailscale Serve kullanır; **B** kendi alan adını Cloudflare Tunnel ve Cloudflare Access üzerinden kullanır. Önce tehdit modeli geliyor, çünkü aşağıdaki her adım ondan çıkıyor.

!!! info "Planlanan (yol haritası issue 074): web arayüzü"
    Bu kapının arkasına koyacağın sayfa, `tau-web`, henüz yok. İlk dilimi, mevcut TUI'nin `textual-serve` aracılığıyla tarayıcıda sunulması; telefondan ses tarayıcı mikrofonuna ihtiyaç duyduğunda (issue 080) düzgün bir web uygulaması gelecek. O zamana kadar bu rehber kapıyı bir yer tutucu sayfayla doğrulatır; böylece web arayüzünün geldiği gün tünelin, DNS'in ve Access politikasının çalıştığı bilinir. Bugün tau'da hiçbir şey dışarıdan gelen trafiği dinlemiyor: hub'ın kontrol API'si yalnızca `127.0.0.1` adresine bağlanır ve loopback olmayan her `Host` başlığına 403 döner.

## Sade anlatımla tehdit modeli

Neyi koruyorsun: tau'nun senin hakkında bildiği bilgileri, konuşmalarını ve hafızasını (yaşam verisi); kimlik bilgilerini; tau'nun çalıştığı makineyi; ve tau'nun dokunabildiği cihazları. Kim saldırır: herkese açık bir uç nokta bulan biri; ajanın önüne metin koyan (bir Telegram mesajı, çekilen bir web sayfası, bir araç sonucu) ve onu bir aracı kötüye kullanmaya ikna eden biri; ve üçüncü bir tarafın deposunda duran veriyi okuyan biri.

Ardından gelen kararların hepsi [ADR 0006](../adr/0006-private-first-topology.md)'dan:

1. **Tek bir herkese açık yüzey, kimlik doğrulaması kenarda.** Hub'ın web arayüzünü tam olarak tek bir hostname sunar. Hub'a *dışa doğru* bir tünel üzerinden ulaşır, böylece hub asla dışarıdan gelen bağlantılara port açmaz. Önündeki bir Access politikası, kimliği doğrulanmamış isteklerin tünele hiç ulaşmaması demektir.
2. **Hiçbir aracı onay veremez.** Tier-2 bir onay (her zaman onay isteyen izin seviyesi) yalnızca TUI'den, TauBar'dan, Access arkasındaki ve cihaz başına bir anahtarla korunan web arayüzünden ve doğrudan yoklanan Telegram'dan kabul edilir. Arada bir aktarıcı (relay) sunucu yoktur, dolayısıyla seninle hub arasında ele geçirilecek bir şey de yoktur.
3. **Yaşam verisi hub'da kalır.** Cloudflare yalnızca istemci tarafında şifrelenmiş yedekleri alır. Access e-postanı görür, verini değil.
4. **Dışarıdan gelen her metin güvenilmezdir.** Kabuk, dosya ve diğer yazma araçları tier 2'dir ya da sandbox içinde çalışır; web'den içerik çeken araçlar bir izin listesi kullanır.

[Tehdit modeli sayfasında](../architecture/threat-model.md), ele geçirilen her parçadan bir saldırganın ne elde ettiğini gösteren tablo var.

## Neler yerelde kalır

| Hub'da kalır | Cloudflare'e ulaşır |
|---|---|
| `persona/user.md`, `.env` | Access kimliği olarak e-postan |
| oturumlar, ayarlar, hafıza, bilgi tabanı | `tau.<your-domain>` için istek metadata'sı (Access logları) |
| onay kararı ve cihaz başına anahtar | [yedekleri](backups.md) kurarsan, özel bir R2 bucket'ında `age` ile şifrelenmiş bir yedek paketi |
| tünelin kimlik bilgisi dosyası (`~/.cloudflared/<UUID>.json`) | tünelin varlığı ve DNS kaydı |

## A seçeneği: Tailscale Serve (alan adı gerekmez)

Tailscale Serve yerel bir portu, Tailscale'in makinenin MagicDNS adı için verdiği bir sertifikayla, HTTPS üzerinden tailnet'ine (Tailscale özel ağın) açar. Herkese açık DNS yok, Cloudflare hesabı yok ve ona yalnızca tailnet'ine giriş yapmış cihazlar ulaşabilir. Alan adın yoksa varsayılan budur; [telefon rehberi](phone-tailscale-termius.md) hub'ı ve telefonunu zaten aynı tailnet'e koydu.

1. Tailscale yönetim konsolunda tailnet için **MagicDNS** ve **HTTPS certificates** seçeneklerini etkinleştir (Serve ikisini de gerektirir).
2. Hub'da, web arayüzünün yerini tutacak bir yer tutucu sayfa başlat:

    ```sh
    mkdir -p /tmp/tau-door && echo '<h1>tau door</h1>' > /tmp/tau-door/index.html
    cd /tmp/tau-door && python3 -m http.server 8000 --bind 127.0.0.1
    ```

3. O portu arka planda tailnet'e sun:

    ```sh
    tailscale serve --bg 8000
    tailscale serve status
    ```

    Durum satırında `https://my-mac.tailXXXXXX.ts.net` ve altında `proxy http://127.0.0.1:8000` yazar.

4. O URL'yi telefonda aç (Tailscale açıkken). Yer tutucu sayfayı görmelisin.
5. Web arayüzü var olana kadar yeniden kapat:

    ```sh
    tailscale serve reset
    ```

!!! note "Not"
    Serve yalnızca tailnet içindir. Portu önünde hiçbir kimlik kontrolü olmadan bütün internete açan `tailscale funnel` komutunu **kullanma**.

## B seçeneği: `tau.<your-domain>` adresinde Cloudflare Tunnel + Access

DNS'i Cloudflare'de olan bir alan adına (ücretsiz bir zone yeterli) ve Zero Trust'ı etkin bir Cloudflare hesabına ihtiyacın var (ücretsiz plan 50 kullanıcıya kadar kapsar). Bir alan adının nameserver'larını Cloudflare'e taşımak [yol haritası issue 022](https://github.com/fport/tau/blob/main/roadmap/L3-cloud/022-move-dns-to-cloudflare.md); önce onu yap ve e-posta kayıtlarını elle doğrula.

!!! info "Planlanan (yol haritası issue 076): `tau setup tunnel`"
    Bir yardımcı, bu bölümün güvenli kısımlarını (tünel oluşturma, yapılandırma dosyası, DNS rotası, servis kurulumu) betikleştirecek ve senin yerine yapamayacağı Access adımlarını yazdıracak. O zamana kadar adımlar elle ve geneldir; Cloudflare panosu etiketlerini zaman zaman değiştirir, o yüzden onları "bu işi yapan ekran" diye oku.

### B.1 `cloudflared` kur

=== "macOS"

    ```sh
    brew install cloudflared
    ```

=== "Linux (Raspberry Pi OS, Debian, Ubuntu)"

    ```sh
    sudo mkdir -p --mode=0755 /usr/share/keyrings
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
    echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" | sudo tee /etc/apt/sources.list.d/cloudflared.list
    sudo apt-get update && sudo apt-get install cloudflared
    ```

    Depo olmadan bir arm64 Pi için: `https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb` adresindeki `.deb`.

### B.2 Tüneli oluştur

```sh
cloudflared tunnel login                 # opens the browser; pick the zone of <your-domain>
cloudflared tunnel create tau            # prints the tunnel UUID and writes ~/.cloudflared/<UUID>.json
cloudflared tunnel list
```

JSON dosyası tünelin kimlik bilgisidir. `0600` izinleriyle hub'da kalır ve asla hiçbir yere kopyalanmaz.

### B.3 Yapılandırmayı yaz

`~/.cloudflared/config.yml` (ya da bir sistem servisi için `/etc/cloudflared/config.yml`):

```yaml
tunnel: <UUID>
credentials-file: /Users/<you>/.cloudflared/<UUID>.json

ingress:
  - hostname: tau.<your-domain>
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Son kural zorunludur: `tau.<your-domain>` olmayan her şey `cloudflared`'ın kendisinden 404 alır. Dosyayı doğrula:

```sh
cloudflared tunnel ingress validate
```

8000 portu A seçeneğindeki yer tutucudur; `tau-web` var olduğunda web arayüzünün portu olur.

### B.4 DNS'i yönlendir ve çalıştır

```sh
cloudflared tunnel route dns tau tau.<your-domain>     # a proxied CNAME to <UUID>.cfargotunnel.com
cloudflared tunnel run tau
```

Yer tutucu sunucu çalışırken `https://tau.<your-domain>` artık onu her yerden gösterir. **Burada dur ve tüneli çalışır hâlde bırakmadan önce B.5'i yap**: bu noktada hostname herkese açık ve kimlik doğrulamasız.

### B.5 Önüne Access koy

Cloudflare panosunda **Zero Trust**'ı aç.

1. **Giriş yöntemi.** **Integrations → Identity providers → Add new identity provider → One-time PIN.** Yapılandırılacak bir IdP (kimlik sağlayıcı) yok: Access girişte sana e-postayla bir kod gönderir. (Google, GitHub ya da başka bir IdP'yi sonra ekleyebilirsin.)
2. **Uygulama.** **Access controls → Applications → Create new application → Self-hosted and private**, sonra **Add public hostname**; alt alan adı olarak `tau`, alan adı olarak `<your-domain>` seç. İçin rahat edeceği bir oturum süresi ver; zaten kilidini açtığın bir telefonda 24 saat makul bir başlangıç.
3. **Politika.** **Allow** eylemli ve tek bir **Include** kuralı olan bir politika ekle: seçici **Emails**, değer senin e-posta adresin. Başka hiçbir şey. Bu uygulamanın Allow politikasında `Everyone` asla görünmemeli.
4. **İsteğe bağlı cihaz kuralı.** Ayrıca kayıtlı bir cihaz şartı koymak için **Warp** ya da **Gateway** seçicisiyle bir **Require** kuralı ekle (cihaz duruşu kontrolleri etkinleştirildiğinde görünür) ve telefona Cloudflare One istemcisini kur. Bu, "senin e-postan"ı "senin cihazındaki senin e-postan"a çevirir.
5. Kaydet. `https://tau.<your-domain>` adresini gizli bir pencerede aç: Access giriş sayfası gelir; e-postanı gir, e-postadaki PIN'i yapıştır ve ancak ondan sonra yer tutucu sayfa gelir.

!!! warning "Reddetme yolunu da doğrula"
    Politikada olmayan ikinci bir e-postayla giriş yap. Hesabın erişimi olmadığını söylemeli. Sayfaya ulaşıyorsa politika yanlıştır; arkasına gerçek bir şey koymadan önce düzelt.

### B.6 `cloudflared`'ı servis olarak çalıştır

=== "macOS"

    ```sh
    cloudflared service install           # a user launch agent; config at ~/.cloudflared/config.yml
    ```

    Bunun yerine `sudo cloudflared service install`, `/etc/cloudflared/config.yml` dosyasını okuyan ve açılışta başlayan bir sistem daemon'u kurar; `sudo launchctl start com.cloudflare.cloudflared` onu başlatır, loglar da `/Library/Logs/com.cloudflare.cloudflared.*.log` altındadır.

=== "Linux"

    ```sh
    sudo cloudflared --config ~/.cloudflared/config.yml service install
    sudo systemctl enable --now cloudflared
    sudo systemctl status cloudflared
    ```

### B.7 Yer tutucuyu kaldır

`python3 -m http.server` yer tutucusunu durdur. Hostname artık Access arkasında 502 döner; `tau-web` o portu dinleyene kadar olması gereken de tam olarak bu.

## Bu kurallara uy

- tau için **asla dışarıdan gelen bağlantılara port açma** ve onu asla `tailscale funnel` ile açma. Tünel de Serve de hub'dan dışa doğrudur.
- **Tek bir hostname.** Mesh, sshd ve hub'ın kontrol API'si yalnızca tailnet'te ya da yalnızca loopback'te kalır; asla tünelden geçmez.
- **Açmadan önce Access.** Açık kalacak ilk `tunnel run`'dan önce politikayı oluştur ya da B.4 ile B.5 arasında tüneli durdur.
- **Onaylar bir girişten fazlasını ister.** Web arayüzü geldiğinde tarayıcıdan gelen tier-2 bir onay, Access'in üstüne cihaz başına bir anahtar da gerektirecek (ADR 0006, karar 5). Çalınmış bir Access oturumu tek başına hiçbir şeyi hareket ettiremez.

## Bu rehberin etrafında planlananlar

| Parça | Issue | Ne ekler |
|---|---|---|
| `tau-web` | 074 | önce `textual-serve` aracılığıyla tarayıcıda TUI, sonra mikrofonlu bir web uygulaması |
| `tau setup tunnel` | 076 | B.2, B.3, B.4 ve B.6'yı betikleştirir ve Access adımlarını yazdırır |
| Cloudflare'de alan adı | 022 | nameserver taşıması, e-posta kayıtları doğrulanmış olarak |
| Hub'ın önünde Tunnel + Access | 023 | politika yalnızca pano tıklamaları olarak değil, depoda yapılandırma olarak |
