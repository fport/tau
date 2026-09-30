# tau-sub

Sub-taus: small, named specialists of your tau. A workout coach (`/coach`), a landing-page
writer (`/landing`), a helper for the robot arm: each is tuned to one job, used on its own or
asked by the main tau. A sub-tau is not a second hub or a second identity; it shares your
tau's hub, spine and address (ADR 0012).

It is its own distribution (`tau-sub`, import `tau_sub`), uses only the public API of
`tau-core` and plugs in through three entry points:

| group | name | what |
|---|---|---|
| `tau.commands` | `sub` | `tau sub …` |
| `tau.tools` | `sub` | `ask_sub` (tier 0), `create_sub` (tier 2) |
| `tau.subs` | `sub` | the public sub-taus, for tau-net (see "Public sub-taus" below) |

## What a sub-tau is

Each sub-tau has:

- a **name**, a slug matching `^[a-z][a-z0-9-]{1,30}$`, shown as `/name`;
- a **persona**: its character and its task instructions;
- an **about** line, at most 200 characters;
- a **model role**: `brain` (default), `fast` or `local`;
- a **tool allowlist**: names from the tool catalog (`tau components`), empty by default;
- a **`public`** flag, false by default: a public sub-tau answers your contacts over the tau
  network and is listed in the universe (see "Public sub-taus" below);
- **its own sessions**, on the channel `sub:<name>`.

## The definition file

`persona/subs/<name>.md` under `TAU_HOME` (gitignored in the tau repository, like
`persona/user.md`): TOML front matter between two `+++` lines, then the persona text.

```markdown
+++
about = "A strict but kind workout coach who plans three short sessions a week."
role = "brain"                      # brain | fast | local
tools = ["current_time"]            # names from the tool catalog
public = false                      # true: contacts reach it as <address>/coach
# public_note = "coach.public.md"   # optional: a file next to the definition
+++

You plan the owner's workouts: three sessions of 20 to 30 minutes a week, ...
```

- The front matter is parsed with `tomllib` and never reaches the model. Unknown keys, wrong
  types, an unknown role, an `about` over 200 characters, an empty persona and every tool
  name that is not in the catalog are errors; an unknown tool is named in the error.
- `ask_sub` and `create_sub` are never allowed in an allowlist, so a sub-tau cannot call or
  create other sub-taus.
- HTML comments in the persona are notes for you, like in `persona.md`.
- A `public_note` is a `.md` file in `persona/subs/` whose name is not itself a sub-tau name
  (the convention is `<name>.public.md`).
- Files are written atomically with mode 0600 in a 0700 directory and never overwritten
  without `--force`. [`examples/coach.md`](examples/coach.md) is a complete example with
  made-up content.

## The prompt

The model reads:

```
You are /<name>, a specialist of your owner's tau: <about>. Stay within this task; say so
when a request is outside it.

<the persona text>

## User
<persona/user.md>

## Now
<the dynamic context: time, profile, host role, live nodes, budget>
```

tau-core's `PersonaLoader` reads a persona file and `user.md` and knows nothing of front
matter, so the first two parts are rendered into a derived file,
`TAU_DATA_DIR/subs/<name>/persona.md` (0600), rewritten only when the definition changes. The
loader keeps its hot reload: `tau sub chat` re-reads the definition before every turn, a new
persona applies from the next turn, and a new role or allowlist rebuilds the agent on the
same session.

## Commands

```sh
tau sub new coach --describe "a strict but kind workout coach that plans three short sessions a week"
tau sub new landing --about "Writes landing-page copy." --tools current_time   # a template to edit
tau sub list                        # name, role, tools, public, last session
tau sub show coach
tau sub edit coach                  # opens $EDITOR, then checks the file
tau sub ask coach "plan my week"    # one turn
tau sub chat coach                  # a conversation; /tools /new /session /quit
tau sub chat coach --new            # a fresh session
tau sub remove coach                # the definition only; sessions are kept
```

- `new --describe` asks the `brain` role for a draft (`{about, persona, tools}`), shows it and
  asks before writing (`--yes` skips the question). The drafter gets the tool catalog without
  tier-2 tools and never sees `user.md`; proposed tools that are unknown, forbidden or tier 2
  are left out and listed (`--allow-tier2` keeps tier-2 tools, which still ask for approval
  on every call). `--about`, `--role`, `--tools` and `--public` win over the draft.
- `chat` and `ask` continue the sub-tau's last session, remembered in
  `TAU_DATA_DIR/subs/<name>/session`; `--new` starts a fresh one.

## Tools for the main tau

- **`ask_sub(name, question)`**, tier 0: runs the sub-tau for one turn, on a new session of
  its own, and returns its answer. An empty name lists the sub-taus.
- **`create_sub(name, about, persona, tools)`**, tier 2, effect "Creates a new sub-tau of
  your tau that can use the listed tools.": validates like `tau sub new` and never
  overwrites.

## Safety rules

- The tier gate stays the only way a tool runs. A sub-tau's agent comes from
  `tau_core.build_agent` with exactly its allowlist; a tool outside it is refused as unknown.
- A tier-2 tool asks for approval on every call:
  - in `tau sub chat`, on the terminal;
  - in `tau sub ask`, on the terminal when stdin is one, and refused otherwise;
  - through `ask_sub`, with the approver of the turn that called it, so the owner answers on
    the channel the conversation came from (terminal, TUI, Telegram), and the approval names
    the sub-tau. The tool finds that approver through its Strands tool context (the calling
    agent's tier hook). When there is none, every tier-2 call of the sub-tau is refused and
    the answer says that tier-2 tools need `tau sub chat`.
- Nothing approves on the owner's behalf, in the code or in the tests (`ScriptedApprover`).
- `create_sub` is tier 2: a new sub-tau is a new agent configuration that may use tools.
- A sub-tau cannot call `ask_sub` or `create_sub`, so delegation is one level deep.
- A remembered session that belongs to another channel is ignored: a sub-tau never continues
  the main tau's history.

## Public sub-taus

`public = true` lets your contacts on the tau network reach a sub-tau directly, as
`<address>/<name>` (`tau net send alice.example.com/coach "…"`); the sealed `message` carries
`"sub": "coach"` (protocol reference, `docs/reference/tau-network.md` §3 and §6.4):

- A public sub-tau answers with the same narrow network turn as the main tau: its persona (the
  header and persona text above) and, as the `## User` section, its `public_note`, or your
  tau's public note (`persona/net.md`) when it names none. Never `persona/user.md`, never the
  tools of its allowlist, no approvals, and the same `max_hops` and hourly cap per contact.
- Each contact gets its own session with it, titled `tau network · <name> · /coach`, on the
  model role of the definition. Its answer carries `/coach`, and a reply to it goes back to
  `/coach`, so the thread stays with it.
- A message for a private, unknown or invalid sub-tau is dropped and logged, like one from a
  stranger, and never answered. Making a sub-tau private takes effect with the next message.
- While your tau is in the universe, each report lists your public sub-taus (`{name, about}`,
  at most 20) and the page draws them inside your hull. Private sub-taus never leave the hub.

tau-net does not import tau-sub. It finds the sub-taus through the `tau.subs` entry point:
`tau_sub.network:public_subs(config)` returns a `PublicSubs` directory whose `public(name)`
and `public_subs()` give plain `PublicSub` records (`name`, `about`, `role`, `persona_file`,
`public_note_file`). Without tau-sub installed, a hub has no public sub-taus.

## Development

```sh
uv run pytest packages/tau-sub -q
uv build --package tau-sub
```
