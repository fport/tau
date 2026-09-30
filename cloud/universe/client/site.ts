/**
 * What the person, sub-tau and claim pages share: the page language and its strings and
 * formats, the breadcrumb in the header, and the language switcher's link, which on these
 * pages depends on the URL.
 */

import { byId, html, link, maybeId } from "./dom";
import { MESSAGES, pageLanguage } from "./messages";
import { splitLanguage } from "./paths";

export const language = pageLanguage(document.documentElement.lang);
export const t = MESSAGES[language];
export const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

const monthYear = new Intl.DateTimeFormat(language, { month: "long", year: "numeric" });
const shortDate = new Intl.DateTimeFormat(language, { month: "short", year: "numeric" });
const numbers = new Intl.NumberFormat(language);

/** "September 2026" from Unix seconds; "" for anything that is not a time. */
export function month(seconds: unknown): string {
  return typeof seconds === "number" && Number.isFinite(seconds) && seconds > 0
    ? monthYear.format(new Date(seconds * 1000))
    : "";
}

/** "Sep 2026" from Unix seconds. */
export function shortMonth(seconds: unknown): string {
  return typeof seconds === "number" && Number.isFinite(seconds) && seconds > 0
    ? shortDate.format(new Date(seconds * 1000))
    : "";
}

/** A counted noun from the messages: `counted(t.links, 3)`. */
export function counted(
  message: (count: number, formatted: string) => string,
  value: unknown,
): string {
  const n = typeof value === "number" && Number.isFinite(value) ? Math.max(0, value) : 0;
  return message(n, numbers.format(n));
}

export function formatNumber(value: number): string {
  return numbers.format(value);
}

/**
 * Points the language switcher at this URL in the other language. The page shells carry a
 * switcher that links the start page; on `/@alice` it should link `/tr/@alice`.
 */
export function linkLanguageTwin(): void {
  const { rest } = splitLanguage(window.location.pathname);
  const other = language === "en" ? "tr" : "en";
  const twin = other === "tr" ? (rest === "/" ? "/tr/" : `/tr${rest}`) : rest;
  const anchor = document.querySelector<HTMLAnchorElement>(".lang-switch a[hreflang]");
  if (anchor !== null) anchor.href = `${twin}?lang=${other}${window.location.hash}`;
}

/** Sets the header's breadcrumb after `tau`: a list of parts, the last one the page itself. */
export function setCrumbs(parts: { text: string; href?: string }[]): void {
  const crumbs = maybeId<HTMLElement>("crumbs");
  if (crumbs === null) return;
  crumbs.replaceChildren();
  parts.forEach((part, index) => {
    crumbs.append(html("span", "crumb-sep", "/"));
    const last = index === parts.length - 1;
    if (part.href !== undefined && !last) {
      crumbs.append(link(part.href, part.text, "crumb"));
    } else {
      const here = html("span", "crumb crumb-here", part.text);
      if (last) here.setAttribute("aria-current", "page");
      crumbs.append(here);
    }
  });
}

/** Shows one of the page's states (loading, missing, failed) instead of its content. */
export function showState(
  title: string,
  detail: string | null,
  retry: (() => void) | null = null,
): void {
  const box = byId<HTMLElement>("page-state");
  box.replaceChildren(html("p", "page-state-title", title));
  if (detail !== null) box.append(html("p", "page-state-detail", detail));
  if (retry !== null) {
    const button = html("button", "button", t.tryAgain);
    button.type = "button";
    button.addEventListener("click", retry);
    box.append(button);
  }
  box.hidden = false;
}

export function hideState(): void {
  byId<HTMLElement>("page-state").hidden = true;
}
