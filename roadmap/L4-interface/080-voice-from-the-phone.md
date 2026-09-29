# 080 · Voice from the phone: browser microphone in the web UI, transcribed on the hub

Status: needs-triage
Type: AFK
Layer: L4 · Interface
Packages: tau-web, tau-voice
Blocked by: 074, 075

## What to build

The second slice of tau-web (ADR 0006 §7 and its consequences): a small page served by the `web` hub service next to the served TUI (`/voice`), usable on a phone through the Tunnel + Access or the tailnet, with one push-to-talk button. The browser records with `MediaRecorder`, streams the audio over a WebSocket to the hub, tau-voice's local STT transcribes it, the turn runs with `channel="voice"` on the phone's session, and the reply comes back as text plus, optionally, audio rendered by the local TTS and played in the page. Audio travels only browser → tunnel → hub and is discarded after transcription (or kept under `TAU_DATA_DIR/media/voice/` with `voice.keep_audio`). Approvals follow 074's per-device key. This is not the "proper web app" yet: one page, plain HTML and JS served from the package with no build step, so the later web app can replace it without a migration.

## Acceptance criteria

- [ ] On a phone behind Access (or on the tailnet), `/voice` records with the browser microphone and shows the transcript and the reply
- [ ] Audio reaches only the hub (WebSocket over the tunnel or tailnet); no third-party speech API; verified by tests with a fake STT
- [ ] Spoken replies are optional (setting), rendered by the local TTS and played in the page
- [ ] Without a device key a tier-2 call is refused with a pointer; with the key, approvals appear in the page
- [ ] Served from the `tau-web` wheel with no build step; documented in the docs guide "Voice"

## Blocked by

- [074 · tau-web: the TUI in the browser through `textual-serve`, served by the hub](074-tau-web-textual-serve.md)
- [075 · tau-voice: push-to-talk from the TUI with local speech-to-text and text-to-speech](075-tau-voice-push-to-talk.md)

## Comments

- 2026-09-29: filed while applying ADR 0006 (private-first) so its "voice from the phone uses the web UI's microphone; audio travels over the tunnel to the hub and is transcribed there" has an issue. Not in the original brief of that pass, hence `needs-triage`.
