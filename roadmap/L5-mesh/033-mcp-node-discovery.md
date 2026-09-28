# 033 · MCP capability discovery over Zenoh

Status: ready-for-agent
Type: AFK
Layer: L5 · Mesh
Packages: tau-mesh, tau-core
Blocked by: 032

## What to build

A node serves its capabilities as an MCP server (streamable HTTP on the tailnet) and announces the endpoint through its liveliness token. The hub registers the node's tools automatically, namespaced (e.g. `mac.screenshot`), and removes them when the node leaves. Demo: a Mac node with one tier-0 tool (screenshot) and one tier-1 tool.

## Acceptance criteria

- [ ] Starting the Mac node makes `mac.*` tools usable from `tau chat` without restarting the hub
- [ ] Stopping it removes them; in-flight calls fail gracefully
- [ ] Node tools must declare tiers and the hub enforces them
- [ ] Nodes must authenticate to the hub

## Blocked by

- [032 · zenohd on the hub, node liveliness and `tau nodes`](032-zenoh-router-and-liveliness.md)

## Comments
