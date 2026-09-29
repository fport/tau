# 018 · Encrypted backups of `TAU_DATA_DIR` to R2 with a restore drill

Status: ready-for-agent
Type: AFK
Layer: L3 · Access and data
Packages: tau-core, infra/backup
Blocked by: 081

## What to build

Life data lives on the hub (ADR 0006 §3); the only copy that leaves it is a client-side encrypted archive in the private R2 bucket from 081. A `tau backup` command group in tau-core plus `infra/backup/`:

- `tau backup now`: streams the data dir (sessions, settings, memory, KB index, routines, hub state, Telegram offsets, media; logs excluded) as a tar into `age` encryption to the configured recipient (`[backup] recipient` in `tau.toml`, an `age1...` public key) and uploads it with the S3 API as `<hub name>/<UTC timestamp>.tar.age`. Nothing is written unencrypted outside the data dir; a partial upload leaves no half object.
- `tau backup list`, `tau backup verify <name>` (download, decrypt with the identity, check the archive) and `tau backup restore <name> --to <dir>` (never onto a live data dir; the restored tree passes `tau doctor` with `TAU_DATA_DIR` pointing at it).
- Key handling: `tau backup keygen` creates the `age` identity outside the data dir (`<home>/backup-identity.txt`, mode 0600, path in `[backup] identity`) and prints the recipient for `tau.toml`; the identity is copied once into the owner's password manager and never goes into Cloudflare, the archive or the repo.
- Schedule: a `backup` `tau.hub_services` component runs `now` on an interval (`[component.backup] interval_hours`, default 24; moves to settings when 019 exists) and reports the last run in `/status`; `infra/backup/` holds a launchd plist for a machine where `tau hub` is not installed, plus the restore-drill notes. Retention (keep N daily, M monthly objects) is configuration; local data is never deleted by backup code.
- Client: S3 behind a small interface with a fake in tests; the real client is an optional extra (`tau-core[backup]`) so the base install stays small. Credentials come from `.env` (081).
- The docs-site guide "Backups" walks through keygen → first backup → restore into a fresh directory → `tau doctor` and `/sessions` show the same data, with example values only.

## Acceptance criteria

- [ ] `tau backup now` uploads an `age`-encrypted archive; a listing shows only `.tar.age` objects and the bucket is private
- [ ] `tau backup restore` into an empty directory reproduces sessions, settings, memory and KB; `tau doctor` and `/sessions` agree with the source (fake S3 in tests; a real bucket in the documented drill)
- [ ] The identity file is never inside the archive, the data dir or the repo; `tau backup keygen` refuses to overwrite an existing identity
- [ ] The scheduled backup runs from the hub and reports its last run in `/status`; a failed upload is a warning in the log and the status, never a crash
- [ ] Retention is configuration; local data is never deleted by the backup code
- [ ] `infra/backup/` holds the launchd example and the drill notes; the docs guide covers keygen, first backup and restore without any personal value

## Blocked by

- [081 · Create a Cloudflare token scoped to Tunnel, Access and R2, and the private backup bucket](081-cloudflare-token-and-backup-bucket.md)

## Comments

- 2026-09-29: reworded `/devam` → `/resume` (Turkish aliases stay accepted, see 062). Backend choice (D1-backed `SessionRepository` vs Strands `Storage`/`SnapshotSessionManager`) is decided in 071 before this starts.
- 2026-09-29: rewritten for ADR 0006 (private-first). Before: a D1 session backend behind the `tau-cloud` Worker API with `/resume` on Telegram. Now: the file session store on the hub (ADR 0003) is the record, and this issue is the encrypted backup of the whole data dir to R2 plus the restore drill; `/resume` on Telegram comes with 014 through the shared command spec. 071 is closed as wontfix (no remote backend to decide for). The file keeps its old slug so links stay stable.
