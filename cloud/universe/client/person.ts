/**
 * The person page, `/@<handle>` (ADR 0013 §6): reads `GET /api/people/<handle>` and shows the
 * person's tau, its public sub-taus as cards with their characters, and the taus it is
 * linked with. Everything from the API is set as text.
 */

import { getJson } from "./api";
import { byId, characterElement, githubIcon, html, link } from "./dom";
import { HANDLE, personFromPath, personPath, subPath, universePath } from "./paths";
import {
  counted,
  hideState,
  language,
  linkLanguageTwin,
  month,
  reducedMotion,
  setCrumbs,
  shortMonth,
  showState,
  t,
} from "./site";
import type { PageSub, PersonView } from "./types";

const handle = personFromPath(window.location.pathname);

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function subsOf(view: PersonView): PageSub[] {
  return Array.isArray(view.subs)
    ? view.subs.filter((sub) => typeof sub?.name === "string" && sub.name !== "")
    : [];
}

function renderHead(view: PersonView, who: string): void {
  const avatar = byId<HTMLElement>("person-avatar");
  avatar.replaceChildren(
    characterElement(text(view.address) || `@${who}`, {
      size: 144,
      animated: !reducedMotion.matches,
    }),
  );
  byId<HTMLElement>("person-handle").textContent = `@${who}`;

  const github = byId<HTMLAnchorElement>("person-github");
  github.href = `https://github.com/${who}`;
  github.replaceChildren(githubIcon(), html("span", undefined, `github.com/${who}`));

  const since = month(view.building_since);
  const sinceLine = byId<HTMLElement>("person-since");
  sinceLine.textContent = since === "" ? "" : t.buildingSince(since);
  sinceLine.hidden = since === "";

  const counts = view.counts ?? { subs: 0, links: 0, messages: 0 };
  byId<HTMLElement>("person-counts").textContent = [
    counted(t.publicSubs, counts.subs),
    counted(t.links, counts.links),
    counted(t.messages, counts.messages),
  ].join(" · ");
}

function renderTau(view: PersonView): void {
  const box = byId<HTMLAnchorElement>("person-tau");
  const address = text(view.address);
  box.href = address === "" ? localUniverse() : universePath(address, language);
  const online = view.online === true;
  const titles = html("span", "strip-titles");
  const status = html("span", "strip-status kicker");
  status.append(html("span", online ? "pip" : "pip pip-off"), online ? t.online : t.offline);
  titles.append(
    status,
    html("span", "strip-name", text(view.name) || address),
    html("span", "strip-address", address),
  );
  if (text(view.about) !== "") titles.append(html("span", "strip-about", text(view.about)));
  box.replaceChildren(
    characterElement(address, { size: 56, animated: !reducedMotion.matches }),
    titles,
  );
}

function localUniverse(): string {
  return language === "tr" ? "/tr/universe" : "/universe";
}

function renderSubs(view: PersonView, who: string): void {
  const subs = subsOf(view);
  byId<HTMLElement>("subs-title").textContent = counted(t.publicSubs, subs.length);
  const grid = byId<HTMLUListElement>("sub-grid");
  grid.replaceChildren();
  byId<HTMLElement>("subs-empty").hidden = subs.length > 0;
  const address = text(view.address);
  for (const sub of subs) {
    const href = subPath(sub, who, language) ?? universePath(`${address}/${sub.name}`, language);
    const card = link(href, "", "sub-card corners");
    const head = html("span", "sub-card-head");
    head.append(html("span", "sub-card-name", `/${sub.name}`));
    if (sub.web === true) head.append(html("span", "tag", t.chatTag));
    card.append(
      characterElement(`${address}/${sub.name}`, { size: 88, animated: !reducedMotion.matches }),
      head,
    );
    if (text(sub.about) !== "") card.append(html("span", "sub-card-about", text(sub.about)));
    const seen = shortMonth(sub.first_seen);
    if (seen !== "") card.append(html("span", "sub-card-meta", t.firstSeen(seen)));
    const item = html("li");
    item.append(card);
    grid.append(item);
  }
}

function renderLinked(view: PersonView): void {
  const list = byId<HTMLUListElement>("linked");
  list.replaceChildren();
  const linked = Array.isArray(view.links) ? view.links : [];
  let shown = 0;
  for (const peer of linked) {
    const address = text(peer?.peer);
    if (address === "") continue;
    const peerHandle =
      typeof peer.handle === "string" && HANDLE.test(peer.handle) ? peer.handle : null;
    const href =
      peerHandle !== null ? personPath(peerHandle, language) : universePath(address, language);
    const anchor = link(href, "", "linked-tau");
    const titles = html("span", "linked-titles");
    const name = html("span", "linked-name");
    name.append(html("span", peer.online === true ? "pip" : "pip pip-off"), text(peer.name) || address);
    titles.append(name);
    const meta = [peerHandle !== null ? `@${peerHandle}` : address];
    if (typeof peer.messages === "number") meta.push(counted(t.msgs, peer.messages));
    titles.append(html("span", "linked-meta", meta.join(" · ")));
    anchor.append(characterElement(address, { size: 40, animated: false }), titles);
    const item = html("li");
    item.append(anchor);
    list.append(item);
    shown++;
  }
  byId<HTMLElement>("linked-empty").hidden = shown > 0;
}

async function load(): Promise<void> {
  linkLanguageTwin();
  if (handle === null) {
    setCrumbs([{ text: "@?" }]);
    showState(t.personMissing, null);
    return;
  }
  setCrumbs([{ text: `@${handle}` }]);
  document.title = t.personTitle(handle);
  showState(t.loading, null);
  const result = await getJson<PersonView>(`/api/people/${encodeURIComponent(handle)}`);
  if (result.status === 404) {
    showState(t.personMissing, t.personMissingHint(handle));
    return;
  }
  if (result.status !== 200 || result.data === null || typeof result.data !== "object") {
    showState(t.pageFailed, null, () => void load());
    return;
  }
  const view = result.data;
  const who = typeof view.handle === "string" && HANDLE.test(view.handle) ? view.handle : handle;
  renderHead(view, who);
  renderTau(view);
  renderSubs(view, who);
  renderLinked(view);
  hideState();
  byId<HTMLElement>("person-view").hidden = false;
}

void load();
