<!-- tr twin of getting-started/install.md, translated 2026-09-30, updated 2026-10-01 -->

# Kurulum

tau bir Python paketleri kümesidir. `tau-core` ajanı ve `tau` komutunu barındırır; `tau-tui` ise Textual arayüzünü ekler. Onları bir kez kurarsın, `tau init` ile bir yapılandırma kökü oluşturursun, `tau doctor` ile kontrol edersin ve konuşmaya başlarsın.

İki giriş kapısı bunların hepsini senin yerine yapar, sonra seçtiğin özellikleri kurar: **Mac uygulaması** ve **tek satırlık kurucu**. İkisi de aynı motoru, `tau setup`'ı çalıştırır ([ADR 0014](../adr/0014-one-installer-and-onboarding.md)). Bu sayfanın geri kalanı elle kurulumu adım adım anlatır.

## Mac uygulaması { #the-mac-app }

macOS 13 ya da sonrası olan, Apple silicon ya da Intel işlemcili bir Mac'te:

1. `tau.dmg` dosyasını [tau.getporti.com/tr/download](https://tau.getporti.com/tr/download) adresinden indir, aç ve **tau**'yu **Uygulamalar** klasörüne sürükle.
2. tau'yu aç. macOS ilk seferde tau'yu kötü amaçlı yazılım açısından denetleyemediğini söyler: uygulama imzalı ama henüz Apple'ın noter onayından geçmedi, yani bu beklenen bir durum. **Sistem Ayarları → Gizlilik ve Güvenlik**'i aç, tau ile ilgili satırın yanındaki **Yine de Aç**'ı seç ve onayla. macOS 13 ve 14'te tau'ya sağ tıklayıp **Aç**'ı seçmek de aynı işi görür.
3. İlk açılış kurulum sihirbazını açar: dil, tau'nun kurulumu (uv ile, ev klasörüne, yönetici parolası olmadan), model anahtarın, senin hakkında birkaç satır, özellikler, onların gerektirdiği macOS izinleri, her özelliğin adımları ve bir özet. Her adım atlanabilir; menüdeki **Set up tau…** sihirbazı yeniden açar.

Uygulama menü çubuğuna bir **τ** koyar, hub'ı çalıştırır ve içinde `tau tui` çalışan sohbet pencereleri açar. [Uygulama rehberi](../guides/taubar.md#first-launch) sihirbazı adım adım anlatır.

## Tek satırlık kurucu { #the-one-line-installer }

macOS ve Linux'ta, Raspberry Pi dahil, tek bir komut tau'yu kurar ve ne istediğini sorar:

```sh
curl -fsSL https://tau.getporti.com/install.sh | sh
```

[uv](https://docs.astral.sh/uv/) yoksa önce onu, sonra `uv tool install tau-core --with tau-tui` ile tau'yu kurar ve `tau setup`'ı başlatır. Hiçbir zaman `sudo` çalıştırmaz.

- **Önce oku:** `curl -fsSL https://tau.getporti.com/install.sh | less`.
- **Yalnızca kur:** `curl -fsSL https://tau.getporti.com/install.sh | TAU_INSTALL_NO_SETUP=1 sh`, sonra `tau setup`'ı kendin çalıştır.
- **Belirli bir sürüm:** aynı yerde `TAU_INSTALL_VERSION=x.y.z`.

## `tau setup` { #tau-setup }

İki kapının arkasındaki sihirbaz, terminalde:

```sh
tau setup                 # kontrol listesi, sonra kurulum ve ayarlar
tau setup run telegram    # tek bir özelliğin adımları, sonradan istediğin zaman
tau setup --remove guard  # bir özelliğin paketini kaldır; ayarlar ve veriler kalır
tau setup --upgrade       # en yeni sürümler
```

- **Kontrol listesi.** Terminal arayüzü, tau uygulaması, sub-tau'lar, Telegram, uzaktan erişim, sahip koruması, tau ağı, oturum açılınca başlatma ve bulut modu. İlk çalıştırmada platformunun varsayılanları işaretlidir; zaten kurulu olanlar `✓` ile gösterilir ve bir daha sorulmaz.
- **Kurulum.** Seçilen özelliklerin paketleri, çalışan tau-core'a sabitlenmiş tek bir komutla kurulur.
- **Ayarlar.** `tau init` (sağlayıcı ve anahtarı, [aşağıda](#create-a-configuration-root)), `persona/user.md` için kısa bir "senin hakkında", her özelliğin adımları ve `tau doctor`. Her adım önce sorar ve atlanabilir. Yönetici parolası gerektiren bir adım o tek komutu gösterir ve senin çalıştırmanı bekler; tau asla `sudo` çalıştırmaz.

[Kurulum özellikleri](../guides/setup-features.md) her özelliği anlatır: neye ihtiyaç duyduğunu, neyi değiştirdiğini ve nasıl kaldırılacağını. [`tau setup` başvurusu](../reference/setup.md) her seçeneği içerir.

## Elle { #by-hand }

Aşağıdaki her şey sihirbazın yaptığının adım adım hâlidir: gereksinimler, paketler, yapılandırma kökü, kontrol ve ilk konuşma.

## Gereksinimler

- **Python 3.12 veya daha yenisi.** Daha eskisi çalışmaz; paketler `requires-python = ">=3.12"` bildirir.
- **[uv](https://docs.astral.sh/uv/)**, tau'nun çalışma alanının (workspace) üzerine kurulduğu Python paket yöneticisi. Hiç Python'un yoksa kendi Python'unu kurar.
- macOS ya da Linux. Hub (tau'nun çalıştığı, sana ait makine) bugün bir MacBook'ta, ileride bir Raspberry Pi 5'te çalışacak; aynı kod ikisinde de çalışır.
- Bir model sağlayıcısı ya da hiçbiri. tau, hiçbir hesap olmadan her şeyi deneyebilmen için senaryolu bir `fake` sağlayıcıyla gelir. Gerçek yanıtlar için Anthropic, OpenAI ya da Google Gemini'den bir API anahtarı veya [Ollama](https://ollama.com) üzerinden yerel bir model gerekir (bkz. [İlk çalıştırma](first-run.md)). tau sağlayıcıyı doğrudan çağırır ve rol başına harcama üst sınırını kendisi uygular; bu yüzden yanında başka hiçbir şeyin çalışması gerekmez ([Modeller ve bütçeler](../guides/models-and-budgets.md)).

=== "macOS"

    ```sh
    brew install uv
    uv python install 3.12
    ```

=== "Linux"

    ```sh
    curl -LsSf https://astral.sh/uv/install.sh | sh
    uv python install 3.12
    ```

!!! tip "İpucu"
    `uv python install 3.12` isteğe bağlıdır. Bir proje ihtiyaç duyduğunda `uv` uygun bir yorumlayıcıyı kendiliğinden indirir.

## Paketleri kur

!!! note "Bunun yerine depodan"
    Katkıda bulunanlar ve henüz yayımlanmamış `main` dalını isteyen herkes uv
    çalışma alanından kurar ve her komutu `uv run` üzerinden çalıştırır:

    ```sh
    git clone https://github.com/fport/tau.git
    cd tau
    uv sync --all-packages --group dev
    uv run tau --help
    ```

    Aşağıdaki her şey aynen geçerli; checkout'un (deponun yerel kopyası) içindeyken `tau …` komutlarını `uv run tau …` olarak oku. Depo kökünde bir `tau.toml` bulunur, yani başka bir yerde `tau init` çalıştırana kadar orası aynı zamanda yapılandırma köküdür. O dosya `brain` ve `fast` rollerini bütçeleriyle Anthropic'e, `local` rolünü de Ollama'ya koyar; bu yüzden checkout'un `.env` dosyasında `ANTHROPIC_API_KEY` gerekir. Başka bir sağlayıcı kullanıyorsan `tau init`'in o sağlayıcı için yazdığı bir kök kullan.

Elle kurulum, `tau`'yu TUI, ağ (`tau-net`) ve sub-tau'lar (`tau-sub`) dahil olarak `PATH`'ine koyan tek bir `uv tool` komutudur:

```sh
uv tool install tau-core --with tau-tui --with tau-net --with tau-sub
tau --help
```

`uv tool install`, tau'yu kendi sanal ortamında tutar ve sistem Python'una asla dokunmaz. Sonradan `tau setup --upgrade` ile yükselt. `tau setup` henüz bir şey kurmadıysa `uv tool upgrade tau-core` de çalışır: `tau setup` paketleri tek bir sürüme sabitler.

## Bir yapılandırma kökü oluştur { #create-a-configuration-root }

`tau init`, tau'nun ihtiyaç duyduğu dosyaları bir **yapılandırma köküne**, varsayılan olarak `~/.tau` dizinine yazar:

```sh
tau init
```

Arayüz dilini (`en` ya da `tr`) sorar. Ortamda ya da `~/.tau/.env` içinde model anahtarı bulamazsa hangi sağlayıcıyı kullandığını (`anthropic`, `openai` ya da `gemini`) ve o sağlayıcının anahtarını sorar; anahtar gizli yazılır. Anahtarı sağlayıcıya tek bir küçük istekle dener (model listesi; ücretsizdir) ve `~/.tau/.env` dosyasına yazar, dosyanın iznini `0600` tutar:

```text
UI language (en, tr) [en]: tr
Ortamda ya da ~/.tau/.env içinde model anahtarı bulunamadı. tau'nun bir sağlayıcıdan anahtara ihtiyacı var (`tau init --yes` anahtarsız, senaryolu 'fake' sağlayıcıyı kurar).
Sağlayıcı (anthropic, openai, gemini) [anthropic]: anthropic
ANTHROPIC_API_KEY (gizli; boş bırakırsan atlanır):
Anahtar anthropic sağlayıcısına tek bir küçük istekle deneniyor...
anthropic anahtarı kabul etti.
```

Sağlayıcının reddettiği bir anahtar ya da yanıt alamayan bir deneme, `tau init`'i hiçbir şey yazmadan durdurur; `--no-check` isteği atlar. Boş bırakılan anahtar atlanır: yapılandırma o sağlayıcı için yazılır, anahtarı sonra `.env` dosyasına eklersin. `--yes` hiçbir şey sormaz ve eski davranışı korur: sağlayıcıyı bulduğu kimlik bilgilerinden seçer, hiçbiri yoksa `fake`. Ardından `tau init` şunları yazar:

| Dosya | Nedir |
|---|---|
| `tau.toml` | Her rolü hangi sağlayıcının ve model id'sinin karşıladığı; ayrıca ajan, oturum, hub ve arayüz ayarları. Bkz. [Yapılandırma](configure.md). |
| `persona/persona.md` | tau'nun karakteri. Depoda takip edilir, herkese açıktır, senin hakkında hiçbir şey içermez. |
| `persona/user.example.md` | Bilgi dosyasının uydurma bir örneği. |
| `persona/user.md` | Örneğin senin kopyan. Onu düzenle; senin hakkındaki gerçek bilgilerin tek yeri burası. |
| `.env.example` | `tau doctor`'ın bildiği her kimlik bilgisinin ve ayarın adı. Gerçek değerlerin hemen yanındaki `.env` dosyasına gider. |
| `.env` | Yazdıysan anahtarın (izin `0600`; var olan bir dosyanın diğer satırlarına dokunmadan sonuna eklenir). |

Kimlik bilgileri zaten varsa `tau init` sağlayıcıyı onlardan seçer ve anahtar sormaz: önce Anthropic (`ANTHROPIC_API_KEY`), sonra OpenAI (`OPENAI_API_KEY`), sonra Gemini (`GEMINI_API_KEY` ya da `GOOGLE_API_KEY`), sonra Bedrock. O sağlayıcının modellerini `brain` ve `fast` için yazar, tau'nun onlar için uyguladığı bütçeleri korur (`brain` için ayda 15 $, `fast` için günde 1 $) ve `local` rolünü, failover'ı (ulaşılamazsa devredeceği rol) `fast` olacak şekilde Ollama'ya koyar. Hiç kimlik bilgisi yokken `tau init --yes`, `fake` sağlayıcı üzerinde çalışan bir yapılandırma ve bunu söyleyen bir not verir. `--force` vermediğin sürece mevcut dosyalar korunur; `user.md` ve `.env.example` asla üzerine yazılmaz.

!!! note "Kök nerede?"
    tau, `tau.toml` dosyasını şu sırayla arar: `--home DIR` seçeneği, `TAU_HOME` değişkeni, içinde bir `tau.toml` varsa geçerli dizin, sonra `~/.tau`. Değişen durum (oturumlar, loglar, hub dosyaları) başka bir yerde, `TAU_DATA_DIR` altında yaşar; varsayılanı `~/.local/share/tau`. Bkz. [Ortam değişkenleri](../reference/environment.md).

## Kurulumu kontrol et

```sh
tau doctor
```

`tau doctor` yapılandırmayı okur, bir model istemcisi oluşturmadan her rolün sağlayıcısını ve kimlik bilgilerini kontrol eder, oturum deposunu açar, persona dosyalarını okur, `.env` dosyasını `.env.example` ile karşılaştırır, her bileşeni yükler ve hub'ı yoklar. Yalnızca bir kontrol başarısız olduğunda 1 ile çıkar; başlangıç için uyarılar sorun değil. [İlk çalıştırma](first-run.md) çıktıyı satır satır anlatır.

## Konuş

```sh
tau chat
```

```text
tau ready. Profile: home, session: 20260929-173826-f949. Commands: /help, /tools, /sessions, /resume, /new, /session, /compact, /clear, /status, /model, /lang, /settings, /quit (Ctrl-D also quits).
you>
```

Bir mesaj yaz ve Enter'a bas. `/help` komutları listeler, `/quit` çıkar. `fake` sağlayıcıda tau her şeye `Okay.` diye yanıt verir; bu bir hata değil, senaryolu model. Gerçek yanıtlar için kimlik bilgisi ekle: TUI'de `/settings` (ya da burada `/settings set ANTHROPIC_API_KEY`) onları `.env` dosyasına yazar ve rolü değiştirir; ya da onları `.env` dosyasına kendin koy ve `tau init --force` komutunu yeniden çalıştır.

Tam ekran arayüz bir komut uzağında:

```sh
tau tui
```

[tau ile konuş](talk.md) ikisini karşılaştırır ve her tuşu ve komutu listeler.

## Sıradaki

- [İlk çalıştırma](first-run.md): `.env` içindeki kimlik bilgileri, fake sağlayıcı, `tau doctor`'ın açıklaması.
- [Yapılandırma](configure.md): `tau.toml` üzerinde bir tur.
- [Modeller ve bütçeler](../guides/models-and-budgets.md): sağlayıcılar, yerel model, rol başına katı bir harcama üst sınırı.
- Hub'ın ayakta kalmasını istediğinde [tau'yu servis olarak çalıştır](../guides/hub-service.md).
