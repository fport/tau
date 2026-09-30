<!-- tr twin of guides/backups.md, translated 2026-09-30 -->

# Yedekler (şifreli, R2)

tau'nun bildiği her şey hub'da (tau'nun çalıştığı, sana ait makine) yaşar. Tasarımın bütün amacı bu, ve bu da yedeklemeyi senin işin yapar. Bu rehber neyin yedekleneceğini, Cloudflare'in yalnızca şifreli metin tutması için yedeğin `age` ile nasıl şifreleneceğini, nasıl yükleneceğini ve nasıl geri yükleneceğini gösterir. Elle yapılan akış bugün çalışıyor; zamanlanmış iş planlanıyor.

!!! info "Planlanan (yol haritası issue 018): yedekleme işi"
    Bir `tau backup` komutu ve zamanlanmış bir hub servisi, bu sayfadaki akışı otomatik çalıştıracak, bir rotasyon tutacak ve geri yüklemeyi belgeleyecek. O zamana kadar yedek, aşağıdaki komutlardır. İşin çalıştıracağı komutlar da bunların aynısı.

## Veri dizininde neler var

`TAU_DATA_DIR` (varsayılan `~/.local/share/tau`), tau'nun yazdığı her şeyi tutar:

```text
~/.local/share/tau/
├── sessions/<id>/            one directory per session, kept forever
│   ├── session.json          the Strands session record
│   ├── meta.json             channel, profile, title, role, compaction links
│   ├── events.jsonl          agent events: tool calls, approvals, limits, errors
│   └── agents/tau/           agent state and one file per message
├── hub/                      hub state: lock, heartbeat, crash reports, launchd logs
├── net/                      tau network: identity.json (your tau's keys), profile, contacts, log
└── logs/tau.log              the log file
```

Sonraki katmanlar ayarları, hafızayı ve bilgi tabanını aynı kökün altına ekler; böylece `TAU_DATA_DIR` yedeği eksiksiz kalır.

İki şey onun **dışında** yaşar ve onları da saklamaya değer:

| Yol | Neden |
|---|---|
| `<TAU_HOME>/persona/user.md` | senin hakkındaki bilgiler; hiçbir yerde takip edilmez |
| `<TAU_HOME>/tau.toml` | rol ve bileşen seçimlerin; zararsız ve işe yarar |

`<TAU_HOME>/.env` kimlik bilgilerini tutar. Onları yedek paketinde değil, parola yöneticinde sakla; böylece geri yükleme, sahip olduğun her anahtarı pakete emanet etmek yerine tek bir yapıştırma gerektirir. Yine de eklersen paket zaten şifrelidir, ama kaybolan bir `age` anahtarının hasar alanı büyür.

## Anahtar

Yedekler, küçük ve modern bir dosya şifreleme aracı olan [`age`](https://github.com/FiloSottile/age) ile bir anahtar çiftine şifrelenir. Özel anahtar hub'da ve parola yöneticinde kalır. Asla Cloudflare'e gitmez.

=== "macOS"

    ```sh
    brew install age
    ```

=== "Linux"

    ```sh
    sudo apt install age
    ```

```sh
mkdir -p ~/.config/tau && chmod 700 ~/.config/tau
age-keygen -o ~/.config/tau/backup.key
chmod 600 ~/.config/tau/backup.key
```

`age-keygen` açık anahtarı yazdırır; `Public key: age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p` gibi bir satır. Onu kolay ulaşabileceğin bir yere kopyala; şifrelemeyi onunla yaparsın. Sonra **`backup.key` dosyasının tamamını parola yöneticine koy**. O olmadan her yedek anlamsız bir gürültüdür.

!!! warning "Uyarı"
    `backup.key` dosyasını kaybetmek bütün yedekleri kaybetmek demektir. Anahtar parola yöneticinde olduğu sürece hub'ı kaybetmek öyle değildir. Aşağıdaki geri yüklemeyi şimdi, ortada kaybedilecek bir şey yokken bir kez dene.

## Yedek al

Tek bir paket, `age` içinden akıtılarak; böylece düz metin arşiv diske hiç dokunmaz:

```sh
export TAU_DATA_DIR="${TAU_DATA_DIR:-$HOME/.local/share/tau}"
export TAU_HOME="${TAU_HOME:-$HOME/.tau}"
export TAU_BACKUP_PUBKEY='age1...'           # from age-keygen

stamp=$(date -u +%Y%m%dT%H%M%SZ)
tar -C / -czf - \
  "${TAU_DATA_DIR#/}/sessions" "${TAU_DATA_DIR#/}/hub" "${TAU_DATA_DIR#/}/net" \
  "${TAU_HOME#/}/persona/user.md" "${TAU_HOME#/}/tau.toml" \
  | age -r "$TAU_BACKUP_PUBKEY" -o "/tmp/tau-$stamp.tar.gz.age"
ls -l "/tmp/tau-$stamp.tar.gz.age"
```

`hub/hub.lock` de dahil edilir ve zararsızdır. `logs/` bilerek dışarıda bırakıldı; istersen ekle. [tau ağı](tau-network.md) kurulu değilse `net` dizini yoktur; `tar` bu durumda `Cannot stat: No such file or directory` yazdırır ve geri kalanı arşivler, yani çıktı temiz kalsın diye onu listeden çıkar. Ağ kuruluysa `net/identity.json` yeniden oluşturamayacağın tek dosyadır: tau'nun anahtarlarını tutar ve kişilerin yeni anahtarları reddeder.

## Özel bir R2 bucket'ına yükle

R2, Cloudflare'in nesne depolamasıdır. Özel bir bucket'ın herkese açık URL'si yoktur; onu yalnızca senin API token'ın okuyabilir, o da yalnızca şifreli metni okur.

1. Hesabında **R2 read and write** yetkisine sahip bir Cloudflare API token'ı oluştur (`Account → R2 → Manage R2 API tokens` ya da *Workers R2 Storage: Edit* kapsamlı bir kullanıcı token'ı). Onu `~/.config/tau/remote.env` içinde `CLOUDFLARE_API_TOKEN=...` olarak sakla ya da bir kez `npx wrangler login` çalıştır.
2. Bucket'ı oluştur ve yükle:

    ```sh
    npx wrangler r2 bucket create tau-backups
    npx wrangler r2 object put "tau-backups/$stamp.tar.gz.age" \
      --file "/tmp/tau-$stamp.tar.gz.age" --remote
    rm "/tmp/tau-$stamp.tar.gz.age"
    ```

    `--remote`, wrangler'ın yerel bir emülasyon yerine gerçek bucket'la konuşmasını sağlar.

3. Orada ne olduğunu kontrol et:

    ```sh
    npx wrangler r2 object get "tau-backups/$stamp.tar.gz.age" --file /tmp/check.age --remote
    cmp /tmp/check.age "/tmp/tau-$stamp.tar.gz.age" 2>/dev/null && echo same
    ```

!!! tip "Büyük paketler: rclone"
    `wrangler r2 object put` birkaç yüz megabayta kadar olan paketler için yeterli. Daha büyükleri ya da artımlı eşitleme için [rclone](https://rclone.org/)'u bir R2 erişim anahtarı çiftiyle R2'nin S3 uyumlu uç noktasına göre yapılandır, ardından `rclone copy /tmp/tau-$stamp.tar.gz.age r2:tau-backups/`. Şifreleme adımı aynı; yalnızca yükleme değişir.

## Geri yükle

Hub'da ya da hub olacak yeni bir makinede:

```sh
npx wrangler r2 object get "tau-backups/<stamp>.tar.gz.age" --file /tmp/restore.age --remote
age -d -i ~/.config/tau/backup.key /tmp/restore.age | tar -C / -xzf -
rm /tmp/restore.age
tau doctor
```

`tar -C /` arşivlenen yolların aynısını geri yükler; bu yüzden yeni makinede `TAU_DATA_DIR` ve `TAU_HOME` aynı olmalı. Farklılarsa geçici bir dizine aç ve parçaları taşı:

```sh
mkdir -p /tmp/restore && age -d -i ~/.config/tau/backup.key /tmp/restore.age | tar -C /tmp/restore -xzf -
rsync -a /tmp/restore/<old data dir>/ "$TAU_DATA_DIR"/
cp /tmp/restore/<old home>/persona/user.md "$TAU_HOME"/persona/user.md
```

Sonra `tau chat --resume`: son oturum geçmişiyle birlikte geri gelir.

## Zamanla

Issue 018 gelene kadar yedekleme betiğini her gece çalıştıran bir cron satırı ya da bir launchd agent'ı yeterli:

```sh
crontab -e
# 03:30 every night; the script is the "Make a backup" block plus the upload
30 3 * * * /path/to/tau-backup.sh >> "$HOME/.local/share/tau/logs/backup.log" 2>&1
```

Betik bucket adını ve token yolunu içeriyorsa onu deponun dışında tut ya da bu değerleri `~/.config/tau/remote.env` dosyasından okut.

## Kurallar

- **Asla düz metin yükleme.** `age`'den önceki bir adım başarısız olursa hiçbir şey yüklenmez.
- **Anahtar asla Cloudflare'de olmaz**; ne bir secret'ta, ne bir Worker'da, ne bir bucket'ta.
- İlk yedekten sonra ve betikteki her değişiklikten sonra **bir geri yüklemeyi dene**.
- **R2 hiçbir kişisel veriyi açık hâlde tutmaz.** D1, Vectorize ve AI Search tau'nun verisi için hiç kullanılmaz ([ADR 0006](../adr/0006-private-first-topology.md)).
