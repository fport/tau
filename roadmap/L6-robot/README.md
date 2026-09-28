# L6 · Robot

**Goal:** tau reaches the physical world: SO-101 arm (sim first) and the workout coach.

**Done when:** Unlocking the Mac makes the arm wave (sim, then real), and the coach flags form errors using a camera.

| # | Issue | Type | Blocked by |
|---|---|---|---|
| 038 | [Decide how SO-101 motions are produced](038-decide-so101-motion-method.md) | HITL | – |
| 039 | [SO-101 simulation node with MCP tools](039-so101-sim-node.md) | AFK | 033 |
| 040 | [Bring up the real SO-101 safely](040-so101-real-bring-up.md) | HITL | 039 |
| 041 | [Greet on sit: presence → wave](041-greet-on-sit.md) | AFK | 036, 037, 038, 039 |
| 042 | [Decide the workout alert channel and target exercises](042-decide-workout-alert-channel.md) | HITL | – |
| 043 | [Workout form coach with the Mac webcam as a stand-in camera](043-workout-coach-webcam.md) | AFK | 032, 042 |
| 044 | [XIAO ESP32S3 Sense necklace camera feeding the coach](044-xiao-necklace-camera.md) | needs-hardware | 043 |
| 045 | [Nicla Vision on-device rep counting and fall detection](045-nicla-on-device-ml.md) | needs-hardware | 035 |

Live status: `python3 roadmap/board.py`
