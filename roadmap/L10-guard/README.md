# L10 · Guard

**Goal:** tau works only for its owner ([ADR 0008](../../docs/adr/0008-owner-guard.md)):

- Guarded local channels (`tau tui`, `tau chat`, tau Desktop) stay locked until the owner's face is verified at the Mac.
- A tier-2 call on them needs a fresh step-up after the approval.
- The guard runs in the hub, locks by reflex without an LLM or the cloud, and nothing biometric leaves the machine.
- Telegram and network turns, which are identified another way, keep working.

**Done when:**

- The owner enrolls once. `tau tui`, `tau chat` and tau Desktop then open locked, unlock with a face check and a head-turn challenge, and lock again on idle, screen lock, sleep and `/guard lock` from Telegram.
- A tier-2 call on a guarded channel runs only after the human approval and a passing step-up. A printed photo or a phone clip held up to the camera does not unlock.
- Touch ID covers the cases where the face check cannot work, and the guard guide on the docs site covers setup, limits and "locked out" recovery with example values only.

| # | Issue | Type | Blocked by |
|---|---|---|---|
| 110 | [Guard seams in tau-core: `HubGuard`, admission, tier-2 step-up and lock checks, protected control routes with a response proof](110-guard-seams-in-tau-core.md) | AFK | – |
| 111 | [`tau-guard` service: state machine, reflex locks, worker subprocess, protected `/guard/*` routes, cooldown, audit log](111-tau-guard-service.md) | AFK | 110 |
| 112 | [Face verification: built-in camera, YuNet + SFace, head-turn challenge, enrollment, encrypted template, `tau guard` CLI](112-face-verification.md) | AFK | 111 |
| 113 | [Guarded channels: TUI lock screen, terminal lock prompt, `/guard`, Telegram lock, live lock propagation](113-guarded-channels.md) | AFK | 110 |
| 114 | [Touch ID: authorises enrollment and forget, unlock fallback, optional step-up](114-touch-id.md) | AFK | 112 |
| 115 | [TauBar: camera and microphone permission plumbing, webview media deny, guard line, "Lock now"](115-taubar-guard-plumbing.md) | AFK | 111 |
| 116 | [tau Desktop v0: Tauri app hosting `tau tui` in xterm.js + PTY](116-tau-desktop.md) | AFK | – |
| 117 | [Remote unlock through Telegram: per-client grants for SSH/mosh sessions and `tau ask`](117-remote-unlock-through-telegram.md) | AFK | 113 |
| 118 | [Voice under the guard: face-fresh mic opening, text replies, no approvals by voice](118-voice-under-the-guard.md) | AFK | 075, 113 |
| 119 | [Speaker verification as a veto signal (sherpa-onnx)](119-speaker-verification-veto.md) | AFK | 118 |
| 120 | [Owner line in the dynamic context](120-owner-line-in-dynamic-context.md) | AFK | 054, 110 |
| 121 | [Guard state on the mesh for owner-arrived routines](121-guard-state-on-the-mesh.md) | AFK | 032, 037, 111 |
| 122 | [Guard on the RPi5 hub: the Mac as a camera node sending signed attestations](122-guard-on-the-rpi5-hub.md) | needs-hardware | 048 |
| 123 | [Owner notifications from the guard: failed attempts, cooldown, guard disabled](123-guard-owner-notifications.md) | AFK | 111 |
| 124 | [In-process guard fallback when no hub runs (worker subprocess, same state machine)](124-in-process-guard-fallback.md) | AFK | 112, 113 |
| 125 | [Lock the Mac session on a non-matching face (optional strong mode)](125-lock-the-mac-on-a-stranger.md) | AFK | 112 |
| 126 | [Guard window in TauBar: live camera preview and head-turn prompts](126-guard-window-with-camera-preview.md) | AFK | 112, 115 |
| 127 | [Tune the head-turn challenge on real captures](127-tune-the-head-turn-challenge.md) | AFK | 112 |

Live status: `python3 roadmap/board.py --layer L10`
