"""``--no-window``, ``[component.guard] window`` in the CLI's requests, and ``tau guard window``
(issue 126). The overlay child process is faked; nothing opens a window or a camera."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from guard_helpers import cli_config, running_hub
from tau_core.i18n import t
from tau_guard import cli_face
from tau_guard.strings import WINDOW_MESSAGES
from tau_guard.testing import match, read_requests
from test_cli_face import InProcess, fresh, invoke


@pytest.fixture(autouse=True)
def at_the_mac(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.delenv("TAU_GUARD_WINDOW", raising=False)


@pytest.fixture
def model_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_face, "model_state", lambda path, expected: "ok")


def last_request(runner: InProcess) -> dict[str, Any]:
    return runner.calls[-1][1]


def test_local_checks_ask_for_the_window(tmp_path: Path, model_ok: None) -> None:
    config = fresh(tmp_path)
    runner = InProcess()
    assert invoke(config, "enroll", runner=runner).exit_code == 0
    window = last_request(runner)["window"]
    assert window["purpose"] == "enroll" and window["language"] == "en"
    assert window["texts"]["guard.window.step.turn_left"] == "TURN LEFT"
    assert invoke(config, "verify", runner=runner).exit_code == 0
    assert last_request(runner)["window"]["purpose"] == "check"  # a local check unlocks nothing
    result = invoke(config, "verify", "--explain", runner=runner)
    assert result.exit_code == 0 and "det=" in result.output  # the numbers print as before
    assert last_request(runner)["explain"] is True and "window" in last_request(runner)
    turkish = invoke(config, "verify", runner=runner, env={"TAU_LANG": "tr"})
    assert turkish.exit_code == 0
    window = last_request(runner)["window"]
    assert window["language"] == "tr"
    assert (
        window["texts"]["guard.window.step.turn_left"]
        == WINDOW_MESSAGES["guard.window.step.turn_left"]["tr"]
    )


@pytest.mark.parametrize(
    "args",
    [("enroll", "--no-window"), ("verify", "--no-window"), ("verify", "--explain", "--no-window")],
)
def test_no_window_leaves_it_out(tmp_path: Path, model_ok: None, args: tuple[str, ...]) -> None:
    config = fresh(tmp_path)
    runner = InProcess()
    assert invoke(config, "enroll", runner=runner).exit_code == 0
    result = invoke(config, *args, runner=runner)
    assert result.exit_code == 0, result.output
    assert "window" not in last_request(runner)


def test_setup_passes_no_window_to_both_checks(tmp_path: Path, model_ok: None) -> None:
    config = fresh(tmp_path)
    runner = InProcess()
    result = invoke(config, "setup", "--no-window", runner=runner)
    assert result.exit_code == 0, result.output
    assert [op for op, _ in runner.calls] == ["enroll", "verify"]
    assert all("window" not in request for _, request in runner.calls)


def test_window_false_in_tau_toml(tmp_path: Path, model_ok: None) -> None:
    config = fresh(tmp_path)
    toml = config.home / "tau.toml"
    toml.write_text(toml.read_text() + "\n[component.guard]\nwindow = false\n")
    runner = InProcess()
    assert invoke(config, "enroll", runner=runner).exit_code == 0
    assert "window" not in last_request(runner)
    assert t("guard.cli.window.off") in invoke(config, "window").output


def test_no_window_through_the_hub_says_who_decides(tmp_path: Path) -> None:
    config = cli_config(tmp_path)
    with running_hub(tmp_path, config=config, runs=[[match()]]) as running:
        result = invoke(config, "verify", "--no-window", runner=InProcess(), client=running.client)
        assert result.exit_code == 0, result.output
        assert t("guard.cli.window.through_hub") in result.output
        (request,) = read_requests(running.script)
        assert request["request"]["window"]["purpose"] == "unlock"  # the hub's own setting
        result = invoke(config, "verify", runner=InProcess(), client=running.client)
        assert t("guard.cli.window.through_hub") not in result.output


def test_esc_in_a_local_check_is_cancelled(tmp_path: Path) -> None:
    config = fresh(tmp_path)

    def cancelled(op: str, request: dict, **kwargs: Any) -> dict:
        return {
            "type": "verdict",
            "ok": False,
            "reason": "cancelled",
            "method": None,
            "cancelled": True,
        }

    result = invoke(config, "verify", runner=cancelled)
    assert result.exit_code == 1 and t("guard.verdict.cancelled") in result.output


# -- tau guard window ----------------------------------------------------------------------------


class Overlay:
    """A fake ``python -m tau_guard.overlay`` runner."""

    def __init__(self, **answers: dict) -> None:
        self.answers = answers
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, args: list[str], request: dict, *, timeout: float = 0.0) -> dict:
        self.calls.append((args, request))
        return self.answers.get(args[0], {"ok": True, "reason": None})


def test_window_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = fresh(tmp_path)
    overlay = Overlay(probe={"ok": False, "reason": "no_gui_session"})
    result = invoke(config, "window", guard_overlay=overlay)
    assert result.exit_code == 0
    assert t("guard.cli.window.state", state=t("guard.cli.window.on")) in result.output
    why = t("guard.cli.window.why.no_gui_session")
    assert t("guard.cli.window.headless", why=why) in result.output
    assert t("guard.cli.window.hub") in result.output
    assert t("guard.cli.window.demo_hint") in result.output
    assert overlay.calls == [(["probe"], {})]
    fine = Overlay(probe={"ok": True, "reason": None})
    assert "run without it" not in invoke(config, "window", guard_overlay=fine).output
    monkeypatch.setenv("SSH_CONNECTION", "100.x.y.z 50000 100.x.y.z 22")
    result = invoke(config, "window", guard_overlay=overlay, env={"TAU_LANG": "tr"})
    assert t("guard.cli.window.why.ssh", "tr") in result.output
    assert len(overlay.calls) == 1  # no probe needed
    result = invoke(config, "window", guard_overlay=overlay, platform="linux")
    assert t("guard.cli.window.why.platform") in result.output


def test_window_demo(tmp_path: Path) -> None:
    config = fresh(tmp_path)
    overlay = Overlay()
    result = invoke(config, "window", "--demo", guard_overlay=overlay, env={"TAU_LANG": "tr"})
    assert result.exit_code == 0, result.output
    assert t("guard.cli.window.demo_start", "tr") in result.output
    ((args, request),) = overlay.calls
    assert args == ["demo"] and request["language"] == "tr" and "snapshot" not in request
    key = "guard.window.result.unlock"
    assert request["texts"][key] == WINDOW_MESSAGES[key]["tr"]
    shots = tmp_path / "shots"
    result = invoke(config, "window", "--demo", "--snapshot", str(shots), guard_overlay=overlay)
    assert result.exit_code == 0 and overlay.calls[-1][1]["snapshot"] == str(shots.resolve())
    assert t("guard.cli.window.demo_saved", path=shots) in result.output
    refused = Overlay(demo={"ok": False, "reason": "no_gui_session"})
    result = invoke(config, "window", "--demo", guard_overlay=refused)
    assert result.exit_code == 1
    assert t("guard.cli.window.why.no_gui_session") in result.output
    assert (
        invoke(config, "window", "--demo", guard_overlay=overlay, platform="linux").exit_code == 2
    )


def test_the_cli_never_loads_pyobjc() -> None:
    import subprocess
    import sys

    names = ("AppKit", "Quartz", "Foundation", "objc", "numpy", "cv2")
    code = (
        "import sys, tau_guard.cli, tau_guard.cli_window; "
        f"print(sorted(m for m in {names!r} if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "[]", out.stderr
