# 031 · "Hey tau": local wake word on top of tau-voice

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: tau-voice, apps/taubar
Blocked by: 009, 024, 030, 075

## What to build

The always-listening mode of tau-voice (075): openWakeWord with the custom phrase (030) runs inside the voice service on the hub → record until silence → local speech-to-text → agent → spoken reply through the local TTS. No audio leaves the machine before the wake phrase, and none after it either, because transcription is local. Wake-word mode is a setting (019), off by default. TauBar shows the microphone state from the hub's `/status` and offers a mute toggle through the control API; the microphone permission belongs to the process that opens the microphone (the hub's Python under launchd, or TauBar's sidecar if 075 moved the capture there).

## Acceptance criteria

- [ ] Fewer than one false trigger per hour in normal desk noise (measured)
- [ ] Latency from end of speech to start of the spoken reply is measured and documented
- [ ] TauBar shows the microphone state and has a mute toggle; the TUI's microphone indicator (075) reflects the same state
- [ ] No network traffic before the wake phrase and no audio upload after it (verified)
- [ ] Wake-word mode is a setting, off by default; `/status` shows it

## Blocked by

- [009 · `tau hub` daemon with launchd service and self-heal](../L1-agent/009-hub-daemon.md)
- [024 · TauBar v0: tray app with sleep modes](024-taubar-sleep-modes.md)
- [030 · Pick the "Hey tau" wake phrase and record samples](030-pick-wake-phrase.md)
- [075 · tau-voice: push-to-talk from the TUI with local speech-to-text and text-to-speech](075-tau-voice-push-to-talk.md)

## Comments

- 2026-09-29: rewritten for ADR 0006 (private-first), §7: the voice pipeline is the separate `tau-voice` package (075), not TauBar's sidecar; this issue adds the wake word on top of it and keeps TauBar as the desk-side indicator and mute switch.
