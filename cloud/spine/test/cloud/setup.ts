import { applyD1Migrations } from "cloudflare:test";
import { env } from "cloudflare:workers";

// The cloud project only: the local project has no D1 database.
// Setup files run outside the per-file storage isolation and may run more than once;
// applyD1Migrations() only applies what is missing.
await applyD1Migrations(env.DB, env.TEST_MIGRATIONS);
