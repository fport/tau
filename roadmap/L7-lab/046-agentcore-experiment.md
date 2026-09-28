# 046 · AgentCore Runtime deployment experiment

Status: ready-for-agent
Type: AFK
Layer: L7 · Lab
Packages: deploy/agentcore
Blocked by: 003, 004

## What to build

Deploy the same `build_agent` to AgentCore Runtime with a restricted tool set (no physical tools, no shell), invoke it from the CLI, measure cost, and tear it down with one command. Pure experiment; not wired into the relay.

## Acceptance criteria

- [ ] Deploy, invoke and teardown scripts exist
- [ ] Same agent code as the hub — no fork
- [ ] Cost of an idle day and of 100 invocations is recorded
- [ ] Teardown leaves no billable resources

## Blocked by

- [003 · Provision model credentials with cost guards](../L1-agent/003-provision-model-credentials.md)
- [004 · Tracer bullet: `tau chat` answers in the Jarvis persona](../L1-agent/004-tau-chat-tracer-bullet.md)

## Comments
