# 100 · Voice calls in cloud mode through a Durable Object

Status: needs-triage
Type: AFK
Layer: L9 · Cloud mode and the tau network
Packages: cloud/spine, tau-cloud, tau-voice
Blocked by: 075, 094

## What to build

Local voice (075) transcribes on the hub. A cloud-mode tau has no microphone, so voice has to arrive from a browser or phone:

- A `VoiceSession` Durable Object on the spine relays microphone audio between the owner's device and the brain container, or a realtime speech API if the owner allows one.
- Access is gated by the owner's identity, through Cloudflare Access or a per-device key.

Recordings stay in R2 (104) only when the owner opts in.

## Acceptance criteria

- [ ] A browser call reaches the cloud tau and gets a spoken answer
- [ ] Only the owner can open a call; the relay holds no audio after the call unless recording is on
- [ ] Local mode voice is unchanged

## Blocked by

- [075 · tau-voice](../L4-interface/075-tau-voice-push-to-talk.md)
- [094 · tau-cloud](094-tau-cloud.md)

## Comments

- 2026-09-30: filed with ADR 0007.
