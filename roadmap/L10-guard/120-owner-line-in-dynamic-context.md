# 120 · Owner line in the dynamic context

Status: ready-for-agent
Type: AFK
Layer: L10 · Guard
Packages: tau-core
Blocked by: 054, 110

## What to build

On a guarded channel, tau learns that the person typing was verified and how long ago, so the persona can act on it. For example, it can greet the owner after an unlock, or keep a sensitive answer short when the last face match is old. `## Now` gains one English line, rendered like the channel line from 054:

```
- Owner: verified 4 min ago (face)
```

- **Values.** `verified <n> min ago (face|touch_id)`, `remote grant` (from 117 on) or `not verified`. The minutes are rounded, and no timestamp or client id reaches the model.
- **When it appears.** Only on turns of an agent whose `guard` is set. Agents built with `guard=None` (Telegram, network turns) and installs without a guard render no owner line, so their prompts stay byte-identical.
- **Data flow.** `Admission` gains two optional fields, `method: str | None = None` and `face_seen_at: datetime | None = None`, an additive change. `POST /guard/admit` returns them, and `HubGuard` maps them. `TauAgent` stores the last admission, and the dynamic-context factory renders the line from it. There is no extra hub call per turn.
- **The label** is fixed English, like every dynamic-context label (062). The persona body (`persona/persona.md`, Turkish like the rest of the body) gets one rule on using the line: greet after a fresh unlock, and do not talk about verification otherwise.

Decision: [ADR 0008](../../docs/adr/0008-owner-guard.md) (decisions 1 and 5): the guard is a gate in v1, and this line is how the model learns about it without the model being able to change it.

## Acceptance criteria

- [ ] With a `FakeGuard` that admits with `method="face"` and a `face_seen_at` 4 minutes ago, `FakeModel.calls[i].system_prompt` contains `- Owner: verified 4 min ago (face)`
- [ ] Without a guard, and on agents built with `guard=None`, the system prompt is byte-identical to before (test)
- [ ] No timestamp, client id or enrollment id appears in the prompt
- [ ] `Admission` and the `/guard/admit` answer carry `method` and `face_seen_at`; an answer without them renders `- Owner: verified` with no details, never an error
- [ ] The persona body has the rule, and the tau-core README lists the new line

## Blocked by

- [054 · Show the conversation channel in the dynamic context](../L1-agent/054-channel-in-dynamic-context.md)
- [110 · Guard seams in tau-core](110-guard-seams-in-tau-core.md)

## Comments

- 2026-09-30: filed with ADR 0008.
