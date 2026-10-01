<!-- tr twin of guides/raspberry-pi.md, translated 2026-10-01 -->

# Hub'ı Raspberry Pi'ye taşı

Hub (tau'nun çalıştığı, sana ait tek makine); ajanı, hub servislerini ve ileride mesh yönlendiricisini çalıştıran tek makinedir. Bir MacBook ilk hub olarak iyidir, kalıcı hub olarak ise zayıftır: uyur, evden çıkar, kapağı kapanır. Rafta duran, fişe takılı ve tailnet'e (Tailscale özel ağın) bağlı bir Raspberry Pi 5 doğal son durumdur. Bu sayfa "hub'ı taşımanın" ne anlama geldiğini, bugün elle neler yapabileceğini ve yol haritasının neleri otomatikleştireceğini anlatır.

!!! info "Planlanan (yol haritası issue 048): kendini kopyalama"
    Taşımanın amaçlanan yolu tau'ya şunu söylemek: *"hub'ı RPi5'e taşı"*. tau, Pi'yi SSH üzerinden hazırlar (uv, paketler, systemd birimi, ileride `zenohd`), yapılandırmasını ve verisini kopyalar, hub rolünü devreder ve Mac'i `mac.*` araçlarıyla bir **node**'a (hub'a yeteneklerini sunan diğer süreç) indirger. Her adım tier 2'dir (her zaman onay isteyen izin seviyesi) ve onay ister; devir sırasında kuyruktaki hiçbir mesaj kaybolmaz; Mac'e geri dönüş yolu vardır. Bunların hiçbiri henüz yapılmadı; issue 048 donanımı ve mesh katmanını (issue 032) bekliyor. Aşağıdaki elle yapılan adımlar, o otomasyonun yapacaklarının ta kendisi.

## Hub'ı taşımak ne demek

Hiçbir zaman birden fazla etkin hub olmaz. Taşımak şu demek:

1. **Yapılandırma** (`TAU_HOME`): `tau.toml`, `.env`, `persona/user.md`, `tools/`. SSH üzerinden kopyalanır; `.env` ve `user.md` gizli değerler ve yaşam verisidir, dolayısıyla asla üçüncü bir taraf üzerinden taşınmaz.
2. **Veri** (`TAU_DATA_DIR`): oturumlar, hub durumu, ileride ayarlar, hafıza ve bilgi tabanı. Kopyalanır ya da [şifreli bir yedekten](backups.md) geri yüklenir.
3. **Servis**: Pi'de systemd altında `tau hub`, Mac'te `tau hub uninstall`.
4. **Kapılar**: Tailscale, sshd sıkılaştırması ve Cloudflare Tunnel ya da Tailscale Serve; `tau.<your-domain>` yeni hub'ı göstersin diye Pi'ye taşınır.
5. **Rol**: Mac tau'yu çalıştırmaya devam eder ama bir node olarak (`TAU_ROLE=node`); yeteneklerini mesh üzerinden hub'a sunar (katman 5).

İki makinede de aynı kod çalışır; yalnızca `TAU_ROLE` farklıdır.

## Bugün, elle

### 1. Pi'yi hazırla

Raspberry Pi OS (64 bit) ya da Ubuntu Server. Sonra:

```sh
sudo apt update && sudo apt install -y git tmux mosh
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

sshd'yi [telefon rehberindeki](phone-tailscale-termius.md) gibi sıkılaştır (yalnızca anahtarlar, `AllowUsers` tailnet'le sınırlı) ve Termius anahtarını ekle. tau kurulduktan sonra (sonraki adım) `tau setup run remote` bunların hepsini denetler ve bunu yapan tek komutu, Pi'de `setup-linux.sh`'i çalıştıran `setup-all.sh`'i gösterir.

### 2. tau'yu kur

```sh
uv tool install tau-core --with tau-tui --with tau-net --with tau-sub
```

Ya da bir checkout'tan: `git clone https://github.com/fport/tau.git ~/tau && cd ~/tau && uv sync --all-packages --group dev`.

### 3. Yapılandırmayı ve veriyi taşı

Mac'ten, tailnet üzerinden:

```sh
rsync -a --mkpath "$HOME/.tau/" pi-hub.tailXXXXXX.ts.net:.tau/
rsync -a --mkpath "$HOME/.local/share/tau/" pi-hub.tailXXXXXX.ts.net:.local/share/tau/
```

Ya da [yedekleme rehberinin](backups.md) gösterdiği gibi şifreli paketten geri yükle. Sonra Pi'de:

```sh
tau doctor
```

İşaretlediği şeyleri düzelt: genellikle `.env` içindeki model anahtarı (`ANTHROPIC_API_KEY` ya da sağlayıcınınki). Bütçeler Pi'de hiçbir şey gerektirmez: `tau.toml` içinde yaşarlar, harcama defteri (ledger) `spend.sqlite3` de veri diziniyle birlikte geldi; böylece mevcut dönemin harcaması kaldığı yerden devam eder. `local` rolü Ollama'ya hâlâ Mac'te ulaşsın diye `TAU_OLLAMA_URL` değerini Mac'in tailnet adresine (`http://my-mac.tailXXXXXX.ts.net:11434`) yönlendir ve Mac'teki Ollama'nın yalnızca kendi tailnet adresini dinlemesini sağla ([Modeller ve bütçeler](models-and-budgets.md#set-up-ollama)).

### 4. Servisi başlat

```sh
cd ~/tau
mkdir -p ~/.config/systemd/user
uv run tau hub systemd-unit > ~/.config/systemd/user/tau-hub.service
systemctl --user daemon-reload
systemctl --user enable --now tau-hub
loginctl enable-linger "$USER"
tau hub status
```

Ayrıntılar, loglar ve yeniden başlatma kuralları [tau'yu servis olarak çalıştır](hub-service.md) sayfasında.

### 5. Eski hub'ı durdur

Mac'te:

```sh
tau hub stop
tau hub uninstall
```

Aynı anda iki hub, mesh var olduğunda onun reddedeceği bir yapılandırma hatasıdır; bugün seni hiçbir şey durdurmuyor, o yüzden düzenli ol.

### 6. Kapıları taşı

- **Tünel:** Pi'de `cloudflared tunnel create` çalıştır ya da `~/.cloudflared/<UUID>.json` ve `config.yml` dosyalarını tailnet üzerinden kopyala ve Mac'te `cloudflared`'ı durdur. DNS rotası makineyi değil tüneli izler.
- **Tailscale Serve:** Mac'te `tailscale serve reset`, Pi'de `tailscale serve --bg <port>`.
- **Termius:** host'u Pi'nin MagicDNS adına yönlendir, startup snippet olarak `tau-attach`'i koru (onu Pi'ye kur: `tmux new -A -s tau` çalıştıran iki satırlık bir betik).

## Pi'de neler farklı

| Konu | Pi'de |
|---|---|
| Uyku | yok; keep-awake agent'ı ve TauBar'ın uyku modları yalnızca Mac'i ilgilendirir |
| Servis yöneticisi | launchd değil, linger ile systemd kullanıcı birimi |
| Modeller | Pi'de ek bir şey çalışmaz: `brain` ve `fast` eskisi gibi, aynı bütçelerle doğrudan kendi sağlayıcılarını çağırır; `local` rolü Ollama'ya tailnet üzerinden Mac'te ulaşır (`TAU_OLLAMA_URL`) ve Mac uyurken ya da uzaktayken birkaç saniye içinde failover ile (başka bir role devrederek) `fast`'e geçer; bir Pi 5 kendi başına yalnızca küçük modelleri çalıştırır |
| Ses | MLX Whisper yalnızca Apple'da çalışır; Pi, CPU için bir Whisper derlemesi alır (`tau-voice`, planlanıyor) |
| Mesh | `zenohd` hub'da, yani Pi'de çalışır; Mac bir node olarak katılır |
| Yedekler | aynı `age` + R2 akışı; anahtar diskle değil parola yöneticisiyle taşınır |

## Geri alma

Pi bir süre çalışana kadar Mac'teki `~/.tau` ve `~/.local/share/tau` dizinlerini sakla. Geri dönmek için: Pi'de `tau hub stop`, veri dizinini Mac'e geri eşitle (Pi'de kaydedilen hiçbir şey kaybolmasın diye `rsync`'i ters yönde çalıştır), Mac'te `tau hub install`, kapıları yeniden taşı.
