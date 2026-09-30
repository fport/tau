<!-- tr twin of guides/guard.md, translated 2026-09-30 -->

# Sahip koruması

Sahip koruması (owner guard), tau'nun yalnızca senin için çalışmasını sağlar. Kurduktan sonra `tau tui`, `tau chat` ve tau Desktop **kilitli** açılır. Mac'in yerleşik kamerası yüzünü gördüğünde ve başını ekranın istediği yöne çevirdiğinde kilit açılır. tau, sen yanından ayrıldığında, ekran kilitlendiğinde, Mac uyuduğunda ve sekiz saat sonra kendiliğinden yeniden kilitlenir. Tier-2 bir eylem (fiziksel dünyaya dokunan, her zaman onay isteyen eylem) çalışmadan önce onu her zamanki gibi onaylarsın; ardından koruma yüzünü bir kez daha kontrol eder (bir **step-up**, yani ek kimlik kontrolü).

Koruma hub'ın (tau'nun çalıştığı, sana ait makine) içinde çalışır; ne bir modele ne de internete ihtiyaç duyar. Yüz şablonun Mac'ten asla çıkmaz ve veri klasörünün bir kopyası ya da bir yedek onu okuyamaz. Karar ve tüm tehdit modeli [ADR 0008](../adr/0008-owner-guard.md)'de. Her anahtar, route ve kayıt alanı [koruma referansında](../reference/guard.md) listelenir.

!!! info "Henüz olmayanlar"
    - **Touch ID yedek yoldur.** İki başarısız yüz kontrolünden sonra ya da kamera kullanılamadığında kilit ekranı Touch ID'yi önerir: `tau tui`'de `t`'ye bas, `tau chat`'in `kilitli>` isteminde `t` yazıp Enter'a bas. macOS isteği Mac'in ekranında çıkar. `step_up` da Touch ID isteyebilir (`face_or_touch_id` ya da `touch_id`). Touch ID kayıt sırasında parmak izi setini sabitler: Sistem Ayarları'nda parmak ekler ya da silersen Touch ID'nin yeniden kabul edilmesi için `tau guard enroll --add` çalıştır.
    - **Uzaktan kilit açma:** SSH ya da mosh üzerinden bir TUI, yalnızca Mac'in başında kilidi açtığın sürece çalışır. Telegram'dan verilen telefon izinleri issue 117 ile geliyor.
    - Koruma altında **ses** issue 118 ve 119 ile geliyor.

## Sade sözlerle ne yapar { #what-it-does-in-plain-words }

- **Bir kapı, gözcü değil.** Kamera yalnızca bir kontrol sürerken, birkaç saniyeliğine açıktır. Kontroller arasında koruma klavye ve fare boşta kalma süresine, ekran kilidine ve arada bir yapılan kısa bir yeniden kontrole dayanır.
- **Yalnızca tau'nun kendi pencereleri için.** Koruma TUI'yi (Terminal'de, SSH üzerinden, tau Desktop'ta ya da bir web sekmesinde), `tau chat`'i ve ileride sesi kapsar. Bunlar **korunan kanallar**dır. Telegram ve başka tau'lardan gelen mesajlar başka yollarla tanınır (chat id'in, bir kişinin anahtarı); bu yüzden Mac kilitliyken de çalışmaya devam ederler. Bunlar **tanınan kanallar**dır.
- **Yalnızca daraltır.** Koruma bir turu ya da bir eylemi reddedebilir. Asla onaylayamaz: tier-2 bir eylem hâlâ senin evetini ister, step-up bunun üstüne gelir.
- **Kapalı başarısız olur.** Çalışan bir hub olmaması, bozuk bir ayar ya da okunamayan bir şablon hep "kilitli" demektir, asla "açık" değil.

## Neye ihtiyacın var { #what-you-need }

- Yerleşik kamerası olan bir Mac. Koruma yalnızca macOS'ta çalışır ve yalnızca yerleşik kamerayı kullanır: Continuity Camera (bir iPhone) ve sanal kameralar asla seçilmez.
- Kurulu `tau-guard`. Bir checkout'ta `uv sync --all-packages` sonrasında vardır. PyPI'dan, bir sürüm onu içerdiğinde (`tau-guard`, `tau-core` ve `tau-tui` ile birlikte yayımlanır):

    ```sh
    uv tool install tau-core --with tau-tui --with tau-guard
    ```

- Koruma servisini çalıştıran bir hub. [TauBar](taubar.md)'ın **Run the hub** seçeneği en iyisidir, çünkü o zaman kamera iznini TauBar tutar. Bir terminalde `tau hub run` de çalışır; o zaman izni o terminal uygulaması tutar. Bkz. [tau'yu servis olarak çalıştır](hub-service.md).
- Bir kerelik yaklaşık 40 MB indirme: yüz tanıma modeli (SFace). Sonrasında internet gerekmez.
- Mac'in başında sen. `tau guard setup`, `enroll` ve `forget` SSH üzerinden çalışmayı reddeder.

