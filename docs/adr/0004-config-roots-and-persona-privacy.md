# 0004 · Config roots, `tau.toml` as data, and persona privacy

- Status: accepted (issue 004; refined by issue 005)
- Date: 2026-09-29

## Context

tau runs from a repository checkout today and from an installed package on the hub later. It
needs a place for static configuration, a separate place for state it writes, a rule that
model ids are data rather than code, and a way to keep facts about the user out of a repository
that may become public.

## Decision

- Two roots:
  - **`TAU_HOME`**: configuration (`tau.toml`, `.env`, `persona/`, `tools/`). Default: the
    current directory when it holds a `tau.toml` (a checkout), else `~/.tau`.
  - **`TAU_DATA_DIR`**: mutable state (sessions, hub state, logs). Default
    `~/.local/share/tau`. Never inside the repository.
- **`tau.toml` is data**: role → provider + model id (+ optional fallback), the loop guard, the
  session backend, hub ports. The class that reads it is **`Config`** (`tau_core.config`); the
  glossary reserves *Settings* for runtime settings stored in D1 (issue 019). Code asks for a
  role, never a model id; a test fails if a model id appears under `packages/*/src`.
- `.env` in `TAU_HOME` is loaded with python-dotenv and never overrides variables that are
  already set; `.env.example` lists every name with example values.
- Persona: `persona/persona.md` (tau's character, no personal facts) and
  `persona/user.example.md` (a fake example) are tracked; **`persona/user.md` is gitignored**
  and holds the real facts about the user. Without it the prompt says so and addresses the
  user as "siz".

## Refinement (issue 005): the persona at runtime

- **Fixed prompt layout**: `persona.md`, then `## Kullanıcı` with `user.md` (or the sentence
  saying there is none and that the address is "siz"), then `## Şu an` with the dynamic
  context. The headings are Turkish because the model reads them and `persona.md` refers to
  those sections by name.
- **Rebuilt before every model call**, not once per turn: a `BeforeModelCallEvent` hook sets
  `agent.system_prompt`, which Strands re-reads on each call. A tool loop therefore sees a
  persona edit or a later time within the same turn.
- **Change detection by `stat`, not a file watcher**: each model call compares the
  `(st_mtime_ns, st_size)` stamp of both files and re-reads only on a change. Two `stat` calls
  per model call cost nothing, need no thread or platform API (FSEvents on the Mac, inotify on
  the RPi5) and cannot miss an event. The trade-off, an edit that keeps both size and mtime, is
  accepted.
- **HTML comments are stripped** before the text reaches the model. Files can carry notes for
  humans; in particular the copy instructions in `user.example.md` would otherwise tell the
  model, after `cp` to `user.md`, that its facts are only an example.
- **Strict first, lenient later**: a missing, empty or unreadable `persona.md` on the first
  read is a `ConfigError`, and `build_agent` reads eagerly, so tau fails at startup. Later the
  last good version is kept (an editor truncating the file mid-save must not strip tau of its
  character for one call). A missing or empty `user.md` is a legitimate state (the user may
  delete it) and falls back to "siz"; an unreadable one keeps the last good version.
- **Dynamic context**: always Europe/Istanbul (a naive clock is Istanbul time; without tzdata
  a fixed UTC+3 is used, since Türkiye has had no DST since 2016). A value no layer provides
  reads `bilinmiyor` and an empty node list reads `yok`, so the model can tell "not wired yet"
  from "nothing there"; `persona.md` tells it never to guess an unknown value.
- **Context sources** (`ContextSource`, passed as `build_agent(context_sources=...)`) are how
  later layers add live values (today's spend in L2, live nodes in L5). They run before every
  model call, so they return cached values and do no network round trip. Results are
  normalized; unknown keys are ignored and a failing source is skipped.
- **Problems are logged once** until they clear (the terminal shows warnings), so a broken
  file or source never floods the chat.
- `persona.md` holds no facts about the user; a test checks the tracked persona files for
  emails, addresses, tailnet names and home paths, and that `persona/user.md` is ignored.

## Consequences

- Tests build a throwaway `TAU_HOME`/`TAU_DATA_DIR` under a temporary directory
  (`tau_core.testing.test_config`) and never read the developer's real files; tests of the
  tracked persona read `user.example.md`, never `user.md`.
- Moving the hub to another machine means copying `TAU_HOME` (including `persona/user.md` and
  `.env` over SSH); `TAU_DATA_DIR` moves with the session backend.
- Changing tau's character is a text edit with no deploy; a bad edit is caught at the next
  start, not in the middle of a conversation.
