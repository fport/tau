# 005 · Live persona files and dynamic context in the system prompt

Status: ready-for-agent
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: 004

## What to build

The system prompt is assembled on every turn from `persona/persona.md`, `persona/user.md` and a dynamic context block: current time (Europe/Istanbul), active profile, live nodes and today's budget. Sources whose layer does not exist yet are shown as unknown. Editing a persona file takes effect on the next turn without a restart.

## Acceptance criteria

- [ ] Editing `persona.md` mid-conversation changes the next reply without restart
- [ ] Dynamic context shows time, active profile, and explicit "unknown" for sources not yet available
- [ ] Persona encodes the Jarvis rules: Turkish, polite, dry humor, ≤2 sentences for notifications and voice, no jokes in approval requests
- [ ] Unit tests cover prompt assembly and reload

## Blocked by

- [004 · Tracer bullet: `tau chat` answers in the Jarvis persona](004-tau-chat-tracer-bullet.md)

## Comments
