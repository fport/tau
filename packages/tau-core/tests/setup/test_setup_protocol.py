"""The JSON mode of ``tau setup``: the contract with the Mac app (docs/reference/setup.md).

Every stream is JSON lines and ends with exactly one ``done`` or ``error``; inputs come on
stdin, secrets go to ``.env`` and never reach argv or the output."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from setup_fakes import TAU, UV, FakeHost
from tau_core.builder import KeyCheck
from tau_core.cli import cli
from tau_core.setup import parse_catalog
from tau_core.setup.protocol import run_json

KEY = "sk-test-not-a-real-key-0123456789"


def events(host: FakeHost, args: list[str]) -> list[dict[str, Any]]:
    result = CliRunner().invoke(cli, ["setup", *args], obj={"setup_host": host}, prog_name="tau")
    lines = [line for line in result.output.splitlines() if line.strip()]
    parsed = [json.loads(line) for line in lines]
    assert parsed, result.output
    assert parsed[-1]["event"] in ("done", "error")
    assert [e["event"] for e in parsed[:-1] if e["event"] in ("done", "error")] == []
    expected = 0 if parsed[-1]["event"] == "done" and parsed[-1].get("ok") else 1
    assert result.exit_code == expected, result.output
    return parsed


def status(host: FakeHost) -> dict[str, Any]:
    result = CliRunner().invoke(
        cli, ["setup", "status", "--json"], obj={"setup_host": host}, prog_name="tau"
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


# -- status ----------------------------------------------------------------------------------------


def test_status_json(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-tui": "0.4.0"})
    payload = status(host)
    assert payload["protocol"] == 1 and payload["version"] == "0.4.0"
    assert payload["platform"] == "darwin" and payload["language"] == "en"
    assert payload["install"] == {"mode": "uv-tool", "can_install": True}
    assert payload["config"] is False and payload["about"] is False and payload["ssh"] is False
    assert payload["core_steps"] == ["init", "about", "doctor"]
    features = {f["id"]: f for f in payload["features"]}
    assert list(features) == [
        "tui",
        "app",
        "sub",
        "telegram",
        "remote",
        "guard",
        "net",
        "autostart",
        "cloud",
    ]
    tui = features["tui"]
    assert tui["installed"] and tui["configured"] and tui["state"] == "done"
    assert tui["version"] == "0.4.0" and tui["lockstep"] and tui["default"]
    guard = features["guard"]
    assert guard["state"] == "missing" and guard["permissions"] == [
        {"id": "camera", "label": "camera"}
    ]
    assert [s["id"] for s in guard["steps"]] == ["doctor", "setup", "restart"]
    setup_step = guard["steps"][1]
    assert setup_step["interactive"] and setup_step["local_only"]
    assert setup_step["command"] == ["guard", "setup"]
    net_init = features["net"]["steps"][0]
    assert net_init["inputs"] == [
        {
            "name": "name",
            "label": "Display name on your card (e.g. Alice's tau)",
            "secret": False,
            "required": False,
            "default": "",
        }
    ]
    assert features["autostart"]["default"] is True
    assert features["guard"]["docs"] == "https://docs.tau.getporti.com/guides/guard/"


def test_status_json_in_turkish_on_linux_outside_a_uv_tool(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, platform="linux", uv_tool=False, environ={"TAU_LANG": "tr"})
    payload = status(host)
    assert payload["language"] == "tr" and payload["platform_label"] == "Linux"
    assert payload["install"] == {"mode": "environment", "can_install": False}
    features = {f["id"]: f for f in payload["features"]}
    guard = features["guard"]
    assert guard["available"] is False and guard["state"] == "unavailable"
    assert guard["unavailable_reason"].startswith("yalnızca macOS")
    assert guard["steps"] == []
    assert features["tui"]["label"] == "Terminal arayüzü"
    assert features["autostart"]["default"] is False
    assert [s["id"] for s in features["autostart"]["steps"]] == ["systemd"]


def test_the_app_is_found_in_applications(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    (host.root / "Applications" / "tau.app").mkdir(parents=True)
    features = {f["id"]: f for f in status(host)["features"]}
    assert features["app"]["state"] == "done"


# -- install ---------------------------------------------------------------------------------------


def test_install_json_streams_the_uv_output(tmp_path: Path) -> None:
    host = FakeHost(
        tmp_path,
        installed={"tau-tui": "0.4.0"},
        output={(UV,): ["Resolved 42 packages", "Installed 2 packages"]},
    )
    stream = events(host, ["install", "--features", "cloud", "--json"])
    assert stream[0] == {
        "event": "progress",
        "phase": "plan",
        "features": ["net", "cloud"],
        "added": ["tau-net", "tau-cloud"],
        "packages": ["tau-tui", "tau-net", "tau-cloud"],
    }
    assert stream[1]["phase"] == "install"
    assert stream[1]["argv"] == [
        UV,
        "tool",
        "install",
        "--force",
        "tau-core==0.4.0",
        "--with",
        "tau-tui==0.4.0",
        "--with",
        "tau-net",
        "--with",
        "tau-cloud",
    ]
    assert stream[2:4] == [
        {"event": "log", "line": "Resolved 42 packages"},
        {"event": "log", "line": "Installed 2 packages"},
    ]
    assert stream[-1] == {
        "event": "done",
        "ok": True,
        "installed": ["tau-net", "tau-cloud"],
        "changed": True,
    }
    assert host.runs == [(stream[1]["argv"], True)]
    assert host.execs == []  # the app starts a new tau for the next call


def test_install_json_with_nothing_to_do(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-tui": "0.4.0"})
    stream = events(host, ["install", "--features", "tui,remote", "--json"])
    assert stream[-1] == {"event": "done", "ok": True, "installed": [], "changed": False}
    assert host.runs == []


@pytest.mark.parametrize(
    ("kwargs", "features", "code"),
    [
        ({"uv_tool": False}, "sub", "not_uv_tool"),
        ({"programs": ()}, "sub", "uv_missing"),
        ({}, "teleport", "unknown_feature"),
        ({"platform": "linux"}, "guard", "unavailable"),
        ({"codes": {(UV,): 2}}, "sub", "install_failed"),
    ],
)
def test_install_json_errors(
    tmp_path: Path, kwargs: dict[str, Any], features: str, code: str
) -> None:
    host = FakeHost(tmp_path, **kwargs)
    stream = events(host, ["install", "--features", features, "--json"])
    assert stream[-1]["event"] == "error" and stream[-1]["code"] == code
    assert stream[-1]["message"]


# -- run a feature ---------------------------------------------------------------------------------


def test_run_guard_reports_the_enrollment_as_needs_ui(tmp_path: Path) -> None:
    host = FakeHost(
        tmp_path,
        installed={"tau-guard": "0.4.0"},
        codes={("guard", "doctor"): 1},
        output={("guard", "doctor"): ["fail sface: not downloaded yet"]},
    )
    host.write_config()
    stream = events(host, ["run", "guard", "--json"])
    kinds = [e["event"] for e in stream]
    assert kinds == ["progress", "log", "progress", "needs_ui", "done"]
    assert stream[0]["status"] == "running" and stream[0]["command"] == ["guard", "doctor"]
    assert stream[1] == {
        "event": "log",
        "feature": "guard",
        "step": "doctor",
        "line": "fail sface: not downloaded yet",
    }
    assert stream[2]["status"] == "done" and stream[2]["reason"] == "advisory"
    assert stream[3] == {
        "event": "needs_ui",
        "feature": "guard",
        "step": "setup",
        "label": "Enroll your face and switch the guard on",
        "command": ["guard", "setup"],
        "argv": [TAU, "guard", "setup"],
    }
    assert stream[4]["ok"] is True and stream[4]["pending"] == ["restart"]
    assert stream[4]["configured"] is False
    assert host.tau_runs() == [["guard", "doctor"]]
    # the app ran `tau guard setup` itself; then the rest
    host.stdin = json.dumps({"steps": ["restart"]})
    stream = events(host, ["run", "guard", "--json"])
    assert stream[0]["status"] == "info" and "Restart the hub" in stream[0]["label"]
    assert stream[-1]["pending"] == []


def test_run_net_takes_its_inputs_on_stdin(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-net": "0.1.0"})
    host.write_config()
    host.stdin = json.dumps({"inputs": {"name": "Alice's tau"}})
    stream = events(host, ["run", "net", "--json"])
    assert host.tau_runs() == [["net", "init", "--name", "Alice's tau"]]
    statuses = [(e.get("step"), e.get("status")) for e in stream if e["event"] == "progress"]
    assert statuses == [("init", "running"), ("init", "done"), ("spine", "info")]
    host.runs.clear()
    host.stdin = json.dumps({"steps": ["universe", "spine-init"], "inputs": {"owner": "Alice"}})
    stream = events(host, ["run", "net", "--json"])
    assert host.tau_runs() == [
        ["net", "spine", "init", str(host.user / "tau-spine")],
        ["net", "universe", "join", "--owner", "Alice"],
    ]
    assert not [e for e in stream if e.get("status") == "skipped"]


@pytest.mark.parametrize(
    ("stdin", "code"),
    [
        ("not json", "bad_input"),
        ("[1, 2]", "bad_input"),
        ('{"inputs": {"name": 3}}', "bad_input"),
        ('{"inputs": {"password": "x"}}', "bad_input"),
        ('{"surprise": true}', "bad_input"),
        ('{"steps": ["warp"]}', "unknown_step"),
    ],
)
def test_run_refuses_bad_input(tmp_path: Path, stdin: str, code: str) -> None:
    host = FakeHost(tmp_path, installed={"tau-net": "0.1.0"}, stdin=stdin)
    stream = events(host, ["run", "net", "--json"])
    assert stream == [stream[-1]] and stream[-1]["code"] == code
    assert host.runs == []


def test_run_a_feature_that_is_not_installed(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    stream = events(host, ["run", "net", "--json"])
    assert stream[-1]["code"] == "not_installed"
    assert "tau setup install --features net" in stream[-1]["message"]


def test_a_secret_input_goes_to_dotenv_never_argv(tmp_path: Path) -> None:
    catalog = parse_catalog(
        """
