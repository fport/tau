"""The remote access checks behind ``tau remote`` and ``tau setup`` → Remote access (issue 173).

Each check is a :class:`~tau_core.setup.checks.CheckResult`, the setup engine's check protocol:

- :func:`tailscale_check`: the Tailscale CLI (on ``PATH``, or inside Tailscale.app on macOS) and
  ``tailscale status --json``: ``BackendState`` is ``Running``, with the MagicDNS name and the
  100.x address. Otherwise how to install it (macOS: the App Store or tailscale.com/download;
  Linux: the official install script, shown for the owner to run) or how to log in.
- :func:`ssh_check`: what ``infra/remote/doctor.sh`` checks for SSH: sshd answers on port 22,
  tau's drop-in turns password and keyboard-interactive login off and restricts ``AllowUsers``
  to the user from the tailnet and localhost, a live probe finds password login refused, mosh
  and tmux are installed (on macOS also Homebrew and the ``~/.zshenv`` block). Otherwise the one
  command, ``bash <kit>/setup-all.sh``, with what it changes: shown, never run.
- :func:`phone_check`: what to enter in Termius (the live MagicDNS name and user, port 22, mosh,
  ``tau-attach``) and whether ``~/.ssh/authorized_keys`` holds a key.

:func:`status_parts` runs all three; remote access counts as set up when every one passes. The
real values (host names, addresses, the user) are printed, never written anywhere.
"""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tau_core.i18n import t
from tau_core.remote.scripts import ADD_KEY, ENTRY, KitError, kit_files, shell_path
from tau_core.remote.system import System
from tau_core.setup.checks import Action, CheckItem, CheckResult

__all__ = [
    "ALLOWED_SOURCES",
    "BLOCK",
    "MAC_APP_CLI",
    "SSHD_CONF",
    "Kit",
    "Tailscale",
    "allow_users_restricted",
    "dropin_problems",
    "phone_check",
    "probe_tailscale",
    "render_template",
    "ssh_check",
    "status_parts",
    "status_result",
    "tailscale_check",
    "tailscale_result",
    "unsupported",
]

SSHD_CONF = "/etc/ssh/sshd_config.d/010-tau.conf"
"""Where infra/remote puts tau's drop-in (``TAU_SSHD_CONF`` in its config.env)."""
SSHD_MAIN = "/etc/ssh/sshd_config"
SSH_PORT = 22
MAC_APP = "/Applications/Tailscale.app"
MAC_APP_CLI = f"{MAC_APP}/Contents/MacOS/Tailscale"
BLOCK = "# >>> tau:remote >>>"
"""The first line of the blocks setup.sh and setup-linux.sh add to dot files."""
STARTUP = "tau-attach"
TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
ALLOWED_SOURCES = (
    TAILNET_V4,
    TAILNET_V6,
    ipaddress.ip_network("127.0.0.1/32"),
    ipaddress.ip_network("::1/128"),
)
"""The only sources ``AllowUsers`` may name: the tailnet and localhost."""
TAILSCALE_URL = {
    "darwin": "https://tailscale.com/download/mac",
    "linux": "https://tailscale.com/download/linux",
}
TAILSCALE_INSTALL = "curl -fsSL https://tailscale.com/install.sh | sh"
TAILSCALE_ADMIN = "https://login.tailscale.com/admin/machines"
BREW_URL = "https://brew.sh"
_DENIED = re.compile(r"Permission denied \(([^)]*)\)")
_INCLUDE = re.compile(r"^[ \t]*Include[ \t]+/etc/ssh/sshd_config\.d/", re.IGNORECASE | re.MULTILINE)

Kit = Callable[[], Path]
"""Returns the kit directory to show commands from (writing the shipped copy when needed)."""


def unsupported(language: str) -> CheckResult:
    return CheckResult(False, t("setup.remote.unsupported", language))


