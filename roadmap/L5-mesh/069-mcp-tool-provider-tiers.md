# 069 · Tiers for node capabilities loaded through MCP `ToolProvider`s

Status: needs-triage
Type: AFK
Layer: L5 · Mesh
Packages: tau-mesh, tau-core
Blocked by: 033

## What to build

033 registers a node's MCP tools on the hub as they appear. Strands loads MCP servers through a `ToolProvider` (`MCPClient` implements it) and the agent can be handed providers directly; but tools that arrive this way carry no tau tier, and the tier gate refuses untiered tools (fail closed). Define how a node declares tiers for its capabilities and how the hub applies them before a tool becomes callable.

Design: each node ships a tier manifest (tool name → tier and effect; served next to its MCP endpoint or embedded in the liveliness token), the hub validates it, wraps the provider's tools so `tier_of`/`effect_of` (064 item 12 annotations) answer for them, and refuses any tool missing from the manifest. A node cannot declare a lower tier than a hub-side policy allows for its kind (a robot node's motion tools are tier 2 whatever the manifest says). Removal on node leave stays as in 033.

## Acceptance criteria

- [ ] A node's manifest gives every exposed tool a tier and effect; the hub refuses tools not in the manifest (fail closed) and logs why
- [ ] Hub-side minimum tiers per node kind override a lower manifest tier; tier 2 always goes through approval
- [ ] `ToolProvider`-loaded tools show their tier in `/tools` and in the event pane like local tools
- [ ] Tests with a fake MCP server and manifest; no network
- [ ] Documented in the tau-mesh README and referenced from ADR 0005

## Blocked by

- [033 · MCP capability discovery over Zenoh](033-mcp-node-discovery.md)

## Comments

- 2026-09-29: filed as a follow-up of the Strands-correctness pass (064); per-node tier manifest, fail closed.
