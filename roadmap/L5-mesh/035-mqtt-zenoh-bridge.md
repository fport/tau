# 035 · MQTT → Zenoh bridge proven with a simulated device

Status: ready-for-agent
Type: AFK
Layer: L5 · Mesh
Packages: tau-mesh
Blocked by: 032

## What to build

`zenohd` loads the MQTT plugin so MQTT clients — later ESPHome devices — appear in the Zenoh keyspace under `tau/home/...`. Proven with a simulated device that publishes a sensor value and receives a command.

## Acceptance criteria

- [ ] A simulated device's publish shows up as a Zenoh event
- [ ] A Zenoh publish reaches an MQTT subscriber (command path)
- [ ] The MQTT listener is reachable only from LAN/tailnet and requires credentials
- [ ] The ESPHome MQTT topic mapping is documented for when hardware arrives

## Blocked by

- [032 · zenohd on the hub, node liveliness and `tau nodes`](032-zenoh-router-and-liveliness.md)

## Comments
