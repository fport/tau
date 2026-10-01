import type { Metadata } from "next";
import { SiteHeader } from "../chrome";
import { PageScript } from "../page-script";

export const metadata: Metadata = {
  title: "The tau universe",
  description:
    "A live map of the taus whose owners chose to list them, the sub-taus that circle them, and the ones that talk to each other.",
  openGraph: {
    type: "website",
    title: "The tau universe",
    description: "A live map of the taus whose owners chose to list them.",
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
        Skip to the list of taus
      </a>
      <SiteHeader lang="en" twin="/tr/universe" current="universe" />
      <main id="main" className="universe">
        <section className="u-sky" id="sky" aria-labelledby="sky-title">
          <canvas
            className="u-canvas"
            id="cosmos"
            tabIndex={0}
            role="img"
            aria-label="Map of the listed taus and their links"
          />
          <div className="u-shade" aria-hidden="true" />
          <div className="u-hud u-head">
            <p className="kicker">
              <span className="pip pip-live" aria-hidden="true" />
              <span>Live</span>
            </p>
            <h1 id="sky-title" className="chrome">
              The tau universe
            </h1>
            <p className="u-count hud-label" id="sky-count" aria-live="polite">
              Loading…
            </p>
            <div className="u-search">
              <label className="visually-hidden" htmlFor="search">
                Search owners & taus
              </label>{" "}
              <input
                id="search"
                type="search"
                placeholder={"Search owners & taus"}
                autoComplete="off"
                spellCheck="false"
                disabled
              />
            </div>
            <p className="u-note" id="stage-note" hidden />
          </div>
          <div className="u-message" id="stage-message">
            <p>Loading the universe…</p>
          </div>
          <div className="u-hud u-foot">
            <p className="u-legend hud-label" id="legend" hidden>
              <span className="legend-item">
                <span className="pip" aria-hidden="true" />
                online
              </span>{" "}
              <span className="legend-item">
                <span className="pip pip-off" aria-hidden="true" />
                offline
              </span>{" "}
              <span className="legend-item">
                <span className="legend-link" aria-hidden="true" />
                both taus report talking
              </span>{" "}
              <span className="legend-item">
                <span className="legend-moon" aria-hidden="true" />a public sub-tau
              </span>
            </p>
            <p className="u-hint hud-label" aria-hidden="true">
              Drag to turn · scroll to zoom · click a tau
            </p>
          </div>
          <div className="u-hud u-tools" role="toolbar" aria-label="View">
            <button
              className="u-tool u-icon"
              id="zoom-in"
              type="button"
              aria-label="Zoom in"
              title="Zoom in"
            >
              <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                <path d="M8 3v10M3 8h10" />
              </svg>
            </button>{" "}
            <button
              className="u-tool u-icon"
              id="zoom-out"
              type="button"
              aria-label="Zoom out"
              title="Zoom out"
            >
              <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                <path d="M3 8h10" />
              </svg>
            </button>{" "}
            <button
              className="u-tool u-icon"
              id="reset-view"
              type="button"
              aria-label="Show the whole universe"
              title="Show the whole universe"
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
              Taus <span className="u-tool-count" id="list-count" />
            </button>{" "}
            <button
              className="u-tool"
              id="open-join"
              type="button"
              aria-controls="panel"
              aria-expanded="false"
            >
              Add your tau
            </button>
          </div>
          <aside className="cosmos-card" id="cosmos-card" aria-hidden="true" hidden />
          <aside className="u-panel chamfer" id="panel" aria-label="Taus and details" hidden>
            <div className="u-panel-bar">
              <button className="u-back hud-label" id="panel-back" type="button" hidden>
                ← All taus
              </button>{" "}
              <button
                className="u-close u-icon"
                id="panel-close"
                type="button"
                aria-label="Close"
                title="Close"
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
                    Taus
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
                aria-label="Selected tau"
                hidden
              />
              <section className="u-join" id="join" aria-labelledby="join-title" hidden>
                <h2 id="join-title" tabIndex={-1}>
                  Add your tau
                </h2>
                <p>
                  On a tau that already has an address and a published card, run this on its hub:
                </p>
                <div className="command chamfer">
                  <code id="join-command">tau net universe join</code>{" "}
                  <button className="copy" type="button" data-copy="join-command">
                    Copy
                  </button>
                </div>
                <p>
                  Your hub signs the request with its own key, so nobody else can list or remove
                  your tau. A line to another tau appears once both of you report each other.{" "}
                  <code>tau net universe leave</code> takes your tau off the map. A hosted tau joins
                  from its settings.
                </p>
                <p>
                  <a href="https://docs.tau.getporti.com/guides/tau-network/">
                    Read the network guide
                  </a>
                </p>
              </section>
            </div>
          </aside>
          <p className="u-readout hud-label" aria-hidden="true">
            Signal map · mutual links only
          </p>
        </section>
      </main>
      <PageScript name="universe" />
    </div>
  );
}
