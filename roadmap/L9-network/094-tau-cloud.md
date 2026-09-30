# 094 · tau-cloud: the hub in a Cloudflare Container with the spine store

Status: done
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: tau-cloud, cloud/spine
Blocked by: 092, 093

## What to build

A new package `tau-cloud` (import `tau_cloud`) for cloud mode (ADR 0007 §1):

- **`spine` session backend** (`tau.sessions` entry point): a `SessionStore` that stores sessions, agents, messages, events and metadata through the spine's session routes (D1). It keeps the semantics of the file store (create refuses to overwrite, update needs the record, nothing is ever deleted).
- **`tau cloud` commands:**
  - `push` uploads `tau.toml`, `persona/persona.md`, `persona/net.md` and, after an explicit confirmation, `persona/user.md` to the spine's KV.
  - `pull` downloads them.
  - `status` shows the spine health and the brain container's `/health`.
  - `run` is the container entrypoint: pull the files into `TAU_HOME`, force `[sessions] backend = "spine"` and `[component.net] store = "spine"`, serve `GET /health` on port 8080, then run the hub.
- The container image (`cloud/spine/container/Dockerfile`) installs tau-core, tau-net and tau-cloud and runs `tau cloud run`.

## Acceptance criteria

- [x] The `spine` backend passes the same session-store contract tests as the file store against `FakeSpine` (tau_net.testing, extended with the session and file routes)
- [x] `tau cloud push` refuses to upload `user.md` without confirmation and never uploads `.env`
- [x] `tau cloud run` with a fake spine writes the files, patches the config and starts the hub with the spine backend; `/health` answers
- [x] A session written by one container run is resumed by the next (fake spine in tests)
- [x] The docs guide "Cloud mode" walks through configure → deploy → secrets → push → Telegram, with example values only

## Blocked by

- [092 · Spine Worker](092-spine-worker.md)
- [093 · tau-net](093-tau-net.md)

## Comments

- 2026-09-30: opened with ADR 0007.
- 2026-09-30: done.
  - Commits: a9c29d7, 85f16e0, f257f88 (package, commands, docs); 766257c and fd409e1 retire tau-core's planned `cloud` backend in favour of `spine`; 0f19021 covers the CLI reference.
  - 125 tau-cloud tests pass, including tau-core's session contract cases on the spine store and a real hub subprocess stopped by SIGTERM. The workspace has 1077 passed, and the one failure is the pre-existing `login.rs` path.
  - Live check without a container:
    - A spine ran in cloud mode on :8799 with `--enable-containers=false`. `tau cloud push` sent `tau.toml` and the persona files, with `user.md` only after `--include-user`.
    - `tau cloud run` in an empty directory played the container and answered `/health`.
    - Bob's local tau on :8798 sent a contact request, the owner accepted it from another machine through the spine store, and a message got an auto-reply.
    - The "container" was stopped with SIGTERM and started again in a fresh directory. The same session continued (4 → 8 messages in D1), the contact was remembered, no `user.md` text reached D1, and the mailbox was empty.
  - The `tau-brain:dev` image builds from the repository root (450 MB; `tau components` inside lists `spine` and `cloud`). It was not run against a spine, because it would need an https spine; that happens in 096.
  - Follow-up: 108 (moving data between modes).
