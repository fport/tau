# 0004 · Config roots, `tau.toml` as data, and persona privacy

- Status: accepted (first version, issue 004; refined by issue 005)
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

## Consequences

- Tests build a throwaway `TAU_HOME`/`TAU_DATA_DIR` under a temporary directory
  (`tau_core.testing.test_config`) and never read the developer's real files.
- Moving the hub to another machine means copying `TAU_HOME` (including `persona/user.md` and
  `.env` over SSH); `TAU_DATA_DIR` moves with the session backend.
