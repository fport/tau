"use client";

/**
 * Runs a page's script from client/ once the page has hydrated. The scripts draw into the
 * markup the server rendered (the universe on its canvas, the star field, the visitor chat)
 * and React never reconciles what they draw, because the pages above them render once.
 */

import { useEffect } from "react";

const SCRIPTS = {
  landing: () => import("../client/landing"),
  universe: () => import("../client/universe"),
  person: () => import("../client/person"),
  sub: () => import("../client/sub"),
  claim: () => import("../client/claim"),
  how: () => import("../client/how"),
  sky: () => import("../client/sky"),
  download: () => import("../client/download"),
} as const;

export type ScriptName = keyof typeof SCRIPTS;

export function PageScript({ name }: { name: ScriptName }) {
  useEffect(() => {
    void SCRIPTS[name]();
  }, [name]);
  return null;
}
