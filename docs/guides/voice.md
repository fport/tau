# Voice

tau will listen and speak through a separate package, `tau-voice`. Everything about it is designed so that no audio leaves the hub: speech-to-text and text-to-speech run locally, and nothing is recorded before you press a key or say the wake phrase.

!!! info "Planned (roadmap issues 075, 031, 026 and 080)"
    None of this exists in the current packages. Issue 075 creates `tau-voice` (push-to-talk, local STT and TTS, the TUI integration); issue 031 adds the wake word on top of it, once the wake phrase is chosen in issue 030; issue 026 transcribes Telegram voice notes on the hub; issue 080 brings voice from the phone through the web UI. This page describes the design so you know what to expect and what to prepare; it does not describe a feature you can run today.

## The shape of it

`tau-voice` is a **hub service** and a **channel** in one: a `tau.hub_services` component that owns the microphone and the speakers on the hub, and a channel that turns speech into turns and replies into speech.

| Piece | Where it runs | What it is |
|---|---|---|
| Microphone capture | the hub | starts on push-to-talk or the wake phrase, stops on silence |
| Speech-to-text | the hub | MLX Whisper on Apple silicon; a CPU Whisper build on the Pi |
| Text-to-speech | the hub | a local voice; no cloud voice API |
| Wake word | the hub | openWakeWord with a custom 3–4 syllable phrase (issue 031) |
| Channel | the hub | `channel = "voice"` in the session metadata; replies limited to two sentences, no lists, no code, no emoji (the persona's voice rule) |

The persona already carries the voice rules: at most two sentences in spoken replies, no jokes in approval requests. The [persona file](https://github.com/fport/tau/blob/main/persona/persona.md) is where they live.

## Push-to-talk at the desk

The TUI shows a microphone state and a push-to-talk key **only when the voice service is present**; it finds the service through the hub's control API and talks to it through events. Without `tau-voice` installed the TUI has no microphone anywhere. Install it, and the hint bar gains the key; hold it, speak, release; the transcript shows what was heard as your turn, and the reply is both printed and spoken.

## Voice from the phone

Voice from the phone goes through the **web UI's microphone**, not through a native app: the browser records, the audio travels over the tunnel to the hub, the hub transcribes it. This is roadmap issue 080, which builds on `tau-web` (issue 074, the TUI in the browser) and on `tau-voice` (issue 075). The reason is the threat model: a cloud speech API would hear everything you say; the hub does not need one.

## Telegram voice notes

A voice note sent to the bot is downloaded by the hub and transcribed there (issue 026). It reaches the agent as text marked as voice; the original audio stays local and is backed up encrypted with the rest of the data directory.

## "Hey tau": the wake word

With issue 031 the hub listens for a wake phrase all the time and records nothing until it hears it. Acceptance criteria that matter for you:

- fewer than one false trigger per hour in normal desk noise, measured;
- no network traffic before the wake phrase, verified;
- a visible microphone state and a mute toggle (TauBar on the Mac).

The wake phrase must have three or four syllables; picking it and recording samples is [issue 030](https://github.com/fport/tau/blob/main/roadmap/L4-interface/030-pick-wake-phrase.md), a human task.

## Under the owner guard

When the [owner guard](guard.md) is on, voice follows its rules (issues 118 and 119, [ADR 0008](../adr/0008-owner-guard.md)):

- **The microphone opens only while your face was seen recently** and the screen is unlocked. The voice service asks the guard inside the hub before it opens the microphone, so a transcript typed into the TUI cannot skip the check.
- **No approvals by voice.** A tier-2 call raised by a voice turn is approved in the TUI when one is open, else on Telegram.
- **Voice never vouches.** Speaker verification may veto a command that does not sound like you; a match never counts as proof that it is you, because voices are easy to replay and clone.
- **Replies** come as text, speech or both (`reply_mode`).
- **Voice routes** are protected control routes, like every route but `/health` and `/status`.

## Microphone permission

!!! warning "Microphone permission on macOS"
    macOS grants microphone access per application identity. A Python process started from the terminal inherits the terminal's permission (or asks for it), a launchd agent has none, and a Tauri app has its own. **TauBar owns the microphone permission**: it runs the hub, and since issue 115 it carries the microphone usage description and the audio-input entitlement, so the voice service inside the hub will ask in TauBar's name and the permission belongs to a signed app you can see in **System Settings → Privacy & Security → Microphone**. No TauBar or tau Desktop window can use the microphone itself: every webview permission request is denied. A hub started from a terminal (`tau hub run`) asks on behalf of that terminal app instead. Grant it there, and revoke it there when you do not want it.

    On a Raspberry Pi there is no permission system; the microphone is a device file. Choose a USB microphone with a hardware mute if that matters to you.

## What to prepare now

- Nothing to install. Do not add speech packages to the hub by hand; `tau-voice` will declare its own dependencies.
- If you want the desk setup, decide where the microphone sits and whether it has a mute switch.
- If you want voice from the phone, follow [Private deployment](private-deployment.md) so the door exists when the web UI arrives.
