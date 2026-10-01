"""The remote access checks (issue 173) against a fake system.

No test runs ``tailscale``, ``ssh``, ``sudo`` or a kit script, reads the real ``/etc/ssh`` or
touches the owner's home: :class:`FakeSystem` answers from fields and temporary directories."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from remote_fakes import HOST, IP, LOGGED_OUT, USER, FakeSystem
from tau_core.remote.checks import (
    MAC_APP_CLI,
    SSHD_CONF,
    allow_users_restricted,
    dropin_problems,
    phone_check,
    probe_tailscale,
    render_template,
    ssh_check,
    status_parts,
    status_result,
    tailscale_check,
)
from tau_core.remote.scripts import kit_dir, kit_files
from tau_core.setup.checks import CheckResult, parse_check
from tau_core.setup.state import data_dir


def statuses(result: CheckResult) -> dict[str, str]:
    return {item.id: item.status for item in result.checks}


def kit(system: FakeSystem):  # the CLI's kit resolver, over the fake
    from tau_core.config import resolve_home

    def build() -> Path:
        home = resolve_home(None, system.environ)
        return kit_dir(system, data_dir(home, system.environ))

    return build


def never_ran_anything_but_probes(system: FakeSystem) -> None:
    """Only ``tailscale status --json`` and the ssh probe ever run; never sudo or a script."""
    for argv in system.runs:
        assert "sudo" not in argv
        assert not any(word.endswith(".sh") for word in argv)
        assert argv[1:] == ["status", "--json"] or argv[0].endswith("/ssh")


# -- Tailscale -------------------------------------------------------------------------------------


def test_tailscale_in_the_app_bundle_on_macos(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path)
    system.app()
    ts = probe_tailscale(system)
    assert ts.shown == MAC_APP_CLI and ts.app and ts.running
    assert (ts.host, ts.ip, ts.address) == (HOST, IP, HOST)
    result = tailscale_check(system, "en")
    assert result.ok and result.action is None
    assert statuses(result) == {"installed": "ok", "connected": "ok"}
    assert result.checks[1].detail == f"{HOST} · {IP}"
    assert result.summary == f"Tailscale is connected as {HOST}"
    assert result.values == {
        "cli": MAC_APP_CLI,
        "state": "Running",
        "host": HOST,
        "ip": IP,
        "magicdns": True,
    }
    assert system.tailscale_runs() == [[str(system.path(MAC_APP_CLI)), "status", "--json"]] * 2


def test_tailscale_on_path_wins(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path, programs=("tailscale",))
    system.app()
    assert probe_tailscale(system).shown == "/fake/bin/tailscale"


def test_tailscale_missing_on_macos_offers_the_download_page(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path)
    result = tailscale_check(system, "en")
    assert not result.ok and statuses(result) == {"installed": "fail"}
    assert result.action is not None
    assert result.action.kind == "install" and result.action.command is None
    assert result.action.url == "https://tailscale.com/download/mac"
    assert "Mac App Store" in result.action.text
    assert system.runs == []


def test_tailscale_missing_on_linux_shows_the_install_script(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path, platform="linux")
    result = tailscale_check(system, "en")
    action = result.action
    assert action is not None and action.sudo
    assert action.command == (
        "curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up"
    )
    assert action.url == "https://tailscale.com/download/linux"
    assert system.runs == []  # shown, never run


@pytest.mark.parametrize(
    ("platform", "app", "command", "sudo"),
    [
        ("darwin", True, "open -a Tailscale", False),
        ("darwin", False, "tailscale up", False),
        ("linux", False, "sudo tailscale up", True),
    ],
)
def test_logged_out(tmp_path: Path, platform: str, app: bool, command: str, sudo: bool) -> None:
    system = FakeSystem(tmp_path, platform=platform, programs=("tailscale",), tailscale=LOGGED_OUT)
    if app:
        system.app()
    result = tailscale_check(system, "en")
    assert not result.ok
    assert statuses(result) == {"installed": "ok", "connected": "fail"}
    assert result.checks[1].detail == "logged out"
    assert result.action is not None and result.action.kind == "login"
    assert (result.action.command, result.action.sudo) == (command, sudo)


def test_a_linux_daemon_that_does_not_answer(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path, platform="linux", programs=("tailscale",), tailscale=None)
    system.tailscale_code = 1
    result = tailscale_check(system, "en")
    assert result.checks[1].detail.startswith("not running")
    assert result.action is not None
    assert result.action.command == "sudo systemctl enable --now tailscaled && sudo tailscale up"


def test_a_machine_waiting_for_approval(tmp_path: Path) -> None:
    system = FakeSystem(
        tmp_path, programs=("tailscale",), tailscale={"BackendState": "NeedsMachineAuth"}
    )
    result = tailscale_check(system, "tr")
    assert result.checks[1].detail == "yönetici konsolunda onay bekliyor"
    assert result.action is not None and result.action.command is None
    assert result.action.url == "https://login.tailscale.com/admin/machines"


def test_without_magicdns_the_address_is_the_ip(tmp_path: Path) -> None:
    data = {
        "BackendState": "Running",
        "Self": {"DNSName": f"{HOST}.", "TailscaleIPs": ["fd7a:115c:a1e0::1", IP]},
        "CurrentTailnet": {"MagicDNSEnabled": False},
    }
    system = FakeSystem(tmp_path, programs=("tailscale",), tailscale=data)
    ts = probe_tailscale(system)
    assert ts.address == IP and ts.running
    phone = phone_check(system, "en", ts=ts)
    assert phone.values["host"] == IP


# -- the drop-in ---------------------------------------------------------------------------------


def test_the_shipped_template_passes() -> None:
    text = render_template(USER)
    assert f"AllowUsers {USER}@100.64.0.0/10 {USER}@fd7a:115c:a1e0::/48" in text
    assert dropin_problems(text, USER, "en") == []


@pytest.mark.parametrize(
    ("entry", "restricted"),
    [
        (f"{USER}@100.64.0.0/10", True),
        (f"{USER}@100.100.0.0/16", True),
        (f"{USER}@{IP}", True),
        (f"{USER}@fd7a:115c:a1e0::/48", True),
        (f"{USER}@127.0.0.1", True),
        (f"{USER}@::1", True),
        (USER, False),
        (f"{USER}@*", False),
        (f"{USER}@192.168.1.0/24", False),
        (f"{USER}@0.0.0.0/0", False),
        (f"{USER}@my-mac.local", False),
        (f"bob@{IP}", False),
    ],
)
def test_allow_users(entry: str, restricted: bool) -> None:
    assert allow_users_restricted(entry, USER) is restricted


def test_dropin_problems() -> None:
    assert dropin_problems("", USER, "en") == [
        "password login is not off",
        "keyboard-interactive login is not off",
        "no AllowUsers line",
    ]
    loose = (
        "PasswordAuthentication=no\nChallengeResponseAuthentication no\n"
        f"AllowUsers {USER}@100.64.0.0/10\nAllowUsers {USER}@*  # added later\n"
    )
    assert dropin_problems(loose, USER, "en") == [
        f"AllowUsers also lets in {USER}@*; only {USER} from the tailnet and localhost belong there"
    ]
    # sshd takes the first value: a later "no" does not undo an earlier "yes".
    first = (
        "PasswordAuthentication yes\nPasswordAuthentication no\n"
        f"KbdInteractiveAuthentication no\nAllowUsers {USER}@::1\n"
    )
    assert dropin_problems(first, USER, "en") == ["password login is not off"]
    # A Match block is not the global section.
    matched = (
        f"KbdInteractiveAuthentication no\nAllowUsers {USER}@::1\n"
        "Match Address 100.64.0.0/10\n  PasswordAuthentication no\n"
    )
    assert dropin_problems(matched, USER, "en") == ["password login is not off"]


# -- SSH and mosh ----------------------------------------------------------------------------------


def test_ssh_ready_on_macos(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path).ready()
    result = ssh_check(system, "en", kit=kit(system))
    assert result.ok and result.action is None, result.checks
    assert statuses(result) == {
        "sshd": "ok",
        "dropin": "ok",
        "include": "ok",
        "password": "ok",
        "mosh": "ok",
        "mosh-server": "ok",
        "tmux": "ok",
        "zshenv": "ok",
        "tmux_conf": "ok",
    }
    [probe] = system.ssh_runs()
    assert "BatchMode=yes" in probe and "PubkeyAuthentication=no" in probe
    assert probe[-2:] == [f"{USER}@127.0.0.1", "true"]
    assert not (system.homedir / ".local" / "share" / "tau" / "remote").exists()
    never_ran_anything_but_probes(system)


def test_a_fresh_mac_gets_the_one_command_and_the_kit(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path, programs=("ssh", "brew"))
    result = ssh_check(system, "en", kit=kit(system))
    assert not result.ok
    assert statuses(result) == {
        "sshd": "fail",
        "dropin": "fail",
        "mosh": "fail",
        "mosh-server": "fail",
        "tmux": "fail",
        "zshenv": "fail",
        "tmux_conf": "warn",
    }
    assert result.summary == "6 problem(s) with SSH, mosh or tmux"
    action = result.action
    assert action is not None and action.kind == "sudo" and action.sudo
    assert action.command == "bash ~/.local/share/tau/remote/setup-all.sh"
    assert action.url is None
    assert "not with sudo" in action.text and "tau never runs it" in action.text
    assert len(action.changes) == 6
    assert any(SSHD_CONF in change and "sshd -t" in change for change in action.changes)
    kit_path = system.homedir / ".local" / "share" / "tau" / "remote"
    assert action.script == str(kit_path / "setup-all.sh")
    assert result.values == {"user": USER, "script": action.script}
    # The shipped kit was written where the command points, the scripts executable.
    written = {
        p.relative_to(kit_path).as_posix(): p.read_bytes()
        for p in kit_path.rglob("*")
        if p.is_file()
    }
    assert written == kit_files()
    assert stat.S_IMODE((kit_path / "setup-all.sh").stat().st_mode) == 0o755
    assert stat.S_IMODE((kit_path / "bin" / "tau-attach").stat().st_mode) == 0o755
    assert stat.S_IMODE((kit_path / "config.env").stat().st_mode) == 0o644
    assert system.ssh_runs() == []  # no probe without sshd and the drop-in
    never_ran_anything_but_probes(system)


def test_a_mac_without_homebrew_is_told_to_install_it(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path)
    result = ssh_check(system, "en", kit=kit(system))
    assert statuses(result)["brew"] == "fail"
    assert result.action is not None and result.action.url == "https://brew.sh"
    assert result.action.text.startswith("Install Homebrew first")


def test_a_checkout_shows_its_own_infra_remote(tmp_path: Path) -> None:
    checkout = tmp_path / "user" / "code" / "tau" / "infra" / "remote"
    system = FakeSystem(tmp_path, checkout=checkout)
    result = ssh_check(system, "en", kit=kit(system))
    assert result.action is not None
    assert result.action.command == "bash ~/code/tau/infra/remote/setup-all.sh"
    assert not (system.homedir / ".local" / "share" / "tau").exists()


def test_linux_needs_no_zshenv_and_says_what_linux_changes(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path, platform="linux", environ={"TAU_DATA_DIR": str(tmp_path / "d")})
    result = ssh_check(system, "tr", kit=kit(system))
    assert "zshenv" not in statuses(result) and "brew" not in statuses(result)
    assert result.checks[0].detail == "22 numaralı portta çalışmıyor"
    action = result.action
    assert action is not None
    assert action.command == f"bash {tmp_path / 'd' / 'remote' / 'setup-all.sh'}"
    assert len(action.changes) == 6 and "openssh-server" in action.changes[2]
    assert "kendini dışarıda bırakamazsın" in action.changes[0]


def test_a_weak_dropin_and_a_password_probe_fail(tmp_path: Path) -> None:
    system = FakeSystem(
        tmp_path,
        probe=f"{USER}@127.0.0.1: Permission denied (publickey,password,keyboard-interactive).",
    ).ready()
    system.harden(
        f"PasswordAuthentication yes\nKbdInteractiveAuthentication no\nAllowUsers {USER}\n"
    )
    result = ssh_check(system, "en", kit=kit(system))
    assert not result.ok
    dropin = next(item for item in result.checks if item.id == "dropin")
    assert dropin.status == "fail"
    assert "password login is not off" in dropin.detail and f"lets in {USER};" in dropin.detail
    probe = next(item for item in result.checks if item.id == "password")
    assert (probe.status, probe.detail) == ("fail", "still offered by sshd")


def test_a_changed_but_safe_dropin_only_warns(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path, probe="ssh: connect to host 127.0.0.1 port 22: timed out").ready()
    system.harden(render_template(USER) + "\nMaxSessions 4\n")
    result = ssh_check(system, "en", kit=kit(system))
    assert result.ok
    assert statuses(result)["template"] == "warn"
    probe = next(item for item in result.checks if item.id == "password")
    assert probe.status == "warn" and "timed out" in probe.detail


def test_a_main_config_without_include_ignores_the_dropin(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path).ready()
    system.write("/etc/ssh/sshd_config", "UsePAM yes\n# Include /etc/ssh/sshd_config.d/*\n")
    result = ssh_check(system, "en", kit=kit(system))
    assert not result.ok and statuses(result)["include"] == "fail"


# -- the phone -------------------------------------------------------------------------------------


def test_the_phone_values(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path).ready()
    system.app()
    result = phone_check(system, "en", kit=kit(system))
    assert result.ok and result.action is None
    assert result.summary == "In Termius, add a host with these values"
    assert result.values == {
        "host": HOST,
        "ip": IP,
        "user": USER,
        "port": 22,
        "mosh": True,
        "startup": "tau-attach",
        "keys": 1,
    }
    lines = {item.id: (item.status, item.detail) for item in result.checks}
    assert lines["host"] == ("info", HOST) and lines["ip"] == ("info", IP)
    assert lines["user"] == ("info", USER) and lines["port"] == ("info", "22")
    assert lines["key"][0] == "ok" and lines["startup"] == ("info", "tau-attach")


def test_the_phone_without_a_key_gets_add_key(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path, programs=("tailscale",))
    result = phone_check(system, "en", kit=kit(system))
    assert not result.ok
    assert result.action is not None and result.action.kind == "key"
    assert result.action.command == "bash ~/.local/share/tau/remote/add-key.sh"
    assert not result.action.sudo and "Generate Key" in result.action.text
    assert next(i for i in result.checks if i.id == "startup").status == "warn"


def test_keys_others_can_write_are_ignored_by_sshd(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path, programs=("tailscale",))
    system.key(mode=0o666)
    result = phone_check(system, "en", kit=kit(system))
    assert result.action is not None
    assert result.action.command == "chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys"


def test_the_phone_before_tailscale_points_to_it(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path, platform="linux", tailscale=None)
    system.key()
    result = phone_check(system, "en", kit=kit(system))
    assert not result.ok and result.values["host"] is None
    assert result.checks[0].status == "fail"
    assert result.action is not None and result.action.kind == "install"


# -- everything ------------------------------------------------------------------------------------


def test_status_when_ready(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path).ready()
    result = status_result(system, "en")
    assert result.ok and result.action is None
    assert result.summary == f"Remote access is ready: ssh {USER}@{HOST}"
    assert [group for group, _ in status_parts(system, "en")] == ["tailscale", "ssh", "phone"]
    assert {item.id.split(".")[0] for item in result.checks} == {"tailscale", "ssh", "phone"}
    assert set(result.values) == {"tailscale", "ssh", "phone"}
    assert parse_check(result.dumps()) == result
    never_ran_anything_but_probes(system)


def test_status_counts_problems_and_writes_nothing(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path, tailscale=LOGGED_OUT, programs=("tailscale", "ssh", "brew"))
    result = status_result(system, "en")
    assert not result.ok and result.action is None
    assert result.summary.startswith("9 problem(s).")
    assert not (system.homedir / ".local").exists()


def test_other_platforms(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path, platform="win32")
    for result in (
        tailscale_check(system, "en"),
        ssh_check(system, "en"),
        phone_check(system, "en"),
    ):
        assert not result.ok and result.summary.startswith("Remote access is set up on macOS")
    assert system.runs == []
