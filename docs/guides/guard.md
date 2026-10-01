# Owner guard

The owner guard makes tau work only for you. After you set it up, `tau tui`, `tau chat` and the tau app's chat windows open **locked**. They unlock when the Mac's built-in camera sees your face and you turn your head the way the screen asks. tau locks again by itself when you walk away, when the screen locks, when the Mac sleeps and after eight hours. Before a tier-2 action runs, you still approve it as always, and then the guard checks your face once more (a **step-up**).

The guard runs inside the hub and does not need a model or the internet. Your face template never leaves the Mac, and a copy of the data folder or a backup cannot read it. The decision and its full threat model are in [ADR 0008](../adr/0008-owner-guard.md). Every key, route and log field is listed in the [guard reference](../reference/guard.md).

!!! tip "The easy way: `tau setup` → Owner guard"
    At the Mac, tick **Owner guard** in `tau setup` or in the Mac app's setup wizard, or run `tau setup run guard` later. It installs `tau-guard`, checks the prerequisites (`tau guard doctor`), runs `tau guard setup` and reminds you to restart the hub. In the app the enrollment runs in the wizard's own terminal, so the camera permission belongs to tau. [Set it up](#set-it-up) below is the same by hand; [Setup features](setup-features.md#owner-guard) says how to remove it.

!!! info "What is not here yet"
    - **Touch ID is the fallback.** After two failed face checks, or when the camera cannot be used, the lock screen offers Touch ID: press `t` in `tau tui`, or type `t` and press Enter at the `locked>` prompt of `tau chat`. The macOS prompt appears on the Mac's screen. `step_up` can also ask for Touch ID (`face_or_touch_id` or `touch_id`). Touch ID pins your fingerprint set at enrollment: after you add or remove a finger in System Settings, run `tau guard enroll --add` so Touch ID is accepted again.
    - **Remote unlock:** a TUI over SSH or mosh works only while you are unlocked at the Mac. Grants for a phone, issued from Telegram, come with issue 117.
    - **Voice** under the guard comes with issues 118 and 119.

## What it does, in plain words

- **A door, not a watcher.** The camera is on only while a check runs, a few seconds at a time. Between checks the guard relies on keyboard and mouse idle time, the screen lock and a short recheck now and then.
- **Only for tau's own windows.** The guard covers the TUI (in Terminal, over SSH, in a chat window of the tau app or in a web tab), `tau chat` and, later, voice. These are the **guarded channels**. Telegram and messages from other taus are identified in other ways (your chat id, a contact's key), so they keep working while the Mac is locked. These are the **identified channels**.
- **It only ever narrows.** The guard can refuse a turn or an action. It can never approve one: a tier-2 action still needs your yes, and the step-up comes on top of it.
- **It fails closed.** No hub running, a broken setting or an unreadable template all mean "locked", never "open".

## What you need

- A Mac with a built-in camera. The guard works only on macOS, and it uses only the built-in camera: Continuity Camera (an iPhone) and virtual cameras are never picked.
- `tau-guard` installed. A checkout has it after `uv sync --all-packages`. From PyPI, once a release includes it (`tau-guard` ships next to `tau-core` and `tau-tui`):

    ```sh
    uv tool install tau-core --with tau-tui --with tau-guard
    ```

- A hub that runs the guard service. The **Run the hub** switch of the [tau app](taubar.md) is the best choice, because the app then holds the camera permission. `tau hub run` in a terminal works too, and then that terminal app holds it. See [Run tau as a service](hub-service.md).
- About 40 MB to download once: the face-recognition model (SFace). No internet is needed after that.
- You, at the Mac. `tau guard setup`, `enroll` and `forget` refuse to run over SSH.

## Set it up

1. **Start the hub.** In the tau app tick **Run the hub**, or run `uv run tau hub run` in a terminal.
2. **Check the prerequisites:**

    ```sh
    uv run tau guard doctor
    ```

    It checks the platform, the worker, OpenCV, the two face models, the enrollment, the template, the Keychain key, the camera and its permission, and which app holds the hub's camera grant. Before setup, `enrollment` is a warning and the `sface` model a failure, because setup downloads it. That is expected.

