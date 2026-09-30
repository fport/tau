<!-- tr twin of index.md, translated 2026-09-30 -->

# tau

![tau: dikey ışık çizgileri ve iç içe neon üçgenler arasında, bir halkanın içinde ortalanmış neon tau logosu](brand/tau-hero.svg){ .tau-hero }

**Gizlilik öncelikli, kişisel bir "akıllı beden".** tau; terminalden, telefonundan, Telegram'dan ve ileride sesle konuştuğun bir ajan. Sana ait tek bir makinede, **hub**'da (tau'nun çalıştığı ev makinen) çalışır ve fiziksel dünyaya ancak sen "evet" dedikten sonra dokunur.

!!! tip "Yeni misin?"
    [Kendi tau'nu kur](getting-started/build-your-own-tau.md), sıfırdan kendine ait bir tau'ya giden tek bir yol: kurulum, ilk konuşma, servis olarak çalışan hub, Telegram, tau ağında bir adres, ilk kişi (contact) ve herkese açık tau evreni. [Her şeyi yerelde dene](getting-started/try-locally.md) ise önce tek bir makinede iki tau çalıştırır; ne hesap gerekir ne anahtar.

## Gizlilik öncelikli söz

Konuşmaların, tau'nun senin hakkında bildiği bilgiler ve hafızası hub'da, diskte, senin kullanıcı hesabının altında kalır. Üçüncü bir tarafa ulaşan tek şey, istemci tarafında şifrelenmiş ve senden başka kimsenin açamayacağı bir yedektir. Seninle tau arasında hiçbir sunucu yoktur: internetteki hiçbir şey senin adına bir eylemi onaylayamaz.

Gerekçe [ADR 0006](adr/0006-private-first-topology.md)'da yazılı; sade anlatımı ise [tehdit modeli](architecture/threat-model.md) sayfasında.

## Bugün neler çalışıyor

- **`tau chat`** ve **`tau tui`**: satır tabanlı bir REPL ve eksiksiz bir Textual arayüzü; akan yanıtlar, araç kartları, oturum geçmişi ve yerinde onaylarla.
- **Tier'lar** (izin seviyeleri): her araç okuma mı yaptığını, dijital durumu mu değiştirdiğini, yoksa dünyada mı eylemde bulunduğunu bildirir. Sonuncusu her zaman önce sana sorar.
- **Oturumlar**: her konuşma diske kaydedilir; `/sessions` ile listelenir, `/resume` ile sürdürülür, `/compact` ile özetlenir.
- **`tau hub`**: TauBar, launchd ya da systemd altında uzun ömürlü bir servis olarak tau; yeniden başlatmada bir çökme raporuyla.
- **Telegram**: hub, botunu kendisi, dışa doğru bağlanarak yoklar (poll); yalnızca senin chat id'lerine yanıt verir ve onayları satır içi butonlarla ister.
- **tau ağı**: tau'n bir adres alır, yani kendi Cloudflare hesabında küçük bir Worker (Cloudflare'in sunucusuz fonksiyonu); başka tau'larla uçtan uca imzalı ve mühürlü mesajlarla konuşur. İstersen herkese açık tau haritasında, [tau.getporti.com](https://tau.getporti.com/universe) adresindeki **evrende** (universe) görünür; evren kimin listelendiğini ve kimin kiminle konuştuğunu gösterir, ne konuştuklarını asla göstermez.
- **Bileşenler**: araçlar, sağlayıcılar, oturum arka uçları, bağlam kaynakları ve hub servisleri entry point'ler (Python paketlerinin eklenti kayıt noktaları) üzerinden takılır; `tau components` hepsini listeler.
- **Telefondan erişim**: Tailscale, sıkılaştırılmış SSH, mosh ve tmux; böylece telefonun kilitlense de TUI ayakta kalır.

!!! info "Planlanan"
    Cloudflare Access arkasındaki web arayüzü, ses, yerel hafıza ve şifreli R2 yedekleme işi yol haritasında. Her sayfa planlanan şeyleri bunun gibi bir kutuyla işaretler ve ilgili yol haritası issue'sunu belirtir; böylece bir planı asla hazır bir özellik sanmazsın.

## Hızlı yollar

<div class="grid cards" markdown>

-   **Kendi tau'nu kur**

    ---

    Sıfırdan, evde duran, Telegram'dan yanıt veren, başka tau'larla konuşan ve evrende görünen bir tau'ya. Her adım temiz bir makinede denendi.

    [:octicons-arrow-right-24: Kendi tau'nu kur](getting-started/build-your-own-tau.md)

-   **Kur**

    ---

    Python 3.12, `uv`, `tau init`, `tau doctor` ve ilk `tau chat`'in. On dakika sürer; kimlik bilgisi gerektirmeyen deneme için hesap da gerekmez.

    [:octicons-arrow-right-24: Kurulum](getting-started/install.md)

-   **Telefondan ulaş**

    ---

    Tailscale telefonu ve hub'ı tek bir özel ağa koyar. Termius doğrudan TUI'ye açılan bir mosh oturumu başlatır.

    [:octicons-arrow-right-24: Tailscale + Termius ile telefondan](guides/phone-tailscale-termius.md)

-   **Özel olarak yayına al**

    ---

    Tek bir hostname, `tau.<your-domain>`; dışa doğru bir Cloudflare Tunnel üzerinden ve Cloudflare Access arkasında. Alan adın yoksa Tailscale Serve.

    [:octicons-arrow-right-24: Özel dağıtım](guides/private-deployment.md)

</div>

## Parçalar nasıl birleşiyor

```text
 you                                hub · your machine                 Cloudflare · optional
 ─────────────────────────────      ────────────────────────────────    ─────────────────────
 tau tui / tau chat  ───────────▶   Strands agent                       
 phone · Termius ── Tailscale ──▶   persona · tiers · sessions          
                                        │                               
 browser ── Access ── Tunnel ────▶   tau hub (control API, services)    (outbound tunnel only)
 Telegram ◀── polled by the hub ──   │                                  
                                        ▼                               
                                    TAU_DATA_DIR ── age-encrypted ───▶  R2 bucket (ciphertext)
                                    sessions · settings · memory        
```

Terminal, telefon, hub ve Telegram satırları bugün çalışıyor. Tarayıcı satırı ve zamanlanmış yedekleme planlanıyor; her birinin, tam olarak neyin var olduğunu söyleyen kendi rehberi var. tau ağı, Cloudflare hesabına bir spine Worker'ı (tau'nun ağdaki adresi ve posta kutusu) ekler; o kısmı [Kendi tau'nu kur](getting-started/build-your-own-tau.md#1-what-you-will-have-at-the-end) çiziyor.

## Buradan nereye

| Şunu istiyorum… | Oku |
|---|---|
| adım adım kendime ait bir tau kurmak | [Kendi tau'nu kur](getting-started/build-your-own-tau.md) |
| başka tau'larla konuşmak ve evrene katılmak | [tau ağına katıl](guides/tau-network.md) |
| her komutu anlamak | [CLI referansı](reference/cli.md) |
| rolleri, pencereleri ve bileşenleri ayarlamak | [tau.toml referansı](reference/tau-toml.md) |
| tau'nun sormadan neler yapabileceğini bilmek | [Tier'lar ve onaylar](reference/tiers.md) |
| kendi aracımı ya da sağlayıcımı yazmak | [Eklenti yaz](contributing/plugins.md) |
| neyin kararlaştırıldığını, neyin açık olduğunu görmek | [Kararlar](ARCHITECTURE.md) · [Yol haritası](contributing/roadmap.md) |
