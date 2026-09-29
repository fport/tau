# 081 · Create a Cloudflare token scoped to Tunnel, Access and R2, and the private backup bucket

Status: ready-for-human
Type: HITL
Layer: L3 · Access and data
Packages: -
Blocked by: none

## What to build

The Cloudflare half of the external identities the private-first topology needs (ADR 0006), split out of 013 so the Telegram channel (014) did not wait on it: a Cloudflare API token that can only manage the Tunnel, the Access policy, the DNS records for the tau hostname and the backup bucket, and the private R2 bucket the encrypted backups (018) go to. No Workers, D1, Vectorize or AI Search permissions: nothing in Cloudflare holds personal data.

Steps for the user:

1. Cloudflare: in the account that will hold the domain (022), create an API token limited to: Cloudflare Tunnel (edit), Access apps and policies (edit), DNS for the tau zone (edit; narrow it to the zone once 022 is done), R2 (edit). Store it as `CLOUDFLARE_API_TOKEN` and the account id as `CLOUDFLARE_ACCOUNT_ID` in `.env`.
2. R2: create a private bucket for the encrypted backups (018) and an R2 API token (S3 access key and secret) limited to that bucket. Store the bucket name as `TAU_BACKUP_BUCKET` and the credentials as `TAU_BACKUP_S3_ACCESS_KEY_ID` / `TAU_BACKUP_S3_SECRET_ACCESS_KEY`.
3. Add every new variable name with an example value to `.env.example`; real values stay in the gitignored `.env`.

## Acceptance criteria

- [ ] Cloudflare API token scoped to Tunnel, Access, zone DNS and R2 only; no Workers, D1, Vectorize, AI Search permissions and no global key
- [ ] A private R2 bucket for backups and a bucket-limited R2 API token exist; names and credentials in `.env`
- [ ] `.env.example` lists every new variable name with an example value; nothing real is committed

## Blocked by

None - can start immediately (the token's DNS scope is narrowed to the tau zone after 022).

## Comments

- 2026-09-29: split out of 013 (steps 3 and 4 and their criteria) so 013 could close with the Telegram half and unblock 014. 018 and 076 now depend on this issue for the token and the bucket.
