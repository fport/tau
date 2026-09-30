/**
 * The script of how it works: the star field behind the page (client/starfield.ts), and the
 * storyline's current station. Every station on the storyline is grey; the one for the
 * chapter being read is lit, and so is that chapter's marker. The page reads the same
 * without it.
 */

import { starfield } from "./starfield";

starfield();

function storyline(): void {
  const chapters = [...document.querySelectorAll<HTMLElement>("section.chapter[id]")];
  const stations = new Map<string, HTMLAnchorElement>();
  for (const anchor of document.querySelectorAll<HTMLAnchorElement>(".story-stops a[href^='#']")) {
    stations.set(anchor.hash.slice(1), anchor);
  }
  if (chapters.length === 0 || !("IntersectionObserver" in window)) return;

  const visible = new Set<HTMLElement>();
  let current: HTMLElement | null = null;

  const mark = (chapter: HTMLElement | null) => {
    if (chapter === current) return;
    if (current !== null) {
      current.classList.remove("is-here");
      const before = stations.get(current.id);
      before?.parentElement?.classList.remove("is-here");
      before?.removeAttribute("aria-current");
    }
    current = chapter;
    if (chapter !== null) {
      chapter.classList.add("is-here");
      const station = stations.get(chapter.id);
      station?.parentElement?.classList.add("is-here");
      station?.setAttribute("aria-current", "location");
    }
  };

  // A chapter is current while it crosses a thin band a little above the middle of the
  // screen; of several, the one furthest down the page wins (the one just entered).
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        const chapter = entry.target as HTMLElement;
        if (entry.isIntersecting) visible.add(chapter);
        else visible.delete(chapter);
      }
      const ordered = chapters.filter((chapter) => visible.has(chapter));
      mark(ordered.at(-1) ?? null);
    },
    { rootMargin: "-38% 0px -58% 0px" },
  );
  for (const chapter of chapters) observer.observe(chapter);
}

storyline();
