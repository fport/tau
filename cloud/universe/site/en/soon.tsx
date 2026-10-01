import type { Metadata } from "next";
import { SiteHeader } from "../chrome";
import { PageScript } from "../page-script";

export const metadata: Metadata = {
  title: "Hosted taus · tau",
  robots: "noindex",
};

export default function SoonPage() {
  return (
    <div className="page page-missing">
      <SiteHeader lang="en" twin="/tr/" />
      <main id="main" className="missing">
        <img className="missing-mark" src="/brand/tau-mark.svg" width="128" height="128" alt="" />
        <p className="kicker">Hosted · opening soon</p>
        <h1 className="chrome">Sign-in opens soon.</h1>
        <p>
          Hosted taus, where you sign in with GitHub and bring only your model key, are not open on
          this universe yet. Until then you can run tau on your own machine, or deploy the hosted
          app into your own Cloudflare account.
        </p>
        <div className="actions">
          <a className="button button-primary" href="/download">
            Run it on your machine
          </a>{" "}
          <a className="button" href="/universe">
            Explore the universe
          </a>
        </div>
      </main>
      <PageScript name="sky" />
    </div>
  );
}
