// The panel's line icons (24 px grid, drawn with currentColor). The tau mark itself comes from
// docs/brand, never from here.

import type { ReactNode } from "react";

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.9}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      {children}
    </svg>
  );
}

export const SendIcon = () => (
  <Icon>
    <path d="M21 3 10 14" />
    <path d="m21 3-7 18-4-7-7-4 18-7z" />
  </Icon>
);

export const AlertIcon = () => (
  <Icon>
    <path d="M12 9v4" />
    <path d="M12 17h.01" />
    <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
  </Icon>
);

export const MoonIcon = () => (
  <Icon>
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
  </Icon>
);

export const PlugIcon = () => (
  <Icon>
    <path d="M9 2v6" />
    <path d="M15 2v6" />
    <path d="M6 8h12v4a6 6 0 0 1-12 0V8z" />
    <path d="M12 18v4" />
  </Icon>
);

export const LaptopIcon = () => (
  <Icon>
    <rect x="3" y="4" width="18" height="12" rx="2" />
    <path d="M2 20h20" />
  </Icon>
);
