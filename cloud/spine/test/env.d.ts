declare namespace Cloudflare {
  interface Env {
    /** The D1 migrations, read by vitest.config.ts and applied by test/setup.ts. */
    TEST_MIGRATIONS: import("cloudflare:test").D1Migration[];
  }
}
