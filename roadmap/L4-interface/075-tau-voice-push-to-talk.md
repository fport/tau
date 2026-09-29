# 075 · tau-voice: push-to-talk from the TUI with local speech-to-text and text-to-speech

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: tau-voice, tau-tui, tau-core
Blocked by: 054

## What to build

A new distribution `packages/tau-voice` (import `tau_voice`, depends on tau-core only): a `tau.hub_services` component `voice` that is also a channel (ADR 0006 §7). On the hub it opens the microphone on request (push-to-talk; always-on listening with the wake word is 031), records until the key is released or silence is detected, transcribes locally with `mlx-whisper` (Apple Silicon; the `stt` seam takes another backend such as `faster-whisper` for the RPi5), runs the turn with `channel="voice"` and speaks the reply through a local TTS: macOS `say` first, Piper later, behind the same `tts` seam. Nothing leaves the machine: no cloud speech API, and audio is kept under `TAU_DATA_DIR/media/voice/` only when the setting `voice.keep_audio` is on (default off).

The TUI shows a microphone indicator and a push-to-talk key **only when the service is present**: it learns that from the `voice` key of the hub's `/status` and drives the service through the control-API routes it registers (`GET /voice/status`, `POST /voice/listen`, `POST /voice/stop`, `POST /voice/say`); the transcript lands in the composer, where the user sees and can edit it before sending, and the reply is spoken while it is rendered. Mesh events (032) replace the status polling later. The service reports `voice: {listening, stt, tts, model}` in `/status` and has a mute switch (`[component.voice]` until 019 exists, then a setting).

First run needs a human step: macOS asks for microphone permission for the process that opens the microphone (the hub's Python under launchd, or the terminal running `tau hub run`); the docs guide "Voice" says where the prompt appears and how to grant it afterwards in System Settings.

## Acceptance criteria

- [ ] With tau-voice installed, `tau hub run` shows `voice` in `/status`; without it the TUI shows no microphone key and no voice hints (snapshot test)
- [ ] Push-to-talk in the TUI records, transcribes locally and puts the text into the composer; the reply is spoken (tests with a fake microphone, a fake STT and a fake TTS; a fixture recording proves the `mlx-whisper` backend on a Mac)
- [ ] The `stt` and `tts` seams are documented; `mlx-whisper` and `say` are the first backends, Piper is a stub with a clear "not installed" message
- [ ] No network traffic from the voice service; only the model roles are called, through the agent (verified in tests)
- [ ] Audio is discarded after transcription unless `voice.keep_audio` is on; then it lives under `TAU_DATA_DIR/media/voice/`
- [ ] `tau-voice` builds as its own wheel, depends on tau-core only through its public API, is added to CI and to the release workflow's package list; the docs guide covers install, the first-run microphone permission and the push-to-talk key
- [ ] (user) Microphone permission granted on the hub Mac and one live round trip confirmed

## Blocked by

- [054 · Show the conversation channel in the dynamic context](../L1-agent/054-channel-in-dynamic-context.md)

## Comments

- 2026-09-29: opened for ADR 0006 (private-first), §7: voice is a separate package, a hub service and a channel; the TUI shows the microphone only when the service is present. Blocked by 054 so the persona sees `Channel: voice` and applies the brevity rule. The last criterion is the user's (microphone permission).
