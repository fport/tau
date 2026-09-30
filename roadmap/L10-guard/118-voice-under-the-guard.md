# 118 · Voice under the guard: face-fresh mic opening, text replies, no approvals by voice

Status: needs-triage
Type: AFK
Layer: L10 · Guard
Packages: tau-voice, tau-tui, tau-core
Blocked by: 075, 113

## What to build

Voice commands work only for the owner who is at the Mac, and the owner can ask for answers in text. The rules come from [ADR 0008](../../docs/adr/0008-owner-guard.md) (decision 18). They are enforced where the microphone opens, not at the channel label: a push-to-talk transcript lands in the TUI composer and is sent as a `tui` turn, so a check keyed on `channel="voice"` would never run.

### Rules

- **Opening the microphone.**
  - The microphone opens only while `GuardService.face_fresh(voice_face_fresh_seconds)` holds (default 60 s) and the screen is unlocked.
  - `POST /voice/listen` and the wake-word loop (031) ask the guard inside the hub before opening the microphone. The guard is found with `hub.find_service("guard")` plus an `isinstance(Guard)` check.
  - When the face is not fresh, the service answers `recheck`. The TUI then runs the passive face check and retries once. A failed check refuses, and the microphone stays closed.
  - With no guard active, the microphone behaves as in 075.
- **Routes.** Every voice route (`/voice/status`, `/voice/listen`, `/voice/stop`, `/voice/say`) is a protected control route (token, no `Origin`, JSON; ADR 0008 decision 8), so no web page can make the Mac listen or speak.
- **Hands-free turns.** Turns the voice service runs itself (the wake word, 031) use `channel="voice"`. They are built with the in-hub `GuardService` as their guard, never with `guard=None`.
- **No approvals by voice.** A spoken "yes" is never an approval. A tier-2 call raised by a voice turn is approved in the TUI when one is open and unlocked, else through Telegram's buttons, and the step-up rules apply as on any guarded channel.
- **Replies.** `reply_mode = "text" | "speech" | "both"` becomes a voice setting (019), with default `both`.
  - `text` shows the reply in the open TUI.
  - For a hands-free turn with no TUI open, the reply goes to a TauBar notification if TauBar runs, else to Telegram.
- **Speaker verification** (119) may veto a command later, but it never replaces the face check.

### To settle in triage

These depend on 075's final shape:

- how the hub-side voice turn reaches the TUI's approval dialog (a hub event the TUI subscribes to, or Telegram only in v1);
- where the "text" reply is rendered for a hands-free turn;
- whether `voice_face_fresh_seconds` lives in `[component.guard]` or in the voice settings.

## Acceptance criteria

- [ ] `POST /voice/listen` refuses to open the microphone when the guard is locked or the face is older than `voice_face_fresh_seconds` (fake guard, fake microphone), and opens it when fresh
- [ ] Voice routes answer 403 without the token and with an `Origin` header
- [ ] A hands-free voice turn is refused while the guard is locked; its agent is built with the in-hub guard (test that `guard=None` is not used)
- [ ] A tier-2 call from a voice turn is never approved by speech: a transcript "yes" / "evet" leaves the approval pending or rejected, and the approval arrives only from the TUI or Telegram (test with a fake approver)
- [ ] `reply_mode` `text`, `speech` and `both` behave as specified (fake TTS, fake TUI sink)
- [ ] (user) Live: with the owner at the Mac, push-to-talk works; with the owner's face absent for longer than the window, the microphone does not open

## Blocked by

- [075 · tau-voice: push-to-talk from the TUI with local speech-to-text and text-to-speech](../L4-interface/075-tau-voice-push-to-talk.md)
- [113 · Guarded channels](113-guarded-channels.md)

## Comments

- 2026-09-30: filed with ADR 0008. needs-triage until 075 settles the voice service's routes and the composer flow.