# -- Tailscale ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Tailscale:
    cli: str | None
    """The CLI to run (under the system root in tests)."""
    shown: str | None
    """The CLI as the owner knows it."""
    app: bool
    """Tailscale.app is installed (macOS)."""
    state: str | None = None
    """``BackendState`` of ``tailscale status --json``; ``None`` when it gave no JSON."""
    host: str | None = None
    """The MagicDNS name, without the trailing dot."""
    ip: str | None = None
    """The 100.x address."""
    magicdns: bool = False

    @property
    def installed(self) -> bool:
        return self.cli is not None or self.app

    @property
    def address(self) -> str | None:
        """What Termius connects to: the MagicDNS name, else the 100.x address."""
        return self.host if self.magicdns and self.host else self.ip

    @property
    def running(self) -> bool:
        return self.state == "Running" and self.address is not None


def _tailnet_ipv4(values: Any) -> str | None:
    for value in values if isinstance(values, list) else ():
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if address.version == 4 and address in TAILNET_V4:
            return str(address)
    return None


def probe_tailscale(system: System) -> Tailscale:
    """Find the CLI and read ``tailscale status --json`` (also when it exits non-zero: logged
    out, it still prints the state)."""
    app = system.platform == "darwin" and system.path(MAC_APP).is_dir()
    on_path = system.which("tailscale")
    if on_path:
        cli, shown = on_path, on_path
    elif system.platform == "darwin" and system.path(MAC_APP_CLI).is_file():
        cli, shown = str(system.path(MAC_APP_CLI)), MAC_APP_CLI
    else:
        return Tailscale(None, MAC_APP if app else None, app)
    ran = system.run([cli, "status", "--json"], timeout=10)
    try:
        data = json.loads(ran.out)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return Tailscale(cli, shown, app)
    state = data.get("BackendState")
    me = data.get("Self") if isinstance(data.get("Self"), dict) else {}
    dns = me.get("DNSName") if isinstance(me.get("DNSName"), str) else ""
    ip = _tailnet_ipv4(me.get("TailscaleIPs")) or _tailnet_ipv4(data.get("TailscaleIPs"))
    tailnet = data.get("CurrentTailnet") if isinstance(data.get("CurrentTailnet"), dict) else {}
    magicdns = tailnet.get("MagicDNSEnabled")
    return Tailscale(
        cli,
        shown,
        app,
        state=state if isinstance(state, str) else None,
        host=dns.rstrip(".") or None,
        ip=ip,
        magicdns=magicdns if isinstance(magicdns, bool) else bool(dns),
    )


def _state_text(state: str | None, language: str) -> str:
    key = {
        None: "setup.remote.ts.state.unreachable",
        "NoState": "setup.remote.ts.state.logged_out",
        "NeedsLogin": "setup.remote.ts.state.logged_out",
        "Stopped": "setup.remote.ts.state.stopped",
        "Starting": "setup.remote.ts.state.starting",
        "NeedsMachineAuth": "setup.remote.ts.state.approval",
    }.get(state, "setup.remote.ts.state.other")
    return t(key, language, state=state or "")


def _install_action(system: System, language: str) -> Action:
    if system.platform == "darwin":
        text = t("setup.remote.ts.install.darwin", language)
        return Action("install", text, url=TAILSCALE_URL["darwin"])
    return Action(
        "install",
        t("setup.remote.ts.install.linux", language),
        command=f"{TAILSCALE_INSTALL} && sudo tailscale up",
        sudo=True,
        url=TAILSCALE_URL["linux"],
    )


def _login_action(system: System, ts: Tailscale, language: str) -> Action:
    if ts.state == "NeedsMachineAuth":
        return Action("login", t("setup.remote.ts.approve", language), url=TAILSCALE_ADMIN)
    if system.platform == "darwin":
        command = "open -a Tailscale" if ts.app else "tailscale up"
        return Action("login", t("setup.remote.ts.login.darwin", language), command=command)
    if ts.state is None:  # tailscaled does not answer
        return Action(
            "login",
            t("setup.remote.ts.start.linux", language),
            command="sudo systemctl enable --now tailscaled && sudo tailscale up",
            sudo=True,
        )
    return Action(
        "login", t("setup.remote.ts.login.linux", language), command="sudo tailscale up", sudo=True
    )


