"""``[component.web]`` and the paired-device registry (issue 178)."""

from __future__ import annotations

import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tau_core import Config
from tau_web.devices import PAIRING_MINUTES, DeviceError, DeviceRegistry
from tau_web.service import make_service
from tau_web.settings import WebConfigError, WebSettings, bind_allowed


@pytest.mark.parametrize(
    "bind", ["127.0.0.1", "::1", "localhost", "100.101.102.103", "fd7a:115c:a1e0::1"]
)
def test_loopback_and_tailnet_binds_are_allowed(bind: str) -> None:
    assert bind_allowed(bind)


@pytest.mark.parametrize("bind", ["0.0.0.0", "::", "192.168.1.20", "10.0.0.5", "8.8.8.8", "tau"])
def test_every_other_bind_is_refused(bind: str) -> None:
    assert not bind_allowed(bind)
    with pytest.raises(WebConfigError, match="loopback"):
        WebSettings.from_table({"bind": bind})


def test_a_hub_with_a_bad_bind_does_not_start_the_service(config: Config) -> None:
    toml = config.home / "tau.toml"
    toml.write_text(toml.read_text() + '\n[component.web]\nbind = "0.0.0.0"\n')
    with pytest.raises(WebConfigError):
        make_service(Config.load(config.home, env={"TAU_DATA_DIR": str(config.data_dir)}))


def test_settings_defaults_and_checks() -> None:
    settings = WebSettings.from_table({})
    assert (settings.bind, settings.port, settings.access_check) == ("127.0.0.1", 7878, False)
    table = {"hostnames": ["Hub.Tau.Example.com"], "access_aud": "aud", "access_team": "team"}
    settings = WebSettings.from_table(table)
    assert "hub.tau.example.com" in settings.allowed_hosts() and settings.access_check
    for bad in ({"port": 0}, {"port": "80"}, {"access_aud": "x"}, {"hostnames": "a"}):
        with pytest.raises(WebConfigError):
            WebSettings.from_table(bad)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def test_a_pairing_code_works_once_and_keeps_only_hashes(tmp_path: Path) -> None:
    registry = DeviceRegistry(tmp_path / "web")
    code = registry.start_pairing("phone")
    device, key = registry.pair(code)
    assert device.name == "phone" and device.id.startswith("web-")
    assert registry.verify(key) == device
    assert registry.verify("not the key") is None and registry.verify(None) is None
    with pytest.raises(DeviceError, match="not valid"):
        registry.pair(code)
    for path in (registry.devices_path, registry.pairing_path):
        text = path.read_text()
        assert code not in text and key not in text
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "key_hash" not in json.dumps(device.public())


def test_a_pairing_code_expires(tmp_path: Path) -> None:
    clock = Clock()
    registry = DeviceRegistry(tmp_path / "web", clock=clock)
    code = registry.start_pairing("laptop")
    clock.now += timedelta(minutes=PAIRING_MINUTES, seconds=1)
    with pytest.raises(DeviceError, match="expired"):
        registry.pair(code)
    with pytest.raises(DeviceError, match="not valid"):
        registry.pair(code)  # an expired code is gone too


def test_devices_can_be_listed_and_removed(tmp_path: Path) -> None:
    registry = DeviceRegistry(tmp_path / "web")
    phone, phone_key = registry.pair(registry.start_pairing("phone"))
    laptop, _ = registry.pair(registry.start_pairing("laptop"))
    assert [d.name for d in registry.list()] == ["phone", "laptop"]
    with pytest.raises(DeviceError, match="already paired"):
        registry.start_pairing("phone")
    assert registry.remove("phone") == phone
    assert registry.verify(phone_key) is None
    assert registry.remove(laptop.id).name == "laptop"
    with pytest.raises(DeviceError):
        registry.remove("phone")
    with pytest.raises(DeviceError, match="device name"):
        registry.start_pairing("bad/name")
