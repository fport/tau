"""Service definitions and the ``tau hub`` service commands, with FakeLaunchctl only."""

from __future__ import annotations

import json
import os
import plistlib
import re
import signal
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from tau_core import Config
from tau_core.cli import cli
from tau_core.hub import (
    LABEL,
    PLACEHOLDER_PATHS,
    FakeLaunchctl,
    HubFiles,
    HubLock,
    HubState,
    LaunchctlError,
    ServicePaths,
    render_plist,
    render_systemd_unit,
)
from tau_core.hub.state import timestamp, utc_now
from tau_core.hub.units import template_text

ROOT = Path(__file__).resolve().parents[3]
PERSONAL_PATH = re.compile("/" + "Users/|/" + "home/[a-z]")


def invoke(
    config: Config, tmp_path: Path, args: list[str], launchctl: FakeLaunchctl | None = None
) -> Result:
    env = {
        "TAU_HOME": str(config.home),
        "TAU_DATA_DIR": str(config.data_dir),
        "TAU_PROFILE": None,
        "TAU_ROLE": None,
        "TAU_HUB_PORT": None,
        "HOME": str(tmp_path / "userhome"),
    }
    obj = {"launchctl": launchctl} if launchctl is not None else None
    return CliRunner().invoke(cli, ["hub", *args], env=env, obj=obj)


def domain() -> str:
    return f"gui/{os.getuid()}"


# -- rendering -------------------------------------------------------------------------------


def test_plist_structure() -> None:
    paths = ServicePaths(
        python="/opt/tau/venv/bin/python",
        tau_home="/opt/tau",
        data_dir="/var/tau",
        hub_dir="/var/tau/hub",
        path="/usr/bin:/bin",
    )
    plist = plistlib.loads(render_plist(paths).encode("utf-8"))
    assert plist == {
        "Label": LABEL,
        "ProgramArguments": ["/opt/tau/venv/bin/python", "-m", "tau_core", "hub", "run"],
        "EnvironmentVariables": {
            "TAU_HOME": "/opt/tau",
            "TAU_DATA_DIR": "/var/tau",
            "TAU_ROLE": "hub",
            "PATH": "/usr/bin:/bin",
        },
        "WorkingDirectory": "/opt/tau",
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 3,
        "StandardOutPath": "/var/tau/hub/logs/launchd.out.log",
        "StandardErrorPath": "/var/tau/hub/logs/launchd.err.log",
    }


def test_plist_escapes_xml() -> None:
    odd = "/opt/a & b/<tau>"
    paths = ServicePaths(odd, odd, odd, f"{odd}/hub", "/bin")
    plist = plistlib.loads(render_plist(paths).encode("utf-8"))
    assert plist["ProgramArguments"][0] == odd
    assert plist["EnvironmentVariables"]["TAU_HOME"] == odd


def test_systemd_unit() -> None:
    unit = render_systemd_unit(PLACEHOLDER_PATHS)
    for line in (
        "ExecStart=/path/to/venv/bin/python -m tau_core hub run",
        "WorkingDirectory=/path/to/tau",
        "Environment=TAU_HOME=/path/to/tau",
        "Environment=TAU_DATA_DIR=/path/to/tau-data",
        "Environment=TAU_ROLE=hub",
        "Restart=on-failure",
        "RestartSec=3",
        "WantedBy=default.target",
    ):
        assert line in unit.splitlines()


def test_systemd_unit_quotes_spaces_and_escapes_specifiers() -> None:
    paths = ServicePaths(
        python="/opt/my venv/bin/python",
        tau_home="/opt/100%/tau",
        data_dir="/var/tau data",
        hub_dir="/var/tau data/hub",
        path="/bin",
    )
    lines = render_systemd_unit(paths).splitlines()
    assert 'ExecStart="/opt/my venv/bin/python" -m tau_core hub run' in lines
    assert "WorkingDirectory=/opt/100%%/tau" in lines
    assert "Environment=TAU_HOME=/opt/100%%/tau" in lines
    assert 'Environment="TAU_DATA_DIR=/var/tau data"' in lines


def test_committed_examples_are_the_templates_with_placeholders() -> None:
    services = ROOT / "infra" / "services"
    assert (services / "com.tau.hub.plist").read_text(encoding="utf-8") == render_plist(
        PLACEHOLDER_PATHS
    )
    assert (services / "tau-hub.service").read_text(encoding="utf-8") == render_systemd_unit(
        PLACEHOLDER_PATHS
    )