## Kurulum { #set-it-up }

1. **Hub'ı başlat.** TauBar'da **Run the hub**'ı işaretle ya da bir terminalde `uv run tau hub run` çalıştır.
2. **Ön koşulları denetle:**

    ```sh
    uv run tau guard doctor
    ```

    Platformu, worker'ı, OpenCV'yi, iki yüz modelini, kaydı, şablonu, Keychain anahtarını, kamerayı ve iznini, hub'ın kamera iznini hangi uygulamanın tuttuğunu denetler. Kurulumdan önce `enrollment` bir uyarı, `sface` modeli de bir hatadır, çünkü kurulum onu indirir. Bu beklenen bir durumdur.

3. **Kurulumu Mac'in başında çalıştır:**

    ```sh
    uv run tau guard setup
    ```

    Sırayla dört şey yapar ve ilk başarısız olanda durur:

    - **SFace'i indirir:** tek bir OpenCV Zoo commit'ine sabitlenmiş bir adresten indirir ve sha256'sını denetler. Çevrimdışıysan dosyayı kendin ver: `tau guard setup --model-file ~/Downloads/face_recognition_sface_2021dec.onnx`. Dosya aynı sha256 ile denetlenir.
    - **Yüzünü kaydeder.** macOS önce Touch ID ya da Mac parolanı, bu uygulamanın daha önce hiç izni olmadıysa kamera erişimini ister. Sonra 15-20 saniye ipuçlarını izle: kameraya bak, sola dön, sağa dön, başını hafifçe kaldır, hafifçe indir. Normal ışıkta, yaklaşık bir kol boyu uzakta ve görüntüde yalnız otur.
    - **Bir kontrol çalıştırır,** tam bir kilit açma gibi: kameraya bak, sonra iki baş çevirme.
    - **Korumayı açar:** `tau.toml`'a `[component.guard] enabled = true` yazar. `TAU_DATA_DIR/guard/` içindeki kayıt işareti, bu satır daha sonra silinse bile korumayı açık tutar.

    Sonunda, sen Mac'in başında değilken uzaktan kullanımın (SSH, mosh) duracağı konusunda uyarır.

4. **Hub'ı yeniden başlat** (TauBar: **Run the hub** işaretini kaldırıp yeniden koy; ya da `tau hub run`'ı durdurup yeniden başlat) ve açık her `tau chat`, `tau tui` ya da tau Desktop penceresini kapat. Koruma bir sonraki hub ile, kilitli olarak başlar.
5. **Bir kez kilidi aç.** `uv run tau tui`'yi aç ve kilit ekranında Enter'a bas. Hub TauBar altında çalışıyorsa macOS şimdi **TauBar**'ın kamerayı kullanıp kullanamayacağını sorar. İzin ver. Nedeni bir sonraki bölümde.
6. **Denetle:**

    ```sh
    uv run tau guard status    # hub'ın bildirdiği durum
    uv run tau doctor          # guard satırı: active; the hub reports it unlocked
    ```

## Kamera izni: TauBar ya da terminal { #the-camera-permission-taubar-or-the-terminal }

macOS kamerayı bir programa değil, bir uygulamaya verir. Korumanın kontrolleri hub'ın başlattığı küçük bir worker'da çalışır; bu yüzden izin **hub'ı hangi uygulama başlattıysa** ona aittir:

| Hub nasıl çalışıyor | Kamera iznini kim tutar |
|---|---|
| TauBar'ın **Run the hub** seçeneği (önerilen) | TauBar |
| Terminal, iTerm ya da başka bir terminalde `uv run tau hub run` | o terminal uygulaması |
| TauBar'ın `bun run tauri dev` ile çalıştırılması | onu çalıştıran terminal |
| `com.tau.hub` launchd agent'ı ya da SSH üzerinden veya ayrılmış bir tmux'ta başlatılan hub | kimse; kamera reddedilir |

