/**
 * A tiny DOM builder. Text always goes in as text nodes, never as HTML, so nothing a model,
 * a visitor or the owner wrote can become markup. The one exception is `svg()`, which takes
 * the character generator's output (built from a seed, with its label escaped).
 */

type Child = Node | string | null | undefined | false;
type Attrs = Record<string, string | number | boolean | null | undefined | EventListener>;

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Attrs = {},
  ...children: (Child | Child[])[]
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (name.startsWith("on") && typeof value === "function") {
      element.addEventListener(name.slice(2).toLowerCase(), value as EventListener);
    } else if (name === "class") {
      element.className = String(value);
    } else if (value === true) {
      element.setAttribute(name, "");
    } else if (name === "value" && "value" in element) {
      (element as HTMLInputElement).value = String(value);
    } else {
      element.setAttribute(name, String(value));
    }
  }
  append(element, children);
  return element;
}

export function append(parent: Node, children: (Child | Child[])[]): void {
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    parent.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
}

export function clear(element: Element): void {
  while (element.firstChild) element.removeChild(element.firstChild);
}

/** An element holding an SVG string made by the character generator. */
export function svg(markup: string, className = "char"): HTMLSpanElement {
  const holder = document.createElement("span");
  holder.className = className;
  // Parsed as HTML (inert: nothing runs in a DOMParser document), so an <svg> without an
  // xmlns still lands in the SVG namespace.
  const doc = new DOMParser().parseFromString(`<body>${markup}</body>`, "text/html");
  const root = doc.body.firstElementChild;
  if (root !== null && root.namespaceURI === "http://www.w3.org/2000/svg") {
    // Drop anything executable, whatever the generator returns.
    for (const node of root.querySelectorAll("script, foreignObject")) node.remove();
    for (const node of [root, ...root.querySelectorAll("*")]) {
      for (const attr of [...node.attributes]) {
        if (/^on/i.test(attr.name) || /javascript:/i.test(attr.value)) node.removeAttribute(attr.name);
      }
    }
    holder.appendChild(document.importNode(root, true));
  }
  return holder;
}

/** The JSON a page put into `<script type="application/json" id="tau-data">`. */
export function pageData<T>(): T {
  const text = document.getElementById("tau-data")?.textContent ?? "{}";
  return JSON.parse(text) as T;
}

export function time(seconds: number, lang: string): string {
  return new Intl.DateTimeFormat(lang, { hour: "2-digit", minute: "2-digit" }).format(new Date(seconds * 1000));
}

export function date(seconds: number, lang: string): string {
  return new Intl.DateTimeFormat(lang, { dateStyle: "medium", timeZone: "UTC" }).format(new Date(seconds * 1000));
}

export function usd(value: number, lang: string): string {
  return new Intl.NumberFormat(lang, { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value);
}