schema = 1
docs = "https://docs.example.com/"

[[feature]]
id = "bot"
label = "setup.feature.telegram"
description = "setup.feature.telegram.about"
platforms = ["darwin", "linux"]

[[feature.step]]
id = "pair"
label = "setup.step.telegram.pair"
command = ["telegram", "pair"]

[[feature.step.input]]
name = "token"
label = "setup.input.owner"
secret = true
env = "TELEGRAM_BOT_TOKEN"
required = true
"""
    )
    host = FakeHost(tmp_path, stdin=json.dumps({"inputs": {"token": "123:not-a-real-token"}}))
    host.write_config()
    lines: list[str] = []
    code = run_json(
        host, catalog, "bot", lambda event, **f: lines.append(json.dumps({"event": event, **f}))
    )
    assert code == 0
    assert host.tau_runs() == [["telegram", "pair"]]
    dotenv = host.home / ".env"
    assert dotenv.read_text(encoding="utf-8") == "TELEGRAM_BOT_TOKEN=123:not-a-real-token\n"
    assert stat.S_IMODE(dotenv.stat().st_mode) == 0o600
    assert not any("not-a-real-token" in line for line in lines)
    assert not any("not-a-real-token" in " ".join(argv) for argv, _ in host.runs)
    # without the required secret the step does not run
    host.runs.clear()
    host.stdin = "{}"
    lines.clear()
    assert run_json(host, catalog, "bot", lambda event, **f: lines.append(json.dumps(f))) == 0
    assert host.runs == [] and "no_input" in lines[0]


# -- the core steps --------------------------------------------------------------------------------


def test_run_init_with_a_key_on_stdin(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, stdin=json.dumps({"inputs": {"provider": "anthropic", "key": KEY}}))
    host.effects[("init",)] = host.init_effect
    stream = events(host, ["run", "init", "--json"])
    assert host.key_calls == [("anthropic", KEY)]
    dotenv = host.home / ".env"
    assert dotenv.read_text(encoding="utf-8") == f"ANTHROPIC_API_KEY={KEY}\n"
    assert stat.S_IMODE(dotenv.stat().st_mode) == 0o600
    assert host.tau_runs() == [["init", "--yes", "--language", "en", "--provider", "anthropic"]]
    assert all(captured for _, captured in host.runs)
    assert KEY not in json.dumps(stream)
    assert stream[-1]["ok"] is True and stream[-1]["step"] == "init"
    # a second call finds the configuration
    stream = events(host, ["run", "init", "--json"])
    assert stream[-1]["results"][0]["reason"] == "configured"


def test_run_init_with_a_refused_key_writes_nothing(tmp_path: Path) -> None:
    host = FakeHost(
        tmp_path,
        stdin=json.dumps({"inputs": {"provider": "openai", "key": KEY}}),
        key_answer=KeyCheck("refused", status=401),
    )
    stream = events(host, ["run", "init", "--json"])
    assert stream[-1]["event"] == "error" and stream[-1]["code"] == "key_refused"
    assert "HTTP 401" in stream[-1]["message"]
    assert not (host.home / ".env").exists() and host.runs == []


def test_run_init_needs_a_known_provider_for_a_key(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, stdin=json.dumps({"inputs": {"provider": "bedrock", "key": KEY}}))
    stream = events(host, ["run", "init", "--json"])
    assert stream[-1]["code"] == "bad_provider" and host.key_calls == []


def test_run_about_and_doctor(tmp_path: Path) -> None:
    host = FakeHost(
        tmp_path,
        stdin=json.dumps({"inputs": {"name": "Deniz", "languages": "Turkish, English"}}),
        output={("doctor",): [json.dumps({"ok": True, "checks": [{"name": "config"}]})]},
    )
    host.write_config()
    stream = events(host, ["run", "about", "--json"])
    assert stream[-1]["ok"] is True
    user = (host.home / "persona" / "user.md").read_text(encoding="utf-8")
    assert user.endswith("- Name: Deniz\n- Languages: Turkish, English\n")
    stream = events(host, ["run", "about", "--json"])
    assert stream[-1]["results"][0]["reason"] == "configured"
    stream = events(host, ["run", "doctor", "--json"])
    assert stream[-1]["checks"] == [{"name": "config"}] and stream[-1]["ok"] is True
