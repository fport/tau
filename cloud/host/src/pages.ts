/**
 * The pages the Worker renders, and the security headers of every answer.
 *
 * Pages are small HTML shells with no inline script and no inline style (the CSP allows
 * neither). Data a page's script needs goes into a `<script type="application/json">`
 * block, which the browser never runs. Styles and scripts come from /app/assets/, built by
 * `bun run build`: theme.css (the shared theme when cloud/shared/theme.css exists, else
 * tau-host's own tokens), host.css, app.js and visit.js.
 */

import {
  type Language,
  PAGE_MESSAGES,
  type PageMessages,
  pageLanguage,
  type SignInError,
  signInErrorText,
} from "./i18n";

export const CONTENT_SECURITY_POLICY =
  "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; " +
  "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'";

export const SECURITY_HEADERS: Readonly<Record<string, string>> = {
  "content-security-policy": CONTENT_SECURITY_POLICY,
  "x-content-type-options": "nosniff",
  "referrer-policy": "strict-origin-when-cross-origin",
  "x-frame-options": "DENY",
};

/** A copy of `response` with the security headers set (a streamed body stays streamed). */
export function withSecurityHeaders(response: Response): Response {
  const secured = new Response(response.body, response);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) secured.headers.set(name, value);
  return secured;
}

const ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ESCAPES[c] ?? c);
}

/** JSON that is safe inside `<script type="application/json">` (no `</script>`, no `<!--`). */
export function jsonForHtml(value: unknown): string {
  return JSON.stringify(value).replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/&/g, "\\u0026");
}

/** The tau triangle, drawn with lines (the mark of the brand, simplified). */
export const TAU_MARK =
  '<svg class="mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false">' +
  '<path d="M16 3 L29 27 L3 27 Z" fill="none" stroke="currentColor" stroke-width="1.5"/>' +
  '<path d="M10 13 H22 M16 13 V23" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>';

const FAVICON =
  "data:image/svg+xml," +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" fill="#07080a"/>' +
      '<path d="M16 4 L28 26 L4 26 Z" fill="none" stroke="#ff2e3e" stroke-width="2"/></svg>',
  );

interface Layout {
  lang: Language;
  title: string;
  body: string;
  kind: string;
  script?: string;
  data?: unknown;
}

function layout({ lang, title, body, kind, script, data }: Layout): string {
  return `<!doctype html>
<html lang="${lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="robots" content="noindex">
<title>${escapeHtml(title)}</title>
<link rel="icon" href="${FAVICON}">
<link rel="stylesheet" href="/app/assets/theme.css">
<link rel="stylesheet" href="/app/assets/host.css">
${script ? `<script type="module" src="/app/assets/${script}"></script>` : ""}
</head>
<body class="page page-${kind}">
<div class="grid-bg" aria-hidden="true"></div>
${data === undefined ? "" : `<script type="application/json" id="tau-data">${jsonForHtml(data)}</script>`}
${body}
</body>
</html>
`;
}

function html(text: string, status = 200, extraHeaders: Record<string, string> = {}): Response {
  return new Response(text, {
    status,
    headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", ...extraHeaders },
  });
}

function langSwitch(lang: Language, path: string): string {
  const other: Language = lang === "en" ? "tr" : "en";
  return `<a class="lang" href="${escapeHtml(path)}?lang=${other}" hreflang="${other}">${other.toUpperCase()}</a>`;
}

function topbar(m: PageMessages, lang: Language, path: string, right = ""): string {
  return `<header class="topbar"><a class="brand" href="/">${TAU_MARK}<span>tau</span><span class="brand-tag">host</span></a><nav class="topnav">${right}${langSwitch(lang, path)}</nav></header>`;
}

function devForm(m: PageMessages, next: string): string {
  return `<section class="panel dev">
<h2 class="hud">${escapeHtml(m.devTitle)}</h2>
<p class="muted">${escapeHtml(m.devNote)}</p>
<form method="post" action="/auth/dev" class="row">
<input type="hidden" name="next" value="${escapeHtml(next)}">
<label class="field"><span>${escapeHtml(m.devLogin)}</span><input name="login" required pattern="[A-Za-z0-9][A-Za-z0-9-]{0,38}" autocomplete="username" value="alice"></label>
<button class="btn primary" type="submit">${escapeHtml(m.devSubmit)}</button>
</form>
</section>`;
}

