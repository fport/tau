# 190 · Public downloads for the tau app and its updates

Status: in-progress
Type: AFK
Layer: L8 · Distribution
Packages: .github, apps/tau, cloud/universe
Blocked by: 170

## What to build

The app's release assets (`tau.dmg`, the updater's `latest.json` and `.app.tar.gz`) are attached to GitHub releases, and the updater and `/download` point there. The repository is private for now, so nobody without access can download them, and the updater cannot reach them either.

Serve them from a public place that does not depend on the repository's visibility:

- CI uploads the signed assets to an R2 bucket on each release tag.
- The universe serves them at `https://tau.getporti.com/download/tau.dmg` and `…/latest.json`, through an R2 binding or a public bucket on a subdomain.
- The updater endpoint and the download page use those URLs.
- GitHub releases keep the copies.

## Acceptance criteria

- [ ] A tag puts `tau.dmg` and `latest.json` where a signed-out visitor can download them; the updater updates from there
- [ ] `/download`, the app guide and `tau setup`'s app step use the public URL

## Comments

- 2026-10-01: found by issue 175. The repository is private, so the GitHub release links do not work for visitors.
- 2026-10-01: built; stays in progress until the owner's one-time steps, the universe wiring and the first tag. Neither criterion can be ticked yet: the first needs a real release, and in the second the app guide and `tau setup` are done but `/download`'s button is not (below). As built (five commits: `feat(cloud)`, `ci(app)`, `feat(app)`, two `docs`):
    - **Serving** (`cloud/universe/src/downloads.ts`): `serveDownload(request, env, url)` answers GET and HEAD for `/download/tau.dmg`, `/download/latest.json`, `/download/tau.app.tar.gz` and `/download/v<version>/{tau.dmg,tau.app.tar.gz}` from the private R2 bucket bound as `DOWNLOADS` (`tau-downloads`). The object key is the path after `/download/`. It returns null for every other path, so the caller's routing answers it (the 404 page), and `/download/` is a `301` to the page.
        - Safety: a fixed allowlist of names, a strict semver version (no build metadata, at most 64 characters), the path matched still percent-encoded, and no `list`.
        - Headers: `application/x-apple-diskimage` with `Content-Disposition: attachment; filename="tau.dmg"`, `application/gzip`, `application/json`. `Cache-Control` is `public, max-age=300` for the unversioned files and `public, max-age=31536000, immutable` for a release's own.
        - Validators and ranges: ETag and Last-Modified come from R2. `If-None-Match` (and `If-Modified-Since` without it) gives 304. One byte range gives 206 with `Content-Range`, a range past the end 416, and an `If-Range` that names another file the whole new file.
        - Reads: `head`, then `get` with `onlyIf: {etagMatches}`. When a release replaces the file between the two reads, it tries once more.
        - Errors: no binding is `503 {"error":"downloads_unavailable"}`, a missing object `404 {"error":"not_found"}`, both `no-store`; other methods are 405.
        - `UniverseEnv` got one optional line, `DOWNLOADS?: R2Bucket`. `test/downloads.test.ts` (23 tests) calls the module with a fake bucket whose `list` throws.
        - `pageRoute`/`isForwarded` never claim `/download/...`, and `download` is in `RESERVED_NAMES`, so there is no collision with the page route.
    - **CI** (`app.yml`): a `downloads` job after `build`, skipped on dry runs, warns and uploads nothing without `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID`. With them it runs `bunx wrangler@4.144.0 r2 object put tau-downloads/<key> --file … --content-type … --remote` in this order: `v<version>/tau.dmg`, `v<version>/tau.app.tar.gz`, then `tau.app.tar.gz`, `tau.dmg`, and `latest.json` last. A pre-release stops after its versioned files, so "latest" and the updater stay on the last release, as GitHub's `latest` did.
    - **latest.json:** `pack-release.sh` takes `TAU_DOWNLOAD_BASE` (default `https://tau.getporti.com/download`, https only) instead of `TAU_RELEASE_URL`, writes `<base>/v<version>/tau.app.tar.gz` as both platforms' URL, and refuses a non-semver version. The GitHub release keeps the same manifest (one manifest; GitHub's URLs only work with repository access). The `.sig` stays a release asset only: the updater reads the signature from `latest.json`.
    - **Updater:** `plugins.updater.endpoints` is `https://tau.getporti.com/download/latest.json`; `requireSignedVersion` and `pubkey` are unchanged. The Rust config test, `update.rs`'s docs and no-key dialog, and the settings window's note name tau.getporti.com.
    - **Docs:** the app guide (EN + TR) and `apps/tau/README.md` link `https://tau.getporti.com/download/tau.dmg` and describe updates from tau.getporti.com. The README and `docs/contributing/release.md` cover the upload order, the bucket, enabling R2, the token (R2 Storage Edit plus Workers Scripts Edit, shared with `docs.yml`) and the two secrets. `docs/reference/tau-universe.md` §2 has a self-contained "App downloads" subsection. `setup.note.app.download` already pointed to `https://tau.getporti.com/download` (994c02d) and is unchanged.
    - **Verified:** universe `bun run test` 337 tests (13 files) and `bun run typecheck`. With the entry hook applied temporarily (not committed), `/download/tau.dmg` was 503 through the Worker with the security headers, POST 405, and an unknown name the 404 page. App: `bun run test` 64, `cargo test` 190 + 4, `cargo clippy --all-targets -D warnings`, `cargo fmt --check`. `pack-release.sh` ran end to end on a stand-in app with a throwaway updater key: `latest.json` named `…/download/v0.5.0/tau.app.tar.gz` (and `-rc1`), a custom base worked, an http base and `0.5.0rc1` were refused. Also: actionlint with shellcheck on `app.yml`, shellcheck on the script, `pytest packages/tau-core/tests/setup`, `mkdocs build --strict`. Not run: the workflow on GitHub, a real upload, a real update.
    - **Left for the universe session (vinext migration):**
        - Call `serveDownload` from the Worker entry before page routing, for paths under `/download/`.
        - Add `"r2_buckets": [{ "binding": "DOWNLOADS", "bucket_name": "tau-downloads" }]` to `wrangler.example.jsonc` and `/download/*` to `run_worker_first` (plus the test that lists those paths), then regenerate the types.
        - Point `/download`'s button (EN + TR) at `/download/tau.dmg` and update `DMG` in `test/pages.test.ts`.
        - Optional: a `configure --downloads-bucket NAME` for another bucket name.
    - **Left for the owner:** enable R2 in the dashboard, `bunx wrangler r2 bucket create tau-downloads`, a token with Account · Workers R2 Storage · Edit and Account · Workers Scripts · Edit, `gh secret set CLOUDFLARE_API_TOKEN` and `gh secret set CLOUDFLARE_ACCOUNT_ID`, deploy the universe with the binding, then tag a release.
