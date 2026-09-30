# 043 · Workout form coach with the Mac webcam as a stand-in camera

Status: ready-for-agent
Type: AFK
Layer: L6 · Robot
Packages: tau-vision (new)
Blocked by: 032, 042

## What to build

A stand-in for the necklace: a vision node reads the Mac webcam, runs MediaPipe Pose locally, detects the form errors defined in #042 and publishes `tau/sport/form` events; a routine delivers the alert through the chosen channel with no LLM in the loop.

## Acceptance criteria

- [ ] Doing a target exercise with a deliberate form error triggers an alert within about 1 second
- [ ] No frames leave the machine unless the user asks to save a clip
- [ ] The camera source is abstracted so the XIAO stream (#044) plugs in unchanged
- [ ] Rep counts and form events are visible in the TUI

## Blocked by

- [032 · zenohd on the hub, node liveliness and `tau nodes`](../L5-mesh/032-zenoh-router-and-liveliness.md)
- [042 · Decide the workout alert channel and target exercises](042-decide-workout-alert-channel.md)

## Comments

- 2026-09-30: ADR 0008 (owner guard): reuse `tau_guard`'s built-in camera source (the `FrameSource` protocol, built-in device selection by type and transport, re-enumeration after the open) instead of a second camera picker, and use `opencv-python-headless`, the one cv2 distribution in the workspace. If MediaPipe is added, override `opencv-contrib-python` (and `sounddevice` unless voice needs it) in the workspace `[tool.uv] override-dependencies`, and pin `mediapipe==1.0.0`, because 1.0.1 aborts on macOS 26 on Apple Silicon.
