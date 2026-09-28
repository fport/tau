# 039 · SO-101 simulation node with MCP tools

Status: ready-for-agent
Type: AFK
Layer: L6 · Robot
Packages: tau-robot
Blocked by: 033

## What to build

A robot node built on strands-robots runs the SO-101 in MuJoCo simulation by default and exposes MCP tools: home, play a named motion, stop. Real mode needs explicit config plus tier-2 approval and is never enabled by defaults or tests. Motions are data (named, versioned) so the method chosen in #038 can plug in.

## Acceptance criteria

- [ ] `arm.play("wave")` runs in simulation with a placeholder motion
- [ ] Real mode is impossible without explicit config and a tier-2 approval
- [ ] `stop` is always available and tier 0
- [ ] `tau-robot` is its own distribution

## Blocked by

- [033 · MCP capability discovery over Zenoh](../L5-mesh/033-mcp-node-discovery.md)

## Comments
