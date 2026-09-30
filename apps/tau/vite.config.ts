import { defineConfig, searchForWorkspaceRoot } from "vite";
import react from "@vitejs/plugin-react";
// @ts-expect-error no @types/node in this package
import process from "node:process";

const host = process.env.TAURI_DEV_HOST;

// https://vite.dev/config/ — options tailored for `tauri dev` / `tauri build`.
export default defineConfig(() => ({
  plugins: [react()],
  // Keep Rust errors visible.
  clearScreen: false,
  server: {
    // Tauri expects a fixed port.
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    watch: { ignored: ["**/src-tauri/**"] },
    // The mark comes straight from docs/brand (never redrawn), two levels up.
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), "../../docs/brand"] },
  },
  // One bundle loaded from disk by the app (xterm.js is most of the chat chunk); no network, so
  // no finer split.
  build: { chunkSizeWarningLimit: 1024 },
  test: {
    include: ["src/**/*.test.ts"],
  },
}));
