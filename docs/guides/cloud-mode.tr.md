<!-- tr twin of guides/cloud-mode.md, translated 2026-09-30 -->

# tau'yu Cloudflare'de çalıştır (bulut modu)

Varsayılan olarak tau kendi makinende çalışır ve yaşam verini orada tutar (yerel mod, [ADR 0006](../adr/0006-private-first-topology.md)). **Bulut modu** aynı tau'yu evde bir makine olmadan çalıştırır. Hub (tau'nun ajanını ve servislerini çalıştıran süreç), kendi Cloudflare hesabında, spine Worker'ının (tau'nun ağdaki adresi ve posta kutusu olan küçük Cloudflare Worker'ı) yanında bir Container (Cloudflare'in yönettiği konteyner) olarak çalışır; sen de onunla Telegram üzerinden konuşursun. Karar [ADR 0007](../adr/0007-cloud-mode-and-tau-network.md)'de.

!!! warning "Karşılığında neyi veriyorsun"
    Bulut modunda oturumların, persona'n (`persona/user.md` dahil) ve ayarların **senin** Cloudflare hesabında yaşar: D1 ve KV içinde, yalnızca senin tuttuğun bir anahtarla değil, Cloudflare'in kendi durağan veri (at-rest) şifrelemesiyle. O hesaba giren herkes ya da sızmış bir `HUB_TOKEN` onları okuyabilir. Yerel mod bunların hepsini senin makinende tutar. Bulut modunu ancak bunu kabul ediyorsan seç.

## Ne nerede çalışır

