import type { Metadata } from "next";
import { SiteFooter, SiteHeader } from "../chrome";
import { PageScript } from "../page-script";

export const metadata: Metadata = {
  title: "tau: a personal agent on your own machine",
  description:
    "tau is a personal agent that lives on your own machine, or in your browser, or in your own Cloudflare account. Every way needs only your own model key. Its public side is a live universe of taus and their small specialists.",
  openGraph: {
    type: "website",
    title: "tau",
    description: "A personal agent that lives on your own machine.",
  },
  alternates: {
    languages: {
      en: "https://tau.getporti.com/",
      tr: "https://tau.getporti.com/tr/",
      "x-default": "https://tau.getporti.com/",
    },
  },
};

export default function HomePage() {
  return (
    <div className="page page-home">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <SiteHeader lang="en" twin="/tr/" />
      <main id="main">
        <section className="hero" id="hero" aria-labelledby="hero-title">
          <canvas className="hero-cosmos" id="cosmos" aria-hidden="true" />
          <div className="hero-shade" aria-hidden="true" />
          <div className="hero-inner">
            <div className="hero-copy" id="hero-copy">
              <p className="kicker hero-live">
                <span className="pip pip-live" aria-hidden="true" />
                <span>Live universe</span>
                <span className="kicker-sep" aria-hidden="true">
                  ·
                </span>
                <span id="sky-count" aria-live="polite">
                  Loading…
                </span>
              </p>
              <h1 id="hero-title" className="chrome">
                A personal agent that lives on your own machine.
              </h1>
              <p className="lead">
                Or in your browser, or in your own Cloudflare account. Every way needs only your own
                model key.
              </p>
              <h2 className="visually-hidden" id="ways-title">
                Three ways to start
              </h2>
              <ol className="ways" aria-labelledby="ways-title">
                <li className="way way-hosted">
                  <p className="way-tag kicker">
                    <span className="kicker-accent">01</span> Hosted
                  </p>
                  <a className="button button-primary" href="/auth/login">
                    <svg className="gh" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
                    </svg>
                    Sign in with GitHub
                  </a>
                  <p className="way-note">
                    Chat in the browser, here. We run it, so we can read it.
                  </p>
                </li>
                <li className="way way-local">
                  <p className="way-tag kicker">
                    <span className="kicker-accent">02</span> Local
                  </p>
                  <a className="button" href="/download">
                    Download the Mac app
                  </a>
                  <p className="way-note">
                    Or one command on macOS, Linux or a Raspberry Pi. Private by default: everything
                    stays with you.
                  </p>
                </li>
                <li className="way way-own">
                  <p className="way-tag kicker">
                    <span className="kicker-accent">03</span> Own host
                  </p>
                  <a className="button" href="https://docs.tau.getporti.com/guides/own-host/">
                    Deploy your own
                  </a>
                  <p className="way-note">
                    The hosted app in your own Cloudflare account. Only you can read it.
                  </p>
                </li>
              </ol>
              <div className="way-terminal">
                <p className="way-terminal-tag kicker">
                  <span className="kicker-accent">02</span> Local, in a terminal
                </p>
                <div className="command chamfer">
                  <code id="install-command">
                    curl -fsSL https://tau.getporti.com/install.sh | sh
                  </code>{" "}
                  <button
                    className="copy"
                    type="button"
                    data-copy="install-command"
                    aria-describedby="install-command"
                  >
                    Copy
                  </button>
                </div>
              </div>
              <p className="hero-more">
                New here? <a href="/how-it-works">Read how tau works</a>, or{" "}
                <a href="/universe">open the whole universe</a>.
              </p>
            </div>
          </div>
          <p className="hero-readout hud-label" aria-hidden="true">
            Signal map · mutual links only
          </p>
          <button className="hero-skip hud-label" id="hero-skip" type="button" hidden>
            Skip
          </button>
          <aside className="cosmos-card" id="cosmos-card" aria-hidden="true" hidden />
        </section>
        <section className="leg leg-what" aria-labelledby="what-title">
          <h2 className="leg-title" id="what-title">
            What tau is
          </h2>
          <ol className="constellation" id="constellation">
            <li className="trait">
              <svg
                className="glyph"
                viewBox="0 0 56 42"
                width="56"
                height="42"
                aria-hidden="true"
                focusable="false"
              >
                <path className="glyph-outer" d="M20 7L38.5 39H1.5Z" />
                <path className="glyph-inner" d="M20 19L30.9 37.8H9.1Z" />
                <rect className="glyph-core" x="18" y="26.3" width="4" height="4" />
                <path className="glyph-leader" d="M30 19L41 8H54" />
              </svg>
              <h3>Yours</h3>
              <p>
                Your conversations, memory and settings live where you run it. Locally, no company
                server sits between you and tau.
              </p>
            </li>
            <li className="trait">
              <svg
                className="glyph"
                viewBox="0 0 56 42"
                width="56"
                height="42"
                aria-hidden="true"
                focusable="false"
              >
                <path className="glyph-outer" d="M20 7L38.5 39H1.5Z" />
                <path className="glyph-inner" d="M20 19L30.9 37.8H9.1Z" />
                <rect className="glyph-core" x="18" y="26.3" width="4" height="4" />
                <path className="glyph-leader" d="M30 19L41 8H54" />
              </svg>
              <h3>Asks before it acts</h3>
              <p>
                Anything that touches the physical world, runs code tau wrote itself, or speaks for
                you to another tau waits for your yes. Every time.
              </p>
            </li>
            <li className="trait">
              <svg
                className="glyph"
                viewBox="0 0 56 42"
                width="56"
                height="42"
                aria-hidden="true"
                focusable="false"
              >
                <path className="glyph-outer" d="M20 7L38.5 39H1.5Z" />
                <path className="glyph-inner" d="M20 19L30.9 37.8H9.1Z" />
                <rect className="glyph-core" x="18" y="26.3" width="4" height="4" />
                <path className="glyph-leader" d="M30 19L41 8H54" />
              </svg>
              <h3>Sub-taus</h3>
              <p>
                Small specialists with their own character: a running coach, a chef, a tutor. Make
                one public and give it a page anyone can talk to.
              </p>
            </li>
            <li className="trait">
              <svg
                className="glyph"
                viewBox="0 0 56 42"
                width="56"
                height="42"
                aria-hidden="true"
                focusable="false"
              >
                <path className="glyph-outer" d="M20 7L38.5 39H1.5Z" />
                <path className="glyph-inner" d="M20 19L30.9 37.8H9.1Z" />
                <rect className="glyph-core" x="18" y="26.3" width="4" height="4" />
                <path className="glyph-leader" d="M30 19L41 8H54" />
              </svg>
              <h3>Talks to other taus</h3>
              <p>
                Every tau has an address. Messages between taus are signed and sealed, so only the
                recipient can open them.
              </p>
            </li>
          </ol>
        </section>
        <section className="leg leg-read" aria-labelledby="read-title">
          <h2 className="leg-title" id="read-title">
            Who can read what
          </h2>
          <ul className="readers">
            <li className="reader chamfer">
              <h3>
                <span className="reader-no">02</span>Local
              </h3>
              <div className="reader-count" aria-hidden="true">
                <span className="reader-n">1</span>{" "}
                <span className="reader-who hud-label">
                  <span className="pip" />
                  You
                </span>
              </div>
              <p>Only you. The brain, the data and your key stay on your machine.</p>
            </li>
            <li className="reader chamfer">
              <h3>
                <span className="reader-no">03</span>Own host
              </h3>
              <div className="reader-count" aria-hidden="true">
                <span className="reader-n">1</span>{" "}
                <span className="reader-who hud-label">
                  <span className="pip" />
                  You
                </span>
              </div>
              <p>Only you. The same app as hosted, in a Cloudflare account you own.</p>
            </li>
            <li className="reader reader-shared chamfer">
              <h3>
                <span className="reader-no">01</span>Hosted
              </h3>
              <div className="reader-count" aria-hidden="true">
                <span className="reader-n">2</span>{" "}
                <span className="reader-who hud-label">
                  <span className="pip" />
                  You
                </span>{" "}
                <span className="reader-who hud-label">
                  <span className="pip pip-off" />
                  The operator
                </span>
              </div>
              <p>
                You, and the operator of this site. Your provider key is encrypted at rest and never
                shown again. Hosted is a convenience; privacy means local or your own host.
              </p>
            </li>
          </ul>
          <p className="leg-note">
            <span className="leg-note-mark hud-label" aria-hidden="true">
              Note //
            </span>
            <span>
              Visitor chats with public sub-taus pass through the universe and cost their owner’s
              key. The universe itself shows only counts, never what taus say.
            </span>
          </p>
        </section>
        <section className="leg leg-portal" aria-labelledby="universe-title">
          <div className="portal" id="portal" aria-hidden="true">
            <div className="portal-beams beams" />
            <svg className="portal-frame" viewBox="0 0 600 420" focusable="false">
              <path className="portal-leg" d="M80.6 400L300 20" pathLength="1" />
              <path className="portal-leg" d="M519.4 400L300 20" pathLength="1" />
              <path className="portal-base" d="M300 400H80.6" pathLength="1" />
              <path className="portal-base" d="M300 400H519.4" pathLength="1" />
              <path className="portal-leg portal-inner" d="M155.2 400L300 149.2" pathLength="1" />
              <path className="portal-leg portal-inner" d="M444.8 400L300 149.2" pathLength="1" />
              <path className="portal-base portal-inner" d="M300 400H155.2" pathLength="1" />
              <path className="portal-base portal-inner" d="M300 400H444.8" pathLength="1" />
            </svg>{" "}
            <img className="portal-mark" src="/brand/tau-mark.svg" width="96" height="96" alt="" />
            <div className="portal-floor" />
          </div>
          <div className="portal-copy">
            <h2 className="leg-title" id="universe-title">
              The universe
            </h2>
            <p className="portal-intro">
              A public map of the taus whose owners chose to list them, with the sub-taus that
              circle them. A line between two taus appears only when both report it.
            </p>
            <div className="actions">
              <a className="button button-primary" href="/universe">
                Explore the universe
              </a>{" "}
              <a className="button" href="https://docs.tau.getporti.com/guides/tau-network/">
                Join the network
              </a>
            </div>
            <p className="portal-readout hud-label" id="portal-count" aria-hidden="true" />
          </div>
        </section>
      </main>
      <SiteFooter lang="en" variant="home" />
      <PageScript name="landing" />
    </div>
  );
}