def _tailscale_action(system: System, ts: Tailscale, language: str) -> Action:
    return (
        _install_action(system, language)
        if not ts.installed
        else _login_action(system, ts, language)
    )


def tailscale_result(system: System, ts: Tailscale, language: str) -> CheckResult:
    installed = CheckItem(
        "installed",
        t("setup.remote.ts.installed", language),
        "ok" if ts.installed else "fail",
        ts.shown or t("setup.remote.ts.missing", language),
    )
    values = {
        "cli": ts.shown,
        "state": ts.state,
        "host": ts.host,
        "ip": ts.ip,
        "magicdns": ts.magicdns,
    }
    if not ts.installed:
        summary = t("setup.remote.ts.summary.missing", language)
        return CheckResult(False, summary, (installed,), _install_action(system, language), values)
    label = t("setup.remote.ts.connected", language)
    if ts.running:
        detail = " · ".join(dict.fromkeys(filter(None, (ts.address, ts.ip))))
        summary = t("setup.remote.ts.ok", language, host=ts.address)
        return CheckResult(
            True, summary, (installed, CheckItem("connected", label, "ok", detail)), None, values
        )
    connected = CheckItem("connected", label, "fail", _state_text(ts.state, language))
    summary = t("setup.remote.ts.summary.down", language)
    return CheckResult(
        False, summary, (installed, connected), _login_action(system, ts, language), values
    )


def tailscale_check(system: System, language: str) -> CheckResult:
    if system.platform not in ("darwin", "linux"):
        return unsupported(language)
    return tailscale_result(system, probe_tailscale(system), language)


# -- SSH and mosh ---------------------------------------------------------------------------------


def _sshd_options(text: str) -> tuple[dict[str, list[str]], list[str]]:
    """``(keyword → the words of its first occurrence, every AllowUsers entry)`` of the global
    section: sshd takes the first value of an option, but adds up every ``AllowUsers`` line."""
    first: dict[str, list[str]] = {}
    allow: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        keyword, rest = _split(line)
        keyword = keyword.lower()
        if keyword == "match":
            break
        words = rest.split()
        first.setdefault(keyword, words)
        if keyword == "allowusers":
            allow += words
    return first, allow


def _split(line: str) -> tuple[str, str]:
    """``Keyword value`` or ``Keyword=value`` → ``(keyword, value)``."""
    match = re.match(r"([A-Za-z]+)\s*(?:=\s*|\s+)(.*)", line)
    if match is None:
        return line, ""
    return match.group(1), match.group(2)


def allow_users_restricted(entry: str, user: str) -> bool:
    """``user@<address or CIDR>`` inside the tailnet or localhost; anything else (another user,
    no host part, a wildcard, a host name, a LAN range) lets more in than tau allows."""
    name, sep, source = entry.partition("@")
    if not sep or name != user:
        return False
    try:
        network = ipaddress.ip_network(source, strict=False)
    except ValueError:
        return False
    return any(
        network.version == allowed.version and network.subnet_of(allowed)  # type: ignore[arg-type]
        for allowed in ALLOWED_SOURCES
    )


def dropin_problems(text: str, user: str, language: str) -> list[str]:
    """What is wrong with tau's sshd drop-in, localized; empty when it holds."""
    first, allow = _sshd_options(text)
    problems = []
    if [w.lower() for w in first.get("passwordauthentication", [])] != ["no"]:
        problems.append(t("setup.remote.ssh.dropin.password", language))
    kbd = first.get("kbdinteractiveauthentication") or first.get("challengeresponseauthentication")
    if [w.lower() for w in kbd or []] != ["no"]:
        problems.append(t("setup.remote.ssh.dropin.kbd", language))
    if not allow:
        problems.append(t("setup.remote.ssh.dropin.allow_missing", language))
    else:
        loose = [entry for entry in allow if not allow_users_restricted(entry, user)]
        if loose:
            problems.append(
                t(
                    "setup.remote.ssh.dropin.allow_open",
                    language,
                    entries=", ".join(loose),
                    user=user,
                )
            )
    return problems