- `tau guard setup` sırasında henüz korumalı bir hub çalışmıyorsa kontrol yerel bir worker'da çalışır; bu yüzden kamerayı **terminalin** de ister. Bu izin TauBar'ınkinden ayrıdır; ilk kilit açmanın yeniden sormasının nedeni budur.
- İzin System Settings → Privacy & Security → **Camera** altında durur. Hub kameranın reddedildiğini bildirdiğinde TauBar menüsünde **Grant camera access…** görünür.
- TauBar'ı sabit bir imza kimliğiyle derle. Ad hoc imzalı bir derleme her yeniden derlemeden sonra macOS için yeni bir uygulamadır ve izin her seferinde kaybolur. [TauBar README](https://github.com/fport/tau/blob/main/apps/taubar/README.md#a-stable-signing-identity-for-the-camera-grant) adım adım anlatır.
- tau Desktop kameraya hiç ihtiyaç duymaz. `tau tui`'yi çalıştırır; kontrol yine hub'da yapılır.

## Günlük kullanım { #daily-use }

### `tau tui` ve tau Desktop'ta

TUI opak bir kilit ekranıyla açılır; oturumlarından hiçbir şey arkadan görünmez.

- Boş satırda **Enter** bir kontrol başlatır. Kameraya bak, sonra istemleri izle ("Turn your head left.", "Look straight at the camera again."). Her istem sana 3,5 saniye verir.
- **Esc** süren bir kontrolü iptal eder, **ctrl+q** çıkar. tau kilitliyken yalnızca `/help`, `/lang`, `/guard` ve `/quit` çalışır. Yazdığın diğer her şey gönderilmez ve alanda kalır.
- Başarılı bir kontrolden sonra `Unlocked (face). Failed attempts since the last unlock: 0.` görürsün. 0'dan büyük bir sayı, sen yokken birinin ya da bir şeyin denediği anlamına gelir. `tau guard log` ne zaman olduğunu gösterir.

tau Desktop penceresinde aynı `tau tui`'yi çalıştırır, bu yüzden aynı kilit ekranını gösterir. Bir web sekmesi (issue 074) de gösterecek.

### `tau chat`'te

`tau chat` ekranı ve kaydırma geçmişini temizler, sonra bir `locked> ` istemi gösterir. Kontrolü başlatmak için Enter'a bas. Sınamanın her adımı geldikçe yazılır.

### tau'yu ne kilitler { #what-locks-tau }

| Tetikleyici | Ne zaman |
|---|---|
| Boşta kalma | `idle_lock_minutes` (10) boyunca klavye ya da fare girdisi yok |
| Ekran kilidi | Mac'in ekranı kilitlenir |
| Uyku | Mac uyudu |
| Azami süre | kilit açıldıktan `max_unlock_hours` (8) sonra, ne yaparsan yap |
| Komut | TUI'de ya da `tau chat`'te `/guard lock`, `tau guard lock`, TauBar'ın **Lock now** seçeneği |
| Telegram | Telegram sohbetinden `/guard lock` |
| Başarısız step-up | bir step-up başka bir yüz, bir sahtecilik ya da iki yüz gördü |
| Hub başlangıcı | her hub başlangıcı kilitli başlar; açık bir kilit asla geri yüklenmez |

Bir kilit süren turu iptal eder ("tau locked; the turn was stopped."), açık bir onay penceresini reddeder ve kilit ekranını hemen geri getirir.

### Varlık yeniden kontrolleri { #presence-rechecks }

Az önce yanından ayrıldığın bir Mac'e oturan herkes yazabilir ve yazmak boşta kalma sayacını sıfırlar. Bu yüzden yüzünün son görülmesinden bu yana 3 dakika boşta kalındıysa ya da son yüz eşleşmesinin üzerinden 30 dakika geçtiyse, bir sonraki mesajın önce "Checking that it is still you…" gösterir. Bu, baş çevirme olmadan yaklaşık bir saniyelik sessiz bir kontroldür. Yüzünü görürse mesaj devam eder. Başka birinin yüzünü görürse tau kilitlenir. Mesaj gönderilmediyse yeniden gönder.

### Tier-2 bir eylemden önceki step-up { #the-step-up-before-a-tier-2-action }

