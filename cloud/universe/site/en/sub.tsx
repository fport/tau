import type { Metadata } from "next";
import { SiteFooter, SiteHeader } from "../chrome";
import { PageScript } from "../page-script";

export const metadata: Metadata = {
  title: "tau",
  description:
    "A public sub-tau in the tau universe: a small specialist of someone’s tau. Some take visitors: talk to it here.",
};

export default function SubPage() {
  return (
    <div className="page page-sub">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <SiteHeader lang="en" twin="/tr/" crumbs />
      <main id="main" className="subpage">
        <div className="page-state" id="page-state" aria-live="polite">
          <p className="page-state-title">Loading…</p>
        </div>
        <article className="sub-view" id="sub-view" aria-labelledby="sub-name" hidden>
          <header className="sub-head">
            <div className="sub-stage" id="sub-stage">
              <svg
                className="hud hud-small"
                viewBox="-120 -120 240 240"
                aria-hidden="true"
                focusable="false"
              >
                <g className="hud-spin">
                  <circle className="hud-ticks" r="114" />
                  <path className="hud-arc" d="M0 -104 A104 104 0 0 1 90 -52" />
                  <rect className="hud-frag" x="-110" y="30" width="5" height="5" />
                </g>
                <g className="hud-spin-back">
                  <circle className="hud-ring" r="98" />
                  <rect className="hud-frag" x="92" y="-2" width="9" height="3" />
                  <path className="hud-arc" d="M-69 69 A98 98 0 0 1 -95 -24" />
                </g>
              </svg>
            </div>
            <h1 className="sub-title chrome" id="sub-name" />
            <p className="sub-about" id="sub-about" />
            <p className="sub-meta">
              <span className="sub-by" id="sub-by" />
              <span className="sub-status kicker" id="sub-status" />
            </p>
          </header>
          <section className="talk" id="chat" aria-label="Chat" hidden>
            <ul className="starters" id="starters" aria-label="Suggestions" />
            <ol className="talk-log" id="chat-log" aria-live="polite" aria-label="Conversation" />
            <p className="talk-typing" id="chat-typing" hidden>
              <span className="talk-typing-name" id="chat-typing-name" />{" "}
              <span id="chat-typing-text" />
              <span className="typing-dots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
            </p>
            <p className="talk-notice" id="chat-notice" role="status" hidden />
            <form className="talk-form" id="chat-form">
              <label className="visually-hidden" htmlFor="chat-input">
                Your message
              </label>{" "}
              <textarea
                id="chat-input"
                name="text"
                rows={3}
                maxLength={2000}
                autoComplete="off"
                placeholder="Message…"
              />
              <div className="talk-bar">
                <p className="talk-keys">
                  <kbd>enter</kbd> send · <kbd>shift</kbd>+<kbd>enter</kbd> newline
                </p>
                <span className="talk-count" id="chat-count">
                  0 / 2,000
                </span>{" "}
                <button className="button button-primary" id="chat-send" type="submit">
                  Send
                </button>
              </div>
            </form>
            <div className="talk-foot">
              <p className="talk-privacy">
                Visitor chats pass through the universe and cost the owner’s model key. Don’t share
                secrets.
              </p>
              <button className="chip" id="chat-new" type="button" hidden>
                New chat
              </button>
            </div>
          </section>
          <p className="no-chat" id="no-chat" hidden />
          <details className="sub-details">
            <summary id="sub-details-title">About</summary>
            <dl className="facts" id="sub-facts" />
            <p className="sub-details-note">
              A sub-tau answers visitors with its own persona and its tau’s public note. It never
              sees its owner’s profile, has no tools and can approve nothing. The universe relays
              the chat, so it is not end-to-end private.
            </p>
          </details>
        </article>
        <p className="back-link">
          <a href="/universe">← The tau universe</a>
        </p>
      </main>
      <SiteFooter lang="en" variant="default" />
      <PageScript name="sub" />
    </div>
  );
}