def render_template(user: str) -> str:
    """tau's drop-in as infra/remote renders it with the default tailnet ranges."""
    template = kit_files()["sshd/tau.conf"].decode("utf-8")
    return (
        template.replace("__USER__", user)
        .replace("__TAILNET_V4__", str(TAILNET_V4))
        .replace("__TAILNET_V6__", str(TAILNET_V6))
    )


def _probe(system: System, user: str, language: str) -> CheckItem:
    """Try to log in to localhost with a password, as doctor.sh does: only ``publickey`` may be
    offered. BatchMode never types a password."""
    label = t("setup.remote.ssh.probe", language)
    ssh = system.which("ssh")
    if ssh is None:
        detail = t("setup.remote.ssh.probe.unknown", language, message="ssh")
        return CheckItem("password", label, "warn", detail)
    ran = system.run(
        [
            ssh,
            "-o",
            "BatchMode=yes",
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "PreferredAuthentications=password,keyboard-interactive",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "LogLevel=ERROR",
            "-o",
            "ConnectTimeout=3",
            f"{user}@127.0.0.1",
            "true",
        ],
        timeout=15,
    )
    text = f"{ran.err}\n{ran.out}"
    denied = _DENIED.search(text)
    if denied is not None:
        methods = {m.strip() for m in denied.group(1).split(",")}
        if methods & {"password", "keyboard-interactive"}:
            return CheckItem("password", label, "fail", t("setup.remote.ssh.probe.on", language))
        if methods == {"publickey"}:
            return CheckItem("password", label, "ok", t("setup.remote.ssh.probe.off", language))
    last = next((line for line in reversed(text.strip().splitlines()) if line.strip()), "")
    message = last.strip()[:200] or f"exit code {ran.code}"
    detail = t("setup.remote.ssh.probe.unknown", language, message=message)
    return CheckItem("password", label, "warn", detail)


def _has_block(system: System, name: str) -> bool:
    text = system.read(system.home() / name)
    return text is not None and BLOCK in text.splitlines()


def _setup_action(system: System, language: str, kit: Kit, *, brew_missing: bool) -> Action:
    try:
        script = kit() / ENTRY
    except KitError as exc:
        return Action("other", t("setup.remote.kit_failed", language, error=exc))
    darwin = system.platform == "darwin"
    changes = [
        t(f"setup.remote.change.{key}", language, path=SSHD_CONF)
        for key in (
            ("darwin.brew", "darwin.dotfiles", "darwin.keepawake", "darwin.tailscale")
            + ("darwin.dropin", "darwin.remote_login")
            if darwin
            else ("linux.keys", "linux.dropin", "linux.packages", "linux.check")
            + ("linux.dotfiles", "linux.service")
        )
    ]
    text = t(
        "setup.remote.ssh.action.brew" if brew_missing else "setup.remote.ssh.action", language
    )
    return Action(
        "sudo",
        text,
        command=f"bash {shell_path(script, system.home())}",
        sudo=True,
        url=BREW_URL if brew_missing else None,
        changes=tuple(changes),
        script=str(script),
    )


