import type { Metadata } from "next";
import { SiteHeader } from "../chrome";
import { PageScript } from "../page-script";

export const metadata: Metadata = {
  title: "Barındırılan tau'lar · tau",
  robots: "noindex",
};

export default function SoonPage() {
  return (
    <div className="page page-missing">
      <SiteHeader lang="tr" twin="/" />
      <main id="main" className="missing">
        <img className="missing-mark" src="/brand/tau-mark.svg" width="128" height="128" alt="" />
        <p className="kicker">Barındırılan · yakında</p>
        <h1 className="chrome">Giriş yakında açılıyor.</h1>
        <p>
          GitHub ile giriş yapıp yalnızca model anahtarını getirdiğin barındırılan tau'lar bu
          evrende henüz açık değil. O zamana kadar tau'yu kendi makinende çalıştırabilir ya da
          barındırılan uygulamayı kendi Cloudflare hesabına kurabilirsin.
        </p>
        <div className="actions">
          <a className="button button-primary" href="/tr/download">
            Kendi makinende çalıştır
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
