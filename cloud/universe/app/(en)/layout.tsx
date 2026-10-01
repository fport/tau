/**
 * The English root layout: `<html lang="en">`, the theme and the site's stylesheet, the
 * web fonts the first paint needs, and what every page's head shares. Each page sets its own
 * title, description and language alternates (site/en/*.tsx).
 */

import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  metadataBase: new URL("https://tau.getporti.com"),
  icons: { icon: { url: "/brand/tau-coin-red.svg", type: "image/svg+xml" } },
};

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#000000",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link
          rel="preload"
          href="/static/fonts/ibm-plex-sans-latin-wght-normal.woff2"
          as="font"
          type="font/woff2"
          crossOrigin=""
        />
        <link
          rel="preload"
          href="/static/fonts/chakra-petch-latin-600-normal.woff2"
          as="font"
          type="font/woff2"
          crossOrigin=""
        />
        <link rel="stylesheet" href="/static/theme.css" precedence="theme" />
        <link rel="stylesheet" href="/styles/site.css" precedence="site" />
      </head>
      <body>{children}</body>
    </html>
  );
}
