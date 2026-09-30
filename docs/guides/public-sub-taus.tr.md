<!-- tr twin of guides/public-sub-taus.md, translated 2026-09-30 -->

# Web sayfalı açık sub-tau'lar

**Sub-tau**, tau'nun kendi personası ve kendi görevi olan küçük bir uzmanı: bir koşu koçu, `/coach`, ya da açılış sayfası metinleri yazan `/landing` ([ADR 0012](../adr/0012-sub-taus.md)). Birini **açık** (public) yaparsan tau ağındaki kişilerin ona yazabilir. Ona bir de **web sayfası** verirsen herkes, hesap ya da anahtar gerekmeden, tarayıcıda onunla konuşabilir; hem de evrende:

```text
https://tau.getporti.com/coach            its short page, when the name was free
https://tau.getporti.com/@alice/coach     its page under your handle
```

Bir ziyaretçiye verilen her cevap, senin anahtarınla yapılan bir model çağrısıdır. Bu yüzden sayfa kendi başına bir bayraktır; varsayılan olarak kapalıdır ve günlük bir sınırı vardır. Kararlar [ADR 0013](../adr/0013-hosted-taus-handles-and-public-pages.md) §5 ve §6'da, protokol ise [tau evreni referansının](../reference/tau-universe.md) 5. bölümünde.

## Ziyaretçiler ne görür

Sayfa sub-tau'nun **karakterini** gösterir: tau'nun adresinden ve sub-tau'nun adından çizilen küçük bir yaratık (her sayfada aynısı). Ayrıca adını, tanıtım satırını ve tau'nun bir kullanıcı adı (handle) varsa "by @alice" bilgisini. Web sayfası açıksa şunlar da gelir:

- en fazla dört **başlangıç mesajı** (starters): ziyaretçinin tıklayabileceği önerilen ilk mesajlar;
- ziyaretçi sohbetlerinin evrenden geçtiğini ve sahibinin anahtarından harcadığını söyleyen bir notla birlikte bir sohbet kutusu;
- hub'ının çalıştırdığı bir sub-tau için hub'ın çevrimiçi olup olmadığı. Çevrimdışı bir hub'a giden mesaj spine'ının posta kutusunda bekler ve hub dönünce cevaplanır.

Ziyaretçi, rastgele ve anonim bir çerezden ibarettir. Bir konuşma 24 saat saklanır ve en fazla 50 mesaj tutar; bir mesaj en fazla 2 000 karakter olabilir; bir IP adresi dakikada 10 mesaj gönderebilir. Sub-tau o günkü ziyaretçi cevaplarını ya da bütçeni tükettiğinde sayfa, yarına kadar dinlendiğini söyler.

## Sub-tau'n ne görür

Bir ziyaretçi, tau ağındaki bir kişiyle aynı kısıtlı turu alır:

- sub-tau'nun personası ve **açık notu** (`persona/subs/coach.public.md`; bir not belirtmemişse tau'nun `persona/net.md` dosyası), sayfasının anonim bir ziyaretçisinden gelen bir mesaj olarak çerçevelenmiş hâlde;
- asla `persona/user.md` görmez; izin listesindekiler dahil hiçbir aracı yoktur ve her onayı reddeder;
- yalnızca o ziyaretçinin kendi konuşmasını görür. Ziyaretçiler birbirini asla görmez; bir ziyaret kişi oluşturmaz ve evrendeki hiçbir bağlantıya sayılmaz.

Açık notu bunu düşünerek yaz: koçun bir yabancıya senin hakkında söyleyebileceği her şey odur.

## Sayfalar, kısa adlar ve kullanıcı adları

- **`/<name>`, kısa sayfa (slug).** Kısa adlar herkes için ortaktır ve onları ilk alan tau'nun olur: adı hâlâ boş olan açık bir sub-tau'yu listeleyen ilk rapor, `/<name>` sayfasını o tau'ya verir. Sub-tau bir süre gizli olsa bile sayfa, tau'n evrenden ayrılana ya da 30 gün rapor göndermeyene kadar onda kalır. Sitenin kendi adları (`universe`, `how-it-works`, `claim`, `app`, `api`, `auth`, `docs`, `about`, `help` ve birkaç tane daha) asla kısa ad olamaz.
- **`/@<handle>/<name>`**, tau'n bir kullanıcı adı aldıktan sonra her zaman sub-tau'nun sayfasıdır.
- **Ne kullanıcı adı ne de kısa sayfa varsa** sub-tau evren haritasında görünür (`/universe#<address>/<name>`) ama sohbet sayfası olmaz. Sohbet sayfası için bir kullanıcı adı al.
- Her sayfanın `/tr/` altında Türkçe ikizi de vardır.

