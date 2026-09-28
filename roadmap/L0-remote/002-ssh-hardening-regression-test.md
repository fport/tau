# 002 · Automated regression test for the SSH hardening

Status: ready-for-agent
Type: AFK
Layer: L0 · Remote access
Packages: infra/remote
Blocked by: none

## What to build

Turn the manual verification into a repeatable test. Render the sshd drop-in, validate it with `sshd -t` using a throwaway host key, start a throwaway unprivileged sshd on a high port with the rendered config, and prove that a valid key is accepted from 127.0.0.1 and rejected from a source address outside the allow list. Lint every shell script. The test must run locally without sudo and without touching system config or `~/.ssh`, and in GitHub Actions on a macOS runner.

## Acceptance criteria

- [ ] One command runs the test locally, without sudo, leaving no files outside a temp dir
- [ ] The test fails if password or keyboard-interactive auth becomes possible
- [ ] The test fails if `AllowUsers` stops restricting the source address
- [ ] shellcheck passes for every script in `infra/remote`
- [ ] A GitHub Actions workflow runs it on `macos-latest` for changes under `infra/remote`
- [ ] The command is listed under Commands in `CLAUDE.md`

## Blocked by

None - can start immediately

## Notes

Locally the machine's LAN address works as the rejected source. In CI, add a loopback alias (e.g. 127.0.0.2, sudo is available there) and bind the client to it.

## Comments
