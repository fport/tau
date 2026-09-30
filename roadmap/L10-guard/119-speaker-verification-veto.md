# 119 · Speaker verification as a veto signal (sherpa-onnx)

Status: needs-triage
Type: AFK
Layer: L10 · Guard
Packages: tau-voice, tau-guard
Blocked by: 118

## What to build

A local speaker check that can stop a voice command from someone other than the owner (T2: other people's speech reaching voice). It can never let a command through on its own. [ADR 0008](../../docs/adr/0008-owner-guard.md) (decision 18): **voice never vouches.** A mismatch vetoes or downgrades a command; a match never raises assurance, never replaces the face check and never approves anything. Replay and cheap voice cloning defeat speaker identity, so it stays a veto.

### Shape

- **Embedder.** A `SpeakerEmbedder` protocol with `model_id` and `embed(samples, rate) -> vector`. The first backend is `sherpa-onnx` (Apache-2.0; it bundles its own onnxruntime, with no torch, and has wheels for macOS and Linux aarch64) with `wespeaker_en_voxceleb_resnet34_LM.onnx`:
  - 26.5 MB, CC-BY-4.0, 256-d;
  - sha256 `e9848563da86f263117134dfd7ad63c92355b37de492b55e325400c9d9c39012`;
  - downloaded by a setup command from the pinned release URL, and checksum-verified.
- **Speed.** The probe measured 19–64 ms per 2–8 s clip on an M5.
- **Enrollment.** The owner records a few sentences behind the same LocalAuthentication gate as the face (112/114). The voice template is encrypted like the face template (a separate file in `TAU_DATA_DIR/guard/`, the same Keychain key scheme), excluded from backups and removed by `tau guard forget`.
- **Scoring.** Scores are scaled per owner (cohort or AS-norm against a small impostor set shipped as embeddings), because raw cosine scores are compressed: in the probe, correct speakers scored 0.856–0.938 and impostors 0.669–0.88, so a fixed global threshold is not usable. Clips of about 2 s or less (most commands) are unreliable. The veto applies only above a minimum speech length and otherwise abstains.
- **Effect.** A clear mismatch drops the command with a notice ("voice not recognised") and writes an audit event. A match or an abstention changes nothing: the face-fresh rule of 118 still decides.
- **Privacy.** Audio and embeddings of other speakers exist only in memory. Nothing leaves the machine.

### To settle in triage

- The exact normalisation and threshold, measured on the owner's own recordings plus a public impostor set, with the numbers written under Comments.
- Whether the veto runs on every command or only on hands-free (wake-word) turns.
- Whether a mismatch locks the guard or only drops the command.

## Acceptance criteria

- [ ] `SpeakerEmbedder` has a sherpa-onnx backend and a fake; the model is fetched by pinned URL and sha256; tests run offline with the fake
- [ ] A mismatch above the minimum length drops the command and records an audit event; a match or a short clip never admits a command that the face-fresh rule refused (test)
- [ ] The voice template is encrypted, 0600, excluded from backups and removed by `tau guard forget`
- [ ] No audio or embedding of another speaker is written anywhere (test over the data dir after a mismatch)
- [ ] (user) The owner records an enrollment; a second person's command is vetoed in a live test; the scores go under Comments

## Blocked by

- [118 · Voice under the guard](118-voice-under-the-guard.md)

## Comments

- 2026-09-30: filed with ADR 0008. needs-triage: the threshold and normalisation need measurements on real recordings.