tau fiziksel ya da dışa dönük bir şey yapmak istediğinde onu her zamanki gibi onaylarsın. Sonra koruma "Confirm it is you: look at the camera." diye sorar ve üç baş çevirme istemi verir. Baş çevirmeleri geçen bir kontrolden sonraki 2 dakika içinde step-up bunun yerine sessiz bir eşleşmedir; böylece art arda üç eylem dokuz baş çevirmeye mal olmaz. Step-up başarısız olursa eylem çalışmaz; başka bir yüz, iki yüz ya da bir sahtecilik gören bir kontrol tau'yu kilitler.

### Bekleme süresi { #cooldown }

10 dakika içinde üç başarısız kontrol (eşleşmeyen bir yüz, başarısız bir baş çevirme sınaması, birden fazla yüz) 30 saniyelik bir bekleme süresi başlatır; bu süre sonraki her başarısızlıkta ikiye katlanır, en fazla 15 dakikaya kadar. Bu sırada yapılan kontroller "Too many failed attempts. Wait a moment, then try again." yanıtını verir. Karanlık bir oda ya da görünmeyen bir yüz sayılmaz; iptal edilen bir kontrol de sayılmaz, meğer ki iptal ettiğinde bir baş çevirme istemi ekranda olsun. Sayım hub yeniden başlasa da korunur.

### Komutlar { #commands }

| Nerede | Komut | Ne yapar |
|---|---|---|
| TUI, `tau chat` | `/guard` | korumanın durumu |
| TUI, `tau chat` | `/guard lock` | hemen kilitle |
| TUI, `tau chat` | `/guard unlock` | kilitliyken bir kontrol başlat (kilit ekranında Enter ile aynı) |
| terminal | `tau guard status` | hub'ın bildirdiği durum |
| terminal | `tau guard lock` | hemen kilitle |
| terminal | `tau guard log --since 2h` | denetim kaydı: kontroller, kilitler, bekleme süreleri |
| TauBar | **Lock now** | hemen kilitle; TauBar kilidi asla açmaz |

## Telegram'dan kilitleme { #locking-from-telegram }

Telegram sohbetin senin uzaktan acil durdurma düğmendir:

- `/guard` durumu gösterir, örneğin `Guard: locked · locked after inactivity`.
- `/guard lock` korunan her kanalı bir anda, `telegram` tetikleyicisiyle kilitler.
- `/guard unlock` yalnızca kilidin Mac'in başında açıldığını söyler.

Mac kilitliyken Telegram yanıt vermeyi sürdürür, çünkü chat-id izin listesi seni tanır. Aynı Mac'te **Telegram Desktop** oturumu açıksa, Mac'in başındaki herkes onun üzerinden tau'ya yazabilir. Bu korumanın kabul ettiği bir risktir; bu yüzden Telegram Desktop'ta yerel bir parola ayarla (Settings → Privacy and Security → Local Passcode).

## Mac'ten uzakken ve bulut modu { #away-from-the-mac-and-cloud-mode }

- SSH ya da mosh üzerinden bir TUI ya da `tau chat` Mac'in kilit durumunu paylaşır: Mac'in başında kilidi açtığın sürece çalışır, yoksa kilitlidir. Telefondan kilit açma issue 117 ile geliyor.
- **Bulut modunda koruma yoktur.** Bir Cloudflare Container'ının kamerası ve Keychain'i yoktur. Orada yalnızca Telegram ve ağ turları çalışır; ikisi de tanınan kanallardır, bu yüzden hiçbir şey kilitlenmez. `tau cloud push` ile gönderdiğin `tau.toml` `[component.guard] enabled = true` içeriyorsa, container'ın koruması yalnızca kalıcı olarak kilitli olur (`unsupported_platform`) ve tanınan kanallar bunu yok sayar. Kayıt işareti ve şablon `TAU_DATA_DIR/guard/` altında durur ve asla gönderilmez.

## Dürüst sınırlar { #honest-limits }

Kızılötesi bir kamera olmadan 2B bir web kamerası kontrolü bir kasa değil, bir varlık ve kolaylık etkenidir.

**Neyi durdurur:**

