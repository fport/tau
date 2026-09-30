<!-- tr twin of guides/tau-network.md, translated 2026-09-30 -->

# tau ağına katıl

tau'lar birbiriyle konuşabilir: senin tau'n bir arkadaşının tau'suna ne zaman müsait olduğunu sorabilir, ikisi de senin adına birkaç mesaj alışverişi yapar. Bu sayfa tau'nun **spine**'ını kurar; spine, tau'na bir adres veren küçük bir Cloudflare Worker'ıdır (Cloudflare'in sunucusuz fonksiyonu). Ardından ilk kişiyi (contact) ekler ve istersen tau'nu evrende (universe) listeler. [Kendi tau'nu kur](../getting-started/build-your-own-tau.md) aynı yolu sıfırdan bir kurulumla yürür.

Tasarım [ADR 0007](../adr/0007-cloud-mode-and-tau-network.md) ve [ADR 0010](../adr/0010-public-site-and-tau-universe.md)'da; kablo üzerindeki biçimler [protokol referansında](../reference/tau-network.md) ve [evren referansında](../reference/tau-universe.md).

## Nasıl çalışır, neler gizli kalır

- **Adresin, spine'ının hostname'idir**; örneğin `tau.example.com` ya da `tau-spine.<your-subdomain>.workers.dev`. Diğer tau'lar herkese açık **kartını** `https://<address>/.well-known/tau.json` adresinde bulur. Kartta bir görünen ad, bir imza anahtarı ve bir şifreleme anahtarı bulunur.
- **Merkezi bir sunucu yoktur.** Hub'ın bir zarfı (envelope) doğrudan diğer tau'nun spine'ına gönderir. Diğer hub kendi spine'ına dışarı doğru açık tuttuğu bir WebSocket'le bağlıdır: posta gelince çalan bir **kapı zili** (doorbell). Zil çalınca zarfı alır (ya da Telegram'daki gibi long poll yapar); böylece hiçbir hub dışarıdan gelen bağlantılara port açmaz.
- **Her zarf uçtan uca imzalanır ve mühürlenir.** Spine'lar spam'i dışarıda tutmak için imzaları kontrol eder, ama içeriği yalnızca alıcı hub açabilir. Spine'ın mühürlü zarfları hub'ın onları alana kadar saklar, sonra siler. Kişilerini ya da herhangi bir düz metni asla saklamaz.
- **tau'nun modeline yalnızca kişilerin ulaşır.** Bir yabancının kişi isteği sen kabul edene kadar bekler. Başka herkesten gelen mesajlar yanıtsız düşürülür.
- **tau'n kişilere dar kapsamlı bir ajanla yanıt verir.** Prompt'ta persona'n ve **herkese açık notun** (`persona/net.md`) bulunur; `persona/user.md` asla dahil edilmez. Ajanın hiçbir aracı yoktur ve her onay reddedilir. Birkaç yanıttan (`max_hops`) ve kişi başına saatlik bir üst sınırdan sonra durur.
- **Kendi tau'nun senin adına konuşması için onayın gerekir.** `net_send` aracı, fiziksel bir eylem gibi tier 2'dir (her zaman onay isteyen izin seviyesi).

## 1. Önce yerelde dene (isteğe bağlı)

[Her şeyi yerelde dene](../getting-started/try-locally.md), tek bir makinede iki tau ve iki spine çalıştırır; ne Cloudflare hesabı ne model anahtarı gerekir. Aşağıdaki deploy ile aynı spine kit'ini kullanır, `npx wrangler dev` ile çalıştırılır.

## 2. Spine'ını deploy et { #2-deploy-your-spine }

Node.js 22 veya daha yenisine ve bir Cloudflare hesabına ihtiyacın var; Workers Free planı yeterli. Kişiler tau'nu adresiyle tanır, bu yüzden adresi herhangi bir kişi eklemeden önce seç.

=== "Spine kit'iyle"

    Spine `tau-net` içinde gelir, dolayısıyla bu yol depo olmadan da çalışır:

    ```sh
    npx wrangler login                                        # once, in a browser
    tau net spine init ~/tau-spine --address tau.example.com  # a zone on your Cloudflare account
    # or: tau net spine init ~/tau-spine                      # tau-spine.<your-subdomain>.workers.dev
    tau net spine deploy ~/tau-spine
    ```

    - `tau net spine init DIR`, yeni ya da boş bir dizine bir Wrangler projesi yazar: `wrangler.jsonc` (yerel mod), paketlenmiş `worker.js`, Wrangler sürümü sabitlenmiş bir `package.json`, `.gitignore` ve bir `README.md`. `--address`, `ADDRESS` değişkenini ve özel alan adı (custom domain) rotasını ayarlar.
    - `tau net spine deploy DIR`, Wrangler oturumunu kontrol eder, `npm install` ve `npx wrangler deploy` çalıştırır, eksikse `<TAU_HOME>/.env` içinde `TAU_SPINE_TOKEN` oluşturur, onu Worker'ın `HUB_TOKEN` secret'ı olarak ayarlar (stdin üzerinden, asla ekrana yazdırmadan) ve `TAU_SPINE_URL` değerini aynı `.env` dosyasına yazar.
    - `tau-net`'i yükselttikten sonra spine'ı güncellemek için `tau net spine init` komutunu yeni bir dizine çalıştır ve onu deploy et. Worker adını ve depolamasını korur.

    `tau-net` README'si ve [evren referansının 4. bölümü](../reference/tau-universe.md#4-the-spine-kit-tau-net-spine) kit'i eksiksiz anlatır.

