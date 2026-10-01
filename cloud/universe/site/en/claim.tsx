import type { Metadata } from "next";
import { SiteFooter, SiteHeader } from "../chrome";
import { PageScript } from "../page-script";

export const metadata: Metadata = {
  title: "Claim a handle · tau",
  description: "Bind your GitHub handle to your tau in the tau universe.",
  robots: "noindex",
};

export default function ClaimPage() {
  return (
    <div className="page page-claim">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <SiteHeader lang="en" twin="/tr/claim" crumbs />
      <main id="main" className="claim">
        <section className="claim-panel" aria-labelledby="claim-title">
          <p className="kicker">Handle claim</p>
          <h1 id="claim-title" className="chrome">
            Bind your GitHub handle to your tau
          </h1>
          <p className="claim-lead">
            Sign in with GitHub. The universe checks your tau’s signature and your GitHub account,
            then shows your tau at <code>/@your-login</code>.
          </p>
          <dl className="facts claim-facts" id="claim-view" hidden>
            <div>
              <dt>Tau</dt>
              <dd>
                <code id="claim-address" />
              </dd>
            </div>
            <div>
              <dt>Universe</dt>
              <dd>
                <code id="claim-universe" />
              </dd>
            </div>
            <div>
              <dt>Link</dt>
              <dd id="claim-expires" />
            </div>
          </dl>
          <div className="actions actions-start claim-actions" id="claim-actions">
            <a className="button button-primary" id="claim-signin" href="/auth/login">
              <svg className="gh" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
              </svg>
              Sign in with GitHub and bind
            </a>{" "}
            <button className="button" id="claim-now" type="button">
              Signed in already? Bind now
            </button>
          </div>
          <div className="claim-result" id="claim-result" role="status" aria-live="polite" hidden />
          <p className="claim-note">
            One handle points to one tau. A new claim from the same GitHub account moves it; a claim
            from another account is refused. The link in your terminal is valid for an hour.
          </p>
        </section>
        <p className="back-link">
          <a href="/universe">← The tau universe</a>
        </p>
      </main>
      <SiteFooter lang="en" variant="default" />
      <PageScript name="claim" />
    </div>
  );
}