- kilidi açık Mac'inde tau'nun pencerelerini kullanan bir ev arkadaşını ya da misafiri;
- kameraya tutulan basılı bir fotoğrafı ya da telefondaki durağan bir resmi (düz bir resim baş çevirmeleri geçemez);
- hub'ın kontrol route'larını çağıran herhangi bir yerel programı ya da web sayfasını (`/health` ve `/status` dışındaki her route imzalı bir istek ister);
- korumayı kapatmaya çalışan enjekte edilmiş metni (hiçbir araç ya da route bunu yapamaz);
- şablonunu veri klasörünün bir kopyasından ya da bir yedekten okumaya çalışan birini (anahtarı Keychain'de duran bir şifreyle korunur).

**Neyi durdurmaz:**

- **hesabında kabuğu (shell) olan herkesi.** `tau.toml`'u düzenleyebilir, `.env`'i okuyabilir ya da tau'yu korumasız başlatabilirler. Hesabı Mac'in ekran kilidi ve FileVault korur; koruma tau'nun pencerelerini korur;
- gerçek zamanlı bir deepfake'i, 3B bir maskeyi ya da tek yumurta ikizini. Yakın akrabalar da yabancılardan daha yüksek puan alır;
- başını çevirdiğin iyi bir döngüsel videoyu. Doğal baş çevirmelerin sentetik klipleri denemelerde iki adımlı kilit açma kontrollerinin yüzde 4-16'sını (üç adımlı step-up'ların yüzde 1-7'sini) geçti; bekleme süresi denemeleri saatte yaklaşık ona sınırlar;
- seni kameraya bakmaya zorlayan birini.

Bu yüzden koruma her zaman yalnızca kendi onayına **ek olarak** istenir, asla onun yerine değil.

**Mac'te kalanlar:** şablon (`owner.face.v1.bin`, AES-GCM ile şifreli, anahtarı macOS Keychain'de), denetim kaydı (görüntü yok, embedding yok, başka insanlar hakkında hiçbir şey yok) ve model dosyaları. Kamera kareleri yalnızca bir kontrol süresince worker'ın belleğinde bulunur; görüntüdeki başka biri dahil hiçbir şey kaydedilmez. `TAU_DATA_DIR/guard/` yedeklere girmez.

## Kilitli mi kaldın? { #locked-out }

**Kamera reddedildi ya da hiç sorulmadı.** System Settings'in Camera bölmesini aç ve hub'ı çalıştıran uygulamayı (TauBar ya da terminalin) etkinleştir:

```sh
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera"
```

TauBar'ın **Grant camera access…** seçeneği aynı bölmeyi açar. macOS'un en baştan yeniden sormasını istersen izni sıfırla ve hub'ı TauBar'dan yeniden başlat (**Run the hub** işaretini kaldırıp yeniden koy):

```sh
tccutil reset Camera com.tau.taubar     # TauBar's bundle id
tccutil reset Camera com.apple.Terminal # if Terminal runs the hub instead
```

**Bir şeyler ters ve ne olduğunu bilmiyorsun.** Doctor'ı çalıştır. Başarısız parçayı ve hub'ın kamera iznini tutan uygulamayı söyler:

```sh
uv run tau guard doctor
uv run tau doctor          # guard satırı hub'ın korumayı çalıştırıp çalıştırmadığını söyler
```

**"The guard cannot be reached."** Hiçbir hub çalışmıyor ya da koruma servisi olmadan çalışıyor. Başlat (TauBar → Run the hub ya da `tau hub run`) ve `tau.toml`'daki `[components.hub] services` listesinin boş olduğunu ya da `guard` içerdiğini denetle.

**Seni tanımıyor.** Daha iyi ışık dene, kameraya dön, şapkanı çıkar. `tau guard verify --explain` her karenin sayılarını (yüzler, dedektör puanı, göz mesafesi, parlaklık, netlik, baş dönüşü, benzerlik) hiçbir kareyi kaydetmeden yazar. Sonra başarısız olan ışıkta örnek ekle: `tau guard enroll --add`. Yüz modeli değiştiyse `tau guard enroll` ile yeniden kaydol.

**Çok fazla başarısız deneme.** Bekle. `tau guard status` bekleme süresinin ne zamana kadar sürdüğünü gösterir.

**Tamamen kaldırmak istiyorsun.** Mac'in başında:

```sh
uv run tau guard forget
```

Touch ID ister (Mac parolanı yalnızca Touch ID'siz bir Mac'te), sonra şablonu, kayıt işaretini ve Keychain anahtarını siler ve `[component.guard] enabled = false` yazar. Hub'ı ve açık her tau penceresini yeniden başlat; koruma kapanır. Keychain'in anahtarı tuttuğunu söylerse yeniden çalıştır. `tau guard setup` her şeyi en baştan yeniden kurar.
