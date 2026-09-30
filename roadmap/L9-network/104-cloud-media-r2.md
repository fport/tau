# 104 · R2 media store in cloud mode

Status: needs-triage
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/spine, tau-cloud
Blocked by: 094

## What to build

In cloud mode the container's disk is temporary, so generated images, voice-note audio and call recordings (100) need a durable home. This issue puts them in the `MEDIA` R2 bucket of the cloud configuration:

- The spine gets upload and download routes, gated by `HUB_TOKEN` and by `TAU_MODE=cloud`.
- tau-cloud gets a media store that the channels use.

## Acceptance criteria

- [ ] Media written in one container run can be read after a restart
- [ ] The media routes answer `404 cloud_mode_off` in local mode

## Blocked by

- [094 · tau-cloud](094-tau-cloud.md)

## Comments

- 2026-09-30: filed with ADR 0007.