| Parça | Nerede |
|---|---|
| Spine Worker'ı (`tau-spine`) | Cloudflare Workers: adresin, kartın ve posta kutun, depo API'si, bir cron |
| Beyin (`tau hub run`, aynı Python kodu) | spine'ın yönettiği, `tau cloud run` ile başlatılan bir Cloudflare Container |
| Oturumlar, küçük durum (kişiler, imleçler) | spine üzerinden D1 (`[sessions] backend = "spine"`) |
| `tau.toml`, `persona/*.md`, sub-tau'lar (`persona/subs/*.md`) | `tau cloud push` ile yüklenen KV |
| Kimlik bilgileri (model anahtarları, Telegram token'ı, ağ kimliği) | Worker secret'ları (gizli değerleri); container'a ortam değişkeni olarak verilir |

## Başlamadan önce

- **Workers Paid** planında (ayda yaklaşık 5 $) bir Cloudflare hesabı, çünkü Container'lar bunu gerektirir. Container'ın kendisi çalıştığı süre kadar faturalanır; spine'ın cron'u Telegram poller'ı çalışabilsin diye onu uyanık tutar.
- Deploy ettiğin (yayına aldığın) makinede çalışan **Docker**, çünkü Wrangler imajı yerelde derler.
- bun ve Node.js 24 (Wrangler Node üzerinde çalışır), bir de bu deponun bir klonu.
- Önce çalışan bir yerel kurulum (`tau init`, `tau doctor`), çünkü bulut modu senin `tau.toml` ve persona dosyalarını yükler.

## 1. Spine'ı bulut modunda yapılandır ve deploy et

```sh
cd cloud/spine
bun install
bun run configure --cloud --force     # wrangler.jsonc from wrangler.cloud.example.jsonc
bunx wrangler login
```

`cloud/spine/wrangler.jsonc` dosyasını aç ve `SPINE_URL` değerini spine'ının sahip olacağı URL'ye ayarla: `workers.dev` URL'si ya da bir rota eklersen kendi alan adın. Container spine'a bununla ulaşır. Sonra deploy et:

```sh
bun run deploy:cloud
```

## 2. Secret'ları ayarla

Aşağıdaki her değer `cloud/spine` içinde `bunx wrangler secret put <NAME>` ile girilir; komut değeri sana sorar. Bir secret'ı asla komut argümanı olarak verme. Yalnızca rollerinin kullandığı model anahtarlarını ayarla; container bu secret'lardan ayarlı olan her birini alır, başka hiçbirini almaz.

| Secret | Değer |
|---|---|
| `HUB_TOKEN` | uzun, rastgele bir değer; yerel `tau cloud` komutların onu `TAU_SPINE_TOKEN` olarak kullanır |
| `ANTHROPIC_API_KEY` (gerekirse `ANTHROPIC_WORKSPACE_ID` ile), ya da `AWS_REGION` + `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` / `AWS_BEARER_TOKEN_BEDROCK` | `tau.toml` içindeki rollerinin ihtiyaç duyduğu model kimlik bilgileri |
| `OPENAI_API_KEY` | isteğe bağlı: yalnızca bir rol `openai` sağlayıcısını kullanıyorsa |
| `GEMINI_API_KEY` ya da `GOOGLE_API_KEY` | isteğe bağlı: yalnızca bir rol `gemini` sağlayıcısını kullanıyorsa (iki ad da çalışır) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS` | [Telegram rehberindeki](telegram.md) gibi |
| `TAU_NET_IDENTITY` | buluttaki tau'nun tau ağına katılması gerekiyorsa ağ kimliğin: `TAU_DATA_DIR/net/identity.json` içindeki JSON'un base64url hâli ([tau ağına katıl](tau-network.md)) |

Beyin, `tau.toml` dosyandaki `budget` tablolarını tıpkı yerel bir hub gibi kendisi uygular ([Modeller ve bütçeler](models-and-budgets.md)); ama harcama defteri (ledger) container'ın diskinde durur ve container her durduğunda kaybolur. Bu yüzden bir yeniden başlatmadan sonra her bütçe yeniden sıfırdan sayar; aylık sınırı sağlayıcının konsolunda da tut.

## 3. Yapılandırmanı ve persona'nı yükle

`tau.toml` ve `persona/` dosyalarının bulunduğu makinede `TAU_SPINE_URL` (spine URL'si) ve `TAU_SPINE_TOKEN` (`HUB_TOKEN`) değerlerini `.env` dosyasına koy, sonra:

```sh
tau cloud push      # tau.toml, persona.md, net.md, persona/subs/*.md; shows the list and asks first
tau cloud status    # spine health and mode, the files it holds, the brain container's health
```

- Dosya kümesi tam olarak `tau.toml`, `persona/persona.md`, `persona/user.md`, `persona/net.md` ve sub-tau'ların: `persona/subs/` içindeki `.md` dosyaları, yani tanımlar (`coach.md`) ve onların açık notları (`coach.public.md`). Başka hiçbir şey okunmaz ya da gönderilmez; `.env` asla yüklenmez.
- `tau cloud push`, `persona/subs/` içindeki başka her şeyi atlar ve nedeniyle birlikte adını yazar: adı düz bir `.md` adı olmayan bir dosya (harf, rakam, `.`, `_`, `-`; harf ya da rakamla başlar), bir alt dizin ya da bir sembolik bağlantı (bir bağlantı, `persona/user.md` gibi dışarıdaki bir dosyayı gönderebilir).
- Burada sildiğin bir sub-tau dosyası (`tau sub remove coach`), bir sonraki push'ta spine'dan da silinir; push sormadan önce onu listeler. `persona/subs/` dizini olmayan bir makine, spine'daki sub-tau'lara dokunmaz.
- `persona/user.md` tau'nun senin hakkında bildiklerini tutar; bu yüzden onun için ayrı bir soru sorulur ve varsayılan yanıt hayırdır. `tau cloud push --include-user` onu soru sormadan yükler.
- Bir betikte (terminal yokken) `tau cloud push --yes` sormadan yükler; `persona/user.md` ise ancak ayrıca `--include-user` verilirse yüklenir.
- Beyin bu dosyaları başlarken okur. Bir push'tan sonra çalışan beyin, bir sonraki başlangıcına kadar eski dosyaları kullanmaya devam eder (yeniden bir deploy onu yeniden başlatır).
- `tau cloud pull` aynı dosyaları indirir; örneğin yeni bir makineye. `--force` vermedikçe farklı olan bir yerel dosyanın yerine asla yazmaz, hiçbir yerel dosyayı silmez ve spine'ın dosya kümesi dışında listelediği her adı atlar.

## 4. Onunla konuş

Telegram'da botuna yaz. Container'daki hub yanıt verir ve tier-2 onaylar (her zaman onay isteyen izin seviyesi) tıpkı yerel moddaki gibi satır içi butonlar olarak gelir. Oturumlar D1'de saklanır, dolayısıyla container'ın yeniden başlamasından sağ çıkar. `/resume` her zamanki gibi çalışır.

## Beyin container'ı neyi çalıştırır

İmaj (`cloud/spine/container/Dockerfile`), `tau cloud run` komutunu başlatır; bu komut:

1. `TAU_SPINE_URL` ve `TAU_SPINE_TOKEN` değerlerinin ayarlı olduğunu ve spine'ın bulut modunda çalıştığını kontrol eder (değilse tek satırlık bir mesajla çıkar);
2. dosyaları, sub-tau'lar dahil, `TAU_HOME` içine çeker ve çekilen `tau.toml` dosyasının iki anahtarını değiştirir: `[sessions] backend = "spine"` ve `[component.net] store = "spine"`. Yorumlar dahil geri kalan her şey senin yazdığın gibi kalır;
3. 8080 portunda `GET /health` isteğine `{"ok": true, "version": ..., "hub": <the hub's /status or null>}` ile yanıt verir; spine'ın `GET /hub/brain` uç noktası bunu iletir;
4. container çalışma ortamı SIGTERM gönderene kadar aynı süreçte `tau hub run` çalıştırır; SIGTERM hub'ı temiz bir şekilde durdurur.

`tau cloud run`, kendisinin yazmadığı bir `tau.toml` içeren bir `TAU_HOME` dizinini reddeder; böylece senin kendi yapılandırmanın üzerine asla yazmaz.

İmaj `tau-core`, `tau-net`, `tau-cloud` ve `tau-sub` paketlerini kurar; böylece beyin sub-tau'larına sahip olur: `ask_sub` Telegram'dan çalışır ve açık (public) bir sub-tau, tau ağında kişilerine tıpkı yerel bir hub'daki gibi cevap verir ([tau ağına katıl](tau-network.md)).

**Bulut modunda sahip koruması yok.** [Sahip koruması](guard.md) yerel moda özgüdür: bir container'ın kamerası ve Keychain'i yoktur ve `tau-guard` imajda bulunmaz. Orada çalışan kanallar, Telegram ve ağ turları, chat id'inle ve kişilerinin anahtarlarıyla tanınır ve korumaya hiç sormaz; bu yüzden hiçbir şey kilitlenmez. `[component.guard] enabled = true` içeren bir `tau.toml` gönderirsen, container'ın koruması yalnızca kalıcı olarak kilitli olur (`unsupported_platform`) ve bu kanallar bunu yok sayar. Kayıt işaretin ve yüz şablonun Mac'inde `TAU_DATA_DIR/guard/` altında durur ve `tau cloud push` onları asla göndermez. Container'ın `GET /health` yanıtı yalnızca hub'ın açık `/status`'unu okur.

## Container olmadan yerelde dene

`bun run dev:cloud`, spine'ı container'lar kapalıyken bulut modunda çalıştırır; böylece dosyaları ve `spine` oturum arka ucunu Docker ya da Cloudflare hesabı olmadan kontrol edebilirsin:

```sh
(cd cloud/spine && bun install && bun run configure && bun run dev:cloud)
# another terminal; TAU_SPINE_URL=http://127.0.0.1:8787 and TAU_SPINE_TOKEN from cloud/spine/.dev.vars in .env
tau cloud push && tau cloud status      # the brain shows as unavailable: containers are off
# play the container: the spine variables in the environment, an empty TAU_HOME and TAU_DATA_DIR,
# and another hub port in case your own hub runs on 7877
export TAU_SPINE_URL=http://127.0.0.1:8787 TAU_SPINE_TOKEN=<HUB_TOKEN from cloud/spine/.dev.vars>
export TAU_HOME=/tmp/brain/tau TAU_DATA_DIR=/tmp/brain/data TAU_HUB_PORT=7977
TAU_CLOUD_HEALTH_HOST=127.0.0.1 tau cloud run
curl http://127.0.0.1:8080/health       # a third terminal
```

Aynı değişkenlerle çalıştırılan bir `tau chat` de oturumunu yerel spine'ın D1'inde saklar.

## Yerel moda geri dönmek

Yerel mod yapılandırmasını, `migrations` listesine `TauBrain` için bir `deleted_classes` migration'ı ekleyerek yeniden deploy et (`bun run configure --force && bun run deploy`). Tam liste `cloud/spine/README.md` içinde. Container durur, adresin kalır. Kişiler (contacts), ağ logu ve oturumlar spine'ın D1'inde kalır; ama yerel moddaki bir spine onları asla sunmaz, dolayısıyla yerel bir hub boş bir kişi listesiyle başlar. Onları taşıyacak bir araç henüz yok ([issue 108](https://github.com/fport/tau/blob/main/roadmap/L9-network/108-move-between-modes.md)). D1 ve KV'de saklanan veriler sen silene kadar hesabında kalır (`wrangler d1 execute`, `wrangler kv key delete` ya da kaynakları panodan sil).
