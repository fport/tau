/**
 * Small DOM helpers shared by the site's scripts. Text from the network is always set with
 * `textContent`; the only markup parsed here is the character SVG, which
 * cloud/shared/character.ts builds from a hash and escapes.
 */

import { type CharacterOptions, character } from "../../shared/character";

export const SVG_NS = "http://www.w3.org/2000/svg";

export function byId<T extends HTMLElement | SVGElement>(id: string): T {
  const element = document.getElementById(id);
  if (element === null) throw new Error(`missing #${id}`);
  return element as T;
}

export function maybeId<T extends HTMLElement | SVGElement>(id: string): T | null {
  return document.getElementById(id) as T | null;
}

export function svg<K extends keyof SVGElementTagNameMap>(
  name: K,
  attributes: Record<string, string | number> = {},
): SVGElementTagNameMap[K] {
  const element = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  return element;
}

export function html<K extends keyof HTMLElementTagNameMap>(
  name: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const element = document.createElement(name);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

/** A link with text, for a path the page built itself. */
export function link(href: string, text: string, className?: string): HTMLAnchorElement {
  const anchor = html("a", className, text);
  anchor.href = href;
  return anchor;
}

/**
 * The character of `seed` as an SVG element, ready to append to HTML or into another SVG.
 * `label: ""` (the default here) makes it decorative, for places where the name is written
 * next to it.
 */
export function characterElement(seed: string, opts: CharacterOptions = {}): SVGSVGElement {
  const template = document.createElement("template");
  template.innerHTML = character(seed, { label: "", ...opts });
  const element = template.content.firstElementChild;
  if (!(element instanceof SVGSVGElement)) throw new Error("character did not parse");
  return element;
}

/** The GitHub mark (Octicons, MIT), for "Sign in with GitHub" and profile links. */
export function githubIcon(): SVGSVGElement {
  const icon = svg("svg", { viewBox: "0 0 16 16", "aria-hidden": "true", focusable: "false" });
  icon.append(
    svg("path", {
      d:
        "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49" +
        "-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82" +
        ".72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15" +
        "-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82" +
        " 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48" +
        " 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z",
    }),
  );
  return icon;
}