def ssh_check(system: System, language: str, kit: Kit | None = None) -> CheckResult:
    """sshd, tau's drop-in, the password probe, mosh and tmux. With ``kit`` a failing check
    carries the one command to run (``kit`` may write the shipped copy first)."""
    if system.platform not in ("darwin", "linux"):
        return unsupported(language)
    darwin = system.platform == "darwin"
    user = system.user()
    items: list[CheckItem] = []
    listening = system.port_open(SSH_PORT)
    off = "setup.remote.ssh.sshd.off.darwin" if darwin else "setup.remote.ssh.sshd.off.linux"
    items.append(
        CheckItem(
            "sshd",
            t("setup.remote.ssh.sshd", language),
            "ok" if listening else "fail",
            t("setup.remote.ssh.sshd.on" if listening else off, language),
        )
    )
    dropin_label = t("setup.remote.ssh.dropin", language, path=SSHD_CONF)
    dropin = system.read(system.path(SSHD_CONF))
    if dropin is None:
        detail = t("setup.remote.ssh.dropin.missing", language)
        items.append(CheckItem("dropin", dropin_label, "fail", detail))
    else:
        problems = dropin_problems(dropin, user, language)
        if problems:
            items.append(CheckItem("dropin", dropin_label, "fail", "; ".join(problems)))
        else:
            detail = t("setup.remote.ssh.dropin.ok", language, user=user)
            items.append(CheckItem("dropin", dropin_label, "ok", detail))
            if dropin.strip() != render_template(user).strip():
                detail = t("setup.remote.ssh.template.differs", language)
                items.append(
                    CheckItem("template", t("setup.remote.ssh.template", language), "warn", detail)
                )
    main = system.read(system.path(SSHD_MAIN))
    if main is not None:
        included = _INCLUDE.search(main) is not None
        detail = "" if included else t("setup.remote.ssh.include.missing", language, path=SSHD_MAIN)
        items.append(
            CheckItem(
                "include",
                t("setup.remote.ssh.include", language),
                "ok" if included else "fail",
                detail,
            )
        )
    if listening and dropin is not None:
        items.append(_probe(system, user, language))
    missing_programs = False
    for program in ("mosh", "mosh-server", "tmux"):
        found = system.which(program)
        missing_programs |= found is None
        detail = found or t("setup.remote.ssh.program.missing", language)
        items.append(CheckItem(program, program, "ok" if found else "fail", detail))
    brew_missing = False
    if darwin:
        if missing_programs and system.which("brew") is None:
            brew_missing = True
            detail = t("setup.remote.ssh.brew.missing", language)
            items.append(CheckItem("brew", "Homebrew", "fail", detail))
        present = _has_block(system, ".zshenv")
        items.append(
            CheckItem(
                "zshenv",
                t("setup.remote.ssh.zshenv", language),
                "ok" if present else "fail",
                t("setup.remote.present" if present else "setup.remote.missing", language),
            )
        )
    present = _has_block(system, ".tmux.conf")
    items.append(
        CheckItem(
            "tmux_conf",
            t("setup.remote.ssh.tmux_conf", language),
            "ok" if present else "warn",
            t("setup.remote.present" if present else "setup.remote.missing", language),
        )
    )
    failed = [item for item in items if item.status == "fail"]
    if not failed:
        return CheckResult(
            True, t("setup.remote.ssh.ok", language), tuple(items), None, {"user": user}
        )
    action = _setup_action(system, language, kit, brew_missing=brew_missing) if kit else None
    values: dict[str, Any] = {"user": user}
    if action is not None and action.script:
        values["script"] = action.script
    summary = t("setup.remote.ssh.problems", language, count=len(failed))
    return CheckResult(False, summary, tuple(items), action, values)


# -- the phone ------------------------------------------------------------------------------------


def _keys(system: System) -> tuple[int, bool]:
    """``(keys in ~/.ssh/authorized_keys, writable by others)``: sshd ignores such a file."""
    path = system.home() / ".ssh" / "authorized_keys"
    text = system.read(path)
    if text is None:
        return 0, False
    count = sum(
        1 for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    )
    try:
        loose = bool(path.stat().st_mode & 0o022)
    except OSError:
        loose = False
    return count, loose


