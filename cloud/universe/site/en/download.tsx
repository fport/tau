import type { Metadata } from "next";
import { SiteFooter, SiteHeader } from "../chrome";
import { PageScript } from "../page-script";

export const metadata: Metadata = {
  title: "Download tau",
  description:
    "Download tau: the Mac app for macOS 13 or later, with a setup wizard on the first launch, or one command in a terminal on macOS, Linux and the Raspberry Pi.",
  openGraph: {
    type: "website",
    title: "Download tau",
    description: "The Mac app, or one command in a terminal.",
  },
  alternates: {
    languages: {
      en: "https://tau.getporti.com/download",
      tr: "https://tau.getporti.com/tr/download",
      "x-default": "https://tau.getporti.com/download",
    },
  },
};

export default function DownloadPage() {
  return (
    <div className="page page-download">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <SiteHeader lang="en" twin="/tr/download" />
      <main id="main" className="explainer">
        <section className="intro" aria-labelledby="intro-title">
          <p className="kicker">
            <span className="kicker-accent">Download</span>
            <span className="kicker-sep" aria-hidden="true">
              ·
            </span>
            <span>Free</span>
            <span className="kicker-sep" aria-hidden="true">
              ·
            </span>
            <span>Runs on your own machine</span>
          </p>
          <h1 id="intro-title">Get tau.</h1>
          <p className="intro-lead">
            The Mac app puts tau in your menu bar, runs it in the background and sets everything up
            the first time you open it. On Linux and the Raspberry Pi, one command in a terminal
            does the same.
          </p>
          <div className="get">
            <section className="get-way get-app chamfer" aria-labelledby="get-app-title">
              <div className="get-head">
                <img
                  className="get-icon"
                  src="/brand/tau-app-icon.svg"
                  width="64"
                  height="64"
                  alt=""
                />
                <div>
                  <h2 className="get-name" id="get-app-title">
                    tau for Mac
                  </h2>
                  <p className="get-meta hud-label">macOS 13 or later · Apple silicon and Intel</p>
                </div>
              </div>
              <a
                className="button button-primary"
                href="/download/tau.dmg"
              >
                <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                  <path d="M7 1h2v7.6l2.8-2.8 1.4 1.4L8 12.4 2.8 7.2l1.4-1.4L7 8.6zM2 13h12v2H2z" />
                </svg>
                Download tau.dmg
              </a>
              <p className="get-note">
                A menu bar app, chat windows and a setup wizard, in one download. Apple has not
                notarised it yet, so macOS asks once before it opens:{" "}
                <a href="#first-open">how to open it</a>.
              </p>
            </section>
            <section className="get-way get-terminal chamfer" aria-labelledby="get-terminal-title">
              <div className="get-head">
                <div>
                  <h2 className="get-name" id="get-terminal-title">
                    One command
                  </h2>
                  <p className="get-meta hud-label">macOS · Linux · Raspberry Pi</p>
                </div>
              </div>
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
              <p className="get-note">
                It installs tau in your home folder and asks which features you want. It never runs{" "}
                <code>sudo</code>. <a href="#terminal">What it does</a>.
              </p>
            </section>
          </div>
        </section>
        <section className="chapter" id="first-open" aria-labelledby="first-open-title">
          <h2 id="first-open-title">Opening it the first time.</h2>
          <p className="chapter-lead">
            tau is signed, but Apple has not notarised it yet, so macOS stops it the first time and
            says it cannot check it for malicious software. That is expected. You allow it once, and
            from then on tau opens like any other app.
          </p>
          <div className="row">
            <ol className="steps">
              <li>
                <h3>Drag tau to Applications.</h3>
                <p>
                  Open <code>tau.dmg</code> and drag <strong>tau</strong> onto the{" "}
                  <strong>Applications</strong> folder.
                </p>
              </li>
              <li>
                <h3>Open it once.</h3>
                <p>
                  Open tau from Applications. When macOS says it cannot check tau, close the
                  message. Do not move tau to the Trash.
                </p>
              </li>
              <li>
                <h3>Choose Open Anyway.</h3>
                <p>
                  Open <strong>System Settings → Privacy & Security</strong>, scroll down to the
                  line about tau and choose <strong>Open Anyway</strong>. Confirm with your password
                  or Touch ID.
                </p>
              </li>
              <li>
                <h3>Or right-click → Open.</h3>
                <p>
                  On macOS 13 and 14 there is a shorter way: right-click tau in Applications, choose{" "}
                  <strong>Open</strong>, then <strong>Open</strong> again. macOS 15 and later only
                  offer the way above.
                </p>
              </li>
            </ol>
            <aside className="fig why" aria-labelledby="why-title">
              <h3 id="why-title">Why macOS asks</h3>
              <p>
                Notarisation is Apple’s check of an app from outside the App Store, and it needs
                Apple’s paid developer programme. tau does not use it yet.
              </p>
              <p>
                Every release is signed with the same certificate instead, so macOS keeps the
                permissions you give tau, such as the camera and notifications, across updates. tau
                looks for updates by itself and asks before it installs one.
              </p>
            </aside>
          </div>
        </section>
        <section className="chapter" id="first-launch" aria-labelledby="first-launch-title">
          <h2 id="first-launch-title">What the first launch does.</h2>
          <p className="chapter-lead">
            The first time tau opens, a setup wizard walks you through eight steps. You can skip any
            of them, and <strong>Set up tau…</strong> in the menu opens the wizard again to add or
            remove features later.
          </p>
          <ol className="wizard">
            <li className="chamfer">
              <h3>Language</h3>
              <p>English or Turkish, for the wizard and everything tau says.</p>
            </li>
            <li className="chamfer">
              <h3>Install tau</h3>
              <p>
                The wizard finds tau, or installs it with uv in your home folder. No administrator
                password.
              </p>
            </li>
            <li className="chamfer">
              <h3>Model key</h3>
              <p>
                Your provider and its key, checked with one small request and kept on your Mac,
                readable only by you.
              </p>
            </li>
            <li className="chamfer">
              <h3>About you</h3>
              <p>
                Optional: your name, how tau should address you and your languages. It stays on your
                Mac.
              </p>
            </li>
            <li className="chamfer">
              <h3>Features</h3>
              <p>
                Choose what tau should do: Telegram, remote access, the owner guard, the tau network
                and <a href="#features">more</a>.
              </p>
            </li>
            <li className="chamfer">
              <h3>Permissions</h3>
              <p>
                Only what your features need, the camera for the guard and notifications for the
                app. macOS asks you in tau’s name.
              </p>
            </li>
            <li className="chamfer">
              <h3>Feature steps</h3>
              <p>
                Each feature is set up live: pairing your Telegram bot, enrolling your face, your
                tau’s address. A command that needs <code>sudo</code> is shown for you to run; tau
                never runs it.
              </p>
            </li>
            <li className="chamfer">
              <h3>Summary</h3>
              <p>What is on and what was skipped, then a chat window or the hub, one click away.</p>
            </li>
          </ol>
        </section>
        <section className="chapter" id="terminal" aria-labelledby="terminal-title">
          <h2 id="terminal-title">The terminal way.</h2>
          <p className="chapter-lead">
            On macOS, Linux and the Raspberry Pi (a 64-bit system), one command installs tau and
            starts the same setup, as questions in the terminal.
          </p>
          <div className="row">
            <div className="prose">
              <div className="command chamfer">
                <code id="terminal-command">
                  curl -fsSL https://tau.getporti.com/install.sh | sh
                </code>{" "}
                <button
                  className="copy"
                  type="button"
                  data-copy="terminal-command"
                  aria-describedby="terminal-command"
                >
                  Copy
                </button>
              </div>
              <p>It is a short shell script, and you can read it before you run it:</p>
              <div className="command chamfer">
                <code id="read-command">curl -fsSL https://tau.getporti.com/install.sh | less</code>{" "}
                <button
                  className="copy"
                  type="button"
                  data-copy="read-command"
                  aria-describedby="read-command"
                >
                  Copy
                </button>
              </div>
              <p>
                To install tau without the questions, and run <code>tau setup</code> yourself later:
              </p>
              <div className="command chamfer">
                <code id="quiet-command">
                  curl -fsSL https://tau.getporti.com/install.sh | TAU_INSTALL_NO_SETUP=1 sh
                </code>{" "}
                <button
                  className="copy"
                  type="button"
                  data-copy="quiet-command"
                  aria-describedby="quiet-command"
                >
                  Copy
                </button>
              </div>
              <p>
                Run <code>tau setup</code> again whenever you want another feature. What is set up
                already is never asked again.
              </p>
            </div>
            <aside className="fig" aria-labelledby="script-title">
              <h3 id="script-title" className="fig-title">
                What the script does
              </h3>
              <ol className="steps steps-small">
                <li>
                  <p>Checks that this is macOS or Linux on a 64-bit Intel or ARM processor.</p>
                </li>
                <li>
                  <p>
                    Installs uv, the Python installer tau uses, when it is missing. uv brings its
                    own Python.
                  </p>
                </li>
                <li>
                  <p>
                    Installs tau with <code>uv tool install tau-core --with tau-tui</code>, in its
                    own folder.
                  </p>
                </li>
                <li>
                  <p>
                    Starts <code>tau setup</code>: your language, the features you want, your model
                    key, then each feature’s steps.
                  </p>
                </li>
              </ol>
              <p className="fig-note">
                It never runs <code>sudo</code>, and a tau that is already installed is left as it
                is.
              </p>
            </aside>
          </div>
        </section>
        <section className="chapter" id="manual" aria-labelledby="manual-title">
          <h2 id="manual-title">By hand.</h2>
          <p className="chapter-lead">
            With uv installed, every part of tau is a package on PyPI. Pick them yourself, then let{" "}
            <code>tau setup</code> do the rest.
          </p>
          <div className="prose prose-wide">
            <pre className="command-block">
              <code>
                {"uv tool install tau-core --with tau-tui --with tau-net --with tau-sub\ntau setup"}
              </code>
            </pre>
            <p>
              <code>tau-core</code> is the agent and the <code>tau</code> command,{" "}
              <code>tau-tui</code> the full-screen terminal interface, <code>tau-net</code> the tau
              network and <code>tau-sub</code> sub-taus. The{" "}
              <a href="https://docs.tau.getporti.com/getting-started/install/">install guide</a>{" "}
              also covers installing from the source.
            </p>
          </div>
        </section>
        <section className="chapter" id="features" aria-labelledby="features-title">
          <h2 id="features-title">What you can set up.</h2>
          <p className="chapter-lead">
            The wizard, in the app or in the terminal, offers the same features. Nothing that
            reaches outside your machine is on unless you choose it.
          </p>
          <ul className="features">
            <li>
              <h3>Terminal UI</h3>
              <p>
                The full-screen interface, <code>tau tui</code>.
              </p>
              <p className="feature-where hud-label">macOS · Linux · on by default</p>
            </li>
            <li>
              <h3>The tau app</h3>
              <p>The menu bar, chat windows and the hub’s supervisor.</p>
              <p className="feature-where hud-label">macOS</p>
            </li>
            <li>
              <h3>Sub-taus</h3>
              <p>Named specialists of your tau: a coach, a chef, a tutor.</p>
              <p className="feature-where hud-label">macOS · Linux · on by default</p>
            </li>
            <li>
              <h3>Telegram</h3>
              <p>Talk to tau from your phone through your own bot, paired with a one-time code.</p>
              <p className="feature-where hud-label">macOS · Linux</p>
            </li>
            <li>
              <h3>Remote access</h3>
              <p>Reach your machine from your phone over Tailscale and SSH.</p>
              <p className="feature-where hud-label">macOS · Linux</p>
            </li>
            <li>
              <h3>Owner guard</h3>
              <p>
                tau answers only while you are at the Mac: a face check, Touch ID as the fallback.
              </p>
              <p className="feature-where hud-label">macOS · camera</p>
            </li>
            <li>
              <h3>The tau network</h3>
              <p>An address for your tau, contacts with other taus and the universe.</p>
              <p className="feature-where hud-label">macOS · Linux · free Cloudflare account</p>
            </li>
            <li>
              <h3>Start at login</h3>
              <p>The hub starts when you log in and keeps running.</p>
              <p className="feature-where hud-label">macOS · Linux · on by default on macOS</p>
            </li>
            <li>
              <h3>Cloud mode</h3>
              <p>Advanced: run tau in your own Cloudflare account instead.</p>
              <p className="feature-where hud-label">macOS · Linux</p>
            </li>
          </ul>
          <div className="actions actions-start">
            <a className="button" href="https://docs.tau.getporti.com/guides/setup-features/">
              Every feature, step by step
            </a>{" "}
            <a className="button" href="https://docs.tau.getporti.com/getting-started/install/">
              The install guide
            </a>
          </div>
        </section>
      </main>
      <SiteFooter lang="en" variant="default" />
      <PageScript name="download" />
    </div>
  );
}
