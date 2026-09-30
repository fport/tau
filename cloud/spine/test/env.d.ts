declare namespace Cloudflare {
  interface Env {
    /**
     * The D1 migrations of the cloud project, read by vitest.config.ts and applied by
     * test/cloud/setup.ts. The local project has neither them nor a D1 database.
     */
    TEST_MIGRATIONS: import("cloudflare:test").D1Migration[];
  }
}
