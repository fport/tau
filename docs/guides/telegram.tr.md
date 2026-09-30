<!-- tr twin of guides/telegram.md, translated 2026-10-01 -->

# Telegram

Telegram, terminalden uzaktayken tau'yla konuştuğun kanal: telefonundan yazarsın, hub (tau'nun çalıştığı ev makinen) yanıt verir. Kanal, tau-core içindeki bir hub servisidir; yani `tau hub run` (ya da launchd/systemd servisi) her çalıştığında o da çalışır. Bu sayfa botun oluşturulmasını, sohbetini botla eşleştirmeyi (aranacak bir chat id yok), kanalı başlatmayı ve kanalın ne yaptığını anlatır.


## Hub neden kendisi yokluyor, neden arada bir sunucu yok

İlk tasarım Telegram'ı bir Cloudflare Worker'ı ve bir Durable Object üzerinden geçiriyordu. [ADR 0006](../adr/0006-private-first-topology.md) bundan vazgeçti: bir aktarıcı (relay) hem konuşmanı hem de onay yolunu herkese açık altyapıda tutardı; oradaki bir hata ya da sızan bir token evine kadar uzanırdı.

Bunun yerine hub, Telegram'ın `getUpdates` çağrısını kendisi, dışa doğru, bir döngü içinde yapar. Sonuçları:

- **Webhook yok, herkese açık URL yok, dışarıdan gelen bağlantıya açık port yok.** Hub yalnızca `api.telegram.org` adresine giden HTTPS istekleri yapar. Başlarken varsa webhook'u siler, çünkü bir webhook ayarlıyken Telegram `getUpdates` çağrısını reddeder.
- **Telegram ile hub arasındaki hiçbir şey bir onayı taklit edemez.** Bir butona basma, aynı poll üzerinden bir callback olarak gelir; hub bir şey yapmadan önce kimin, hangi sohbette bastığını ve isteğin hâlâ beklediğini kontrol eder.
- **Çevrimdışı olmak sorun değil.** Hub kapalıyken Telegram güncellemeleri yaklaşık bir gün saklar; hub başladığında aradaki farkı kapatır. "tau çevrimdışı" diye bir otomatik yanıt yoktur.
- **Hub üzerindeki bir chat id izin listesi**, senin dışındaki herkesin mesajını ajan görmeden düşürür. Yabancılar hiç yanıt almaz; bot hayatta olduğunu bile belli etmez.

## 1. Botu BotFather ile oluştur

1. Telegram'ı aç ve [@BotFather](https://t.me/botfather) ile bir sohbet başlat.
2. `/newbot` gönder.
3. Bir görünen ad (herhangi bir şey) ve bir kullanıcı adı ver: 5–32 karakter, `bot` ile bitmeli ve kullanılmıyor olmalı (örneğin `deniz_tau_bot`).
4. BotFather **token**'la yanıt verir; `110201543:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw` gibi bir dizge. Ona bir parola gibi davran.

Hazır oradayken önerilenler:

- `/setjoingroups` → botun → **Disable**. Kimse botu bir gruba ekleyemez; botun yalnızca senin doğrudan mesajlarına ihtiyacı var.
- Gizlilik modunu (`/setprivacy`) varsayılanında, açık bırak.
- İstersen daha hoş bir sohbet başlığı için `/setdescription` ve `/setuserpic`.

## 2. Sohbetini eşleştir

```sh
tau telegram pair
```

Komut BotFather'dan aldığın token'ı sorar (gizli; yapıştırırken hiçbir şey görünmez), Telegram'a doğrulatır ve tek kullanımlık bir kod gösterir:

