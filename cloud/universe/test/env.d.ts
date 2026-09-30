/** Vite's `?raw` imports: the file's text (used to compare tracked copies and config). */
declare module "*?raw" {
  const text: string;
  export default text;
}

/** Vite's `import.meta.glob`, lazy: the matching paths, each with a loader (never called). */
interface ImportMeta {
  glob(pattern: string | string[]): Record<string, () => Promise<unknown>>;
}
