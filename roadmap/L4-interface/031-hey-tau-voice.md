# 031 · "Hey tau": local wake word, speech-to-text and spoken replies

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: apps/taubar
Blocked by: 009, 024, 030

## What to build

TauBar runs a local voice pipeline through its Python sidecar: openWakeWord with the custom phrase → record until silence → MLX Whisper (Turkish) → hub → spoken reply. No audio leaves the Mac before the wake phrase. Microphone permission belongs to TauBar's identity.

## Acceptance criteria

- [ ] Fewer than one false trigger per hour in normal desk noise (measured)
- [ ] Latency from end of speech to start of the spoken reply is measured and documented
- [ ] TauBar shows microphone state and has a mute toggle
- [ ] No network traffic before the wake phrase (verified)

## Blocked by

- [009 · `tau hub` daemon with launchd service and self-heal](../L1-agent/009-hub-daemon.md)
- [024 · TauBar v0: tray app with sleep modes](024-taubar-sleep-modes.md)
- [030 · Pick the "Hey tau" wake phrase and record samples](030-pick-wake-phrase.md)

## Comments
