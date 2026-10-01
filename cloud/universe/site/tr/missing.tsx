import type { Metadata } from "next";
import { SiteHeader } from "../chrome";
import { PageScript } from "../page-script";

export const metadata: Metadata = {
  title: "Bulunamadı · tau",
  robots: "noindex",
};

export default function MissingPage() {
  return (
    <div className="page page-missing">
      <SiteHeader lang="tr" twin="/" />
      <main id="main" className="missing">
        <img className="missing-mark" src="/brand/tau-mark.svg" width="128" height="128" alt="" />
        <p className="kicker">404 · sinyal yok</p>
        <h1 className="chrome">Bu adreste bir şey yok.</h1>
        <p>
          Aradığın sayfa yok. Ana sayfa, tau’nun nasıl çalıştığını anlatan sayfa ve evren hâlâ
          burada.
        </p>
        <div className="actions">
          <a className="button button-primary" href="/tr/">
            Ana sayfaya git
          </a>{" "}
          <a className="button" href="/tr/universe">
            Evreni keşfet
          </a>
        </div>
      </main>
      <PageScript name="sky" />
    </div>
  );
}
