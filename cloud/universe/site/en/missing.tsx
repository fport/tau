import type { Metadata } from "next";
import { SiteHeader } from "../chrome";
import { PageScript } from "../page-script";

export const metadata: Metadata = {
  title: "Not found · tau",
  robots: "noindex",
};

export default function MissingPage() {
  return (
    <div className="page page-missing">
      <SiteHeader lang="en" twin="/tr/" />
      <main id="main" className="missing">
        <img className="missing-mark" src="/brand/tau-mark.svg" width="128" height="128" alt="" />
        <p className="kicker">404 · no signal</p>
        <h1 className="chrome">Nothing at this address.</h1>
        <p>
          The page you asked for does not exist. The home page, the guide to how tau works and the
          universe are still here.
        </p>
        <div className="actions">
          <a className="button button-primary" href="/">
            Go to the home page
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
