# 174 · Deploy a spine without Node: the Cloudflare API with a scoped token

Status: done
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-net
Blocked by: –

## What to build

[ADR 0014](../../docs/adr/0014-one-installer-and-onboarding.md) §4.

`tau net spine deploy` gains an API path that needs no Node, bun or Wrangler:

- **The token.** It opens Cloudflare's token page pre-filled with the scopes the spine needs (Workers Scripts, Durable Objects, KV, custom domains, rate limits), and takes the token at a hidden prompt. The token is stored in `.env` as `CLOUDFLARE_API_TOKEN`, never in argv.
- **The deploy.** It uploads the kit's pre-bundled `worker.js` with its metadata (bindings, migrations, compatibility date, rate limits), sets `HUB_TOKEN` as a secret and adds the custom domain or the workers.dev route.
- **Wrangler stays** as the other path. Tests use a fake Cloudflare API.

## Acceptance criteria

- [x] A deploy through the fake API sends exactly the documented requests; secrets never reach argv or logs
- [x] `docs/guides/tau-network` and `build-your-own-tau` (EN + TR) show the no-Node path first

## Comments

- 2026-10-01: filed with ADR 0014.
- 2026-10-01: done. `tau net spine deploy DIR` deploys through the Cloudflare API by default (`tau_net/spine_api.py`); `--wrangler` keeps the Wrangler path, `--api` names the default. The API path reads the same `wrangler.jsonc` + `worker.js` and needs no Node.js, bun or Wrangler.
  - **Token.** `CLOUDFLARE_API_TOKEN` from the environment, else `<TAU_HOME>/.env`, else a hidden prompt (or `--json` stdin). Before the prompt it prints, and on a local terminal (not over SSH) opens, Cloudflare's user-token template URL, verified against Cloudflare's "API token template URLs" page: `https://dash.cloudflare.com/profile/api-tokens?permissionGroupKeys=<URL-encoded JSON>&accountId=%2A&zoneId=all&name=tau%20spine`. The JSON is `[{"key":"workers_scripts","type":"edit"},{"key":"workers_kv_storage","type":"edit"},{"key":"account_settings","type":"read"}]` (+ `{"key":"workers_routes","type":"edit"}` for a custom domain), after Cloudflare's "Edit Cloudflare Workers" template. `GET /user/tokens/verify` must say `active`; then the token is written to `.env` with `set_credential` (0600, only that line).
  - **Requests, in order:** `GET /user/tokens/verify`; `GET /accounts?page=1&per_page=50` (unless `--account-id`, `account_id` in `wrangler.jsonc` or `CLOUDFLARE_ACCOUNT_ID`); `GET /accounts/{a}/workers/subdomain` (workers.dev only; 10007 → stop with the onboarding link before any write); `GET /accounts/{a}/workers/scripts` (migration tag); for KV without an id `GET …/workers/scripts/tau-spine/settings` (deployed binding), else `GET /accounts/{a}/storage/kv/namespaces?page=1&per_page=100` (title `tau-spine-tau`, Wrangler's name), else `POST` there `{"title":"tau-spine-tau"}`; `PUT /accounts/{a}/workers/scripts/tau-spine` (multipart: `metadata` application/json + `worker.js` application/javascript+module); `PUT …/secrets` `{"name":"HUB_TOKEN","text":…,"type":"secret_text"}`; `PUT …/schedules` `[{"cron":"* * * * *"}]`; `POST …/subdomain` `{"enabled":true}` (or `false` with a custom domain, as Wrangler does) and `PUT /accounts/{a}/workers/domains` `{"hostname","service":"tau-spine"}`; then `GET https://<address>/hub/health` with the new hub token, up to 6 × 5 s (a note, not a failure, when it does not answer yet).
  - **Metadata** mirrors Wrangler 4.144.0's `createWorkerUploadForm` (read from its source): `main_module`, bindings (`plain_text` vars, `kv_namespace` + `namespace_id`, `durable_object_namespace` + `class_name`, `ratelimit` + `namespace_id` + `simple`), `compatibility_date`, `compatibility_flags`, `migrations`, `observability`.
  - **Migrations and ids.** Migrations follow Wrangler's `getMigrationsToUpload`: tags from `wrangler.jsonc`, `{new_tag, steps}` for a new Worker, nothing when the deployed `migration_tag` is the last one, `{old_tag, new_tag, steps}` otherwise (all steps for an unknown tag). So the API path and `--wrangler` can take turns on one Worker. `account_id` and the KV `id`s are written into the project's `wrangler.jsonc` (comments kept), and an `--address` the project lacks becomes `ADDRESS` + its custom-domain route there. A fresh `init` directory finds the deployed Worker's namespace through its settings.
  - **Secrets.** The API token only in `Authorization`, the hub token only in the secret body and the health check's header; every error is masked. A 401/403 or code 10000/9109 names the missing permission. D1, R2, zone routes and build steps are refused with a pointer to `--wrangler`.
  - **`--json`** (for the app's wizard, issue 171): stdin `{"token"?, "account_id"?}`; stdout JSON lines `progress {key,text,fields}`, `need_token {link,scopes,permissions,message}`, `choose_account {accounts:[{id,name}],message}`, `error {message}`, `done {url,account_id,token_created,healthy}`; exit 0 only for `done`.
  - Tests: `packages/tau-net/tests/test_spine_api.py`, a fake Cloudflare that records every request and serves the deployed `FakeSpine` (first deploy, redeploy, fresh directory, Wrangler takeover, custom domain, missing scopes, bad token, several accounts, JSON mode); the Wrangler tests pass `--wrangler`. The kit README (`kit.mjs`, regenerated) and the docs show the API path first; `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID` are in the environment reference and both `.env.example` files.
