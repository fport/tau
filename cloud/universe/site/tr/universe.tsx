import type { Metadata } from "next";
import { SiteHeader } from "../chrome";
import { PageScript } from "../page-script";

export const metadata: Metadata = {
  title: "tau evreni",
  description:
    "Sahiplerinin listelemeyi seçtiği tau’ların, çevrelerinde dönen sub-tau’ların ve birbiriyle konuşanların canlı haritası.",
  openGraph: {
    type: "website",
    title: "tau evreni",
    description: "Sahiplerinin listelemeyi seçtiği tau’ların canlı haritası.",
    locale: "tr_TR",
  },
  alternates: {
    languages: {
      en: "https://tau.getporti.com/universe",
      tr: "https://tau.getporti.com/tr/universe",
      "x-default": "https://tau.getporti.com/universe",
    },
  },
};

export default function UniversePage() {
  return (
    <div className="page page-universe">
      <link rel="stylesheet" href="/styles/universe.css" precedence="page" />
      <a className="skip" href="#taus-title" id="skip-list">
        Tau listesine geç
      </a>
      <SiteHeader lang="tr" twin="/universe" current="universe" />
      <main id="main" className="universe">
        <section className="u-sky" id="sky" aria-labelledby="sky-title">
          <canvas
            className="u-canvas"
            id="cosmos"
            tabIndex={0}
            role="img"
            aria-label="Listelenen tau’ların ve bağlantılarının haritası"
          />
          <div className="u-shade" aria-hidden="true" />
          <div className="u-hud u-head">
            <p className="kicker">
              <span className="pip pip-live" aria-hidden="true" />
              <span>Canlı</span>
            </p>
            <h1 id="sky-title" className="chrome">
              tau evreni
            </h1>
            <p className="u-count hud-label" id="sky-count" aria-live="polite">
              Yükleniyor…
            </p>
            <div className="u-search">
              <label className="visually-hidden" htmlFor="search">
                Sahip ya da tau ara
              </label>{" "}
              <input
                id="search"
                type="search"
                placeholder="Sahip ya da tau ara"
                autoComplete="off"
                spellCheck="false"
                disabled
              />
            </div>
            <p className="u-note" id="stage-note" hidden />
          </div>
          <div className="u-message" id="stage-message">
            <p>Evren yükleniyor…</p>
          </div>
          <div className="u-hud u-foot">
            <p className="u-legend hud-label" id="legend" hidden>
              <span className="legend-item">
                <span className="pip" aria-hidden="true" />
                çevrimiçi
              </span>{" "}
              <span className="legend-item">
                <span className="pip pip-off" aria-hidden="true" />
                çevrimdışı
              </span>{" "}
              <span className="legend-item">
                <span className="legend-link" aria-hidden="true" />
                iki tau da konuştuğunu bildiriyor
              </span>{" "}
              <span className="legend-item">
                <span className="legend-moon" aria-hidden="true" />
                açık bir sub-tau
              </span>
            </p>
            <p className="u-hint hud-label" aria-hidden="true">
              Döndürmek için sürükle · yakınlaşmak için kaydır · bir tau’ya tıkla
            </p>
          </div>
          <div className="u-hud u-tools" role="toolbar" aria-label="Görünüm">
            <button
              className="u-tool u-icon"
              id="zoom-in"
              type="button"
              aria-label="Yakınlaş"
              title="Yakınlaş"
            >
              <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                <path d="M8 3v10M3 8h10" />
              </svg>
            </button>{" "}
            <button
              className="u-tool u-icon"
              id="zoom-out"
              type="button"
              aria-label="Uzaklaş"
              title="Uzaklaş"
            >
              <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                <path d="M3 8h10" />
              </svg>
            </button>{" "}
            <button
              className="u-tool u-icon"
              id="reset-view"
              type="button"
              aria-label="Bütün evreni göster"
              title="Bütün evreni göster"
            >
              <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                <path d="M1.5 5V1.5H5M11 1.5h3.5V5M14.5 11v3.5H11M5 14.5H1.5V11" />
                <path d="M8 4.5l3.2 5.6H4.8z" />
              </svg>
            </button>{" "}
            <button
              className="u-tool"
              id="open-list"
              type="button"
              aria-controls="panel"
              aria-expanded="false"
            >
              Tau’lar <span className="u-tool-count" id="list-count" />
            </button>{" "}
            <button
              className="u-tool"
              id="open-join"
              type="button"
              aria-controls="panel"
              aria-expanded="false"
            >
              tau’nu ekle
            </button>
          </div>
          <aside className="cosmos-card" id="cosmos-card" aria-hidden="true" hidden />
          <aside className="u-panel chamfer" id="panel" aria-label="Tau’lar ve ayrıntılar" hidden>
            <div className="u-panel-bar">
              <button className="u-back hud-label" id="panel-back" type="button" hidden>
                ← Bütün tau’lar
              </button>{" "}
              <button
                className="u-close u-icon"
                id="panel-close"
                type="button"
                aria-label="Kapat"
                title="Kapat"
              >
                <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                  <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" />
                </svg>
              </button>
            </div>
            <div className="u-panel-body">
              <section className="u-roster" id="roster" aria-labelledby="taus-title">
                <div className="u-roster-head">
                  <h2 id="taus-title" tabIndex={-1}>
                    Tau’lar
                  </h2>
                  <p className="u-roster-count hud-label" id="roster-count" />
                </div>
                <p className="u-roster-empty" id="roster-empty" hidden />
                <ul className="u-list" id="tau-list" />
              </section>
              <section
                className="u-detail"
                id="detail"
                aria-live="polite"
                aria-label="Seçili tau"
                hidden
              />
              <section className="u-join" id="join" aria-labelledby="join-title" hidden>
                <h2 id="join-title" tabIndex={-1}>
                  tau’nu ekle
                </h2>
                <p>Adresi ve yayımlanmış bir kartı olan bir tau’da, hub’ında şunu çalıştır:</p>
                <div className="command chamfer">
                  <code id="join-command">tau net universe join</code>{" "}
                  <button className="copy" type="button" data-copy="join-command">
                    Kopyala
                  </button>
                </div>
                <p>
                  Hub’ın isteği kendi anahtarıyla imzalar; bu yüzden tau’nu senden başkası
                  listeleyemez ya da kaldıramaz. Başka bir tau’yla aranızdaki çizgi, ikiniz de
                  birbirinizi bildirdiğinde görünür. <code>tau net universe leave</code> tau’nu
                  haritadan kaldırır. Barındırılan bir tau, ayarlarından katılır.
                </p>
                <p>
                  <a href="https://docs.tau.getporti.com/tr/guides/tau-network/">
                    Ağ kılavuzunu oku
                  </a>
                </p>
              </section>
            </div>
          </aside>
          <p className="u-readout hud-label" aria-hidden="true">
            Sinyal haritası · yalnızca karşılıklı bağlar
          </p>
        </section>
      </main>
      <PageScript name="universe" />
    </div>
  );
}
