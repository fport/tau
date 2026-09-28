# 051 · `doctor.sh` flags other remote services exposed on every interface

Status: needs-triage
Type: AFK
Layer: L0 · Remote access
Packages: infra/remote
Blocked by: none

## What to build

The sshd hardening only covers SSH. Other macOS sharing services listen on every interface, accept the macOS login password and are not limited to the tailnet, so anyone on the same café Wi-Fi can reach them (the firewall is off on purpose for mosh). `doctor.sh` should detect them and tell the user how to turn them off, without sudo.

## Acceptance criteria

- [ ] `doctor.sh` warns when Remote Management / Screen Sharing (5900, 3283) or Remote Application Scripting (3031) is listening, naming the System Settings toggle to switch off
- [ ] Detection needs no sudo (e.g. `netstat -an -p tcp` LISTEN sockets)
- [ ] A warning does not hide the SSH result; a clean machine still reports "uzaktan erişim hazır"
- [ ] `infra/remote/README.md` security model lists these services and why they stay off

## Blocked by

None - can start immediately

## Notes

Found while closing #001: Remote Management and Remote Application Scripting were on and listening on `*`; `doctor.sh` still exited 0. Also listening on that Mac: 88 (Kerberos), 5000/7000 (AirPlay Receiver). Triage should decide whether those are flagged too or treated as harmless defaults.

## Comments
