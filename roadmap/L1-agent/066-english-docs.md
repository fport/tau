# 066 · English docs: README, ARCHITECTURE, infra/remote, CLAUDE.md, CONTEXT.md, ADRs

Status: in-progress
Type: AFK
Layer: L1 · Agent
Packages: docs, infra/remote
Blocked by: none

## What to build

The repo language becomes English everywhere except two places: the user's chat with the coding agent and tau's own persona body (`persona/persona.md`). Rewrite the Turkish documents and script messages in English and change the rule that kept them Turkish.

- `README.md`: English throughout (keep the hero, badges and brand assets from `docs/brand`).
- `docs/ARCHITECTURE.md`: English in place, same structure, every decision and the layer roadmap preserved; command and profile names follow 062 (`/resume`, `/settings`, `home`/`travel`/`sport`).
- `infra/remote/`: README, `setup.sh`, `doctor.sh` and any helper messages in English, including the doctor success line `remote access ready` quoted by 001 and 051. Behaviour unchanged: password auth stays off, `AllowUsers` stays restricted to tailnet + localhost; `doctor.sh` is re-run after the change.
- `CLAUDE.md`: the "Language" section becomes the wave's language policy (English repo; Turkish only for talking to the user and for the persona body); the "Don't translate them unasked" rule is removed; commands and paths updated for 062-065.
- `CONTEXT.md`: English terms only (`home`/`travel`/`sport`, `/resume`, `/settings`), new terms "UI language", "Slash command", "Component".
- `docs/adr/`: quoted Turkish command names and profile values updated (ADR 0003 `/devam` → `/resume`); ADR bodies stay as history otherwise.
- Package READMEs (`tau-core`, `tau-tui`) already touched by 062/063 are checked for leftovers; auto-memory notes outside the repo are not part of this issue.

## Acceptance criteria

- [ ] `README.md` is English; hero, badges and brand assets unchanged
- [ ] `docs/ARCHITECTURE.md` is English in place with the same sections and decisions; no decision is dropped or changed in meaning
- [ ] `infra/remote/README.md`, `setup.sh`, `doctor.sh` and helpers print and document in English; `doctor.sh` still exits 0 on the user's Mac with `remote access ready`; sshd invariants unchanged and `infra/remote/doctor.sh` re-run
- [ ] `CLAUDE.md` Language section states the new policy; no rule forbids translating tracked files
- [ ] `CONTEXT.md` uses English command and profile names and defines "UI language", "Slash command", "Component"
- [ ] `docs/adr/*.md` quote `/resume` and English profile names; ADR history otherwise untouched
- [ ] `grep -rn` for `/devam`, `/yeni`, `/oturum`, `/araçlar`, `/çık`, `/ayar`, `/hafiza`, `Onayla`, `Reddet`, `seyahat`, `spor` over tracked files hits only done issue files (001, 004-009), alias tables and persona content
- [ ] Nothing personal in any file (hostnames, tailnet names, addresses, fingerprints stay example values)

## Blocked by

None - can start immediately; terminology follows 062 (same wave).

## Comments

- 2026-09-29: opened by the 2026-09-29 wave on the user's request (English UI, premium TUI, Strands audit, plug-and-play setup). Spec: wave decisions sections 1 and 7. The user asked for English docs in general, which lifts the earlier CLAUDE.md rule against translating `docs/ARCHITECTURE.md` and `infra/remote/`.