3. **Run setup at the Mac:**

    ```sh
    uv run tau guard setup
    ```

    It does four things in order, and stops at the first one that fails:

    - **Downloads SFace** from a URL pinned to one OpenCV Zoo commit and checks its sha256. Offline, pass the file yourself: `tau guard setup --model-file ~/Downloads/face_recognition_sface_2021dec.onnx`. The file is checked against the same sha256.
    - **Enrolls your face.** macOS first asks for Touch ID or your Mac password, then for camera access if this app has never had it. Then follow the [guard window](#the-guard-window) for 15 to 20 seconds: look at the camera, turn left, turn right, tilt up, tilt down. Sit in normal light, about an arm's length away, alone in the picture.
    - **Runs one check,** exactly like an unlock: look at the camera, then two head turns.
    - **Switches the guard on:** it writes `[component.guard] enabled = true` to `tau.toml`. The enrollment marker in `TAU_DATA_DIR/guard/` keeps the guard on even if that line is later removed.

    At the end it warns you that remote use (SSH, mosh) stops while you are away from the Mac.

4. **Restart the hub** (the tau app: untick and tick **Run the hub**; or stop and start `tau hub run`) and close any open `tau chat`, `tau tui` or chat window of the tau app. The guard starts with the next hub, locked.
5. **Unlock once.** Open `uv run tau tui` and press Enter on the lock screen. If the hub runs under the tau app, macOS now asks whether **tau** may use the camera. Allow it. The next section explains why.
6. **Check it:**

    ```sh
    uv run tau guard status    # the state as the hub reports it
    uv run tau doctor          # its guard line: active; the hub reports it unlocked
    ```

## The guard window

While a check runs, tau covers the Mac's screen, all but the menu bar, with a dark window, so you do not have to follow text in a terminal:

- **Your camera picture**, mirrored like a mirror, in the middle of the τ ring. Turn the way the triangle points: for "turn left" your face moves left in the picture.
- **What to do now**, as a large triangle and one line: `LOOK AT THE CAMERA` (a hollow triangle pointing up at the camera), `TURN LEFT`, `TURN RIGHT`, `BACK TO CENTER`, and during enrollment `TILT UP`, `TILT DOWN`, `TURN FURTHER` with the samples collected so far (`6/10 SAMPLES`).
- **The time left** for the current step, as a bright comet running down the ring; it turns red near the end.
- **A hint** when something is off: `TOO DARK · FIND MORE LIGHT`, `MOVE CLOSER`, `ONE FACE ONLY`.
- **The result:** `UNLOCKED` (or `CONFIRMED`, `ENROLLED`) with a check, or `NOT VERIFIED` with the reason. The window closes itself about a second later.

It appears for every check, whichever window asked for it: the TUI lock screen, `tau chat`, a chat window of the tau app, a step-up before a tier-2 action, a presence recheck, and `tau guard setup`, `enroll` and `verify`. The terminal lines stay as they were.

- **Esc**, or a click on `ESC · CANCEL`, cancels the check. As on the lock screen, cancelling while a head-turn prompt is up counts as a failed attempt.
- **Touch ID or the Mac password** (enrollment, the Touch ID fallback, a Touch ID step-up): the window shrinks to a small panel at the top of the screen, so the macOS prompt is free.
- **Privacy:** the picture stays inside the worker that holds the camera. Nothing is recorded or saved, and the window asks macOS to keep it out of screenshots and screen recordings.
- It follows your UI language (`[ui] language`), and it stops moving when System Settings → Accessibility → Display → **Reduce motion** is on.
- **See it first:** `uv run tau guard window --demo` plays a scripted check in it without the camera. `uv run tau guard window` says whether it can open from where you are.
- **Turn it off** with `[component.guard] window = false` in `tau.toml` (restart the hub), or for one command with `--no-window` (`setup`, `enroll`, `verify`; a check that runs through the hub follows the hub's setting). Over SSH, or when the hub has no GUI session (a launchd job, a hub started over SSH), checks run without it.

## The camera permission: the tau app or the terminal

macOS grants the camera to an app, not to a program. The guard's checks run in a small worker that the hub starts, so the grant belongs to **whatever app started the hub**:

| How the hub runs | Who holds the camera grant |
|---|---|
| the tau app's **Run the hub** (recommended) | the tau app ("tau", `com.tau.app`) |
| `uv run tau hub run` in Terminal, iTerm or another terminal | that terminal app |
| `bun run tauri dev` of the tau app | the terminal that runs it |
| the `com.tau.hub` launchd agent, or a hub started over SSH or in a detached tmux | nobody, so the camera is refused |

- During `tau guard setup` with no guarded hub running yet, the check runs in a local worker, so the app that runs the setup asks for the camera too: your **terminal**, or **tau** when you run it in a chat window of the tau app. A terminal's grant is separate from the tau app's, which is why the first unlock then asks again.
- The grant lives in System Settings → Privacy & Security → **Camera**. The tau app's menu has **Grant camera access…** when the hub reports the camera as denied.
- The grant survives the tau app's updates: every release is signed with the same certificate, and macOS keeps a grant for the app that certificate identifies. A build from the checkout is signed ad hoc and is a new app to macOS after every rebuild, so the grant is lost each time; the [app's README](https://github.com/fport/tau/blob/main/apps/tau/README.md#why-a-stable-identity-keeps-the-camera-permission) explains the signing.
- Coming from TauBar, macOS asks once more: TauBar's grant belonged to TauBar (`com.tau.taubar`), and the tau app is a new app.
- The pages of the tau app's windows never get the camera: every webview permission request is denied, and the check runs in the hub.

## Daily use

### In `tau tui` and the tau app's chat windows

The TUI opens on an opaque lock screen, so nothing of your sessions shows through.

- **Enter** on an empty line starts a check. Look at the camera, then follow the prompts ("Turn your head left.", "Look straight at the camera again."); the [guard window](#the-guard-window) shows them large, with your camera picture. Each prompt gives you 4 seconds. A clear turn of 15 to 20 degrees is enough; swinging a little past the centre on the way back is fine.
- **Esc** cancels a running check, and **ctrl+q** quits. Only `/help`, `/lang`, `/guard` and `/quit` work while tau is locked. Anything else you type is not sent and stays in the field.
- After a successful check you see `Unlocked (face). Failed attempts since the last unlock: 0.` A number above 0 means someone, or something, tried while you were away. `tau guard log` shows when.

A chat window of the tau app runs the same `tau tui`, so it shows the same lock screen. A web tab (issue 074) will too.

### In `tau chat`

`tau chat` clears the screen and the scrollback, then shows a `locked> ` prompt. Press Enter to start a check. Every challenge step is printed as it comes.

### What locks tau

| Trigger | When |
|---|---|
| Idle | no keyboard or mouse input for `idle_lock_minutes` (10) |
| Screen lock | the Mac's screen locks |
| Sleep | the Mac slept |
| Max age | `max_unlock_hours` (8) after the unlock, whatever you do |
| Command | `/guard lock` in the TUI or `tau chat`, `tau guard lock`, the tau app's **Lock now** |
| Telegram | `/guard lock` from your Telegram chat |
| Failed step-up | a step-up saw another face, a spoof or two faces |
| Hub start | every hub start begins locked; an unlock is never restored |

A lock cancels a running turn ("tau locked; the turn was stopped."), rejects an open approval dialog and brings the lock screen back at once.

### Presence rechecks

Anyone who sits down at a Mac you just left can type, and typing resets the idle timer. So after 3 minutes of idle time since your face was last seen, or 30 minutes after the last face match, your next message first shows "Checking that it is still you…". That is a quiet check of about a second with no head turns. If it sees your face, the message goes on. If it sees someone else's face, tau locks. If the message was not sent, send it again.

### The step-up before a tier-2 action

When tau wants to do something physical or outward-facing, you approve it as always. Then the guard asks "Confirm it is you: look at the camera." and gives three head-turn prompts. Within 2 minutes of a check that passed the head turns, the step-up is a quiet match instead, so three actions in a row do not cost nine head turns. If the step-up fails, the action does not run, and a check that saw another face, two faces or a spoof locks tau.

### Cooldown

Three failed checks within 10 minutes (a face that did not match, a failed head-turn challenge, more than one face) start a 30-second cooldown, which doubles with each further failure up to 15 minutes. Checks during it answer "Too many failed attempts. Wait a moment, then try again." A dark room or a missing face do not count, and neither does a cancelled check, unless a head-turn prompt was up when you cancelled. The count survives a hub restart.

### Commands

| Where | Command | What it does |
|---|---|---|
| TUI, `tau chat` | `/guard` | the guard's state |
| TUI, `tau chat` | `/guard lock` | lock now |
| TUI, `tau chat` | `/guard unlock` | while locked, start a check (the same as Enter on the lock screen) |
| terminal | `tau guard status` | the state as the hub reports it |
| terminal | `tau guard lock` | lock now |
| terminal | `tau guard log --since 2h` | the audit log: checks, locks, cooldowns |
| the tau app | **Lock now** | lock now; the app never unlocks |

## Locking from Telegram

Your Telegram chat is your remote kill switch:

- `/guard` shows the state, for example `Guard: locked · locked after inactivity`.
- `/guard lock` locks every guarded channel at once, with trigger `telegram`.
- `/guard unlock` only answers that unlocking happens at the Mac.

Telegram itself keeps answering while the Mac is locked, because the chat-id allowlist identifies you. If **Telegram Desktop** is logged in on the same Mac, anyone at the Mac can write to tau through it. That is a risk the guard accepts, so set a local passcode in Telegram Desktop (Settings → Privacy and Security → Local Passcode).

## Away from the Mac, and cloud mode

- A TUI or `tau chat` over SSH or mosh shares the Mac's unlock: it works while you are unlocked at the Mac and is locked otherwise. Unlocking from the phone comes with issue 117.
- **Cloud mode has no guard.** A Cloudflare Container has no camera and no Keychain. Only Telegram and network turns run there, and both are identified channels, so nothing locks. If the `tau.toml` you push with `tau cloud push` carries `[component.guard] enabled = true`, the container's guard is simply locked for good (`unsupported_platform`), which the identified channels ignore. The enrollment marker and the template live under `TAU_DATA_DIR/guard/` and are never pushed.

## Honest limits

Without an infrared camera, a 2D webcam check is a presence and convenience factor, not a vault.

**What it stops:**

- a housemate or visitor using tau's windows on your unlocked Mac;
- a printed photo, or a still picture on a phone, held up to the camera (a flat picture cannot pass the head turns);
- any local program or web page calling the hub's control routes (every route but `/health` and `/status` needs a signed request);
- injected text trying to switch the guard off (no tool or route can);
- someone reading your template from a copy of the data folder or a backup (it is encrypted with a key in the Keychain).

**What it does not stop:**

- **anyone with a shell in your account.** They can edit `tau.toml`, read `.env` or start tau without the guard. The Mac's screen lock and FileVault protect the account; the guard protects tau's windows;
- a real-time deepfake, a 3D mask or an identical twin. Close relatives also score higher than strangers;
- a good looping video of you turning your head. Synthetic clips of natural head turns passed 4 to 16 % of the two-step unlock checks in testing (1 to 9 % of the three-step step-ups); the cooldown limits the attempts to about ten an hour;
- someone forcing you to look at the camera.

That is why the guard is only ever required **in addition** to your own approval, never instead of it.

**What stays on the Mac:** the template (`owner.face.v1.bin`, AES-GCM encrypted, key in the macOS Keychain), the audit log (no images, no embeddings, nothing about other people) and the model files. Camera frames exist only in the worker's memory for the length of a check; nothing is saved, including of anyone else in view. `TAU_DATA_DIR/guard/` is left out of backups.

## Locked out?

**The camera is denied or never asked.** Open the Camera pane of System Settings and switch on the app that runs the hub (tau, or your terminal):

```sh
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Camera"
```

The tau app's **Grant camera access…** opens the same pane. To make macOS ask again from scratch, reset the grant and restart the hub from the tau app (untick and tick **Run the hub**):

```sh
tccutil reset Camera com.tau.app       # the tau app's bundle id
tccutil reset Camera com.apple.Terminal # if Terminal runs the hub instead
```

**Something is off, and you do not know what.** Run the doctor. It names the failing part and the app that holds the hub's camera grant:

```sh
uv run tau guard doctor
uv run tau doctor          # its guard line says whether the hub runs the guard at all
```

**"The guard cannot be reached."** No hub runs, or it runs without the guard service. Start it (the tau app → Run the hub, or `tau hub run`) and check that `[components.hub] services` in `tau.toml` is empty or lists `guard`.

**It does not recognize you.** Try better light, face the camera, take off a cap. `tau guard verify --explain` shows each prompt as a highlighted line (`>>> TURN YOUR HEAD LEFT <<<`) and prints the numbers of every third frame (faces, detector score, eye distance, brightness, sharpness, head yaw and your turn in degrees, similarity) without saving a frame; `--explain=all` prints every frame. When the head turns fail, it names the rule that failed, for example `no_turn` when the turn was not big enough. Then add samples under the light that fails: `tau guard enroll --add`. After a change of face model, enroll again with `tau guard enroll`.

**Too many failed attempts.** Wait. `tau guard status` shows until when the cooldown runs.

**You want it gone.** At the Mac:

```sh
uv run tau guard forget
```

It asks for Touch ID (your Mac password only on a Mac without Touch ID), then removes the template, the enrollment marker and the Keychain key, and writes `[component.guard] enabled = false`. Restart the hub and any open tau window; the guard is off. If it says the Keychain kept the key, run it again. `tau guard setup` sets everything up again from scratch.
