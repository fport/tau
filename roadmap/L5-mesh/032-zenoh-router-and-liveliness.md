# 032 · zenohd on the hub, node liveliness and `tau nodes`

Status: ready-for-agent
Type: AFK
Layer: L5 · Mesh
Packages: tau-mesh
Blocked by: 009

## What to build

The hub runs `zenohd` and joins the mesh. Nodes connect with explicit endpoints over the tailnet (multicast discovery does not cross Tailscale; it is fine on the LAN). Every node declares liveliness under `tau/nodes/<name>`; `tau nodes` lists live nodes with role and capability count. Event key conventions (`tau/<area>/<name>`) are defined.

## Acceptance criteria

- [ ] A second process started as a node appears in `tau nodes`; stopping it removes it within seconds
- [ ] A node on another tailnet machine connects through a configured endpoint
- [ ] Key-expression conventions are documented in `CONTEXT.md` and the package README
- [ ] `tau-mesh` is its own distribution; the `zenohd` config is versioned in the repo

## Blocked by

- [009 · `tau hub` daemon with launchd service and self-heal](../L1-agent/009-hub-daemon.md)

## Comments
