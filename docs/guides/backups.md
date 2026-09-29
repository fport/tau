# Backups (encrypted, R2)

Everything tau knows lives on the hub. That is the point of the design, and it makes backups your job. This guide shows what to back up, how to encrypt it with `age` so that Cloudflare only ever holds ciphertext, and how to upload and restore it. The manual flow works today; the scheduled job is planned.

!!! info "Planned (roadmap issue 018): the backup job"
    A `tau backup` command and a scheduled hub service will run the flow on this page automatically, keep a rotation, and document the restore. Until then, the commands below are the backup. They are the same commands the job will run.

## What is in the data directory

`TAU_DATA_DIR` (default `~/.local/share/tau`) holds everything tau writes:

```text
~/.local/share/tau/
├── sessions/<id>/            one directory per session, kept forever
│   ├── session.json          the Strands session record
│   ├── meta.json             channel, profile, title, role, compaction links
│   ├── events.jsonl          agent events: tool calls, approvals, limits, errors
│   └── agents/tau/           agent state and one file per message
├── hub/                      hub state: lock, heartbeat, crash reports, launchd logs
└── logs/tau.log              the log file
```

Later layers add settings, memory and the knowledge base under the same root, so a backup of `TAU_DATA_DIR` stays complete.

Two things live **outside** it and are also worth keeping:

| Path | Why |
|---|---|
| `<TAU_HOME>/persona/user.md` | the facts about you; it is not tracked anywhere |
| `<TAU_HOME>/tau.toml` | your role and component choices; harmless, convenient |

`<TAU_HOME>/.env` holds credentials. Keep those in your password manager, not in the backup bundle; a restore then needs one paste instead of trusting the bundle with every key you own. If you do include it, the bundle is encrypted anyway, but the blast radius of a lost `age` key grows.

## The key

Backups are encrypted with [`age`](https://github.com/FiloSottile/age), a small modern file encryption tool, to a key pair. The private key stays on the hub and in your password manager. It never goes to Cloudflare.

=== "macOS"

    ```sh
    brew install age
    ```

=== "Linux"

    ```sh
    sudo apt install age
    ```

```sh
mkdir -p ~/.config/tau && chmod 700 ~/.config/tau
age-keygen -o ~/.config/tau/backup.key
chmod 600 ~/.config/tau/backup.key
```

`age-keygen` prints the public key, a line like `Public key: age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p`. Copy it somewhere handy; you encrypt with it. Then **put the whole `backup.key` file into your password manager**. Without it, every backup is noise.

!!! warning
    Losing `backup.key` loses every backup. Losing the hub does not, as long as the key is in the password manager. Test the restore below once, now, while nothing is at stake.

## Make a backup

One bundle, streamed through `age`, so the plaintext archive never touches the disk:

```sh
export TAU_DATA_DIR="${TAU_DATA_DIR:-$HOME/.local/share/tau}"
export TAU_HOME="${TAU_HOME:-$HOME/.tau}"
export TAU_BACKUP_PUBKEY='age1...'           # from age-keygen

stamp=$(date -u +%Y%m%dT%H%M%SZ)
tar -C / -czf - \
  "${TAU_DATA_DIR#/}/sessions" "${TAU_DATA_DIR#/}/hub" \
  "${TAU_HOME#/}/persona/user.md" "${TAU_HOME#/}/tau.toml" \
  | age -r "$TAU_BACKUP_PUBKEY" -o "/tmp/tau-$stamp.tar.gz.age"
ls -l "/tmp/tau-$stamp.tar.gz.age"
```

`hub/hub.lock` is included and harmless. `logs/` is left out on purpose; add it if you want it.

## Upload to a private R2 bucket

R2 is Cloudflare's object storage. A private bucket has no public URL; only your API token can read it, and even then it only reads ciphertext.

1. Create a Cloudflare API token with **R2 read and write** on your account (`Account → R2 → Manage R2 API tokens`, or a user token scoped to *Workers R2 Storage: Edit*). Store it in `~/.config/tau/remote.env` as `CLOUDFLARE_API_TOKEN=...` or run `npx wrangler login` once.
2. Create the bucket and upload:

    ```sh
    npx wrangler r2 bucket create tau-backups
    npx wrangler r2 object put "tau-backups/$stamp.tar.gz.age" \
      --file "/tmp/tau-$stamp.tar.gz.age" --remote
    rm "/tmp/tau-$stamp.tar.gz.age"
    ```

    `--remote` makes wrangler talk to the real bucket instead of a local emulation.

3. Check what is there:

    ```sh
    npx wrangler r2 object get "tau-backups/$stamp.tar.gz.age" --file /tmp/check.age --remote
    cmp /tmp/check.age "/tmp/tau-$stamp.tar.gz.age" 2>/dev/null && echo same
    ```

!!! tip "Large bundles: rclone"
    `wrangler r2 object put` is fine for bundles up to a few hundred megabytes. For more, or for incremental sync, configure [rclone](https://rclone.org/) against R2's S3-compatible endpoint with an R2 access key pair, then `rclone copy /tmp/tau-$stamp.tar.gz.age r2:tau-backups/`. The encryption step is the same; only the upload changes.

## Restore

On the hub, or on a new machine that will become the hub:

```sh
npx wrangler r2 object get "tau-backups/<stamp>.tar.gz.age" --file /tmp/restore.age --remote
age -d -i ~/.config/tau/backup.key /tmp/restore.age | tar -C / -xzf -
rm /tmp/restore.age
tau doctor
```

`tar -C /` restores the exact paths that were archived, so `TAU_DATA_DIR` and `TAU_HOME` should be the same on the new machine. If they differ, extract into a scratch directory and move the pieces:

```sh
mkdir -p /tmp/restore && age -d -i ~/.config/tau/backup.key /tmp/restore.age | tar -C /tmp/restore -xzf -
rsync -a /tmp/restore/<old data dir>/ "$TAU_DATA_DIR"/
cp /tmp/restore/<old home>/persona/user.md "$TAU_HOME"/persona/user.md
```

Then `tau chat --resume`: the last session comes back with its history.

## Schedule it

Until issue 018 lands, a cron line or a launchd agent that runs the backup script nightly is enough:

```sh
crontab -e
# 03:30 every night; the script is the "Make a backup" block plus the upload
30 3 * * * /path/to/tau-backup.sh >> "$HOME/.local/share/tau/logs/backup.log" 2>&1
```

Keep the script outside the repository if it holds the bucket name and token path, or read those from `~/.config/tau/remote.env`.

## Rules

- **Never upload plaintext.** If a step fails before `age`, nothing goes up.
- **The key is never in Cloudflare**, not in a secret, not in a Worker, not in a bucket.
- **Test a restore** after the first backup and after every change to the script.
- **R2 holds no personal data in clear.** D1, Vectorize and AI Search are not used for tau's data at all ([ADR 0006](../adr/0006-private-first-topology.md)).
