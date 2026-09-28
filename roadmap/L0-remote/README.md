# L0 · Remote access

**Goal:** Reach the MacBook from the phone and keep a Claude Code session alive across disconnects.

**Done when:** Phone → Tailscale → mosh → tmux → Claude Code works, and the SSH hardening is protected by an automated test.

| # | Issue | Type | Blocked by |
|---|---|---|---|
| 001 | [Finish remote access setup on the MacBook and verify from the phone](001-finish-remote-access-setup.md) | HITL | – |
| 002 | [Automated regression test for the SSH hardening](002-ssh-hardening-regression-test.md) | AFK | – |
| 051 | [`doctor.sh` flags other remote services exposed on every interface](051-doctor-flags-exposed-remote-services.md) | AFK | – |

Live status: `python3 roadmap/board.py`
