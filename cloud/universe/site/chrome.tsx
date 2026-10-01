/**
 * The header and the footer every page shares, in English and in Turkish.
 *
 * The header: the coin and the name, the breadcrumb slot of the person, sub-tau and claim
 * pages (client/site.ts fills it), the main menu with the current page marked, sign-in, and
 * the language switcher. The switcher links the page's twin with `?lang=`, which the Worker
 * turns into the `lang` cookie (src/pages.ts). The footer comes in three sets of links.
 */

import type { ReactNode } from "react";

export type Language = "en" | "tr";

const WORDS = {
  en: {
    brand: "/",
    nav: "Main",
    how: ["/how-it-works", "How it works"],
    universe: ["/universe", "Universe"],
    docs: ["https://docs.tau.getporti.com/", "Docs"],
    signIn: "Sign in",
    language: "Language",
    footer: "Footer",
    download: ["/download", "Download"],
    home: ["/", "Home"],
    guide: ["https://docs.tau.getporti.com/guides/tau-network/", "Network guide"],
    early: "tau is in early development. The source code will be published.",
    source: "The source code will be published.",
  },
  tr: {
    brand: "/tr/",
    nav: "Ana menü",
    how: ["/tr/how-it-works", "Nasıl çalışır"],
    universe: ["/tr/universe", "Evren"],
    docs: ["https://docs.tau.getporti.com/tr/", "Belgeler"],
    signIn: "Giriş yap",
    language: "Dil",
    footer: "Alt bilgi",
    download: ["/tr/download", "İndir"],
    home: ["/tr/", "Ana sayfa"],
    guide: ["https://docs.tau.getporti.com/tr/guides/tau-network/", "Ağ kılavuzu"],
    early: "tau erken geliştirme aşamasında. Kaynak kodu yayımlanacak.",
    source: "Kaynak kodu yayımlanacak.",
  },
} as const;

/** GitHub's mark, for sign-in. */
export function GitHubMark(): ReactNode {
  return (
    <svg className="gh" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path>
    </svg>
  );
}

function Current({ lang }: { lang: Language }): ReactNode {
  return (
    <span className="lang-current" lang={lang}>
      <span aria-hidden="true">{lang.toUpperCase()}</span>
      <span className="visually-hidden">{lang === "en" ? "English" : "Türkçe"}</span>
    </span>
  );
}

function Other({ lang, href }: { lang: Language; href: string }): ReactNode {
  return (
    <a href={`${href}?lang=${lang}`} hrefLang={lang} lang={lang}>
      <span aria-hidden="true">{lang.toUpperCase()}</span>
      <span className="visually-hidden">{lang === "en" ? "English" : "Türkçe"}</span>
    </a>
  );
}

export function SiteHeader({
  lang,
  twin,
  current,
  crumbs = false,
}: {
  lang: Language;
  /** This page in the other language, without `?lang=`. */
  twin: string;
  current?: "how" | "universe";
  /** The breadcrumb slot after the name (the person, sub-tau and claim pages). */
  crumbs?: boolean;
}): ReactNode {
  const w = WORDS[lang];
  const here = (key: "how" | "universe") => (current === key ? ("page" as const) : undefined);
  return (
    <header className="site-header">
      <a className="brand" href={w.brand}>
        <img className="brand-coin" src="/brand/tau-coin-red.svg" width="26" height="26" alt="" />
        <span className="brand-name">tau</span>
      </a>
      {crumbs ? <div className="crumbs" id="crumbs"></div> : null}
      <nav className="site-nav" aria-label={w.nav}>
        <a href={w.how[0]} aria-current={here("how")}>
          {w.how[1]}
        </a>
        <a href={w.universe[0]} aria-current={here("universe")}>
          {w.universe[1]}
        </a>
        <a href={w.docs[0]}>{w.docs[1]}</a>
      </nav>
      <a className="signin" href="/auth/login">
        <GitHubMark />
        <span>{w.signIn}</span>
      </a>
      <nav className="lang-switch" aria-label={w.language}>
        {lang === "en" ? (
          <>
            <Current lang="en" />
            <Other lang="tr" href={twin} />
          </>
        ) : (
          <>
            <Other lang="en" href={twin} />
            <Current lang="tr" />
          </>
        )}
      </nav>
    </header>
  );
}

const FOOTERS = {
  home: ["download", "how", "universe", "docs", "guide"],
  how: ["home", "universe", "docs", "guide"],
  default: ["home", "how", "universe", "docs"],
} as const;

export function SiteFooter({
  lang,
  variant,
}: {
  lang: Language;
  variant: keyof typeof FOOTERS;
}): ReactNode {
  const w = WORDS[lang];
  return (
    <footer className="site-footer">
      <img className="footer-coin" src="/brand/tau-coin-red.svg" width="18" height="18" alt="" />
      <nav aria-label={w.footer}>
        {FOOTERS[variant].map((key) => (
          <a key={key} href={w[key][0]}>
            {w[key][1]}
          </a>
        ))}
      </nav>
      <p>{variant === "how" ? w.source : w.early}</p>
    </footer>
  );
}
