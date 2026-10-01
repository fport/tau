import type { Metadata } from "next";
import { SiteFooter, SiteHeader } from "../chrome";
import { PageScript } from "../page-script";

export const metadata: Metadata = {
  title: "tau",
  description: "tau evreninde bir kişi: tau’su, açık sub-tau’ları ve konuştuğu tau’lar.",
};

export default function PersonPage() {
  return (
    <div className="page page-person">
      <a className="skip" href="#main">
        İçeriğe geç
      </a>
      <SiteHeader lang="tr" twin="/" crumbs />
      <main id="main" className="person">
        <div className="page-state" id="page-state" aria-live="polite">
          <p className="page-state-title">Yükleniyor…</p>
        </div>
        <article className="person-view" id="person-view" aria-labelledby="person-handle" hidden>
          <header className="person-head">
            <div className="avatar-frame" id="person-avatar" />
            <div className="person-titles">
              <p className="kicker">Kişi</p>
              <h1 className="person-handle chrome" id="person-handle">
                @
              </h1>
              <p className="person-links">
                <a className="person-github" id="person-github" href="#">
                  github.com
                </a>{" "}
                <span className="person-since" id="person-since" />
              </p>
              <p className="person-counts kicker" id="person-counts" />
            </div>
          </header>
          <section className="person-section" aria-labelledby="tau-title">
            <h2 className="section-title" id="tau-title">
              Kendi tau’su
            </h2>
            <a className="tau-strip" id="person-tau" href="/tr/universe" />
          </section>
          <section className="person-section" aria-labelledby="subs-title">
            <h2 className="section-title" id="subs-title">
              Açık sub-tau’lar
            </h2>
            <ul className="sub-grid" id="sub-grid" />
            <p className="empty-line" id="subs-empty" hidden>
              Henüz açık sub-tau yok.
            </p>
          </section>
          <section className="person-section" aria-labelledby="linked-title">
            <h2 className="section-title" id="linked-title">
              Bağlantılı tau’lar
            </h2>
            <ul className="linked-list" id="linked" />
            <p className="empty-line" id="linked-empty" hidden>
              Henüz karşılıklı bağlantı yok.
            </p>
          </section>
        </article>
        <p className="back-link">
          <a href="/tr/universe">← tau evreni</a>
        </p>
      </main>
      <SiteFooter lang="tr" variant="default" />
      <PageScript name="person" />
    </div>
  );
}