@pytest.mark.parametrize("name", ["com.tau.hub.plist", "tau-hub.service"])
def test_templates_hold_no_absolute_personal_path(name: str) -> None:
    text = template_text(name)
    assert not PERSONAL_PATH.search(text)
    assert "${python}" in text or "${exec_start}" in text
    for value in PLACEHOLDER_PATHS.__dict__.values():
        assert value not in text  # every path is a substitution, never baked in


def test_service_paths_from_config(config: Config) -> None:
    paths = ServicePaths.from_config(config, path="/bin")
    assert paths == ServicePaths(
        python=sys.executable,
        tau_home=str(config.home),
        data_dir=str(config.data_dir),
        hub_dir=str(config.hub_dir),
        path="/bin",
    )
    assert paths.log_dir == f"{config.hub_dir}/logs"


# -- install / uninstall ---------------------------------------------------------------------


def test_install_and_uninstall_with_fake_launchctl(config: Config, tmp_path: Path) -> None:
    fake = FakeLaunchctl()
    plist_path = tmp_path / "userhome" / "Library" / "LaunchAgents" / "com.tau.hub.plist"

    result = invoke(config, tmp_path, ["install"], fake)
    assert result.exit_code == 0, result.output
    assert f"launchd ajanı kuruldu: {plist_path}" in result.output
    assert fake.calls == [("bootstrap", domain(), plist_path)]
    assert fake.is_loaded(domain(), LABEL)
    plist = plistlib.loads(plist_path.read_bytes())
    assert plist["ProgramArguments"] == [sys.executable, "-m", "tau_core", "hub", "run"]
    assert plist["EnvironmentVariables"]["TAU_HOME"] == str(config.home)
    assert plist["EnvironmentVariables"]["TAU_DATA_DIR"] == str(config.data_dir)
    assert plist["EnvironmentVariables"]["TAU_ROLE"] == "hub"
    assert plist["KeepAlive"] == {"SuccessfulExit": False}
    assert (config.hub_dir / "logs").is_dir()  # launchd does not create the log directory
    assert oct(plist_path.stat().st_mode & 0o777) == oct(0o644)

    result = invoke(config, tmp_path, ["install"], fake)
    assert result.exit_code == 0, result.output
    assert "launchd ajanı yeniden kuruldu" in result.output
    assert fake.calls[1:] == [
        ("bootout", domain(), LABEL),
        ("bootstrap", domain(), plist_path),
    ]

    result = invoke(config, tmp_path, ["uninstall"], fake)
    assert result.exit_code == 0, result.output
    assert "launchd ajanı kaldırıldı." in result.output
    assert not plist_path.exists()
    assert not fake.is_loaded(domain(), LABEL)

    result = invoke(config, tmp_path, ["uninstall"], fake)
    assert result.exit_code == 0
    assert "launchd ajanı kurulu değildi." in result.output


def test_install_warns_about_a_hub_started_by_hand(config: Config, tmp_path: Path) -> None:
    with HubLock(config.hub_dir / "hub.lock"):
        result = invoke(config, tmp_path, ["install"], FakeLaunchctl())
    assert result.exit_code == 0, result.output
    assert f"elle başlatılmış bir hub çalışıyor (pid {os.getpid()})" in result.output


def test_install_reports_launchctl_failure(config: Config, tmp_path: Path) -> None:
    class Failing(FakeLaunchctl):
        def bootstrap(self, domain: str, plist: Path) -> None:
            raise LaunchctlError("launchctl bootstrap başarısız: 5: Input/output error")

    result = invoke(config, tmp_path, ["install"], Failing())
    assert result.exit_code == 1
    assert "launchd ajanı kurulamadı: launchctl bootstrap başarısız" in result.output
    assert "Traceback" not in result.output


