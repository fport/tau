<!-- tr twin of getting-started/three-ways.md, translated 2026-09-30 -->

# Başlamanın üç yolu

Bir tau'yu üç yoldan çalıştırabilirsin. Hepsi yalnızca kendi model anahtarını ister; Anthropic, OpenAI ya da Google Gemini'den. tau sağlayıcıyı bu anahtarla doğrudan çağırır, arada ne bir yönlendirici (router) ne de bir proxy vardır; her cevabın maliyetini de bütçenden kendisi düşer. Üç yol; tau'nun nerede çalıştığı, onu kimin okuyabildiği ve neler yapabildiğiyle ayrılır. Arkadaki karar [ADR 0013](../adr/0013-hosted-taus-handles-and-public-pages.md).

- **Yerel**: kendi makinende çalışan Python hub'ı. Varsayılan ve gizli olan yol bu.
- **Barındırılan** (hosted): [tau.getporti.com](https://tau.getporti.com) üzerindeki tau-host. GitHub ile giriş yapar, tau'nla tarayıcıda konuşursun.
- **Kendi kurulumun** (own host): aynı tau-host, kendi Cloudflare hesabına senin tarafından kurulmuş hâliyle; yalnızca senin için.

## Yan yana

| | Yerel | Barındırılan | Kendi kurulumun |
|---|---|---|---|
| **tau nerede çalışır** | makinendeki hub'da (`tau hub run`) | `tau.getporti.com` üzerindeki tau-host'ta, işletmecinin Cloudflare hesabında | kendi Cloudflare hesabındaki tau-host'ta |
| **Ne gerekir** | macOS ya da Linux, [uv](https://docs.astral.sh/uv/), model anahtarın | bir GitHub hesabı, model anahtarın | bir Cloudflare hesabı, bir GitHub OAuth App, bun ve Node.js 24, model anahtarın |
| **tau'nu kim okuyabilir** | yalnızca sen | sen **ve** sunucunun **işletmecisi** | yalnızca sen |
| **Onunla nerede konuşursun** | terminal, TUI, Telegram | tarayıcı | tarayıcı |
| **Neler yapabilir** | hub'ın yaptığı her şey: tier denetiminden geçen araçlar, sub-tau'lar ve açık sayfaları, ağ, evren; geldikçe node'lar, ses ve robot kol | sohbet, sub-tau'lar, sub-tau'lar için açık sayfalar, ağ ve evren | barındırılanla aynı |
| **Neleri yapamaz** | henüz tarayıcı uygulaması yok (web arayüzü planlanıyor) | cihaz araçları, node'lar, ses, hafıza ve rutinler yok | barındırılanla aynı |
| **Adresi** | spine'ının host'u, `tau.example.com` | `tau.getporti.com/@alice` | `tau.example.com/@alice` |
| **Maliyeti** | model kullanımın | model kullanımın | model kullanımın; tau-host birkaç tau için Workers Free planına sığar |

Model sağlayıcı, tau'nun düşünmek için ona gönderdiklerini her üç yolda da görür. Güvendiğin birini seç ve son savunma hattı olarak onun konsolunda bir harcama sınırı koy.

## Kim neyi okuyabilir

- **Yerel.** Konuşmaların, `persona/user.md` (tau'ya kendin hakkında anlattıkların), oturumların ve anahtarların makinende, `TAU_HOME` ve `TAU_DATA_DIR` altında kalır. Hub hiçbir zaman dışarıdan gelen bağlantıya port açmaz. [ADR 0006](../adr/0006-private-first-topology.md)'nın sözleri eksiksiz geçerlidir.
- **Barındırılan.** tau'n başka birinin Worker'ında yaşar. İşletmecisi sohbetlerini, persona'nı ve profilini, sub-tau'larını ve ziyaretçilerinin sohbetlerini okuyabilir. Sağlayıcı anahtarın ücretsiz tek bir istekle denenir, şifreli saklanır (AES-256-GCM) ve bir daha gösterilmez, sana bile: uygulama yalnızca sağlayıcıyı ve anahtarın son dört karakterini gösterir. Barındırılan bir kolaylıktır; gizlilik, yerel ya da kendi kurulumun demektir.
- **Kendi kurulumun.** İşletmeci sensin. tau'n kendi Cloudflare hesabındaki bir Durable Object'te yaşar ve sağlayıcı anahtarlarını şifreleyen anahtar, yalnızca senin koyduğun bir secret'tır.
- **Ziyaretçi sohbetleri.** Web sayfası olan açık bir sub-tau, anonim ziyaretçilerle evren üzerinden konuşur. Evren bu sohbetleri düz metin olarak aktarır ve her konuşmayı 24 saat tutar. Üç yolun hiçbirinde uçtan uca gizli değildir. Bkz. [Web sayfalı açık sub-tau'lar](../guides/public-sub-taus.md).

## Yerel: tau senin makinende

Her şey kendi bilgisayarında olur. `tau init` önce arayüz dilini sorar; ortamda ya da `.env`'de anahtar bulamazsa sağlayıcını (`anthropic`, `openai` ya da `gemini`) ve anahtarını ister, anahtar yazılırken görünmez. Anahtarı küçük bir istekle dener ve `0600` izinle `~/.tau/.env` dosyasına yazar.

```sh
uv tool install tau-core --with tau-tui
tau init        # the UI language, your provider and its key
tau doctor      # checks the config, the key, the persona and the sessions
tau chat
```

```text
UI language (en, tr) [en]: en
No model key was found in the environment or ~/.tau/.env. tau needs a key from one provider (`tau init --yes` sets up the scripted 'fake' provider without one).
Provider (anthropic, openai, gemini) [anthropic]: anthropic
ANTHROPIC_API_KEY (hidden; empty skips):
Checking the key with one small request to anthropic...
anthropic accepted the key.
```

`tau init --yes` hiçbir şey sormaz ve senaryolu `fake` modeli kurar; her komutu denemek için bu yeterli. Dil olarak `tr` seçersen sonraki sorular Türkçe gelir. Ağ, bulut modu ve sub-tau'lar (`tau-net`, `tau-cloud`, `tau-sub`) PyPI'a çıkana kadar kaynaktan kurulur ([Kurulum](install.md)).

Sonra:

- [Kendi tau'nu kur](build-your-own-tau.md): kurulumdan Telegram'a, tau ağında bir adrese ve evrene kadar bütün yol.
- [Her şeyi yerelde dene](try-locally.md): tek makinede iki tau; ne hesap gerekir ne anahtar.

## Barındırılan: tau.getporti.com

1. [tau.getporti.com](https://tau.getporti.com) adresini aç ve **GitHub ile giriş yap**'ı seç. Kullanıcı adın (handle), GitHub kullanıcı adının küçük harfli hâlidir: `Alice` girişi `@alice` olur, tau'nun adresi de `tau.getporti.com/@alice`.
2. tau'nu kur: sağlayıcıyı seç, anahtarını yapıştır, dili seç (İngilizce ya da Türkçe) ve tau'nun evrende listelenip listelenmeyeceğini söyle. Hiçbiri önceden seçili değildir.
3. `/app` adresinde onunla konuş. Uygulamada oturumların, sub-tau'ların, seni bekleyen onaylar ve ayarlar da var: anahtar, rol başına model kimlikleri, aylık bütçe (varsayılan 5 USD), persona, profilin, dil, her şeyin JSON olarak dışa aktarımı ve hesabı silme.

Bir sub-tau oluşturmak ve senin adına başka bir tau'ya yazmak, hub'da olduğu gibi tier 2'dir: tur bir onay kartıyla durur ve ancak sen onaylayınca devam eder.

## Kendi kurulumun: tau-host kendi Cloudflare hesabında

Aynı uygulama, senin kurduğun hâliyle: bir GitHub OAuth App oluştur, `cloud/host` içinde `bun run configure` çalıştır, iki secret koy ve yayına al. Yalnızca senin GitHub kullanıcı adın hesap açabilir. [Kendi kurulumunu yap](../guides/own-host.md) her adımı örnek değerlerle anlatıyor.

```sh
cd cloud/host
bun install
bun run configure --route tau.example.com --client-id <client id> --signup alice
bun run deploy
```

!!! info "Planlanan"
    Barındırılan tau'ların tau ağına (`<host>/@<handle>` altında bir kart ve gelen kutusu, kişiler, `net_send`) ve evrene katılması [162](https://github.com/fport/tau/blob/main/roadmap/L9-network/162-hosted-taus-on-the-network.md) numaralı issue ile geliyor. `tau.getporti.com` üzerinde giriş, işletmeci yayına geçince açılacak: issue [165](https://github.com/fport/tau/blob/main/roadmap/L9-network/165-hosted-go-live.md). O zamana kadar uygulama evren tercihini sonrası için saklar; kendi kurulumun sohbet, sub-tau'lar ve onların web sayfaları için çalışır.

## Dördüncü yol: bulut modu

**Bulut modu**, Python hub'ının kendisini kendi hesabındaki bir Cloudflare Container'da, spine'ının yanında çalıştırır; sürekli açık bir makinesi olmayanlar için. Yerel makinesiz yerel hub gibidir: Telegram, sub-tau'lar ve ağ evdeki gibi çalışır; oturumların ve persona'n ise Cloudflare hesabında durur. Workers Paid (ayda yaklaşık 5 $) ve container'ın çalışma süresi kadar ücret ister, imajı derlemek için de Docker gerekir. İleri düzey yol budur: [tau'yu Cloudflare'de çalıştır (bulut modu)](../guides/cloud-mode.md).

## Hangisi?

- tau cihazlarına dokunsun ya da senden başka kimse okuyamasın istiyorsan: **yerel**.
- tau'yu bir dakikada denemek istiyor ve işletmecinin okuyabileceğini kabul ediyorsan: **barındırılan**.
- Tarayıcı uygulamasını gizli biçimde istiyorsan ve bir Cloudflare hesabın varsa: **kendi kurulumun**.
- Hub'ın tamamını istiyor ama sürekli açık bir makinen yoksa: **bulut modu**.
