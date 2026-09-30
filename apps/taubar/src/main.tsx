import React from "react";
import ReactDOM from "react-dom/client";
import { isTauri } from "@tauri-apps/api/core";

// One page, two windows: the panel under the menu bar icon (`index.html#panel`) and the
// settings window. Each view module brings its own stylesheet, so a window loads only its own.
async function view(panel: boolean) {
  if (panel) return (await import("./Panel")).default;
  return (await import("./App")).default;
}

async function start() {
  if (import.meta.env.DEV && !isTauri()) await import("./devmock");
  const panel = window.location.hash === "#panel";
  // The panel sits on macOS's popover material; in a browser it draws its own background.
  document.documentElement.classList.toggle("material", panel && isTauri());
  const View = await view(panel);
  ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
    <React.StrictMode>
      <View />
    </React.StrictMode>,
  );
}

start();
