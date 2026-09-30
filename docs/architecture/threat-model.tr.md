<!-- tr twin of architecture/threat-model.md, translated 2026-09-30 -->

# Tehdit modeli

Bu, [ADR 0006](../adr/0006-private-first-topology.md)'nın okunabilir hâli: tau neyi, kime karşı koruyor, bundan hangi kararlar çıkıyor ve bir saldırgan ele geçirebileceği her parçadan ne elde eder, bunun tablosu. Herhangi bir şeyi dışarıya açmadan önce oku; pratik tamamlayıcısı [Özel dağıtım](../guides/private-deployment.md) rehberi.

## Korunan ne

| Varlık | Nerede yaşar | Neden önemli |
|---|---|---|
| Yaşam verisi: `persona/user.md`, oturumlar, hafıza, bilgi tabanı | hub'da (tau'nun çalıştığı, sana ait makine), `TAU_HOME` ve `TAU_DATA_DIR` altında | senin hakkındaki bilgiler, her konuşma, tau'nun hatırladığı her şey |
| Kimlik bilgileri: `.env`, tünel kimlik bilgisi dosyası, yedekleme anahtarı | hub'da; yedekleme anahtarı ayrıca parola yöneticinde | model sağlayıcıları, Cloudflare, Telegram; yedeklerin kendisi |
| Hub makinesi | masan | ileride kabuk ve dosya araçları; şimdilik diskteki oturumlar |
| Ev cihazları ve robot | evin; node'lar (cihazlara ulaşan süreçler) üzerinden erişilir | tier-2 araçlar (her zaman onay isteyen izin seviyesi): fiziksel dünya |

## Kim, nasıl saldırır

1. **Herkese açık bir uç nokta üzerinden.** İnternetten ulaşılabilen her şey taranır ve yoklanır. tau'nun yanıtı, böyle yalnızca tek bir uç noktaya sahip olmak; o da kimlik doğrulamasının arkasında ve hub'da dışarıdan gelen bağlantılara açık hiçbir port olmadan.
2. **Metin üzerinden.** Bir Telegram mesajı, çekilen bir web sayfası, bir araç sonucu: modele ulaşan her şey onu bir aracı kötüye kullanmaya ikna etmeye çalışabilir (prompt injection). tau'nun yanıtı: model asla hiçbir şeyi onaylamaz, yazma işlemleri tier 2'dir ya da sandbox içinde çalışır, içerik çekme işlemleri bir izin listesine tabidir ve refleksler hiç model kullanmaz.
3. **Başka yerde duran veri üzerinden.** Üçüncü bir tarafın deposu ihlal edilebilir, mahkeme kararıyla istenebilir ya da yanlış yapılandırılabilir. tau'nun yanıtı, yaşam verisini hub'da tutmak ve dışarıya yalnızca şifreli metin göndermek.

