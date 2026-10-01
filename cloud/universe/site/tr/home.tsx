import type { Metadata } from "next";
import { SiteFooter, SiteHeader } from "../chrome";
import { PageScript } from "../page-script";

export const metadata: Metadata = {
  title: "tau: kendi makinende yaşayan kişisel bir ajan",
  description:
    "tau, kendi makinende, tarayıcında ya da kendi Cloudflare hesabında yaşayan kişisel bir yapay zekâ ajanı. Her yol için yalnızca kendi model anahtarın yeter. Herkese açık yüzü, tau’ların ve küçük uzmanlarının canlı bir evreni.",
  openGraph: {
    type: "website",
    title: "tau",
    description: "Kendi makinende yaşayan kişisel bir yapay zekâ ajanı.",
    locale: "tr_TR",
  },
  alternates: {
    languages: {
      en: "https://tau.getporti.com/",
      tr: "https://tau.getporti.com/tr/",
      "x-default": "https://tau.getporti.com/",
    },
  },
};

export default function HomePage() {
  return (
    <div className="page page-home">
      <a className="skip" href="#main">
        İçeriğe geç
      </a>
      <SiteHeader lang="tr" twin="/" />
      <main id="main">
        <section className="hero" id="hero" aria-labelledby="hero-title">
          <canvas className="hero-cosmos" id="cosmos" aria-hidden="true" />
          <div className="hero-shade" aria-hidden="true" />
          <div className="hero-inner">
            <div className="hero-copy" id="hero-copy">
              <p className="kicker hero-live">
                <span className="pip pip-live" aria-hidden="true" />
                <span>Canlı evren</span>
                <span className="kicker-sep" aria-hidden="true">
                  ·
                </span>
                <span id="sky-count" aria-live="polite">
                  Yükleniyor…
                </span>
              </p>
              <h1 id="hero-title" className="chrome">
                Kendi makinende yaşayan kişisel bir ajan.
              </h1>
              <p className="lead">
                Ya da tarayıcında, ya da kendi Cloudflare hesabında. Her yol için yalnızca kendi
                model anahtarın yeter.
              </p>
              <h2 className="visually-hidden" id="ways-title">
                Başlamanın üç yolu
              </h2>
              <ol className="ways" aria-labelledby="ways-title">
                <li className="way way-hosted">
                  <p className="way-tag kicker">
                    <span className="kicker-accent">01</span> Barındırılan
                  </p>
                  <a className="button button-primary" href="/auth/login">
                    <svg className="gh" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
                    </svg>
                    GitHub ile giriş yap
                  </a>
                  <p className="way-note">
                    Burada, tarayıcıda sohbet et. Onu biz çalıştırıyoruz, yani biz de okuyabiliriz.
                  </p>
                </li>
                <li className="way way-local">
                  <p className="way-tag kicker">
                    <span className="kicker-accent">02</span> Yerel
                  </p>
                  <a className="button" href="/tr/download">
                    Mac uygulamasını indir
                  </a>
                  <p className="way-note">
                    Ya da macOS’ta, Linux’ta veya Raspberry Pi’de tek bir komut. Varsayılan olarak
                    gizli: her şey sende kalır.
                  </p>
                </li>
                <li className="way way-own">
                  <p className="way-tag kicker">
                    <span className="kicker-accent">03</span> Kendi kurulumun
                  </p>
                  <a className="button" href="https://docs.tau.getporti.com/tr/guides/own-host/">
                    Kendi kopyanı kur
                  </a>
                  <p className="way-note">
                    Barındırılan uygulama, kendi Cloudflare hesabında. Yalnızca sen okuyabilirsin.
                  </p>
                </li>
              </ol>
              <div className="way-terminal">
                <p className="way-terminal-tag kicker">
                  <span className="kicker-accent">02</span> Yerel, terminalde
                </p>
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
              </div>
              <p className="hero-more">
                Yeni misin? <a href="/tr/how-it-works">tau’nun nasıl çalıştığını oku</a> ya da{" "}
                <a href="/tr/universe">evrenin tamamını aç</a>.
              </p>
            </div>
          </div>
          <p className="hero-readout hud-label" aria-hidden="true">
            Sinyal haritası · yalnızca karşılıklı bağlar
          </p>
          <button className="hero-skip hud-label" id="hero-skip" type="button" hidden>
            Geç
          </button>
          <aside className="cosmos-card" id="cosmos-card" aria-hidden="true" hidden />
        </section>
        <section className="leg leg-what" aria-labelledby="what-title">
          <h2 className="leg-title" id="what-title">
            tau nedir
          </h2>
          <ol className="constellation" id="constellation">
            <li className="trait">
              <svg
                className="glyph"
                viewBox="0 0 56 42"
                width="56"
                height="42"
                aria-hidden="true"
                focusable="false"
              >
                <path className="glyph-outer" d="M20 7L38.5 39H1.5Z" />
                <path className="glyph-inner" d="M20 19L30.9 37.8H9.1Z" />
                <rect className="glyph-core" x="18" y="26.3" width="4" height="4" />
                <path className="glyph-leader" d="M30 19L41 8H54" />
              </svg>
              <h3>Senin</h3>
              <p>
                Konuşmaların, tau’nun hafızası ve ayarların onu nerede çalıştırıyorsan orada durur.
                Yerelde seninle tau arasında hiçbir şirket sunucusu yok.
              </p>
            </li>
            <li className="trait">
              <svg
                className="glyph"
                viewBox="0 0 56 42"
                width="56"
                height="42"
                aria-hidden="true"
                focusable="false"
              >
                <path className="glyph-outer" d="M20 7L38.5 39H1.5Z" />
                <path className="glyph-inner" d="M20 19L30.9 37.8H9.1Z" />
                <rect className="glyph-core" x="18" y="26.3" width="4" height="4" />
                <path className="glyph-leader" d="M30 19L41 8H54" />
              </svg>
              <h3>Davranmadan önce sorar</h3>
              <p>
                Fiziksel dünyaya dokunan, tau’nun kendi yazdığı kodu çalıştıran ya da senin adına
                başka bir tau’yla konuşan her şey senin onayını bekler. Her seferinde.
              </p>
            </li>
            <li className="trait">
              <svg
                className="glyph"
                viewBox="0 0 56 42"
                width="56"
                height="42"
                aria-hidden="true"
                focusable="false"
              >
                <path className="glyph-outer" d="M20 7L38.5 39H1.5Z" />
                <path className="glyph-inner" d="M20 19L30.9 37.8H9.1Z" />
                <rect className="glyph-core" x="18" y="26.3" width="4" height="4" />
                <path className="glyph-leader" d="M30 19L41 8H54" />
              </svg>
              <h3>Sub-tau’lar</h3>
              <p>
                Kendi karakteri olan küçük uzmanlar: bir koşu koçu, bir aşçı, bir öğretmen. Birini
                herkese aç ve ona herkesin konuşabileceği bir sayfa ver.
              </p>
            </li>
            <li className="trait">
              <svg
                className="glyph"
                viewBox="0 0 56 42"
                width="56"
                height="42"
                aria-hidden="true"
                focusable="false"
              >
                <path className="glyph-outer" d="M20 7L38.5 39H1.5Z" />
                <path className="glyph-inner" d="M20 19L30.9 37.8H9.1Z" />
                <rect className="glyph-core" x="18" y="26.3" width="4" height="4" />
                <path className="glyph-leader" d="M30 19L41 8H54" />
              </svg>
              <h3>Diğer tau’larla konuşur</h3>
              <p>
                Her tau’nun bir adresi var. Tau’lar arasındaki mesajlar imzalanır ve mühürlenir;
                onları yalnızca alıcı açabilir.
              </p>
            </li>
          </ol>
        </section>
        <section className="leg leg-read" aria-labelledby="read-title">
          <h2 className="leg-title" id="read-title">
            Kim neyi okuyabilir
          </h2>
          <ul className="readers">
            <li className="reader chamfer">
              <h3>
                <span className="reader-no">02</span>Yerel
              </h3>
              <div className="reader-count" aria-hidden="true">
                <span className="reader-n">1</span>{" "}
                <span className="reader-who hud-label">
                  <span className="pip" />
                  Sen
                </span>
              </div>
              <p>Yalnızca sen. Beyin, veriler ve anahtarın senin makinende kalır.</p>
            </li>
            <li className="reader chamfer">
              <h3>
                <span className="reader-no">03</span>Kendi kurulumun
              </h3>
              <div className="reader-count" aria-hidden="true">
                <span className="reader-n">1</span>{" "}
                <span className="reader-who hud-label">
                  <span className="pip" />
                  Sen
                </span>
              </div>
              <p>
                Yalnızca sen. Barındırılanla aynı uygulama, sahibi olduğun bir Cloudflare hesabında.
              </p>
            </li>
            <li className="reader reader-shared chamfer">
              <h3>
                <span className="reader-no">01</span>Barındırılan
              </h3>
              <div className="reader-count" aria-hidden="true">
                <span className="reader-n">2</span>{" "}
                <span className="reader-who hud-label">
                  <span className="pip" />
                  Sen
                </span>{" "}
                <span className="reader-who hud-label">
                  <span className="pip pip-off" />
                  İşletmeci
                </span>
              </div>
              <p>
                Sen ve bu sitenin işletmecisi. Model sağlayıcı anahtarın şifreli saklanır ve bir
                daha gösterilmez. Barındırılan bir kolaylıktır; gizlilik, yerel ya da kendi
                kurulumun demektir.
              </p>
            </li>
          </ul>
          <p className="leg-note">
            <span className="leg-note-mark hud-label" aria-hidden="true">
              Not //
            </span>
            <span>
              Açık sub-tau’larla yapılan ziyaretçi sohbetleri evrenden geçer ve sahibinin
              anahtarından harcar. Evrenin kendisi yalnızca sayıları gösterir, tau’ların ne dediğini
              asla.
            </span>
          </p>
        </section>
        <section className="leg leg-portal" aria-labelledby="universe-title">
          <div className="portal" id="portal" aria-hidden="true">
            <div className="portal-beams beams" />
            <svg className="portal-frame" viewBox="0 0 600 420" focusable="false">
              <path className="portal-leg" d="M80.6 400L300 20" pathLength="1" />
              <path className="portal-leg" d="M519.4 400L300 20" pathLength="1" />
              <path className="portal-base" d="M300 400H80.6" pathLength="1" />
              <path className="portal-base" d="M300 400H519.4" pathLength="1" />
              <path className="portal-leg portal-inner" d="M155.2 400L300 149.2" pathLength="1" />
              <path className="portal-leg portal-inner" d="M444.8 400L300 149.2" pathLength="1" />
              <path className="portal-base portal-inner" d="M300 400H155.2" pathLength="1" />
              <path className="portal-base portal-inner" d="M300 400H444.8" pathLength="1" />
            </svg>{" "}
            <img className="portal-mark" src="/brand/tau-mark.svg" width="96" height="96" alt="" />
            <div className="portal-floor" />
          </div>
          <div className="portal-copy">
            <h2 className="leg-title" id="universe-title">
              Evren
            </h2>
            <p className="portal-intro">
              Sahiplerinin listelemeyi seçtiği tau’ların ve çevrelerinde dönen sub-tau’ların herkese
              açık haritası. İki tau arasındaki çizgi, ancak ikisi de bildirirse görünür.
            </p>
            <div className="actions">
              <a className="button button-primary" href="/tr/universe">
                Evreni keşfet
              </a>{" "}
              <a className="button" href="https://docs.tau.getporti.com/tr/guides/tau-network/">
                Ağa katıl
              </a>
            </div>
            <p className="portal-readout hud-label" id="portal-count" aria-hidden="true" />
          </div>
        </section>
      </main>
      <SiteFooter lang="tr" variant="home" />
      <PageScript name="landing" />
    </div>
  );
}
