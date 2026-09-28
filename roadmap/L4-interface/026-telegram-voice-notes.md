# 026 · Telegram voice notes with Whisper in the Worker

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: cloud/tau-cloud, tau-core
Blocked by: 014

## What to build

Voice notes sent to the bot are transcribed in the Worker with Workers AI Whisper (Turkish) and reach the hub as text marked as voice. The original audio is stored permanently in a private R2 bucket and linked from the session. Voice replies (TTS) sit behind a setting, off by default.

## Acceptance criteria

- [ ] A Turkish voice note yields a correct transcript on the hub and a reply on Telegram
- [ ] Audio is stored privately in R2 and referenced from the session
- [ ] Transcription failures produce a clear Turkish error, not silence
- [ ] Voice replies are controlled by a setting, default off

## Blocked by

- [014 · Telegram relay tracer bullet: webhook → Worker → Durable Object → hub → reply](../L3-cloud/014-telegram-relay-tracer-bullet.md)

## Comments