**Kapsam dışı:** model çıkarımı (inference). Prompt'lar hub'dan doğrudan yapılandırılmış sağlayıcıya gider (sahibinin anahtarıyla Anthropic, OpenAI ya da Google Gemini; [ADR 0011](../adr/0011-budgets-in-tau-no-litellm.md)); arada hiçbir şey yoktur. Hub'daki harcama defteri (`TAU_DATA_DIR/spend.sqlite3`) her çağrı için token'ları ve dolarları kaydeder, asla metni değil. Önlem, veri minimizasyonu (sistem prompt'u `user.md` ve konuşmayı taşır, başka hiçbir şeyi değil) ve bir prompt'u sahibinin Mac'inde (Ollama) tutan `local` rolüdür.

## Kararlar

| # | Karar | Tek cümleyle |
|---|---|---|
| 1 | Tek bir herkese açık yüzey, kimlik doğrulaması kenarda | `tau.<your-domain>` → Cloudflare Access → Cloudflare Tunnel (hub'dan dışa doğru) → web arayüzü. Alan adı yoksa Tailscale Serve. Dışarıdan gelen bağlantıya açık port asla yok. |
| 2 | Aracısız Telegram | Hub `getUpdates` çağrısını kendisi yoklar; webhook yok, Worker yok; hub üzerinde bir `chat_id` izin listesi. |
| 3 | Yaşam verisi hub'da yaşar | Oturumlar, ayarlar, hafıza, bilgi tabanı ve rutinler `TAU_DATA_DIR` altında; vektör arama yerel; Cloudflare yalnızca özel bir R2 bucket'ında `age` ile şifrelenmiş yedekleri tutar. |
| 4 | Ayarlar yerel veridir | `TAU_DATA_DIR` altında, anında yeniden yüklenen bir dosya; asla üçüncü bir tarafa eşitlenmez. |
| 5 | Onaylar yalnızca güvenilen kanallardan | TUI, TauBar, Access arkasındaki ve cihaz başına bir anahtarla korunan web arayüzü ve doğrudan yoklanan Telegram. Hiçbir aracı yok, dolayısıyla hiçbiri onay veremez. |
| 6 | Araçlar girdinin düşmanca olduğunu varsayar | Kabuk, dosya ve yazma araçları tier 2 ya da sandbox içinde; içerik çeken araçlar izin listesine tabi; tau'nun yazdığı araçlar `tools/_pending/` içinde bekler; mesh ve sshd yalnızca tailnet'te kalır. |
| 7 | Ses ayrı bir paket | Mikrofon, STT ve TTS hub'da; uyandırma ifadesinden önce hiçbir şey dışarı çıkmaz; telefondan ses, web arayüzünün mikrofonu üzerinden hub'a gider. |
| 8 | Herkes kurabilir | PyPI paketleri, `tau init`, `tau doctor`, bu doküman sitesi; kurmak ya da okumak için kişisel hiçbir şey gerekmez. |

## X ele geçirilirse saldırgan ne elde eder

Her satırı şöyle oku: *yalnızca bu tek şey düşerse ve başka hiçbir şey düşmezse*.

| Ele geçirilen | Elde ettikleri | Elde edemedikleri | Sınırlayan ne |
|---|---|---|---|
| **Telegram bot token'ı** | bota gönderdiğin mesajlar ve tau olarak yanıt verebilme | hub, dosyaları, bir onay | izin listesi hub'da kontrol edilir; butonlar senin sohbetinden gelen callback'lerdir ve token sahibi bunları taklit edemez. Token'ı BotFather ile yenile. |
| **Cloudflare hesabın** | Access politikasının kontrolü, yani web arayüzünün ön kapısı; R2 bucket'ı | okunabilir veri: R2 yalnızca şifreli metin tutar; tarayıcıdan bir onay, çünkü bu Access'in üstüne cihaz başına anahtar da gerektirecek (issue 074) | hesapta iki aşamalı doğrulama; tünel kimlik bilgisi hub'da kalır; yedekleme anahtarı asla Cloudflare'de olmaz |
| **Tek başına R2 bucket'ı** | `age` ile şifrelenmiş paketler | okunabilir hiçbir şey | anahtar hub'da ve parola yöneticinde yaşar |
| **Access aşılarak ulaşılan, web arayüzündeki bir hata** | sen olarak ajan: konuşmalar, model üzerinden `user.md`, tier 0 ve 1'deki araç çağrıları | cihaz anahtarı olmadan tier-2 bir eylem; kabuk (tier 2 ya da sandbox içinde) | önde Access + isteğe bağlı cihaz kuralı; arkada tier'lar. Cihaz kuralını haklı çıkaran satır bu. |
| **Hub makinesi** | her şey: yaşam verisi, `.env`, tünel, cihazlar | – | tam disk şifreleme, yalnızca tailnet'ten ve yalnızca anahtarla sshd, `0600` dosyalar; yedek ve anahtarı yeniden kurmanı sağlar |
| **Tailscale hesabın** | tailnet'inde bir cihaz: sshd'ye (yalnızca anahtar, yani giriş yok), mesh'e (katman 5) ve bir Tailscale Serve web arayüzüne (önünde Access yok) ulaşabilir | SSH anahtarın olmadan bir giriş; cihaz anahtarı olmadan bir onay | yalnızca anahtarla sshd; alan adın varsa Serve yerine Tunnel + Access'i tercih et; tanımadığın cihazları yönetim konsolundan kaldır |
| **Telefon** | SSH anahtarı ve Tailscale cihazı iptal edilene kadar TUI'li bağlı bir tmux oturumu; Telegram uygulaması; bir Access oturum çerezi | yedekleme anahtarı; tmux oturumunun kullanıcısının ötesinde hub'ın kabuğu | `authorized_keys` içindeki anahtarı ve Tailscale'deki cihazı iptal et; telefonda Telegram'dan çıkış yap; kısa Access oturum süreleri |
| **Model sağlayıcısı** | prompt'lar ve yanıtlar: `user.md`, konuşma, araç açıklamaları | dosyalar, hub, onaylar | veri minimizasyonu; `local` rolü (Mac'te Ollama) |
| **Enjekte edilmiş metin** (zehirli bir sayfa, izin listesindeki bir sohbetten gelen düşmanca bir Telegram mesajı) | yanlış bir şey yapmak isteyen bir model | sen olmadan tier-2 bir eylem; sandbox dışında bir yazma | tier'lar; model asla onaylamaz; modelsiz refleksler |

## Neden alternatifler değil

- **API'sinde Access olan herkese açık bir Worker.** Access ön kapıyı korur, ama Worker yine de onay yolunu ve veriyi tutardı; oradaki bir hata ya da sızan bir token evine kadar uzanır.
- **Her şey yalnızca Tailscale üzerinden.** En gizlisi bu, ama her cihazdan bir tarayıcı arayüzü ve başkalarının da izleyebileceği bir kurulum istiyorsun. Tunnel + Access bunu hub'ı açmadan sağlar; Tailscale Serve ise alan adı olmayanlar için varsayılan olarak kalır.
- **Bulut vektör araması (Vectorize, AI Search).** Şifreli veride arama yapamazlar, yani onları kullanmak yaşam verisini açık hâlde saklamak demek. Kişisel bir derlem küçüktür; yerel arama yeterince hızlı.

## Bunun sana maliyeti

- Bir yedekleme disiplini: zamanlanmış şifreli yedekler ve denenmiş bir geri yükleme ([Yedekler](../guides/backups.md)).
- Sürekli açık bir hub, zamanla bir Raspberry Pi ([Hub'ı Raspberry Pi'ye taşı](../guides/raspberry-pi.md)); o zamana kadar fişe takılı ve uyanık tutulan bir Mac.
- Hub kapalıyken Telegram'da "tau çevrimdışı" diye bir otomatik yanıt yok (Telegram güncellemeleri yaklaşık bir gün saklar; hub açıldığında aradaki farkı kapatır).
- Sıfıra yakın bulut maliyeti: Tunnel, Access ve R2'nin hepsinin tek bir kişiyi karşılayan ücretsiz katmanları var.
