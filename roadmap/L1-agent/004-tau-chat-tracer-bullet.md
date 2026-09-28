# 004 · Tracer bullet: `tau chat` answers in the Jarvis persona

Status: ready-for-agent
Type: AFK
Layer: L1 · Agent
Packages: tau-core
Blocked by: none

## What to build

The thinnest end-to-end path through the agent. `tau chat` starts a REPL; each message goes through `build_agent(profile)` built on Strands Agents; the system prompt comes from the persona files; the model is resolved from the `brain` role through config; the reply comes back in Turkish in the Jarvis persona. This slice also establishes the uv workspace, the first independently publishable package (`tau-core`, import `tau_core`), the `tau` CLI entry point, the `tau.tools` entry-point group for plugins, a fake model for tests, and CI.

## Acceptance criteria

- [ ] `uv run tau chat` holds a multi-turn conversation in Turkish
- [ ] Without credentials it exits with a clear Turkish message naming the missing variables
- [ ] Roles map to provider + model id in a config file; no model id is hardcoded in code
- [ ] Bedrock and Anthropic are selectable by config only
- [ ] `build_agent(profile)` has no hub-specific assumptions and runs in isolation
- [ ] A tool shipped by another installed distribution is discovered through the `tau.tools` entry point (test plugin)
- [ ] `uv build` produces a standalone `tau-core` wheel with its own README and version
- [ ] Tests run offline with a fake model; GitHub Actions runs lint and tests
- [ ] Commands in `CLAUDE.md` updated

## Blocked by

None - can start immediately

## Notes

Do not add `litellm` as a Python dependency — the proxy arrives in #010 as a container.

## Comments