def test_install_needs_launchd(
    config: Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    for command in ("install", "uninstall"):
        result = invoke(config, tmp_path, [command])
        assert result.exit_code == 2
        assert "launchd yalnızca macOS'ta var. Linux'ta systemd için: tau hub systemd-unit" in (
            result.output
        )


def test_systemd_unit_command(config: Config, tmp_path: Path) -> None:
    result = invoke(config, tmp_path, ["systemd-unit", "--python", "/opt/venv/bin/python"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert "ExecStart=/opt/venv/bin/python -m tau_core hub run" in lines
    assert f"Environment=TAU_HOME={config.home}" in lines
    assert "Environment=TAU_ROLE=hub" in lines
    assert "Restart=on-failure" in lines


# -- status / stop ---------------------------------------------------------------------------


def test_status_when_never_started(config: Config, tmp_path: Path) -> None:
    result = invoke(config, tmp_path, ["status"], FakeLaunchctl())
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        "tau hub çalışmıyor.",
        "  Son çökme: yok",
        "  launchd: kurulu değil (kurmak için: tau hub install)",
    ]


def test_status_after_an_unclean_exit_and_a_crash(config: Config, tmp_path: Path) -> None:
    files = HubFiles(config.hub_dir)
    files.write_state(
        HubState(
            pid=4242,
            started_at="2026-09-29T10:00:00+00:00",
            heartbeat_at="2026-09-29T11:59:55+00:00",
            version="0.1.0",
            role="hub",
            profile="ev",
            last_crash=None,
        )
    )
    files.last_crash.write_text(
        json.dumps(
            {
                "pid": 4100,
                "started_at": "2026-09-28T10:00:00+00:00",
                "last_heartbeat_at": "2026-09-28T11:00:00+00:00",
                "reason": "RuntimeError: boom",
                "detected_at": "2026-09-28T11:00:03+00:00",
            }
        )
    )
    fake = FakeLaunchctl()
    fake.loaded[f"{domain()}/{LABEL}"] = Path("x")
    result = invoke(config, tmp_path, ["status"], fake)
    assert result.exit_code == 0, result.output
    out = result.output
    assert out.startswith("tau hub çalışmıyor.\n")
    assert "  Son çalışma temiz kapanmadı (pid 4242, son nabız " in out
    assert "bir sonraki başlatma bunu çökme olarak kaydeder." in out
    assert "  Son çökme: pid 4100, son nabız " in out
    assert out.count("RuntimeError: boom") == 1
    assert f"  launchd: kurulu ve yüklü ({LABEL})" in out

    result = invoke(config, tmp_path, ["status", "--json"], fake)
    info = json.loads(result.output)
    assert info["running"] is False
    assert info["state"]["pid"] == 4242
    assert info["last_crash"]["reason"] == "RuntimeError: boom"
    assert info["launchd"]["loaded"] is True
    assert info["control_url"] == "http://127.0.0.1:7877"


def test_status_while_running(config: Config, tmp_path: Path) -> None:
    files = HubFiles(config.hub_dir)
    with HubLock(files.lock):
        files.write_state(
            HubState(
                pid=os.getpid(),
                started_at=timestamp(utc_now() - timedelta(hours=1)),
                heartbeat_at=timestamp(utc_now() - timedelta(minutes=5)),
                version="0.1.0",
                role="hub",
                profile="ev",
                last_crash=None,
            )
        )
        result = invoke(config, tmp_path, ["status"], FakeLaunchctl())
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == f"tau hub çalışıyor (pid {os.getpid()})."
    assert lines[1] == "  Profil: ev · Rol: hub · Sürüm: 0.1.0"
    assert lines[3].endswith("— gecikmiş; hub yanıt vermiyor olabilir")  # an old heartbeat
    assert "  Kontrol API: http://127.0.0.1:7877" in lines


def test_stop_when_not_running(config: Config, tmp_path: Path) -> None:
    fake = FakeLaunchctl()
    result = invoke(config, tmp_path, ["stop"], fake)
    assert result.exit_code == 0
    assert result.output.strip() == "tau hub çalışmıyor."
    assert fake.killed == []


def test_stop_sends_sigterm_and_waits(config: Config, tmp_path: Path) -> None:
    lock = HubLock(config.hub_dir / "hub.lock")
    lock.acquire()
    fake = FakeLaunchctl(on_kill=lambda pid, sig: lock.release())  # plays the hub stopping
    try:
        result = invoke(config, tmp_path, ["stop"], fake)
    finally:
        lock.release()
    assert result.exit_code == 0, result.output
    assert fake.killed == [(os.getpid(), signal.SIGTERM)]
    assert result.output.splitlines() == [
        f"Durdurma sinyali gönderildi (pid {os.getpid()}).",
        "tau hub durdu.",
    ]


def test_stop_times_out(config: Config, tmp_path: Path) -> None:
    fake = FakeLaunchctl()
    with HubLock(config.hub_dir / "hub.lock"):
        result = invoke(config, tmp_path, ["stop", "--timeout", "0.2"], fake)
    assert result.exit_code == 1
    assert "tau hub 0.2 sn içinde durmadı." in result.output


def test_hub_commands_without_config_exit_2(tmp_path: Path) -> None:
    env = {"TAU_HOME": str(tmp_path / "empty"), "TAU_DATA_DIR": str(tmp_path / "data")}
    for command in ("run", "status", "stop", "install", "systemd-unit"):
        result = CliRunner().invoke(
            cli, ["hub", command], env=env, obj={"launchctl": FakeLaunchctl()}
        )
        assert result.exit_code == 2, (command, result.output)
        assert "Yapılandırma dosyası bulunamadı" in result.output