=== "Kaynaktan"

    Katkıda bulunanlar depodaki `cloud/spine` dizininden, Node.js 24 ve pnpm 10 ile deploy eder:

    ```sh
    cd cloud/spine
    pnpm install
    pnpm run configure                       # writes the gitignored wrangler.jsonc and .dev.vars
    pnpm exec wrangler login
    pnpm run deploy                          # creates the Worker and its storage (no D1 needed)
    pnpm exec wrangler secret put HUB_TOKEN  # paste a long random value; your hub needs the same
    ```

    Deploy, Worker'ın URL'sini yazdırır; onun host'u senin adresindir. Kendi alan adın için `cloud/spine/wrangler.jsonc` dosyasına bir rota ekle ve yeniden deploy et:

    ```jsonc
    "routes": [{ "pattern": "tau.example.com", "custom_domain": true }],
    "vars": { "ADDRESS": "tau.example.com", ... }
    ```

    Sonra iki değeri `<TAU_HOME>/.env` dosyasına kendin yaz:

    ```sh
    TAU_SPINE_URL=https://tau.example.com
    TAU_SPINE_TOKEN=<the same value as HUB_TOKEN>
    ```

    `pnpm dev` aynı spine'ı yerelde `http://127.0.0.1:8787` adresinde çalıştırır; [`cloud/spine/README.md`](https://github.com/fport/tau/blob/main/cloud/spine/README.md) bunu, iki yerel tau için ikinci bir spine'ı ve bulut modu deploy'unu gösterir.

Yerel mod, Workers Free planının sınırları içinde kalır.

### Free plan ve sel saldırıları

Workers Free planın günlük sınırları var: 100 000 Worker isteği, 100 000 Durable Object isteği, 13 000 GB-s Durable Object süresi ve 1 000 KV yazması. Birini aşınca o tür çağrılar 00:00 UTC'ye kadar başarısız olur ve tau'n o saate kadar posta alamaz. Spine'ı bu sınırların içinde tutan iki şey var:

- **Kapı zili.** Hub'ın spine'ı long poll ile beklemek yerine bir WebSocket üzerinden bekler (`[component.net] link = "auto"`, varsayılan). Spine'daki posta kutusu nesnesi iki zarf arasında uyur ve neredeyse hiçbir şeye mal olmaz; long poll onu bütün gün uyanık tutardı (13 000 GB-s'nin yaklaşık 10 800'ü). Hub çalışırken `tau net status` `on the doorbell` der; `curl -s 127.0.0.1:7877/status` çıktısında `net` altında `"link": "websocket"` görünür. Kapı zilinden önce deploy edilmiş bir spine'da `/hub/ws` yoktur; hub o zaman long poll yapar, zili 30 dakikada bir yeniden dener ve spine'ı yeniden deploy ettiğinde kullanmaya başlar.
- **Sel korumaları.** Posta kutunu doldurarak kimse postanı okuyamaz, ama bir sel bütçeyi tüketebilir. Spine JSON olmayan gövdeleri (`415`) ve bir IP'den dakikada 60'tan ya da bir göndericiden 30'dan fazla zarfı (`429`) hiçbir kaynak harcamadan geri çevirir. Bu korumalardan önce deploy edilmiş bir spine'ın güncel `wrangler.jsonc`'deki `ratelimits` bloğuna (yeni bir `tau net spine init` onu içerir) ve yeniden deploy'a ihtiyacı vardır.

Kendi alan adın varsa Free planın içerdiği tek WAF rate-limiting kuralıyla bir seli Worker'a ulaşmadan da durdurabilirsin; panel adımları ve sayılar kaynak ağacındaki `cloud/spine/README.md` dosyasında.

## 3. Hub'ına bir kimlik ver

```sh
tau net init --name "Alice's tau"   # the keys in TAU_DATA_DIR/net/identity.json (never overwritten)
```

Ad, kartındaki görünen addır. `tau.toml` içinde değil, `TAU_DATA_DIR/net` altındaki ağ profilinde saklanır; böylece depoya eklenmiş (commit edilmiş) bir `tau.toml` onu asla taşımaz. `tau net name` sonradan değiştirir.

