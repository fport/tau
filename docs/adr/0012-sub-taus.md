# ADR 0012 · Sub-taus

Date: 2026-09-30 · Status: accepted · Builds on [ADR 0007](0007-cloud-mode-and-tau-network.md) and [ADR 0010](0010-public-site-and-tau-universe.md).

## Context

A tau is one generalist agent. Owners want small specialists as well: a workout coach, a landing-page writer, a helper for the robot arm, each tuned to one job, used alone or asked by the main tau, and, when the owner wants, reachable by the owner's contacts. The tiny project shows the shape: one builder, many small agents, each with a slash name (`/coach`, `/landing`) and shown together in the universe.

Constraints from the earlier ADRs:

- The tier gate stays the only way a tool runs.
- Network turns never see `user.md`.
- Nothing personal lands in tracked files.

## Decision

1. **A sub-tau is a named specialization of the owner's tau.** It is not a second hub or a second identity. It shares the hub, the identity, the spine and the address. Each sub-tau has:
   - a **name**, a slug `^[a-z][a-z0-9-]{1,30}$`, shown as `/name`;
   - a **persona**: its character and its task instructions;
   - an **about** line;
   - a **model role** (`brain`, `fast` or `local`);
   - a **tool allowlist**: names from the tool catalog, empty by default. The tiers are unchanged, so a tier-2 tool still asks for approval on the channel the call came from;
   - a **`public`** flag, false by default;
   - **its own sessions**, on the channel `sub:<name>`.
2. **Definitions are owner files.** Each sub-tau is `persona/subs/<name>.md`: TOML front matter (`about`, `role`, `tools`, `public`, `public_note`) followed by the persona text. The files live under `TAU_HOME`, are gitignored in this repository like `user.md`, and are hot-read like the persona. Cloud mode pushes and pulls them with the other persona files.
3. **Creating one.**
   - `tau sub new NAME --describe "…"` asks the `brain` role to draft the persona, the about line and a proposed tool allowlist from a description. The draft is written for the owner to read.
   - `tau sub new NAME` without `--describe` writes a template.
   - The main tau can create one through the tool `create_sub`, which is **tier 2**: it activates a new agent configuration that may use tools, like a self-written tool does.
   - An allowlist can name only tools that exist in the catalog.
4. **Using one.**
   - `tau sub chat NAME` opens a conversation and `tau sub ask NAME "…"` is one-shot.
   - `tau sub list|show|edit|remove` manage the definitions.
   - The main tau can delegate through the tool `ask_sub(name, question)`. This tool is tier 0, but every tool the sub-tau calls goes through the same tier gate and the same approver as the main turn.
   - The sub-tau sees `user.md` in the owner's own chats, the same as the main tau.
5. **Over the network, only public sub-taus answer.**
   - A contact addresses one as `<address>/<name>`: an envelope `message` gets an optional `sub` field in the signed payload.
   - A public sub-tau answers with the same narrow network turn as the main tau: its persona plus its own public note (never `user.md`), no tools, no approvals, and the same hop and hourly limits.
   - A message for a private or unknown sub-tau is dropped and logged like one from a stranger.
6. **In the universe, public sub-taus appear inside the owner's hull.** The hub's report lists them as `{name, about}`, and the page draws them as small nodes around the main tau, the way tiny shows a builder's tinys. Private sub-taus never leave the hub.

## Consequences

- A new package, `tau-sub` (import `tau_sub`), holds the definitions, the drafting, the CLI (`tau sub …`), the tools (`ask_sub` tier 0, `create_sub` tier 2) and the `tau.tools` and `tau.commands` entry points. tau-core needs no change: sub-taus are built with `build_agent`, with an explicit persona and an explicit tool list.
- `tau-net` gets the optional `sub` field, routing to public sub-taus and sub-taus in universe reports. `cloud/universe` shows them.
- Slash commands inside `tau chat`, the TUI and Telegram (`/coach …`) need tau-core's command table, so they come in a follow-up issue.
- Generated interfaces, like the scoreboard a tiny renders in its chat, need the web UI (074). They are out of scope here.

## Why not

- **Separate identities and spines per sub-tau:** one Worker per specialist would multiply the setup, the Free plan usage and the keys to back up, with nothing gained. They share the owner's address instead.
- **Code generation for sub-tau skills:** a sub-tau is a persona plus an allowlist of existing tools. Tools tau writes itself keep going through `tools/_pending/` and tier 2.
- **Always public:** most specialists are for the owner alone, so public stays an explicit flag.
