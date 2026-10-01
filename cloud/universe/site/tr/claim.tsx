import type { Metadata } from "next";
import { SiteFooter, SiteHeader } from "../chrome";
import { PageScript } from "../page-script";

export const metadata: Metadata = {
  title: "Kullanıcı adı talebi · tau",
  description: "GitHub kullanıcı adını tau evrenindeki tau’na bağla.",
  robots: "noindex",
};

export default function ClaimPage() {
  return (
    <div className="page page-claim">
      <a className="skip" href="#main">
        İçeriğe geç
      </a>
      <SiteHeader lang="tr" twin="/claim" crumbs />
      <main id="main" className="claim">
        <section className="claim-panel" aria-labelledby="claim-title">
          <p className="kicker">Kullanıcı adı talebi</p>
          <h1 id="claim-title" className="chrome">
            GitHub kullanıcı adını tau’na bağla
          </h1>
          <p className="claim-lead">
            GitHub ile giriş yap. Evren, tau’nun imzasını ve GitHub hesabını kontrol eder, sonra
            tau’nu <code>/@github-adın</code> adresinde gösterir.
          </p>
          <dl className="facts claim-facts" id="claim-view" hidden>
            <div>
              <dt>Tau</dt>
              <dd>
                <code id="claim-address" />
              </dd>
            </div>
            <div>
              <dt>Evren</dt>
              <dd>
                <code id="claim-universe" />
              </dd>
            </div>
            <div>
              <dt>Bağlantı</dt>
              <dd id="claim-expires" />
            </div>
          </dl>
          <div className="actions actions-start claim-actions" id="claim-actions">
            <a className="button button-primary" id="claim-signin" href="/auth/login">
              <svg className="gh" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
              </svg>
              GitHub ile giriş yap ve bağla
            </a>{" "}
            <button className="button" id="claim-now" type="button">
              Zaten giriş yaptın mı? Şimdi bağla
            </button>
          </div>
          <div className="claim-result" id="claim-result" role="status" aria-live="polite" hidden />
          <p className="claim-note">
            Bir kullanıcı adı tek bir tau’yu gösterir. Aynı GitHub hesabından gelen yeni bir talep
            onu taşır; başka bir hesaptan gelen talep reddedilir. Terminalindeki bağlantı bir saat
            geçerlidir.
          </p>
        </section>
        <p className="back-link">
          <a href="/tr/universe">← tau evreni</a>
        </p>
      </main>
      <SiteFooter lang="tr" variant="default" />
      <PageScript name="claim" />
    </div>
  );
}
