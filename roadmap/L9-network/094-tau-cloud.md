# 094 · tau-cloud: the hub in a Cloudflare Container with the spine store

Status: ready-for-agent
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

- [ ] The `spine` backend passes the same session-store contract tests as the file store against `FakeSpine` (tau_net.testing, extended with the session and file routes)
- [ ] `tau cloud push` refuses to upload `user.md` without confirmation and never uploads `.env`
- [ ] `tau cloud run` with a fake spine writes the files, patches the config and starts the hub with the spine backend; `/health` answers
- [ ] A session written by one container run is resumed by the next (fake spine in tests)
- [ ] The docs guide "Cloud mode" walks through configure → deploy → secrets → push → Telegram, with example values only

## Blocked by

- [092 · Spine Worker](092-spine-worker.md)
- [093 · tau-net](093-tau-net.md)

## Comments

- 2026-09-30: opened with ADR 0007.