def phone_check(
    system: System, language: str, kit: Kit | None = None, ts: Tailscale | None = None
) -> CheckResult:
    """The values for Termius, from the live Tailscale state, and the key on this machine."""
    if system.platform not in ("darwin", "linux"):
        return unsupported(language)
    ts = ts if ts is not None else probe_tailscale(system)
    user = system.user()
    keys, loose = _keys(system)
    address = ts.address if ts.running else None
    items: list[CheckItem] = []
    host_label = t("setup.remote.phone.host", language)
    if address is None:
        detail = t("setup.remote.phone.host.none", language)
        items.append(CheckItem("host", host_label, "fail", detail))
    else:
        items.append(CheckItem("host", host_label, "info", address))
        if ts.ip and ts.ip != address:
            items.append(CheckItem("ip", t("setup.remote.phone.ip", language), "info", ts.ip))
    items.append(CheckItem("user", t("setup.remote.phone.user", language), "info", user))
    items.append(CheckItem("port", t("setup.remote.phone.port", language), "info", str(SSH_PORT)))
    key_label = t("setup.remote.phone.key", language)
    if loose:
        detail = t("setup.remote.phone.key.loose", language)
        items.append(CheckItem("key", key_label, "fail", detail))
    elif keys:
        items.append(
            CheckItem("key", key_label, "ok", t("setup.remote.phone.key.ok", language, count=keys))
        )
    else:
        items.append(
            CheckItem("key", key_label, "fail", t("setup.remote.phone.key.none", language))
        )
    on = t("setup.remote.phone.on", language)
    items.append(CheckItem("mosh", "Mosh", "info", on))
    attach = system.which(STARTUP) or (system.home() / ".local" / "bin" / STARTUP).exists()
    startup = t("setup.remote.phone.startup", language)
    if attach:
        items.append(CheckItem("startup", startup, "info", STARTUP))
    else:
        detail = t("setup.remote.phone.startup.missing", language)
        items.append(CheckItem("startup", startup, "warn", detail))
    detail = t("setup.remote.phone.tailscale.same", language)
    items.append(
        CheckItem("tailscale", t("setup.remote.phone.tailscale", language), "info", detail)
    )
    values = {
        "host": address,
        "ip": ts.ip,
        "user": user,
        "port": SSH_PORT,
        "mosh": True,
        "startup": STARTUP,
        "keys": keys,
    }
    if address is None:
        summary = t("setup.remote.phone.need_tailscale", language)
        return CheckResult(
            False, summary, tuple(items), _tailscale_action(system, ts, language), values
        )
    if loose:
        action = Action(
            "key",
            t("setup.remote.phone.key.chmod", language),
            command="chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys",
        )
        summary = t("setup.remote.phone.need_key", language)
        return CheckResult(False, summary, tuple(items), action, values)
    if not keys:
        action = None
        if kit is not None:
            try:
                script = kit() / ADD_KEY
            except KitError as exc:
                action = Action("other", t("setup.remote.kit_failed", language, error=exc))
            else:
                action = Action(
                    "key",
                    t("setup.remote.phone.key.action", language),
                    command=f"bash {shell_path(script, system.home())}",
                    script=str(script),
                )
        summary = t("setup.remote.phone.need_key", language)
        return CheckResult(False, summary, tuple(items), action, values)
    summary = t("setup.remote.phone.ok", language)
    return CheckResult(True, summary, tuple(items), None, values)


# -- everything -----------------------------------------------------------------------------------


def status_parts(system: System, language: str) -> list[tuple[str, CheckResult]]:
    """``[("tailscale", …), ("ssh", …), ("phone", …)]``, without actions and without writing
    anything: ``tau remote status`` is also what ``tau setup`` asks to know whether remote
    access is set up."""
    if system.platform not in ("darwin", "linux"):
        return [("remote", unsupported(language))]
    ts = probe_tailscale(system)
    return [
        ("tailscale", tailscale_result(system, ts, language)),
        ("ssh", ssh_check(system, language)),
        ("phone", phone_check(system, language, ts=ts)),
    ]


def status_result(system: System, language: str) -> CheckResult:
    parts = status_parts(system, language)
    items = tuple(
        CheckItem(f"{group}.{item.id}", item.label, item.status, item.detail)
        for group, result in parts
        for item in result.checks
    )
    ok = all(result.ok for _, result in parts)
    values = {group: dict(result.values) for group, result in parts}
    if ok:
        phone = values.get("phone", {})
        summary = t(
            "setup.remote.status.ready",
            language,
            user=phone.get("user", ""),
            host=phone.get("host", ""),
        )
    else:
        problems = sum(1 for item in items if item.status == "fail")
        summary = t("setup.remote.status.problems", language, count=problems)
    return CheckResult(ok, summary, items, None, values)
