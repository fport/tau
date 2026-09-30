/**
 * The claim page, `/claim#<b64u wire>` (ADR 0013 §6): binds a GitHub handle to a tau.
 *
 * `tau net universe claim` prints the link. Its fragment is the base64url of a signed
 * universe request (`{"payload": b64u, "sig": b64u}`, kind `claim`, valid for an hour); the
 * fragment never reaches a server. The page shows what the claim would bind, sends the owner
 * through the GitHub sign-in (keeping the claim in sessionStorage over the round trip), then
 * posts the wire to `POST /api/claim`, where the universe checks both the tau's signature and
 * the GitHub session.
 */

import { fixtureMode, postJson } from "./api";
import { byId, html, link } from "./dom";
import { HANDLE, localPath, personPath } from "./paths";
import { language, linkLanguageTwin, setCrumbs, t } from "./site";
import { starfield } from "./starfield";
import type { ClaimResult } from "./types";

starfield();

/** A claim is valid for an hour after its `ts` (issue 157). */
const VALID_SECONDS = 3_600;
const STORE_WIRE = "tau.claim.wire";
const STORE_PENDING = "tau.claim.pending";

interface Claim {
  wire: { payload: string; sig: string };
  address: string;
  universe: string;
  ts: number;
}

function b64uDecode(text: string): string | null {
  if (!/^[A-Za-z0-9_-]*$/.test(text) || text.length % 4 === 1) return null;
  try {
    const binary = atob(text.replaceAll("-", "+").replaceAll("_", "/"));
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
}

/** The claim in a fragment, or null when it is not one. Nothing here is trusted: it is shown. */
export function readClaim(fragment: string): Claim | null {
  const json = b64uDecode(fragment.trim());
  if (json === null) return null;
  let wire: unknown;
  try {
    wire = JSON.parse(json);
  } catch {
    return null;
  }
  if (typeof wire !== "object" || wire === null) return null;
  const { payload, sig } = wire as { payload?: unknown; sig?: unknown };
  if (typeof payload !== "string" || typeof sig !== "string") return null;
  const inner = b64uDecode(payload);
  if (inner === null) return null;
  let body: unknown;
  try {
    body = JSON.parse(inner);
  } catch {
    return null;
  }
  if (typeof body !== "object" || body === null) return null;
  const { kind, address, universe, ts } = body as Record<string, unknown>;
  if (kind !== "claim" || typeof address !== "string" || typeof universe !== "string") return null;
  if (typeof ts !== "number" || !Number.isFinite(ts)) return null;
  return { wire: { payload, sig }, address, universe, ts };
}

function storage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function setResult(message: string, kind: "ok" | "error" | "busy", extra?: Node): void {
  const result = byId<HTMLElement>("claim-result");
  result.className = `claim-result claim-result-${kind}`;
  result.replaceChildren(html("p", undefined, message));
  if (extra !== undefined) result.append(extra);
  result.hidden = false;
}

/** What an error answer of `POST /api/claim` means for the owner (issue 160's codes). */
function explain(status: number, data: ClaimResult | null): string {
  switch (data?.error ?? "") {
    case "not_signed_in":
      return t.claimSignIn;
    case "handle_taken":
    case "handle_mismatch":
      return t.claimRefused;
    case "stale":
      return t.claimExpired;
    case "not_joined":
      return t.claimNotJoined;
    case "bad_signature":
      return t.claimBadSignature;
    case "card_unavailable":
      return t.claimCard;
    case "claims_unavailable":
      return t.claimUnavailable;
    case "rate_limited":
      return t.rateLimited;
  }
  if (status === 401) return t.claimSignIn;
  if (status === 409) return t.claimRefused;
  if (status === 429) return t.rateLimited;
  if (status === 501) return t.claimUnavailable;
  return t.claimFailed;
}

async function bind(claim: Claim): Promise<void> {
  const button = byId<HTMLButtonElement>("claim-now");
  button.disabled = true;
  setResult(t.claimBinding, "busy");
  const result = await postJson<ClaimResult>("/api/claim", claim.wire);
  button.disabled = false;
  const data = result.data;
  if (result.status >= 200 && result.status < 300 && data !== null && data.ok !== false) {
    storage()?.removeItem(STORE_WIRE);
    const handle =
      typeof data.handle === "string" && HANDLE.test(data.handle) ? data.handle : null;
    const moved = typeof data.moved_from === "string" && data.moved_from !== "";
    const message =
      handle === null ? t.claimBound("?") : moved ? t.claimMoved(handle) : t.claimBound(handle);
    const extra =
      handle !== null
        ? link(personPath(handle, language), `${t.claimOpenPage} →`, "button")
        : undefined;
    setResult(message, "ok", extra);
    byId<HTMLElement>("claim-actions").hidden = true;
    return;
  }
  setResult(explain(result.status, data), "error");
}

function signInHref(): string {
  return `/auth/login?next=${encodeURIComponent(localPath("/claim", language))}`;
}

async function main(): Promise<void> {
  linkLanguageTwin();
  setCrumbs([{ text: t.claimCrumb }]);
  const store = storage();
  let fragment = window.location.hash.slice(1);
  if (fragment === "" && fixtureMode()) {
    const { fixtureClaim } = await import("./fixtures");
    fragment = fixtureClaim();
  }
  if (fragment === "") fragment = store?.getItem(STORE_WIRE) ?? "";
  const claim = readClaim(fragment);
  const view = byId<HTMLElement>("claim-view");
  if (claim === null) {
    setResult(t.claimBad, "error");
    byId<HTMLElement>("claim-actions").hidden = true;
    view.hidden = true;
    return;
  }
  // Keep the claim in the URL, so the page can be reloaded and the link copied again.
  if (window.location.hash.slice(1) !== fragment) {
    history.replaceState(null, "", `${window.location.pathname}${window.location.search}#${fragment}`);
  }

  byId<HTMLElement>("claim-address").textContent = claim.address;
  byId<HTMLElement>("claim-universe").textContent = claim.universe;
  const now = Math.floor(Date.now() / 1000);
  const left = claim.ts + VALID_SECONDS - now;
  const relative = new Intl.RelativeTimeFormat(language, { numeric: "auto" });
  byId<HTMLElement>("claim-expires").textContent =
    left > 0 ? t.claimExpires(relative.format(Math.ceil(left / 60), "minute")) : t.claimExpired;
  view.hidden = false;

  const here = window.location.host.toLowerCase();
  if (claim.universe.toLowerCase() !== here) {
    setResult(t.claimOtherUniverse(claim.universe), "error");
    byId<HTMLElement>("claim-actions").hidden = true;
    return;
  }
  if (left <= 0) {
    setResult(t.claimExpired, "error");
    byId<HTMLElement>("claim-actions").hidden = true;
    return;
  }

  const signIn = byId<HTMLAnchorElement>("claim-signin");
  signIn.href = signInHref();
  signIn.addEventListener("click", () => {
    store?.setItem(STORE_WIRE, fragment);
    store?.setItem(STORE_PENDING, "1");
  });
  byId<HTMLButtonElement>("claim-now").addEventListener("click", () => void bind(claim));

  // Back from the GitHub sign-in: finish what the owner started.
  if (store?.getItem(STORE_PENDING) === "1") {
    store.removeItem(STORE_PENDING);
    await bind(claim);
  }
}

void main();
