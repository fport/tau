/**
 * The site's script strings, in English (the source) and Turkish: the universe graph (on
 * the landing page and /universe), the person page, the sub-tau page and its visitor chat,
 * and the claim page.
 *
 * A page picks a table by `<html lang>`. Numbers, dates and relative times come
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
  offline: string;
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
  /** The detail card's link to a tau's person page or a sub-tau's page. */
  openPage: string;

  // The person page (`/@handle`).
  /** The document title. */
  personTitle: (handle: string) => string;
  personMissing: string;
  personMissingHint: (handle: string) => string;
  pageFailed: string;
  buildingSince: (date: string) => string;
  publicSubs: (count: number, formatted: string) => string;
  /** A sub-tau card's line: when the universe first saw it. */
  firstSeen: (date: string) => string;
  /** The tag of a sub-tau that takes visitor chats. */
  chatTag: string;

  // The sub-tau page (`/<slug>`, `/@handle/<name>`) and its chat.
  subTitle: (name: string) => string;
  subMissing: string;
  subMissingHint: (path: string) => string;
  by: (owner: string) => string;
  offlineWaits: string;
  noChat: (name: string) => string;
  messagePlaceholder: (name: string) => string;
  you: string;
  waiting: string;
  waitingOffline: string;
  stillWaiting: string;
  rateLimited: string;
  tooLong: (max: string) => string;
  dailyCap: string;
  overBudget: string;
  chatClosed: string;
  chatFailed: string;
  aboutSub: (name: string) => string;
  factAddress: string;
  factFirstSeen: string;
  factRunsOn: string;
  runsHosted: string;
  runsHub: string;

  // The claim page (`/claim#…`).
  claimCrumb: string;
  claimBad: string;
  claimOtherUniverse: (universe: string) => string;
  claimExpired: string;
  claimExpires: (when: string) => string;
  claimBinding: string;
  claimBound: (handle: string) => string;
  claimMoved: (handle: string) => string;
  claimRefused: string;
  claimSignIn: string;
  claimUnavailable: string;
  claimCard: string;
  claimNotJoined: string;
  claimBadSignature: string;
  claimFailed: string;
  claimOpenPage: string;
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
  offline: "Offline",
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
  openPage: "Open page",

  personTitle: (handle) => `@${handle} · tau`,
  personMissing: "Nobody here yet.",
  personMissingHint: (handle) => `No tau in this universe has claimed @${handle}.`,
  pageFailed: "This page could not be loaded. Check your connection and try again.",
  buildingSince: (date) => `building since ${date}`,
  publicSubs: (count, n) => `${n} public ${count === 1 ? "sub-tau" : "sub-taus"}`,
  firstSeen: (date) => `alive since ${date}`,
  chatTag: "chat",

  subTitle: (name) => `${name} · tau`,
  subMissing: "No sub-tau at this address.",
  subMissingHint: (path) => `Nothing in this universe answers to ${path}.`,
  by: (owner) => `by ${owner}`,
  offlineWaits: "offline — messages wait",
  noChat: (name) => `${name} has no public chat. Its owner can turn one on.`,
  messagePlaceholder: (name) => `Message ${name}…`,
  you: "You",
  waiting: "Thinking…",
  waitingOffline: "Its tau is offline. Your message waits until it is back.",
  stillWaiting: "Still no answer. Keep the page open, or come back later.",
  rateLimited: "Too many messages. Wait a minute and try again.",
  tooLong: (max) => `Keep it under ${max} characters.`,
  dailyCap: "It has talked to all the visitors it can today. Try again tomorrow.",
  overBudget: "Its owner’s budget for this month is used up.",
  chatClosed: "This sub-tau does not take visitor chats.",
  chatFailed: "The message could not be sent. Try again.",
  aboutSub: (name) => `About ${name}`,
  factAddress: "Address",
  factFirstSeen: "First seen",
  factRunsOn: "Runs on",
  runsHosted: "a tau-host, in the cloud",
  runsHub: "its owner’s own machine",

  claimCrumb: "claim",
  claimBad: "This link holds no claim. Copy the whole link that tau net universe claim printed.",
  claimOtherUniverse: (universe) => `This claim is for ${universe}, not for this universe.`,
  claimExpired: "This claim has expired. Run tau net universe claim again.",
  claimExpires: (when) => `expires ${when}`,
  claimBinding: "Binding…",
  claimBound: (handle) => `Done. Your tau is now @${handle}.`,
  claimMoved: (handle) => `Done. @${handle} now points to this tau.`,
  claimRefused: "This handle is bound to another GitHub account.",
  claimSignIn: "Sign in with GitHub first.",
  claimUnavailable: "This universe cannot bind handles.",
  claimCard: "The universe could not fetch your tau’s card. Is its address online?",
  claimNotJoined: "This tau is not in the universe yet. Run tau net universe join first.",
  claimBadSignature: "The claim’s signature does not match your tau’s card. Run tau net universe claim again.",
  claimFailed: "The claim did not go through. Try again.",
  claimOpenPage: "Open your page",
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
  offline: "Çevrimdışı",
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
  openPage: "Sayfayı aç",

  personTitle: (handle) => `@${handle} · tau`,
  personMissing: "Burada henüz kimse yok.",
  personMissingHint: (handle) => `Bu evrende @${handle} kullanıcı adını alan bir tau yok.`,
  pageFailed: "Bu sayfa yüklenemedi. Bağlantını kontrol edip tekrar dene.",
  buildingSince: (date) => `${date} itibarıyla üretiyor`,
  publicSubs: (_count, n) => `${n} açık sub-tau`,
  firstSeen: (date) => `ilk görülme: ${date}`,
  chatTag: "sohbet",

  subTitle: (name) => `${name} · tau`,
  subMissing: "Bu adreste bir sub-tau yok.",
  subMissingHint: (path) => `Bu evrende ${path} adresine yanıt veren bir şey yok.`,
  by: (owner) => `${owner} tarafından`,
  offlineWaits: "çevrimdışı — mesajlar bekler",
  noChat: (name) => `${name} için açık sohbet yok. Sahibi açabilir.`,
  messagePlaceholder: (name) => `${name} ile konuş…`,
  you: "Sen",
  waiting: "Düşünüyor…",
  waitingOffline: "tau’su şu an çevrimdışı. Mesajın o dönene kadar bekler.",
  stillWaiting: "Hâlâ cevap yok. Sayfayı açık tut ya da sonra tekrar gel.",
  rateLimited: "Çok fazla mesaj. Bir dakika bekleyip tekrar dene.",
  tooLong: (max) => `En fazla ${max} karakter yaz.`,
  dailyCap: "Bugün konuşabileceği tüm ziyaretçilerle konuştu. Yarın tekrar dene.",
  overBudget: "Sahibinin bu ayki bütçesi doldu.",
  chatClosed: "Bu sub-tau ziyaretçi sohbeti kabul etmiyor.",
  chatFailed: "Mesaj gönderilemedi. Tekrar dene.",
  aboutSub: (name) => `${name} hakkında`,
  factAddress: "Adres",
  factFirstSeen: "İlk görülme",
  factRunsOn: "Çalıştığı yer",
  runsHosted: "bulutta, bir tau-host üzerinde",
  runsHub: "sahibinin kendi makinesi",

  claimCrumb: "talep",
  claimBad:
    "Bu bağlantıda bir talep yok. tau net universe claim komutunun yazdığı bağlantının tamamını kopyala.",
  claimOtherUniverse: (universe) => `Bu talep bu evren için değil; hedefi ${universe}.`,
  claimExpired: "Bu talebin süresi doldu. tau net universe claim komutunu yeniden çalıştır.",
  claimExpires: (when) => `süresi ${when} doluyor`,
  claimBinding: "Bağlanıyor…",
  claimBound: (handle) => `Tamam. tau’n artık @${handle}.`,
  claimMoved: (handle) => `Tamam. @${handle} artık bu tau’yu gösteriyor.`,
  claimRefused: "Bu kullanıcı adı başka bir GitHub hesabına bağlı.",
  claimSignIn: "Önce GitHub ile giriş yap.",
  claimUnavailable: "Bu evren kullanıcı adı bağlayamıyor.",
  claimCard: "Evren tau’nun kimlik kartını alamadı. Adresi çevrimiçi mi?",
  claimNotJoined: "Bu tau henüz evrende değil. Önce tau net universe join komutunu çalıştır.",
  claimBadSignature:
    "Talebin imzası tau’nun kimlik kartıyla eşleşmiyor. tau net universe claim komutunu yeniden çalıştır.",
  claimFailed: "Talep tamamlanamadı. Tekrar dene.",
  claimOpenPage: "Sayfanı aç",
};

export const MESSAGES: Readonly<Record<PageLanguage, Messages>> = { en, tr };

/** The page language from a `lang` attribute: `tr` or `tr-TR` is Turkish, the rest English. */
export function pageLanguage(lang: string | null | undefined): PageLanguage {
  return (lang ?? "").trim().toLowerCase().split("-")[0] === "tr" ? "tr" : "en";
}
