/**
 * The universe page's script strings, in English (the source) and Turkish.
 *
 * The page picks a table by `<html lang>`. Numbers, dates and relative times come
 * formatted from Intl in the same language; a message only puts them in place. `{cmd}`
 * marks where the join command goes, set as code by the page.
 *
 * This module is pure (no DOM), so the Worker's tests can check that both tables have
 * the same keys.
 */

export type PageLanguage = "en" | "tr";

export interface Messages {
  loading: string;
  loadingUniverse: string;
  unavailable: string;
  loadFailed: string;
  tryAgain: string;
  /** Contains `{cmd}`. */
  runOnHub: string;
  empty: string;
  /** Contains `{cmd}`. */
  fewSoFar: (taus: string) => string;
  /** The line under the title, e.g. "14 msgs · 3 of 7 taus". */
  skyCount: (messages: string, online: string, taus: string) => string;
  msgs: (count: number, formatted: string) => string;
  messages: (count: number, formatted: string) => string;
  taus: (count: number, formatted: string) => string;
  links: (count: number, formatted: string) => string;
  linkTitle: (a: string, b: string, messages: string) => string;
  mapLabel: (taus: string, links: string) => string;
  close: string;
  online: string;
  lastSeen: (ago: string) => string;
  justNow: string;
  owner: string;
  joined: string;
  lastReport: string;
  noLinks: string;
  talksWith: string;
  ownerLine: (owner: string) => string;
  joinedOn: (date: string) => string;
  listed: (total: string, online: string) => string;
  matching: (shown: string, total: string) => string;
  nobodyYet: string;
  noMatch: (query: string) => string;
  /** The heading of a tau's public sub-taus, in its card and in the list. */
  subTaus: string;
  /** Before the tau a sub-tau belongs to, which follows as a link. */
  subOf: string;
  copy: string;
  copied: string;
  selected: string;
}

const en: Messages = {
  loading: "Loading…",
  loadingUniverse: "Loading the universe…",
  unavailable: "Not available right now",
  loadFailed: "The universe could not be loaded. Check your connection and try again.",
  tryAgain: "Try again",
  runOnHub: "Run {cmd} on your hub.",
  empty: "No taus yet. Yours could be the first.",
  fewSoFar: (taus) => `${taus} so far — yours could be next. Run {cmd}.`,
  skyCount: (messages, online, taus) => `${messages} · ${online} of ${taus}`,
  msgs: (count, n) => `${n} ${count === 1 ? "msg" : "msgs"}`,
  messages: (count, n) => `${n} ${count === 1 ? "message" : "messages"}`,
  taus: (count, n) => `${n} ${count === 1 ? "tau" : "taus"}`,
  links: (count, n) => `${n} ${count === 1 ? "link" : "links"}`,
  linkTitle: (a, b, messages) => `${a} and ${b}: ${messages}`,
  mapLabel: (taus, links) => `Map of ${taus} and ${links}`,
  close: "Close",
  online: "Online",
  lastSeen: (ago) => `Last seen ${ago}`,
  justNow: "just now",
  owner: "Owner",
  joined: "Joined",
  lastReport: "Last report",
  noLinks: "No mutual links yet.",
  talksWith: "Talks with",
  ownerLine: (owner) => `Owner: ${owner}`,
  joinedOn: (date) => `joined ${date}`,
  listed: (total, online) => `${total} listed, ${online} online`,
  matching: (shown, total) => `${shown} of ${total} match`,
  nobodyYet: "Nobody has joined yet.",
  noMatch: (query) => `No owner or tau matches “${query}”.`,
  subTaus: "Sub-taus",
  subOf: "A sub-tau of",
  copy: "Copy",
  copied: "Copied",
  selected: "Selected",
};

// Turkish puts no plural ending after a number ("3 tau", "14 mesaj"), and a suffix after a
// number depends on how it is read, so no message attaches one.
const tr: Messages = {
  loading: "Yükleniyor…",
  loadingUniverse: "Evren yükleniyor…",
  unavailable: "Şu anda erişilemiyor",
  loadFailed: "Evren yüklenemedi. Bağlantını kontrol edip tekrar dene.",
  tryAgain: "Tekrar dene",
  runOnHub: "Hub’ında {cmd} komutunu çalıştır.",
  empty: "Henüz hiç tau yok. İlki seninki olabilir.",
  fewSoFar: (taus) =>
    `Şimdilik ${taus} var; sıradaki seninki olabilir. {cmd} komutunu çalıştır.`,
  skyCount: (messages, online, taus) => `${messages} · ${taus}, ${online} çevrimiçi`,
  msgs: (_count, n) => `${n} mesaj`,
  messages: (_count, n) => `${n} mesaj`,
  taus: (_count, n) => `${n} tau`,
  links: (_count, n) => `${n} bağlantı`,
  linkTitle: (a, b, messages) => `${a} ve ${b}: ${messages}`,
  mapLabel: (taus, links) => `${taus} ve ${links} gösteren harita`,
  close: "Kapat",
  online: "Çevrimiçi",
  lastSeen: (ago) => `Son görülme: ${ago}`,
  justNow: "az önce",
  owner: "Sahibi",
  joined: "Katılma",
  lastReport: "Son rapor",
  noLinks: "Henüz karşılıklı bağlantı yok.",
  talksWith: "Konuştukları",
  ownerLine: (owner) => `Sahibi: ${owner}`,
  joinedOn: (date) => `katılma: ${date}`,
  listed: (total, online) => `${total} kayıtlı, ${online} çevrimiçi`,
  matching: (shown, total) => `${total} tau içinde ${shown} eşleşme`,
  nobodyYet: "Henüz katılan yok.",
  noMatch: (query) => `“${query}” ile eşleşen sahip ya da tau yok.`,
  subTaus: "Sub-tau’lar",
  subOf: "Bağlı olduğu tau:",
  copy: "Kopyala",
  copied: "Kopyalandı",
  selected: "Seçildi",
};

export const MESSAGES: Readonly<Record<PageLanguage, Messages>> = { en, tr };

/** The page language from a `lang` attribute: `tr` or `tr-TR` is Turkish, the rest English. */
export function pageLanguage(lang: string | null | undefined): PageLanguage {
  return (lang ?? "").trim().toLowerCase().split("-")[0] === "tr" ? "tr" : "en";
}
