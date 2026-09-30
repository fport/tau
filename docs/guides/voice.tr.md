<!-- tr twin of guides/voice.md, translated 2026-09-30 -->

# Ses

tau ayrı bir paket olan `tau-voice` üzerinden dinleyip konuşacak. Onunla ilgili her şey, hiçbir sesin hub'dan (tau'nun çalıştığı, sana ait makine) çıkmaması için tasarlandı: konuşmayı metne ve metni konuşmaya çevirme yerelde çalışır ve sen bir tuşa basmadan ya da uyandırma ifadesini söylemeden önce hiçbir şey kaydedilmez.

!!! info "Planlanan (yol haritası issue 075, 031, 026 ve 080)"
    Bunların hiçbiri mevcut paketlerde yok. Issue 075, `tau-voice` paketini oluşturur (bas-konuş, yerel STT ve TTS, TUI entegrasyonu); issue 031, uyandırma ifadesi issue 030'da seçildikten sonra bunun üzerine uyandırma kelimesini ekler; issue 026 Telegram sesli notlarını hub üzerinde yazıya döker; issue 080 web arayüzü üzerinden telefondan sesi getirir. Bu sayfa neyi bekleyeceğini ve neyi hazırlayacağını bil diye tasarımı anlatır; bugün çalıştırabileceğin bir özelliği anlatmaz.

## Genel şekli

`tau-voice` bir arada hem bir **hub servisi** hem de bir **kanaldır**: hub'daki mikrofonu ve hoparlörleri sahiplenen bir `tau.hub_services` bileşeni ve konuşmayı turlara, yanıtları da konuşmaya çeviren bir kanal.

| Parça | Nerede çalışır | Nedir |
|---|---|---|
| Mikrofon kaydı | hub | bas-konuş ya da uyandırma ifadesiyle başlar, sessizlikte durur |
| Konuşmadan metne (STT) | hub | Apple silicon'da MLX Whisper; Pi'de CPU için bir Whisper derlemesi |
| Metinden konuşmaya (TTS) | hub | yerel bir ses; bulut ses API'si yok |
| Uyandırma kelimesi | hub | özel, 3–4 heceli bir ifadeyle openWakeWord (issue 031) |
| Kanal | hub | oturum metadata'sında `channel = "voice"`; yanıtlar iki cümleyle sınırlı, liste yok, kod yok, emoji yok (persona'nın ses kuralı) |

Persona ses kurallarını zaten taşıyor: sesli yanıtlarda en fazla iki cümle, onay isteklerinde şaka yok. Bu kurallar [persona dosyasında](https://github.com/fport/tau/blob/main/persona/persona.md) yaşar.

## Masada bas-konuş

TUI, bir mikrofon durumunu ve bir bas-konuş tuşunu **yalnızca ses servisi mevcutsa** gösterir; servisi hub'ın kontrol API'si üzerinden bulur ve onunla event'ler (olaylar) aracılığıyla konuşur. `tau-voice` kurulu değilse TUI'nin hiçbir yerinde mikrofon yoktur. Kurduğunda ipucu çubuğuna tuş eklenir: basılı tut, konuş, bırak; transkript duyulanı senin turun olarak gösterir, yanıt da hem yazdırılır hem seslendirilir.

## Telefondan ses

Telefondan ses, yerel bir uygulama üzerinden değil, **web arayüzünün mikrofonu** üzerinden gelir: tarayıcı kaydeder, ses tünel üzerinden hub'a gider, hub onu yazıya döker. Bu, `tau-web` (issue 074, tarayıcıdaki TUI) ve `tau-voice` (issue 075) üzerine kurulan yol haritası issue 080'dir. Nedeni tehdit modeli: bir bulut konuşma API'si söylediğin her şeyi duyardı; hub'ın buna ihtiyacı yok.

## Telegram sesli notları

Bota gönderilen bir sesli not hub tarafından indirilir ve orada yazıya dökülür (issue 026). Ajana ses olarak işaretlenmiş metin şeklinde ulaşır; özgün ses yerelde kalır ve veri dizininin geri kalanıyla birlikte şifreli olarak yedeklenir.

## "Hey tau": uyandırma kelimesi

Issue 031 ile hub, bir uyandırma ifadesini sürekli dinler ve onu duyana kadar hiçbir şey kaydetmez. Senin için önemli kabul kriterleri:

- normal masa gürültüsünde saatte birden az yanlış tetikleme, ölçülmüş olarak;
- uyandırma ifadesinden önce hiç ağ trafiği yok, doğrulanmış olarak;
- görünür bir mikrofon durumu ve bir sessize alma düğmesi (Mac'te TauBar).

Uyandırma ifadesi üç ya da dört heceli olmalı; onu seçmek ve örnek kaydetmek [issue 030](https://github.com/fport/tau/blob/main/roadmap/L4-interface/030-pick-wake-phrase.md), yani bir insanın yapması gereken bir iş.

## Mikrofon izni

!!! warning "macOS'ta mikrofon izni"
    macOS mikrofon erişimini uygulama kimliği başına verir. Terminalden başlatılan bir Python süreci terminalin iznini devralır (ya da onu ister), bir launchd agent'ının hiç izni yoktur ve bir Tauri uygulamasının kendi izni vardır. Plan şu: **mikrofon izni TauBar'a ait olacak** ve TauBar ses hattını kendi sidecar'ı (yan süreci) olarak çalıştıracak; böylece izin, **System Settings → Privacy & Security → Microphone** altında görebileceğin imzalı bir uygulamaya ait olur. TauBar ses hattını çalıştırana kadar (TauBar'ın kendisi issue 024'ten beri var, ama sessiz), `tau tui` içindeki bas-konuş izni terminal uygulaman adına ister. İzni orada ver, istemediğinde de orada geri al.

    Raspberry Pi'de bir izin sistemi yoktur; mikrofon bir aygıt dosyasıdır. Bu senin için önemliyse donanımsal sessize alma düğmesi olan bir USB mikrofon seç.

## Şimdi neyi hazırlamalı

- Kurulacak bir şey yok. Hub'a elle konuşma paketleri ekleme; `tau-voice` kendi bağımlılıklarını bildirecek.
- Masa kurulumu istiyorsan mikrofonun nerede duracağına ve sessize alma anahtarı olup olmayacağına karar ver.
- Telefondan ses istiyorsan [Özel dağıtım](private-deployment.md) rehberini izle; böylece web arayüzü geldiğinde kapı hazır olur.
