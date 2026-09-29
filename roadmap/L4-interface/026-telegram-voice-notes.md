# 026 · Telegram voice notes transcribed on the hub

Status: ready-for-agent
Type: AFK
Layer: L4 · Interface
Packages: tau-core, tau-voice
Blocked by: 014, 075

## What to build

A voice note sent to the bot is handled by the hub's polling loop (014): `getFile` and the download go out over the Bot API like every other call, the audio is saved under `TAU_DATA_DIR/media/telegram/<chat>/<update id>.oga` and linked from the session, tau-voice's local speech-to-text (075: `mlx-whisper` on the Mac, another backend through the `stt` seam on the RPi5) transcribes it, and the text reaches the agent marked as a voice message on the `telegram` channel, so the persona's brevity rule applies. The reply is text; a spoken reply (tau-voice's TTS rendered to an `.ogg` voice note sent with `sendVoice`) sits behind a setting (019), off by default. No cloud speech API. When tau-voice is not installed the bot answers, in the UI language, that voice notes are not supported on this hub.

## Acceptance criteria

- [ ] A Turkish voice note yields a correct transcript on the hub and a reply on Telegram (fake Bot API plus a fixture recording in tests; one live check by the user)
- [ ] Audio is stored under `TAU_DATA_DIR/media/` and referenced from the session; it is part of the backup (018) and is never uploaded anywhere else
- [ ] Transcription failures produce a clear error in the UI language, not silence; a hub without tau-voice says so
- [ ] Voice replies are controlled by a setting, default off; when on, the reply is also sent as a voice note
- [ ] The only network calls are the Bot API and the model roles (verified in tests)

## Blocked by

- [014 · Telegram channel by direct polling: `getUpdates` loop on the hub → agent → reply](../L3-cloud/014-telegram-relay-tracer-bullet.md)
- [075 · tau-voice: push-to-talk from the TUI with local speech-to-text and text-to-speech](075-tau-voice-push-to-talk.md)

## Comments

- 2026-09-29: rewritten for ADR 0006 (private-first). Before: Workers AI Whisper in the Worker and the audio in R2. Now: the hub downloads the file and transcribes it locally with tau-voice; the audio stays on the hub.