```text
Token Telegram'a soruluyor...
Telegram botu @deniz_tau_bot olarak tanıyor.
TELEGRAM_BOT_TOKEN, ~/.tau/.env dosyasına yazıldı (izin 0600)
Telegram'da t.me/deniz_tau_bot adresini aç ve şunu gönder: /start K7QM-X2PA
Ya da tek dokunuşla: https://t.me/deniz_tau_bot?start=K7QM-X2PA
Kod bir kez ve 10 dakika geçerli (14:32 saatine kadar). Bekleniyor; Ctrl-C iptal eder.
Kodu çalışan hub alacak.
```

Telefonunda bağlantıya dokunup **Start**'a bas ya da botu açıp `/start K7QM-X2PA` mesajını kendin gönder. Bot "Eşleşme tamam" diye yanıt verir ve komut biter:

```text
Deniz @deniz ile eşleşildi. tau bundan sonra Telegram'da yalnızca bu sohbete yanıt verir.
```

Ne oldu:

- **Token**, `TELEGRAM_BOT_TOKEN` olarak `<TAU_HOME>/.env` dosyasına girdi. Yalnızca o satır eklenir ya da değiştirilir; dosyanın diğer satırları ve `0600` izni korunur. İstemde Enter'a basmak `.env` içindeki mevcut token'ı korur; yeniden eşleştirme böyle yapılır.
- **Sohbetin**, kanalın kontrol ettiği izin listesi olan `TELEGRAM_ALLOWED_CHAT_IDS` oldu. Yeniden eşleştirme listeyi değiştirir ve komut kaç sohbetin erişimini kaybettiğini söyler.
- **Kodu kim aldı.** Hub çalışıyorsa komut ondan (yerel kontrol API'sindeki imzalı `POST /telegram/reload` ile) `.env`'i ve kodu yeniden okumasını ister; kodu hub'ın kendi poll döngüsü kabul eder ve yeniden başlatma gerekmeden o andan itibaren yanıt verir. Hub yoksa komut Telegram'ı kendisi, hub'ın kaydettiği konumdan yoklar ve kodun gelir gelmez durur; böylece hub daha sonra kaldığı yerden başlar. Her iki durumda da botu tek bir süreç yoklar ve işin içinde senin makinen ile `api.telegram.org`'dan başka hiçbir şey yoktur.

Kodun kuralları:

- Birbirine benzeyen karakterler olmadan (`0`/`O`, `1`/`I`/`L` yok) 8 karakter; kriptografik bir rastgelelik kaynağından gelir; büyük/küçük harf ve tireler önemsenmez.
- 10 dakika geçerlidir ve bir kez çalışır. Komut beklerken yalnızca tuzlanmış bir özet (hash) olarak `TAU_DATA_DIR/telegram/pairing.json` içinde durur ve komut dururken onu siler; Ctrl-C kodu geri çeker.
- Yalnızca özel bir sohbet eşleşebilir, grup asla. Yanlış ya da süresi dolmuş bir kod, bir yabancının mesajı gibi yanıt almaz ve hiçbir şeyi değiştirmez. 10 yanlış koddan sonra kod çalışmaz olur.

`tau telegram status` bir token tanımlı mı (ve botun adı), bir sohbet eşleşmiş mi, bekleyen bir kod var mı ve hub'ın poller'ı ne yapıyor, bunları gösterir. Token'ı ya da bir chat id'yi asla yazmaz. Mac uygulamasının kurulum sihirbazı aynı komutu `--json` ile çalıştırır (bkz. [CLI başvurusu](../reference/cli.md#tau-telegram)).

!!! note "Sahip korumasıyla"
    Eşleşmiş bir sohbet tau ile [sahip korumasına](guard.md) takılmadan konuşur: izin listesi seni tanır. Bu yüzden korumalı bir Mac'te `tau telegram pair` yalnızca tau'nun kilidi açıkken çalışır (`tau guard verify`).

## 3. Ya da: chat id'yi elle ayarla

Elle yapılan yol; örneğin iki değerin `.env` satırları yerine spine'ın gizli değerleri olduğu [bulut modu](cloud-mode.md) için. Önce token'ı `<TAU_HOME>/.env` dosyasına koy (aşağıda), botunu Telegram'da aç, **Start**'a bas ve bir mesaj daha gönder. Sonra Bot API'den bekleyen güncellemeleri iste:

```sh
curl -s "https://api.telegram.org/bot<token>/getUpdates" | python3 -m json.tool
```

İlk `message` içinde `"chat": {"id": 123456789, ...}` kısmını ara. O sayı senin **chat id**'n. Özel bir sohbette bu, senin kendi Telegram kullanıcı id'ndir ve asla değişmez.

!!! tip "İpucu"
    Boş bir `"result": []`, mesajın henüz gelmediği ya da botun başlatılmadığı anlamına gelir. Sohbette **Start**'a bas, bir mesaj daha gönder ve yeniden sor. Bunu hub'ın Telegram kanalı çalışmadan önce yap: kanal poll yapmaya başladığında güncellemeleri kendisi alır.

İki değer de hem gizli hem kişisel; `<TAU_HOME>/.env` dosyasına girerler, başka hiçbir yere değil:

```sh
TELEGRAM_BOT_TOKEN=110201543:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw
TELEGRAM_ALLOWED_CHAT_IDS=123456789
```

`TELEGRAM_ALLOWED_CHAT_IDS` virgülle ayrılmış birden fazla id alır; yalnızca sen kullanıyorsan bir tanesi yeter. `tau init`'in yazdığı `.env.example` iki adı da zaten listeler, böylece `tau doctor` onlar hakkında sessiz kalır. Zaten çalışan bir hub dosyayı bir sonraki başlangıcında yeniden okur (`tau hub stop`, ardından `tau hub run`).

## 4. Başlat

Hub çalışırken eşleştirdiysen zaten yanıt veriyor. Değilse:

```sh
tau doctor        # ok   telegram: configured (1 allowed chat); polls while the hub runs
tau hub run       # or `tau hub install` for the launchd service
```

İsteğe bağlı ayarlar `tau.toml` içinde:

```toml
[component.telegram]
poll_timeout_seconds = 50    # how long one getUpdates waits on Telegram's side
backoff_max_seconds = 60     # cap of the backoff after network errors
approval_timeout_seconds = 300   # an unanswered approval counts as "not approved"
```

Botuna yaz. Yanıt hub'dan gelir ve `tau doctor` artık `polling as @your_bot` gösterir. `curl -s http://127.0.0.1:7877/status` çıktısında poller durumunu (`polling`, `retrying`, `failed`), son poll zamanını, son hatayı ve kaç güncellemenin işlenip kaçının düşürüldüğünü içeren bir `telegram` anahtarı bulunur. Token'ı ya da bir chat id'yi asla göstermez.

Token yoksa ya da izin verilen bir sohbet ve bekleyen bir eşleşme kodu yoksa kanal boşta başlar ve tek satırlık bir log yazar; hub her iki durumda da çalışmaya devam eder. `tau telegram pair`'in bir kodu beklerken `/status` ayrıca `pairing: true` der.

## 5. Kanal ne yapar

- **Metin girer, metin çıkar.** Mesajın, `channel = "telegram"` etiketli bir oturumda bir tura dönüşür; yanıt aynı sohbete geri gönderilir, modelin Markdown'ından (kalın, kod, bağlantılar) biçimlendirilir ve Telegram'ın 4096 karakter sınırını aşarsa bölünür. tau düşünürken "typing…" görünür. Fotoğraflar, sesli notlar ve çıkartmalar kısa bir "şimdilik yalnızca metin" notu alır.
- **Konuşman yeniden başlatmalardan sağ çıkar.** Her sohbet, hub yeniden başlasa da mevcut oturumunu korur (`TAU_DATA_DIR/telegram/chats.json`). Poll konumu (`offset`) ve hâlâ üzerinde çalışılan mesajlar (`inflight.json`) değiştikçe kaydedilir; böylece bir yeniden başlatma ne bir mesajı iki kez yanıtlar ne de birini atlar. Turu bir durdurmayla yarıda kesilen mesaj yeniden çalışır.
- **Slash komutları.** `/help`, `/tools`, `/sessions`, `/resume`, `/new`, `/session`, `/status`, `/model`, `/compact` ve `/lang`, terminaldeki gibi, aynı ifadelerle ve Türkçe takma adlarıyla çalışır. Hub başlarken bunları botun komut menüsü olarak kaydeder (`setMyCommands`); böylece Telegram'da `/` yazınca komutlar, yardım metinleriyle birlikte arayüz dilinde listelenir. Menü yalnızca senin sohbetin için ayarlanır, dolayısıyla botu açan yabancılar hiçbirini görmez. Bkz. [Slash komutları](../reference/slash-commands.md#on-telegram).
- **Ağ sorunları.** Bağlantı koptuğunda poller bekleme süresini artırarak (1 sn, 2 sn, 4 sn, … bir dakikaya kadar) yeniden bağlanır; hub ayakta kalır. Bot API'nin reddettiği bir token, poller'ı bir sonraki hub başlangıcına kadar durdurur (`tau doctor`, `fail` gösterir).
- **Satır içi butonlarla onaylar.** Tier-2 bir çağrı (fiziksel bir eylem ya da tau'nun yazdığı bir aracı etkinleştirmek; her zaman onay isteyen izin seviyesi) aracı, argümanlarını ve etkisini içeren bir mesaj ile arayüz dilinde etiketlenmiş iki buton gönderir: **Approve** ve **Reject**. Approve aracı bir kez çalıştırır; Reject ya da beş dakika içinde yanıt gelmemesi (`approval_timeout_seconds`) "onaylanmadı" sayılır ve tau bunu sana söyler. Ardından mesaj sonucu gösterecek şekilde düzenlenir ve butonlarını kaybeder. Yalnızca senin (id'n `TELEGRAM_ALLOWED_CHAT_IDS` içinde) hâlâ bekleyen bir isteğe basman sayılır; geri kalan her şey yok sayılır ve loglanır. Bir onay beklerken gönderdiğin mesajlar ondan sonra yanıtlanır. Bir onay beklerken hub yeniden başlarsa istek iptal edilir ve yeniden başlatmadan sonra tekrar sorulur.

Planlananlar:
- **Açılış durum raporu** (issue 015). Hub başladığında ya da yeniden başladığında kısa bir mesaj gönderir: sürüm, profil, varsa son çökme.
- **Sesli notlar** (issue 026); bir bulut konuşma API'siyle değil, **hub üzerinde** yazıya dökülür. Bkz. [Ses](voice.md).

## Güvenlik notları

- Bot token'ı, sahibinin bota gönderdiğin mesajları okumasına ve bot olarak yanıt vermesine izin verir. Hub'a, onun dosyalarına ya da onay yoluna erişmez. Bir sızıntıdan şüphelenirsen BotFather'da `/revoke` ile yenile ve `.env` dosyasını güncelle.
- Herkes bir botu kullanıcı adıyla bulup ona mesaj atabilir; yabancıları ajanından uzak tutan şey izin listesidir. Oraya asla başka birinin chat id'sini koyma.
- Eşleştirme, terminalinin gösterdiği kodu ister. Kod bir kez kullanıldıktan ya da 10 dakika geçtikten sonra işe yaramaz, yanlış bir kod asla yanıt almaz ve bot tahmin eden bir yabancıya hiçbir şeyi doğrulamaz.
- Kimlik bilgileri asla Telegram'dan ayarlanmaz: yapılandırmayı düzenleyen komutlar bu kanalda kullanılamadıklarını söyler.
- Telegram'dan gelen metin, her şey gibi, ajan için güvenilmeyen girdidir. Yazma işlemlerinin tier 2 ya da sandbox içinde olmasının ve onayların asla modelden gelmemesinin nedeni bu.