export function landingPage(request: Request, options: { devLogin: boolean }): Response {
  const lang = pageLanguage(request);
  const m = PAGE_MESSAGES[lang];
  const body = `${topbar(m, lang, "/")}
<main class="landing">
<section class="hero">
<p class="hud">tau-host</p>
<h1>${escapeHtml(m.tagline)}</h1>
<p class="lead">${escapeHtml(m.intro)}</p>
<p><a class="btn primary big" href="/auth/login?next=%2Fapp">${escapeHtml(m.signIn)}</a></p>
</section>
${options.devLogin ? devForm(m, "/app") : ""}
<section class="panel">
<h2 class="hud">${escapeHtml(m.privacyTitle)}</h2>
<ul class="lines"><li>${escapeHtml(m.privacy1)}</li><li>${escapeHtml(m.privacy2)}</li><li>${escapeHtml(m.privacy3)}</li></ul>
</section>
<section class="panel">
<h2 class="hud">${escapeHtml(m.waysTitle)}</h2>
<ol class="lines"><li>${escapeHtml(m.wayLocal)}</li><li>${escapeHtml(m.wayHosted)}</li><li>${escapeHtml(m.wayOwn)}</li></ol>
</section>
</main>`;
  return html(layout({ lang, title: m.htmlTitle, body, kind: "landing" }), 200, { vary: "Accept-Language, Cookie" });
}

export function devLoginPage(request: Request, next: string): Response {
  const lang = pageLanguage(request);
  const m = PAGE_MESSAGES[lang];
  const body = `${topbar(m, lang, "/auth/login")}<main class="narrow">${devForm(m, next)}</main>`;
  return html(layout({ lang, title: m.devTitle, body, kind: "dev" }));
}

export function signInErrorPage(request: Request, code: SignInError, status: number, setCookie?: string): Response {
  const lang = pageLanguage(request);
  const m = PAGE_MESSAGES[lang];
  const body = `${topbar(m, lang, "/")}<main class="narrow"><section class="panel">
<h1 class="hud alert">${escapeHtml(m.signInFailed)}</h1>
<p>${escapeHtml(signInErrorText(m, code))}</p>
<p><a class="btn" href="/">${escapeHtml(m.back)}</a></p>
</section></main>`;
  return html(layout({ lang, title: m.signInFailed, body, kind: "error" }), status, setCookie ? { "set-cookie": setCookie } : {});
}

export function notFoundPage(request: Request): Response {
  const lang = pageLanguage(request);
  const m = PAGE_MESSAGES[lang];
  const body = `${topbar(m, lang, "/")}<main class="narrow"><section class="panel">
<h1 class="hud">404 · ${escapeHtml(m.notFoundTitle)}</h1>
<p>${escapeHtml(m.notFound)}</p>
<p><a class="btn" href="/">${escapeHtml(m.home)}</a></p>
</section></main>`;
  return html(layout({ lang, title: m.notFoundTitle, body, kind: "error" }), 404);
}

/** The owner's app: an empty shell the script fills (client/app.ts). */
export function appPage(request: Request, data: { handle: string; dev: boolean }): Response {
  const lang = pageLanguage(request);
  const m = PAGE_MESSAGES[lang];
  const body = `<div id="app" class="app" data-lang="${lang}"><p class="loading hud">${escapeHtml(m.loadingApp)}</p></div>
<noscript><p class="panel">${escapeHtml(m.noscript)}</p></noscript>`;
  return html(layout({ lang, title: `@${data.handle} · tau`, body, kind: "app", script: "app.js", data: { ...data, lang } }));
}

/** The chat page of a public web sub-tau at /@<handle>/<name> (client/visit.ts). */
export function visitPage(
  request: Request,
  sub: { handle: string; name: string; about: string; starters: string[] },
): Response {
  const lang = pageLanguage(request);
  const m = PAGE_MESSAGES[lang];
  const path = `/@${sub.handle}/${sub.name}`;
  const starters = sub.starters
    .map((text) => `<button type="button" class="chip" data-starter="${escapeHtml(text)}">${escapeHtml(text)}</button>`)
    .join("");
  const body = `${topbar(m, lang, path)}
<main class="visit">
<section class="visit-head">
<div class="char-slot" data-seed="${escapeHtml(`${sub.handle}/${sub.name}`)}" data-label="/${escapeHtml(sub.name)}"></div>
<div>
<h1 class="sub-name">/${escapeHtml(sub.name)}</h1>
<p class="lead">${escapeHtml(sub.about)}</p>
<p class="muted hud">${escapeHtml(m.by)} @${escapeHtml(sub.handle)}</p>
</div>
</section>
<section class="chat panel" aria-live="polite">
<div class="log" id="log"></div>
<div class="starters" id="starters">${starters}</div>
<form class="composer" id="composer"><textarea id="text" rows="2" maxlength="2000" required></textarea><button class="btn primary" type="submit">→</button></form>
<p class="muted small">${escapeHtml(m.visitorNote)}</p>
</section>
</main>`;
  return html(layout({ lang, title: `/${sub.name} · @${sub.handle}`, body, kind: "visit", script: "visit.js", data: { ...sub, lang } }));
}
