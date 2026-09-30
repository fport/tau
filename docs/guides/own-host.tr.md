<!-- tr twin of guides/own-host.md, translated 2026-09-30 -->

# Kendi kurulumunu yap

**tau-host**, barındırılan tau'ların arkasındaki Cloudflare Worker'ı: GitHub ile giriş, tarayıcıda sahibin uygulaması ve web sayfası olan her açık sub-tau için bir sohbet sayfası. Onu kendi Cloudflare hesabına kurarsan barındırılan uygulama yalnızca senin olur: [tau.getporti.com](https://tau.getporti.com) üzerindekiyle aynı tarayıcı sohbeti, ama senden başka kimsenin okuyamadığı hâliyle. Bu, [Başlamanın üç yolu](../getting-started/three-ways.md) sayfasındaki üçüncü yol; karar [ADR 0013](../adr/0013-hosted-taus-handles-and-public-pages.md)'te.

Bu sayfa örnek değerler kullanıyor: host olarak `tau.example.com`, GitHub kullanıcı adı olarak `alice`. Onların yerine kendi değerlerini koy.

## Ne elde edersin

| Adres | Ne olduğu |
|---|---|
| `https://tau.example.com/` | Giriş sayfası: barındırılan tau nedir, kim neyi okuyabilir, **GitHub ile giriş yap** |
| `https://tau.example.com/app` | tau'n: sohbet, oturumlar, sub-tau'lar, onaylar, ayarlar, dışa aktarma ve hesap silme |
| `https://tau.example.com/@alice/coach` | Web sayfasıyla açtığın her sub-tau için herkese açık bir sohbet sayfası |
| `tau.example.com/@alice` | tau'nun tau ağındaki adresi (bkz. [Evren](#8-evren-istege-bagl)) |

tau-host'un ne hub'ı ne de container'ı var. Her tau, kimse onunla konuşmadığında uyuyan, SQLite tabanlı tek bir Durable Object'tir; beyin de sağlayıcının HTTP API'sini doğrudan çağıran küçük bir ajan döngüsüdür. Bu yüzden cihaz araçları, node'lar, ses, hafıza ve rutinler burada yok: onlar [yerel hub](../getting-started/install.md)'da kalır.

## 1. Gerekenler

| Gereken | Neden |
|---|---|
| Bir **Cloudflare hesabı** | tau-host orada, birkaç tau için Workers Free planında çalışır ([Maliyet](#maliyet-ve-snrlar)). |
| **[bun](https://bun.sh)** 1.3 ve **Node.js 24** | bun paketleri kurar ve betikleri çalıştırır; Cloudflare'in komut satırı aracı Wrangler ise Node.js üzerinde çalışır. |
| Deponun bir kopyası (clone) | tau-host `cloud/host` dizininden yayına alınır. |
| Bir **GitHub hesabı** | Giriş, senin oluşturacağın bir GitHub OAuth App üzerinden olur. |
| Cloudflare'de bir alan adı (isteğe bağlı) | `tau.example.com` gibi bir host için. Yoksa host `tau-host.<your-subdomain>.workers.dev` olur. |
| Bir model anahtarı | Anthropic, OpenAI ya da Google Gemini'den. Onu bir dosyaya değil, uygulamaya yapıştırırsın. |

=== "macOS"

    ```sh
    brew install oven-sh/bun/bun
    # Node.js 24 from https://nodejs.org, nvm or Homebrew
    ```

=== "Linux"

    ```sh
    curl -fsSL https://bun.sh/install | bash
    # Node.js 24 from https://nodejs.org, nvm or your distribution
    ```

```sh
git clone https://github.com/fport/tau.git
cd tau/cloud/host
bun install
```

## 2. Host adını seç

Bu ad GitHub OAuth App'e yazılacak, o yüzden önce onu seç.

- **Cloudflare'de bir alan adın varsa:** o bölgede (zone) bir ad, örneğin `tau.example.com`. Yayına alma adımı onu Worker'a özel alan adı (custom domain) olarak bağlar; DNS kaydını ve sertifikayı Cloudflare oluşturur. Bu adın henüz bir DNS kaydı olmamalı.
- **Yoksa:** `tau-host.<your-subdomain>.workers.dev`. Kendi `workers.dev` alt alan adını Cloudflare panelinde **Workers & Pages** altında görürsün.

## 3. Bir GitHub OAuth App oluştur

GitHub'da **Settings → Developer settings → OAuth Apps → New OAuth App** yolunu aç ve şunları doldur:

| Alan | Değer |
|---|---|
| Application name | herhangi bir ad, örneğin `tau (tau.example.com)` |
| Homepage URL | `https://tau.example.com` |
| Authorization callback URL | `https://tau.example.com/auth/callback` |

Kaydet. **Client ID**'yi bir sonraki adım için bir kenara al, sonra **Generate a new client secret**'ı seç ve sayfayı açık bırak: GitHub bu secret'ı yalnızca bir kez gösterir, onu [6. adımda](#6-secretlar-koy) yapıştıracaksın. Bir dosyaya kaydetme, bir komut satırına da yazma.

`workers.dev` host'unda iki adres de o adı kullanır: `https://tau-host.<your-subdomain>.workers.dev` ve `https://tau-host.<your-subdomain>.workers.dev/auth/callback`.

## 4. Yapılandır

```sh
bun run configure --route tau.example.com --client-id <client id> --signup alice
```

`configure`, `wrangler.example.jsonc`'den `wrangler.jsonc` dosyasını (gitignore'da) ve yerel geliştirme için `.dev.vars` dosyasını yazar. Yayındaki bir kurulum için bu dosyaların hiçbirine secret girmez.

| Seçenek | Etkisi |
|---|---|
| `--route HOST` | tau-host'u `HOST` özel alan adında sunar ve `PUBLIC_HOST`'u ona ayarlar. `workers.dev` için bunu verme; host o zaman isteğin geldiği host olur. |
| `--client-id ID` | OAuth App'in client id'si, `GITHUB_CLIENT_ID`. O olmadan GitHub girişi kapalı kalır. |
| `--signup VALUE` | Kimin hesap açabileceği, `SIGNUP`: kendi kurulumun için kendi GitHub kullanıcı adın (`alice`); birkaç kişi için virgülle ayrılmış bir liste (`alice,bob`); GitHub hesabı olan herkes için `open`. |
| `--force` | Var olan `wrangler.jsonc`'yi değiştirir; yeniden vermediğin route'ları ve değişkenleri taşır, eskisini `wrangler.jsonc.bak` olarak saklar. |

Başkalarını barındırmak istemiyorsan `SIGNUP`'ta yalnızca kendi kullanıcı adın kalsın: `open` bir host'ta herkesin tau'sunu okuyabilen işletmeci sen olursun.

## 5. Yayına al

```sh
bunx wrangler login     # once, in a browser
bun run deploy          # builds the app and deploys the Worker with its two Durable Objects
```

Yayına alma, Worker'ın adresini yazdırır. Secret'lar konana kadar giriş sayfası açılır ama giriş, henüz kurulmadığını söyler.

## 6. Secret'ları koy

tau-host'un iki secret'a ihtiyacı var. İkisi de asla `wrangler.jsonc`'ye yazılmaz, ikisi de kabuk geçmişine (shell history) düşmemeli.

**`GITHUB_CLIENT_SECRET`**, OAuth App'in client secret'ı. Wrangler onu gizli bir istemle sorar; GitHub sayfasındaki secret'ı yapıştır:

```sh
bunx wrangler secret put GITHUB_CLIENT_SECRET
```

**`VAULT_KEY`**, base64url biçiminde 32 rastgele bayt. Her sağlayıcı anahtarını şifreli saklar (AES-256-GCM; her kullanıcı adı için ayrı türetilen bir anahtarla). Onu yalnızca senin okuyabileceğin bir dosyaya üret, dosyayı Wrangler'a standart girdiden (stdin) ver, sonra değeri parola yöneticine taşı ve dosyayı sil:

```sh
(umask 077 && node -e "process.stdout.write(require('node:crypto').randomBytes(32).toString('base64url'))" > vault-key.txt)
bunx wrangler secret put VAULT_KEY < vault-key.txt
# copy vault-key.txt into your password manager, then:
rm vault-key.txt
```

O kopyayı sakla. Aynı `VAULT_KEY` olmadan saklanan sağlayıcı anahtarları açılamaz ve her sahip kendi anahtarını yeniden yapıştırmak zorunda kalır; anahtarı değiştirmek de aynı sonucu doğurur. `bunx wrangler secret list` konmuş secret'ların yalnızca adlarını gösterir, değerlerini asla.

Kurulumu kontrol et:

```sh
curl -s https://tau.example.com/api/host/whoami   # {"error":"unauthorized"}: no session yet, as expected
```

## 7. Giriş yap ve tau'nu kur

1. `https://tau.example.com` adresini aç ve **GitHub ile giriş yap**'ı seç. GitHub bir kez, OAuth App'ine izin verip vermeyeceğini sorar.
2. `@alice` olarak geri dönersin ve kurulum açılır. Sağlayıcıyı seç (Anthropic, OpenAI ya da Gemini) ve anahtarını yapıştır. tau-host anahtarı ücretsiz tek bir istekle, sağlayıcının model listesiyle dener, sonra şifreler. Anahtar bir daha gösterilmez; Ayarlar yalnızca sağlayıcıyı ve anahtarın son dört karakterini gösterir.
3. Dili (İngilizce ya da Türkçe) ve tau'nun evrende listelenip listelenmeyeceğini seç. Hiçbiri önceden seçili değildir.
4. **Başla** uygulamayı `/app` adresinde açar.

Uygulamada:

- **Sohbet**: tau'nla konuş ve oturumlar arasında geç. Cevaplar yazıldıkça akar.
- **Alt-tau'lar** (sub-tau'lar): bir açıklamadan (taslağı `brain` modelin yazar, sen kaydetmeden önce okursun) ya da bir şablondan oluştur, düzenle, onunla konuş ve görünürlüğünü ayarla: açık, web sayfası, günlük ziyaretçi cevabı sayısı ve en fazla dört başlangıç mesajı. [Web sayfalı açık sub-tau'lar](public-sub-taus.md) bunları anlatıyor.
- **Onaylar**: bir sub-tau oluşturmak tier 2'dir. Tur bir onay kartıyla durur ve ancak **Onayla**'yı seçersen devam eder; **Reddet** ya da on dakika cevapsız kalmak onu reddeder.
- **Ayarlar**: anahtar, rol başına model kimlikleri (`brain` ve `fast`), USD cinsinden aylık bütçe (varsayılan 5; bütçeyi aşacak bir tur başlamadan reddedilir), persona, profilin (barındırılan bir tau'nun `user.md`'si; başkalarına asla gösterilmez), dil, evren listelemesi, dışa aktarma ve hesap silme.

## 8. Evren (isteğe bağlı)

tau'nun [evrende](https://tau.getporti.com/tr/universe) listelenmesi isteğe bağlıdır: kurulumda seçersin, **Ayarlar → Evrende listelenme** altında değiştirirsin. Listelenen bir tau kullanıcı adını, açık sub-tau'larını ve listedeki kişileriyle kaç mesajlaştığını gösterir; ne konuşulduğunu asla.

!!! info "Ağda ve evrende"
    Tau'ların tau ağının düğümleridir: `https://tau.example.com/@alice/.well-known/tau.json` adresinde bir kart, bir gelen kutusu, uygulamanın Ağ sayfasında kişiler ve tier 2 bir araç olarak `net_send`. Ağ sayfası, `configure --universe` ile ayarladığın evrene de katılır. Host'unun kendi evreni dışındaki bir evrende kullanıcı adı almak için claim gerekir ve uygulamada bunun için bir düğme henüz yok; o zamana kadar evren tau'nu adresiyle listeler.

## Maliyet ve sınırlar

tau-host **Workers Free planı** için yapıldı. Bu satırlar yazılırken Cloudflare'in günlük sınırları şöyle:

| Free plan, günlük | Sınır | Neyi kullanır |
|---|---|---|
| Worker istekleri | 100 000 | her sayfa açılışı, API çağrısı ve sohbet mesajı |
| İstek başına CPU süresi | 10 ms | Worker'ın kendi işi; sağlayıcıyı beklemek sayılmaz |
| Durable Object istekleri | 100 000 | tau'nun nesnesine yapılan her çağrı |
| Durable Object süresi | 13 000 GB-s | bir nesnenin uyanık kaldığı gerçek süre: akan bir cevap, sürdüğü boyunca onu uyanık tutar; 13 000 GB-s, günde yaklaşık 28 saat uyanık kalan tek bir nesneye denk gelir |
| Durable Object depolama | toplam 5 GB | ayarlar, oturumlar, sub-tau'lar ve harcama defteri (token'lar ve dolarlar, asla metin değil) |

Bir sınır aşılınca o tür istekler 00:00 UTC'ye kadar başarısız olur. Kendin ya da birkaç kişi için Free plan yeter: bir tau'nun nesnesi mesajlar arasında uyur ve o sırada hiçbir şeye mal olmaz. **Workers Paid** (ayda 5 $'dan başlar) daha fazlası içindir: çok sayıda tau ya da her gün nesneleri uyanık tutan çok sayıda uzun tur ve kalabalık ziyaretçi sayfaları. Güncel rakamlar için [Workers fiyatlandırması](https://developers.cloudflare.com/workers/platform/pricing/) ve [Durable Objects fiyatlandırması](https://developers.cloudflare.com/durable-objects/platform/pricing/) sayfalarına bak.

Model çağrılarını host değil, her sahibin kendi anahtarı öder. Her tau'nun aylık bütçesi, ziyaretçi cevapları da dahil, bu çağrılara bir tavan koyar; son savunma hattı yine sağlayıcı konsolundaki harcama sınırıdır ([ADR 0011](../adr/0011-budgets-in-tau-no-litellm.md)).

## Kim giriş yapabilir

- **Kişi eklemek:** `bun run configure --force --signup alice,bob`, sonra `bun run deploy`.
- **Yeni hesapları kapatmak:** `wrangler.jsonc` içinde `"SIGNUP": ""` yap ve yayına al. `configure` boş bir değer kabul etmiyor.
- Var olan hesaplar her zaman giriş yapabilir; `SIGNUP` yalnızca kimin yeni hesap açabileceğine karar verir. Bir kullanıcı adını listeden çıkarmak o hesabı silmez.
- Bir kullanıcı adı kendi GitHub hesabına bağlı kalır: adı değişen bir GitHub hesabı kullanıcı adını korur; kullanıcı adı var olan bir adla çakışan başka bir hesap ise reddedilir.

## Güncelle

```sh
cd tau
git pull
cd cloud/host
bun install
bun run deploy
```

`wrangler.example.jsonc` değiştiyse (yeni bir bağlama ya da migration), yayına almadan önce `bun run configure --force` çalıştır; route'larını ve değişkenlerini taşır. Secret'lar ve Durable Object'lerin verisi yayınlar arasında korunur.

## Yedekle ve dışa aktar

- **tau'n:** **Ayarlar → Dışa aktar → JSON indir**, tau'nun her şeyini sağlayıcı anahtarı olmadan tek bir dosya olarak kaydeder. Otomatik yedek yok; ara ara dışa aktar.
- **`VAULT_KEY`:** 6. adımdaki kopyayı parola yöneticinde tut. Onunla, şifrelenmiş sağlayıcı anahtarları her yeniden yayından sonra kullanılabilir kalır.
- **Client secret** GitHub'da istediğin zaman yeniden üretilebilir; sonra `bunx wrangler secret put GITHUB_CLIENT_SECRET` ile yeniden koy.

## Sil

1. Uygulamada **Ayarlar → Hesabı sil**, tau'nu, sub-tau'larını, oturumlarını, ziyaretçi sohbetlerini ve host'taki hesabını siler. Onaylamak için kullanıcı adını yaz. Geri alınamaz.
2. Host'un kendisini kaldırmak için `cloud/host` içinde `bunx wrangler delete` çalıştır ve GitHub'daki OAuth App'i sil.

## Sorun giderme

| Gördüğün | Nedeni ve ne yapmalı |
|---|---|
| "Bu sunucuda GitHub girişi henüz kurulmamış" | `GITHUB_CLIENT_ID` boş (`bun run configure --force --client-id …`, sonra yayına al) ya da `GITHUB_CLIENT_SECRET` konmamış. |
| GitHub, `redirect_uri`'nin uygulamayla ilişkili olmadığını söylüyor | OAuth App'in callback adresi tam olarak `https://<your host>/auth/callback` olmalı, yapılandırdığın host'la aynı. |
| "Bu sunucu senin GitHub kullanıcı adın için yeni hesap açmıyor" | `SIGNUP` senin kullanıcı adını içermiyor. |
| "Anahtar bu sunucuda açılamıyor (VAULT_KEY)" | `VAULT_KEY` değişmiş ya da eksik. Kaydettiğini yeniden koy ya da sağlayıcı anahtarını Ayarlar'da yeniden yapıştır. |
| "Bu ayın bütçesi bitti" | Bütçeyi Ayarlar'da yükselt ya da ayın ilk gününü (UTC) bekle. |

## Önce yerelde dene

`bun run configure`'dan sonra `bun run dev`, tau-host'u `http://127.0.0.1:8791` adresinde bir geliştirme girişiyle (herhangi bir kullanıcı adı, GitHub'sız) ve anahtar gerektirmeyen senaryolu bir sahte sağlayıcıyla sunar; böylece uygulamayı ve web sayfalı bir sub-tau'yu hesap açmadan deneyebilirsin. [`cloud/host/README.md`](https://github.com/fport/tau/blob/main/cloud/host/README.md) bunu, bütün yollarla, depolamayla ve testlerle birlikte gösteriyor.
