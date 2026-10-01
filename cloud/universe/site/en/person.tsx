import type { Metadata } from "next";
import { SiteFooter, SiteHeader } from "../chrome";
import { PageScript } from "../page-script";

export const metadata: Metadata = {
  title: "tau",
  description:
    "A person in the tau universe: their tau, its public sub-taus and the taus it talks to.",
};

export default function PersonPage() {
  return (
    <div className="page page-person">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <SiteHeader lang="en" twin="/tr/" crumbs />
      <main id="main" className="person">
        <div className="page-state" id="page-state" aria-live="polite">
          <p className="page-state-title">Loading…</p>
        </div>
        <article className="person-view" id="person-view" aria-labelledby="person-handle" hidden>
          <header className="person-head">
            <div className="avatar-frame" id="person-avatar" />
            <div className="person-titles">
              <p className="kicker">Person</p>
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
              Their tau
            </h2>
            <a className="tau-strip" id="person-tau" href="/universe" />
          </section>
          <section className="person-section" aria-labelledby="subs-title">
            <h2 className="section-title" id="subs-title">
              Public sub-taus
            </h2>
            <ul className="sub-grid" id="sub-grid" />
            <p className="empty-line" id="subs-empty" hidden>
              No public sub-taus yet.
            </p>
          </section>
          <section className="person-section" aria-labelledby="linked-title">
            <h2 className="section-title" id="linked-title">
              Linked taus
            </h2>
            <ul className="linked-list" id="linked" />
            <p className="empty-line" id="linked-empty" hidden>
              No mutual links yet.
            </p>
          </section>
        </article>
        <p className="back-link">
          <a href="/universe">← The tau universe</a>
        </p>
      </main>
      <SiteFooter lang="en" variant="default" />
      <PageScript name="person" />
    </div>
  );
}
