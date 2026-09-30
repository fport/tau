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
  test: {
    include: ["src/**/*.test.ts"],
  },
}));