**Kullanıcı adı** (handle), GitHub girişiyle kanıtlanmış bir GitHub kullanıcı adıdır; böylece GitHub'da `alice` olmayan kimse `@alice`'i alamaz. `tau.getporti.com` üzerinde barındırılan bir tau, kullanıcı adını adresinden alır. Yerel bir tau (ya da bulut modundaki bir tau) onu **talep eder** (claim):

```sh
tau net universe claim
```

```text
Open this link within an hour and sign in with GitHub there; tau.getporti.com then binds your GitHub login as the handle of tau.example.com:
https://tau.getporti.com/claim#eyJwYXlsb2FkIjoi...
The link is a signed claim for this tau: whoever opens it with their GitHub account could take the handle for it, so do not share it.
```

Arayüz dilin `tr` ise bu satırlar Türkçe gelir. Bağlantıyı aç, GitHub ile giriş yap; evren GitHub kullanıcı adını tau'nun adresine bağlar. Bir kullanıcı adı tek bir adresi gösterir: aynı GitHub hesabından gelen yeni bir talep onu taşır, başka bir hesaptan gelen talep reddedilir. Ardından `tau net universe status`, `handle: @alice  https://tau.getporti.com/@alice` satırını gösterir ve `/@alice` kişi sayfan olur: tau'n, açık sub-tau'ların ve bağlantılı olduğu tau'lar orada.

## Yerel bir tau'da

tau ağında ve evrende olan bir tau gerekir ([tau ağına katıl](tau-network.md)): bir adres, bir kimlik, `tau net universe join` ve çalışan bir hub (`tau hub run`), çünkü ziyaretleri hub cevaplar. Ziyaretler yeni bir zarf türüdür, `visit`: `tau-net`'i güncelledikten sonra spine'ını güncel kitten yeniden yayına al (`tau net spine init` ile yeni bir dizine, sonra `tau net spine deploy`); yoksa spine bu zarfları geri çevirir.

**1. Sub-tau'yu sayfasıyla birlikte açık yap.** Yeni bir tane:

```sh
tau sub new coach --describe "a patient running coach for beginners" \
  --public --web --web-daily 30 --starter "Plan my week" --starter "I missed a run"
```

Ya da var olanı `tau sub edit coach` ile düzenle. Sayfa ayarları, `persona/subs/coach.md` dosyasının ön bilgisindeki (front matter) üç alandır:

```toml
+++
about = "A patient running coach for beginners."
role = "fast"                       # visitor answers run on this role's budget
tools = []
public = true
public_note = "coach.public.md"     # what /coach may tell others about you
web = true                          # a chat page for visitors; needs public = true
web_daily = 30                      # visitor answers per UTC day, 1 to 1000 (default 50)
starters = ["Plan my week", "I missed a run"]   # up to 4, each 1 to 80 characters
+++
```

`tau sub show coach` sayfa ayarlarını yazdırır; `web` açık ama `public` kapalıysa bunu da söyler.

**2. Açık notunu yaz**: `persona/subs/coach.public.md`. Ya da hiç yazma, onun adına `persona/net.md` konuşsun.

**3. Bildir.** tau'n listelendiği sürece hub her saat rapor gönderir; bir sonraki rapor sub-tau'yu `web` ve `starters` ile birlikte taşır. Hemen bildirmek için `tau net universe join` komutunu yeniden çalıştır; listelediği sub-tau'ları da yazdırır:

```sh
tau net universe join
tau net universe status     # handle, public sub-taus, today's visitor answers per web page
```

**4. Kullanıcı adı al**: tau'nun henüz yoksa `tau net universe claim` ile (yukarıda).

Ziyaretçi sohbetleri, adres olarak evrenle birlikte ağ günlüğüne düşer: `tau net log --address tau.getporti.com`.

## Barındırılan bir tau'da ya da kendi kurulumunda

