// The web fonts of the hard theme (cloud/shared/theme.css), copied from their @fontsource
// packages next to theme.css by scripts/build.mjs (and scripts/gallery.mjs). The file names
// are the ones theme.css's @font-face rules ask for; each family's OFL licence goes along.
//
//   Chakra Petch     headings and buttons: angular, chamfered letters (500 and 600)
//   IBM Plex Sans    reading text (variable weight)
//   JetBrains Mono   HUD labels and code (variable weight)

import { copyFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const SUBSETS = ["latin", "latin-ext"];

export const FONTS = [
  {
    package: "@fontsource/chakra-petch",
    files: ["500", "600"].flatMap((weight) =>
      SUBSETS.map((subset) => `chakra-petch-${subset}-${weight}-normal.woff2`),
    ),
    licence: "chakra-petch-OFL.txt",
  },
  {
    package: "@fontsource-variable/ibm-plex-sans",
    files: SUBSETS.map((subset) => `ibm-plex-sans-${subset}-wght-normal.woff2`),
    licence: "ibm-plex-sans-OFL.txt",
  },
  {
    package: "@fontsource-variable/jetbrains-mono",
    files: SUBSETS.map((subset) => `jetbrains-mono-${subset}-wght-normal.woff2`),
    licence: "jetbrains-mono-OFL.txt",
  },
];

/** Copies every font file and licence from `root`'s node_modules into `out`. */
export function copyFonts(root, out) {
  mkdirSync(out, { recursive: true });
  for (const font of FONTS) {
    const source = join(root, "node_modules", font.package);
    for (const file of font.files) copyFileSync(join(source, "files", file), join(out, file));
    copyFileSync(join(source, "LICENSE"), join(out, font.licence));
  }
}
