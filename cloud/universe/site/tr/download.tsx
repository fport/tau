import type { Metadata } from "next";
import { SiteFooter, SiteHeader } from "../chrome";
import { PageScript } from "../page-script";

export const metadata: Metadata = {
  title: "tau’yu indir",
  description:
    "tau’yu indir: macOS 13 ve sonrası için, ilk açılışta bir kurulum sihirbazıyla gelen Mac uygulaması ya da macOS, Linux ve Raspberry Pi’de terminalde tek bir komut.",
  openGraph: {
    type: "website",
    title: "tau’yu indir",
    description: "Mac uygulaması ya da terminalde tek bir komut.",
    locale: "tr_TR",
  },
  alternates: {
    languages: {
      en: "https://tau.getporti.com/download",
      tr: "https://tau.getporti.com/tr/download",
      "x-default": "https://tau.getporti.com/download",
    },
  },
};

export default function DownloadPage() {
  return (
    <div className="page page-download">
      <a className="skip" href="#main">
        İçeriğe geç
      </a>
      <SiteHeader lang="tr" twin="/download" />
      <main id="main" className="explainer">
        <section className="intro" aria-labelledby="intro-title">
          <p className="kicker">
            <span className="kicker-accent">İndir</span>
            <span className="kicker-sep" aria-hidden="true">
              ·
            </span>
            <span>Ücretsiz</span>
            <span className="kicker-sep" aria-hidden="true">
              ·
            </span>
            <span>Kendi makinende çalışır</span>
          </p>
          <h1 id="intro-title">tau’yu indir.</h1>
          <p className="intro-lead">
            Mac uygulaması tau’yu menü çubuğuna koyar, arka planda çalıştırır ve onu ilk açtığında
            her şeyi kurar. Linux’ta ve Raspberry Pi’de terminaldeki tek bir komut aynısını yapar.
          </p>
          <div className="get">
            <section className="get-way get-app chamfer" aria-labelledby="get-app-title">
              <div className="get-head">
                <img
                  className="get-icon"
                  src="/brand/tau-app-icon.svg"
                  width="64"
                  height="64"
                  alt=""
                />
                <div>
                  <h2 className="get-name" id="get-app-title">
                    Mac için tau
                  </h2>
                  <p className="get-meta hud-label">
                    macOS 13 ve sonrası · <span lang="en">Apple silicon</span> ve Intel
                  </p>
                </div>
              </div>
              <a
                className="button button-primary"
                href="/download/tau.dmg"
              >
                <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                  <path d="M7 1h2v7.6l2.8-2.8 1.4 1.4L8 12.4 2.8 7.2l1.4-1.4L7 8.6zM2 13h12v2H2z" />
                </svg>
                tau.dmg’yi indir
              </a>
              <p className="get-note">
                Menü çubuğu uygulaması, sohbet pencereleri ve bir kurulum sihirbazı, tek bir
                indirmede. Uygulama Apple’ın noter onayından henüz geçmedi; bu yüzden macOS onu
                açmadan önce bir kez sorar: <a href="#first-open">nasıl açılır</a>.
              </p>
            </section>
            <section className="get-way get-terminal chamfer" aria-labelledby="get-terminal-title">
              <div className="get-head">
                <div>
                  <h2 className="get-name" id="get-terminal-title">
                    Tek komut
                  </h2>
                  <p className="get-meta hud-label">
                    macOS · <span lang="en">Linux</span> · <span lang="en">Raspberry Pi</span>
                  </p>
                </div>
              </div>
              <div className="command chamfer">
                <code id="install-command">
                  curl -fsSL https://tau.getporti.com/install.sh | sh
                </code>{" "}
                <button
                  className="copy"
                  type="button"
                  data-copy="install-command"
                  aria-describedby="install-command"
                >
                  Kopyala
                </button>
              </div>
              <p className="get-note">
                tau’yu ev klasörüne kurar ve hangi özellikleri istediğini sorar. Hiçbir zaman{" "}
                <code>sudo</code> çalıştırmaz. <a href="#terminal">Ne yaptığını gör</a>.
              </p>
            </section>
          </div>
        </section>
        <section className="chapter" id="first-open" aria-labelledby="first-open-title">
          <h2 id="first-open-title">İlk kez açarken.</h2>
          <p className="chapter-lead">
            tau imzalı, ama Apple’ın noter onayından henüz geçmedi. Bu yüzden macOS onu ilk seferde
            durdurur ve kötü amaçlı yazılım denetimini yapamadığını söyler. Bu beklenen bir durum:
            bir kez izin verirsin, sonra tau her uygulama gibi açılır.
          </p>
          <div className="row">
            <ol className="steps">
              <li>
                <h3>tau’yu Uygulamalar’a sürükle.</h3>
                <p>
                  <code>tau.dmg</code> dosyasını aç ve <strong>tau</strong>’yu{" "}
                  <strong>Uygulamalar</strong> klasörüne sürükle.
                </p>
              </li>
              <li>
                <h3>Bir kez aç.</h3>
                <p>
                  tau’yu Uygulamalar’dan aç. macOS tau’yu denetleyemediğini söylediğinde mesajı
                  kapat. tau’yu Çöp Sepeti’ne taşıma.
                </p>
              </li>
              <li>
                <h3>Yine de Aç’ı seç.</h3>
                <p>
                  <strong>Sistem Ayarları → Gizlilik ve Güvenlik</strong> bölümünü aç, tau ile
                  ilgili satıra kadar aşağı kaydır ve <strong>Yine de Aç</strong>’ı seç. Parolanla
                  ya da Touch ID ile onayla.
                </p>
              </li>
              <li>
                <h3>Ya da sağ tık → Aç.</h3>
                <p>
                  macOS 13 ve 14’te daha kısa bir yol var: Uygulamalar’da tau’ya sağ tıkla,{" "}
                  <strong>Aç</strong>’ı, ardından yine <strong>Aç</strong>’ı seç. macOS 15 ve
                  sonrası yalnızca yukarıdaki yolu sunar.
                </p>
              </li>
            </ol>
            <aside className="fig why" aria-labelledby="why-title">
              <h3 id="why-title">macOS neden soruyor</h3>
              <p>
                Noter onayı, Apple’ın App Store dışından gelen bir uygulamayı denetlemesidir ve
                Apple’ın ücretli geliştirici programını gerektirir. tau bu programı henüz
                kullanmıyor.
              </p>
              <p>
                Bunun yerine her sürüm aynı sertifikayla imzalanır; böylece macOS, tau’ya verdiğin
                kamera ve bildirim gibi izinleri güncellemelerden sonra da korur. tau güncellemeleri
                kendisi arar ve birini kurmadan önce sorar.
              </p>
            </aside>
          </div>
        </section>
        <section className="chapter" id="first-launch" aria-labelledby="first-launch-title">
          <h2 id="first-launch-title">İlk açılışta neler olur.</h2>
          <p className="chapter-lead">
            tau ilk açıldığında bir kurulum sihirbazı seni sekiz adımdan geçirir. Her birini
            atlayabilirsin; menüdeki <strong>Set up tau…</strong> sihirbazı sonradan özellik eklemek
            ya da kaldırmak için yeniden açar.
          </p>
          <ol className="wizard">
            <li className="chamfer">
              <h3>Dil</h3>
              <p>Sihirbaz ve tau’nun söylediği her şey için İngilizce ya da Türkçe.</p>
            </li>
            <li className="chamfer">
              <h3>tau’yu kur</h3>
              <p>
                Sihirbaz tau’yu bulur ya da uv ile ev klasörüne kurar. Yönetici parolası gerekmez.
              </p>
            </li>
            <li className="chamfer">
              <h3>Model anahtarı</h3>
              <p>
                Sağlayıcın ve anahtarı. Anahtar tek bir küçük istekle denenir ve Mac’inde, yalnızca
                senin okuyabileceğin bir dosyada kalır.
              </p>
            </li>
            <li className="chamfer">
              <h3>Hakkında</h3>
              <p>
                İsteğe bağlı: adın, tau’nun sana nasıl hitap edeceği ve dillerin. Mac’inde kalır.
              </p>
            </li>
            <li className="chamfer">
              <h3>Özellikler</h3>
              <p>
                tau’nun ne yapacağını seç: Telegram, uzaktan erişim, sahip koruması, tau ağı ve{" "}
                <a href="#features">fazlası</a>.
              </p>
            </li>
            <li className="chamfer">
              <h3>İzinler</h3>
              <p>
                Yalnızca özelliklerinin gerektirdikleri: koruma için kamera, uygulama için
                bildirimler. macOS sana tau adına sorar.
              </p>
            </li>
            <li className="chamfer">
              <h3>Özellik adımları</h3>
              <p>
                Her özellik canlı olarak kurulur: Telegram botunu eşleştirmek, yüzünü kaydetmek,
                tau’nun adresi. <code>sudo</code> isteyen bir komut senin çalıştırman için
                gösterilir; tau onu asla çalıştırmaz.
              </p>
            </li>
            <li className="chamfer">
              <h3>Özet</h3>
              <p>
                Nelerin açık olduğu, nelerin atlandığı; ardından bir tıkla bir sohbet penceresi ya
                da hub.
              </p>
            </li>
          </ol>
        </section>
        <section className="chapter" id="terminal" aria-labelledby="terminal-title">
          <h2 id="terminal-title">Terminal yolu.</h2>
          <p className="chapter-lead">
            macOS’ta, Linux’ta ve Raspberry Pi’de (64 bit bir sistemde) tek bir komut tau’yu kurar
            ve aynı kurulumu terminalde, sorular hâlinde başlatır.
          </p>
          <div className="row">
            <div className="prose">
              <div className="command chamfer">
                <code id="terminal-command">
                  curl -fsSL https://tau.getporti.com/install.sh | sh
                </code>{" "}
                <button
                  className="copy"
                  type="button"
                  data-copy="terminal-command"
                  aria-describedby="terminal-command"
                >
                  Kopyala
                </button>
              </div>
              <p>Bu kısa bir kabuk betiği; çalıştırmadan önce okuyabilirsin:</p>
              <div className="command chamfer">
                <code id="read-command">curl -fsSL https://tau.getporti.com/install.sh | less</code>{" "}
                <button
                  className="copy"
                  type="button"
                  data-copy="read-command"
                  aria-describedby="read-command"
                >
                  Kopyala
                </button>
              </div>
              <p>
                tau’yu soru sormadan kurmak ve <code>tau setup</code>’ı sonra kendin çalıştırmak
                için:
              </p>
              <div className="command chamfer">
                <code id="quiet-command">
                  curl -fsSL https://tau.getporti.com/install.sh | TAU_INSTALL_NO_SETUP=1 sh
                </code>{" "}
                <button
                  className="copy"
                  type="button"
                  data-copy="quiet-command"
                  aria-describedby="quiet-command"
                >
                  Kopyala
                </button>
              </div>
              <p>
                Başka bir özellik istediğinde <code>tau setup</code>’ı yeniden çalıştır. Kurulu
                olanlar bir daha sorulmaz.
              </p>
            </div>
            <aside className="fig" aria-labelledby="script-title">
              <h3 id="script-title" className="fig-title">
                Betik ne yapar
              </h3>
              <ol className="steps steps-small">
                <li>
                  <p>
                    Sistemin 64 bit Intel ya da ARM işlemcili bir macOS ya da Linux olduğunu
                    denetler.
                  </p>
                </li>
                <li>
                  <p>
                    Eksikse tau’nun kullandığı Python kurucusu uv’yi kurar. uv kendi Python’unu
                    getirir.
                  </p>
                </li>
                <li>
                  <p>
                    tau’yu <code>uv tool install tau-core --with tau-tui</code> ile kendi klasörüne
                    kurar.
                  </p>
                </li>
                <li>
                  <p>
                    <code>tau setup</code>’ı başlatır: dilin, istediğin özellikler, model anahtarın,
                    ardından her özelliğin adımları.
                  </p>
                </li>
              </ol>
              <p className="fig-note">
                Hiçbir zaman <code>sudo</code> çalıştırmaz; zaten kurulu bir tau’ya da dokunmaz.
              </p>
            </aside>
          </div>
        </section>
        <section className="chapter" id="manual" aria-labelledby="manual-title">
          <h2 id="manual-title">Elle.</h2>
          <p className="chapter-lead">
            uv kuruluysa tau’nun her parçası PyPI’da bir pakettir. Paketleri kendin seç, gerisini{" "}
            <code>tau setup</code>’a bırak.
          </p>
          <div className="prose prose-wide">
            <pre className="command-block">
              <code>
                {"uv tool install tau-core --with tau-tui --with tau-net --with tau-sub\ntau setup"}
              </code>
            </pre>
            <p>
              <code>tau-core</code> ajanın kendisi ve <code>tau</code> komutudur;{" "}
              <code>tau-tui</code> tam ekran terminal arayüzü, <code>tau-net</code> tau ağı,{" "}
              <code>tau-sub</code> de sub-tau’lar.{" "}
              <a href="https://docs.tau.getporti.com/tr/getting-started/install/">
                Kurulum rehberi
              </a>{" "}
              kaynaktan kurulumu da anlatır.
            </p>
          </div>
        </section>
        <section className="chapter" id="features" aria-labelledby="features-title">
          <h2 id="features-title">Neleri kurabilirsin.</h2>
          <p className="chapter-lead">
            Sihirbaz, uygulamada da terminalde de aynı özellikleri sunar. Makinenin dışına uzanan
            hiçbir şey sen seçmedikçe açılmaz.
          </p>
          <ul className="features">
            <li>
              <h3>Terminal arayüzü</h3>
              <p>
                Tam ekran arayüz, <code>tau tui</code>.
              </p>
              <p className="feature-where hud-label">
                macOS · <span lang="en">Linux</span> · varsayılan olarak açık
              </p>
            </li>
            <li>
              <h3>tau uygulaması</h3>
              <p>Menü çubuğu, sohbet pencereleri ve hub’ın gözetmeni.</p>
              <p className="feature-where hud-label">macOS</p>
            </li>
            <li>
              <h3>Sub-tau’lar</h3>
              <p>tau’nun adı olan uzmanları: bir koç, bir aşçı, bir öğretmen.</p>
              <p className="feature-where hud-label">
                macOS · <span lang="en">Linux</span> · varsayılan olarak açık
              </p>
            </li>
            <li>
              <h3>Telegram</h3>
              <p>
                Kendi botun üzerinden telefondan tau ile konuş; bot tek kullanımlık bir kodla
                eşleşir.
              </p>
              <p className="feature-where hud-label">
                macOS · <span lang="en">Linux</span>
              </p>
            </li>
            <li>
              <h3>Uzaktan erişim</h3>
              <p>Makinene telefondan Tailscale ve SSH ile ulaş.</p>
              <p className="feature-where hud-label">
                macOS · <span lang="en">Linux</span>
              </p>
            </li>
            <li>
              <h3>Sahip koruması</h3>
              <p>
                tau yalnızca sen Mac’in başındayken yanıt verir: yüz denetimi, yedek olarak Touch
                ID.
              </p>
              <p className="feature-where hud-label">macOS · kamera</p>
            </li>
            <li>
              <h3>tau ağı</h3>
              <p>tau’na bir adres, başka tau’larla kişiler ve evren.</p>
              <p className="feature-where hud-label">
                macOS · <span lang="en">Linux</span> · ücretsiz Cloudflare hesabı
              </p>
            </li>
            <li>
              <h3>Oturum açılınca başlat</h3>
              <p>Hub sen oturum açınca başlar ve çalışmayı sürdürür.</p>
              <p className="feature-where hud-label">
                macOS · <span lang="en">Linux</span> · macOS’ta varsayılan olarak açık
              </p>
            </li>
            <li>
              <h3>Bulut modu</h3>
              <p>İleri düzey: tau’yu bunun yerine kendi Cloudflare hesabında çalıştır.</p>
              <p className="feature-where hud-label">
                macOS · <span lang="en">Linux</span>
              </p>
            </li>
          </ul>
          <div className="actions actions-start">
            <a className="button" href="https://docs.tau.getporti.com/tr/guides/setup-features/">
              Her özellik, adım adım
            </a>{" "}
            <a className="button" href="https://docs.tau.getporti.com/tr/getting-started/install/">
              Kurulum rehberi
            </a>
          </div>
        </section>
      </main>
      <SiteFooter lang="tr" variant="default" />
      <PageScript name="download" />
    </div>
  );
}
