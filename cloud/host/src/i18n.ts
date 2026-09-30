/**
 * The strings of the pages the Worker renders (landing, sign-in, visitor page, errors), in
 * English (the source) and Turkish. The owner's app has its own table (client/messages.ts).
 * A test checks that both columns have the same keys.
 */

export type Language = "en" | "tr";

export const LANGUAGES: readonly Language[] = ["en", "tr"];

const en = {
  htmlTitle: "tau · host",
  tagline: "Your tau, in the browser.",
  intro:
    "Sign in with GitHub, bring your own provider key (Anthropic, OpenAI or Gemini) and talk to your tau and its sub-taus. Make a sub-tau public and give it a page anyone can talk to.",
  signIn: "Sign in with GitHub",
  openApp: "Open your tau",
  privacyTitle: "Who can read what",
  privacy1:
    "Your tau lives on this host. Its operator can read your chats, your sub-taus and the chats of your visitors.",
  privacy2: "Provider keys are encrypted at rest and never shown again, not even to you.",
  privacy3: "For privacy, run tau on your own machine or deploy your own host.",
  waysTitle: "Three ways to run a tau",
  wayLocal: "Local: tau on your machine, everything stays there.",
  wayHosted: "Hosted: here, after a GitHub sign-in.",
  wayOwn: "Your own host: this same Worker in your Cloudflare account.",
  devTitle: "Development sign-in",
  devNote: "DEV_LOGIN is on and this is localhost: sign in as any login, without GitHub.",
  devLogin: "Login",
  devSubmit: "Sign in",
  signInFailed: "Sign-in failed",
  back: "Back",
  err_cancelled: "The sign-in was cancelled on GitHub.",
  err_bad_state: "The sign-in expired or came from another browser. Start again.",
  err_github_failed: "GitHub did not confirm the sign-in. Try again in a moment.",
  err_signup_closed: "This host does not take new accounts for your GitHub login.",
  err_handle_taken: "Your GitHub login is already the handle of another account on this host.",
  err_bad_login: "That login cannot be a handle.",
  err_not_configured: "GitHub sign-in is not set up on this host yet (GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET).",
  notFoundTitle: "Not found",
  notFound: "There is nothing here.",
  home: "Home",
  by: "by",
  visitorNote:
    "Visitor chats are not end-to-end private: this host and its operator can read them. Each answer uses the owner's key, so there is a daily limit.",
  loadingApp: "Loading your tau…",
  noscript: "This page needs JavaScript.",
};

export type PageMessages = typeof en;

const tr: PageMessages = {
  htmlTitle: "tau · host",
  tagline: "tau'n tarayıcında.",
  intro:
    "GitHub ile giriş yap, kendi sağlayıcı anahtarını getir (Anthropic, OpenAI ya da Gemini) ve tau'nla ve alt-tau'larıyla konuş. Bir alt-tau'yu herkese açık yap ve ona herkesin konuşabileceği bir sayfa ver.",
  signIn: "GitHub ile giriş yap",
  openApp: "tau'nu aç",
  privacyTitle: "Kim neyi okuyabilir",
  privacy1:
    "tau'n bu sunucuda yaşar. İşletmecisi sohbetlerini, alt-tau'larını ve ziyaretçilerinin sohbetlerini okuyabilir.",
  privacy2: "Sağlayıcı anahtarları şifreli saklanır ve bir daha gösterilmez, sana bile.",
  privacy3: "Gizlilik için tau'yu kendi makinende çalıştır ya da kendi sunucunu kur.",
  waysTitle: "Bir tau'yu çalıştırmanın üç yolu",
  wayLocal: "Yerel: tau senin makinende, her şey orada kalır.",
  wayHosted: "Barındırılan: burada, GitHub ile girişten sonra.",
  wayOwn: "Kendi sunucun: aynı Worker, senin Cloudflare hesabında.",
  devTitle: "Geliştirme girişi",
  devNote: "DEV_LOGIN açık ve bu localhost: GitHub olmadan istediğin kullanıcı adıyla gir.",
  devLogin: "Kullanıcı adı",
  devSubmit: "Giriş yap",
  signInFailed: "Giriş olmadı",
  back: "Geri",
  err_cancelled: "Giriş GitHub'da iptal edildi.",
  err_bad_state: "Girişin süresi doldu ya da başka bir tarayıcıdan geldi. Baştan başla.",
  err_github_failed: "GitHub girişi doğrulamadı. Birazdan yeniden dene.",
  err_signup_closed: "Bu sunucu senin GitHub kullanıcı adın için yeni hesap açmıyor.",
  err_handle_taken: "GitHub kullanıcı adın bu sunucuda başka bir hesabın adı.",
  err_bad_login: "Bu kullanıcı adı bir ad (handle) olamaz.",
  err_not_configured: "Bu sunucuda GitHub girişi henüz kurulmamış (GITHUB_CLIENT_ID ve GITHUB_CLIENT_SECRET).",
  notFoundTitle: "Bulunamadı",
  notFound: "Burada bir şey yok.",
  home: "Ana sayfa",
  by: "sahibi",
  visitorNote:
    "Ziyaretçi sohbetleri uçtan uca gizli değildir: bu sunucu ve işletmecisi onları okuyabilir. Her yanıt sahibinin anahtarını kullanır, bu yüzden günlük bir sınır vardır.",
  loadingApp: "tau'n yükleniyor…",
  noscript: "Bu sayfa JavaScript ister.",
};

export const PAGE_MESSAGES: Readonly<Record<Language, PageMessages>> = { en, tr };

/** The sign-in error codes a page can explain. */
export type SignInError =
  | "cancelled"
  | "bad_state"
  | "github_failed"
  | "signup_closed"
  | "handle_taken"
  | "bad_login"
  | "not_configured";

export function signInErrorText(messages: PageMessages, code: SignInError): string {
  return messages[`err_${code}`];
}

/**
 * The language of a page: `?lang=`, then the `lang` cookie (the universe sets it on a shared
 * domain), then Accept-Language, then English.
 */
export function pageLanguage(request: Request): Language {
  const url = new URL(request.url);
  const asked = url.searchParams.get("lang");
  if (asked === "en" || asked === "tr") return asked;
  const header = request.headers.get("cookie") ?? "";
  for (const part of header.split(";")) {
    const [name, value] = part.split("=").map((s) => s.trim());
    if (name === "lang" && (value === "en" || value === "tr")) return value;
  }
  const accept = (request.headers.get("accept-language") ?? "").toLowerCase();
  let best: { lang: Language; q: number } | null = null;
  for (const entry of accept.split(",")) {
    const [tag = "", ...params] = entry.trim().split(";");
    const lang = tag.split("-")[0];
    if (lang !== "en" && lang !== "tr") continue;
    let q = 1;
    for (const param of params) {
      const [key, value] = param.trim().split("=");
      if (key === "q") q = Number(value) || 0;
    }
    if (q > 0 && (best === null || q > best.q)) best = { lang, q };
  }
  return best?.lang ?? "en";
}