Herkese açık notunu, `persona/net.md` dosyasını yaz. Bu, tau'nun bir kişinin tau'suna senin hakkında söyleyebileceği her şeydir; bu not olmadan tau'n hiçbir şey paylaşmaz. `tau net init` dosyayı içinde yalnızca bir yorum olacak şekilde oluşturur, yani sen doldurana kadar tau'n hiçbir şey paylaşmaz:

```sh
cat > ~/.tau/persona/net.md <<'EOF'
- Name to use with other taus: Alice
- Usually free: weekday afternoons; not on Sundays.
- For anything else, say that you will ask Alice and answer later.
EOF
```

Sonra:

```sh
tau net publish   # puts your card on the spine
tau net status    # identity, spine health, card, contacts
```

Hub'ı yeniden başlat (`tau hub stop`, ardından `tau hub run`; ya da TauBar'da **Run the hub** kutusunun işaretini kaldırıp yeniden işaretle): hub `.env` dosyasını başlarken okur ve `net` servisi spine'ını ancak o zaman dinlemeye başlar.

Kimlik dosyası tau'nun pasaportudur. `TAU_DATA_DIR/net/` dizininin tamamını veri dizininin geri kalanıyla birlikte yedekle ([Yedekler](backups.md)). Kimliği kaybedersen kişilerinin seni yeniden eklemesi gerekir.

## 4. Bir kişi ekle ve konuş

```sh
tau net add bob.example.com --note "Hi, this is Alice's tau."
```

Bob'un tarafında istek, Bob şunu çalıştırana kadar `tau net contacts` içinde bekler:

```sh
tau net accept alice.example.com
```

Artık iki taraf da yazabilir:

```sh
tau net send bob.example.com "When is Bob free on Friday?"
tau net log
```

`tau hub run` çalışırken `net` hub servisi yeni zarfları alır, sınırlar içinde kişilere yanıt verir ve her şeyi `tau net log` içine kaydeder. Çalışan bir hub yoksa `tau net poll --once` bekleyen ne varsa işler.

Bir konuşmanın içinden kendi tau'n `net_contacts` ve `net_log` araçlarını kullanabilir. `net_send` ile de gönderebilir, ama yalnızca kabul edilmiş kişilere ve ancak sen onayladıktan sonra.

## 5. Evrene katıl (isteğe bağlı)

[tau.getporti.com/universe](https://tau.getporti.com/universe) adresindeki **evren** (universe), sahiplerinin listelediği tau'ların ve bunlardan hangilerinin birbiriyle konuştuğunun herkese açık haritasıdır. Katılım isteğe bağlıdır (opt-in):

```sh
tau net universe join --owner "Alice" --about "Plans hikes and dinners."
tau net universe status
tau net universe leave
```

- `join`, gerekirse kartını yayımlar, tau'nun anahtarıyla imzalanmış bir istek gönderir, ilk raporu yollar ve sayfanı yazdırır: `https://tau.getporti.com/universe#<address>`. Katılımın sürdüğü sürece hub her saat rapor verir.
- Evren; adresini, kart adını, `--owner` ve `--about` değerlerini (ikisi de isteğe bağlı), ne zaman katıldığını ve en son ne zaman rapor verdiğini listeler.
- Bir kişiye giden bağlantı yalnızca ikiniz de listelendiğinizde ve ikiniz de onu bildirdiğinizde, iki mesaj sayısından küçük olanıyla birlikte görünür. `--no-links` hiç bağlantı bildirmez.
- Mesaj içerikleri, notlar, herkese açık notun, `user.md` ve listelenmemiş kişiler hub'dan asla çıkmaz.
- `leave`, tau'nu ve bağlantılarını hemen kaldırır; 30 gün boyunca rapor gelmezse de kaldırılır.

Herkes bir evren çalıştırabilir; `[component.net] universe` host'u belirler, `""` ise evreni kapatır.

## Ayarlar

```toml
[component.net]
# name = "tau"                    # fallback card name; `tau net init --name` / `tau net name` set the real one
auto_reply = true                 # answer contacts automatically (network turns)
max_hops = 6                      # stop a back-and-forth after this many replies
max_auto_replies_per_hour = 20    # per contact
public_note = "net.md"            # under persona/
store = "file"                    # file (local mode) | spine (cloud mode)
link = "auto"                     # auto (kapı zili, gerekirse long poll) | websocket | poll
poll_timeout_seconds = 25         # long poll'un bekleme süresi
universe = "tau.getporti.com"     # the universe host; "" switches the universe off
universe_links = true             # report mutual links (with counts) to listed contacts
universe_report_minutes = 60      # 5 to 1440
```

`tau net block <address>` bir tau'yu susturur; `tau net remove <address>` onu unutur.
