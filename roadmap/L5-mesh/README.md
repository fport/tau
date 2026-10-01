# L5 · Mesh

**Goal:** Nodes join tau over Zenoh (events, liveliness) and MCP (capabilities); routines react to events without an LLM.

**Done when:** A second node's tools appear automatically, MQTT devices show up as events, and routines fire on events offline.

| # | Issue | Type | Blocked by |
|---|---|---|---|
| 032 | [zenohd on the hub, node liveliness and `tau nodes`](032-zenoh-router-and-liveliness.md) | AFK | 009 |
| 033 | [MCP capability discovery over Zenoh](033-mcp-node-discovery.md) | AFK | 032 |
| 034 | [Hot-reloaded tools and `_pending` approval for tau-written tools](034-hot-reload-tools-and-pending.md) | AFK | 006 |
| 035 | [MQTT → Zenoh bridge proven with a simulated device](035-mqtt-zenoh-bridge.md) | AFK | 032 |
| 036 | [Desk presence: screen unlock → `tau/desk/presence`](036-desk-presence-event.md) | AFK | 024, 032 |
| 037 | [Reflex engine for user-registered routines](037-reflex-routine-engine.md) | AFK | 006, 032, 181 |
| 069 | [Tiers for node capabilities loaded through MCP `ToolProvider`s](069-mcp-tool-provider-tiers.md) | AFK | 033 |
| 181 | [Routines on a clock: the `tau-routines` hub service, one approval at registration](181-routines-on-a-clock.md) | AFK | – |
| 183 | [A simulated lamp: the first device the app and routines can drive](183-simulated-lamp.md) | AFK | – |

Live status: `python3 roadmap/board.py`