Uygulamada **Alt-tau'lar** bölümünü aç, birini seç (ya da oluştur) ve **Görünürlük** ayarlarını yap: **Herkese açık**, **Web sayfası**, **Günlük ziyaretçi yanıtı** ve en fazla dört **Başlangıçlar**; sonra **Kaydet**. **Sayfasını aç** onu gösterir. Sub-tau'nun altında **Ziyaretçi sohbetleri (24 sa)**, ziyaretçilerin ne yazdığını ve ne cevap aldığını listeler; bir sayaç da bugünkü ziyaretçi cevaplarını sınırla karşılaştırır.

- Kendi kurulumunda sayfa host'un kendisindedir: `https://tau.example.com/@alice/coach`.
- `tau.getporti.com` üzerinde sayfayı evren sunar: `/@alice/coach` adresinde ve ad boşsa `/coach` adresinde.

!!! info "Barındırılan tau'lar"
    Barındırılan bir tau'nun web sayfalı sub-tau'ları, tau uygulamanın Ağ sayfasından evrene katılınca evrenin sayfalarına ulaşır; raporları onları bir hub'ınkiler gibi listeler. Katılmadan da barındırılan bir tau'nun web sayfalı sub-tau'suna host'un kendi sayfasından, `https://<host>/@<handle>/<name>` adresinden ulaşılır.

## Maliyet

- Her ziyaretçi cevabı **senin** anahtarınla yapılan bir model çağrısıdır. Yerel bir tau'da, o rolün diğer bütün cevapları gibi sub-tau'nun model rolünün bütçesinden düşer; `role = "fast"` sayfayı ucuzlatır. Barındırılan bir tau'da ya da kendi kurulumunda tau'nun aylık bütçesinden düşer.
- **`web_daily`**, sub-tau'yu çalıştıran tau'nun saydığı, UTC gününe göre ziyaretçi cevabı sınırıdır (varsayılan 50). Sınırına ulaşan barındırılan bir sub-tau "yarına kadar dinleniyor" der. Bir hub ise sonraki ziyaretleri sessizce bırakır; sayfaya çevrimdışı bir hub gibi görünür.
- Gerisi küçüktür: bir ziyaret, spine'ının posta kutusuna giren tek bir zarftır ve Workers Free planının rahatça içinde kalır.

## Gizlilik

- **Ziyaretçi sohbetleri uçtan uca gizli değildir.** Evren onları düz metin olarak aktarır, her konuşmayı 24 saat tutar ve sonra siler. Bir ziyaretçinin metnini asla günlüğe yazmaz. Barındırılan bir tau'da host'un işletmecisi de onları okuyabilir. Sayfa bunu ziyaretçilerin yazdığı yerde söyler.
- Evrenle hub'ın arasında bir ziyaret, diğer zarflar gibi gider: evrenin kendi ağ kimliğiyle imzalanır ve senin tau'na mühürlenir. Hub'ın ziyaretleri yalnızca katıldığı evrenden kabul eder; evrenin anahtarlarını ilk ziyarette sabitler (pin) ve yalnızca `public` olan ve `web`'i açık bir sub-tau için kabul eder.
- Hub'ın ziyaretçi sohbetlerini ağ günlüğünde, senin makinende tutar.
- Kimse sub-tau'na bir şey yaptıramaz: ziyarette hiçbir aracı yoktur ve bir ziyaretçi ne yazarsa yazsın her onayı reddeder.

## Kapat

- **Sayfayı kapat:** `web = false` yap (`tau sub edit coach`) ya da uygulamada **Web sayfası** işaretini kaldır. Hub bir sonraki ziyareti hemen reddeder; sayfa sohbet kutusunu bir sonraki raporla kaybeder.
- **Gizli yap:** `public = false`, ya da **Herkese açık** işaretini kaldır. Kişilere ve ziyaretçilere cevap vermeyi bırakır ve evrenin bir sonraki anlık görüntüsünden çıkar. Kısa sayfası tau'n için ayrılmış kalır.
- **Evrenden ayrıl:** `tau net universe leave`, tau'nu, sub-tau'larını ve kısa sayfalarını hemen kaldırır; hub'ın da evrenin anahtarlarını unutur, böylece hiçbir ziyaret gelmez.
