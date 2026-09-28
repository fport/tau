# 045 · Nicla Vision on-device rep counting and fall detection

Status: needs-hardware
Type: needs-hardware
Layer: L6 · Robot
Packages: firmware/nicla
Blocked by: 035

## What to build

Use the Nicla's IMU and on-device ML for things that should not need the network: rep counting and fall detection. Results are published as events through the MQTT bridge.

## Acceptance criteria

- [ ] Rep counting works on-device for one exercise
- [ ] Fall detection triggers an event
- [ ] Events arrive in Zenoh through the MQTT bridge (#035)

## Blocked by

- [035 · MQTT → Zenoh bridge proven with a simulated device](../L5-mesh/035-mqtt-zenoh-bridge.md)

## Comments
