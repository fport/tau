"""``tau guard setup | enroll | verify | forget | doctor`` with an in-process worker of fakes
(or a hub on port 0 with the fake worker script); never a camera, the Keychain or a prompt."""

from __future__ import annotations

import json
import os
import time
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from guard_helpers import running_hub
from tau_core import Config
from tau_core.hub import HubClient
from tau_core.i18n import t
from tau_guard import cli_face, worker
from tau_guard.cli import guard
from tau_guard.cli_face import responsible_app
from tau_guard.engine import SFACE_SHA256
from tau_guard.local import LocalWorkerError, run_local, validate_explain
from tau_guard.runner import parse_line
from tau_guard.store import MARKER_FILE, MemoryKeyStore
from tau_guard.testing import (
    STRANGER,
    FakeLocalAuth,
    SimulatedUser,
    fake_deps,
    fake_worker_command,
    match,
    read_requests,
    write_script,
)
from test_cli import cli_config


@pytest.fixture(autouse=True)
def restore_environ() -> Iterator[None]:
    saved = dict(os.environ)
    os.environ.pop("SSH_CONNECTION", None)
    yield
    os.environ.clear()
    os.environ.update(saved)


class InProcess:
    """A runner like ``run_local`` that runs the worker's operations in this process with
    fakes and a fresh simulated user per run."""

    def __init__(self, *, users: list[SimulatedUser] | None = None, auth: Any = None) -> None:
        self.keys = MemoryKeyStore()
        self.auth = auth or FakeLocalAuth()
        self.users = users or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, op, request, *, on_progress=None, on_explain=None, timeout=None):
        self.calls.append((op, dict(request)))
        user = self.users.pop(0) if self.users else SimulatedUser(duration=25)

        def emit(message: dict[str, Any]) -> None:
            if message["type"] == "progress":
                user.on_progress(message)
                if on_progress is not None:
                    on_progress(parse_line(json.dumps(message).encode(), op=op))
            elif message["type"] == "explain" and on_explain is not None:
                on_explain(validate_explain(message))

        deps = fake_deps(
            source=lambda camera: user.source(),
            keys=self.keys,
            local_auth=self.auth,
            clock=user.now,
        )
        return worker.run(op, request, deps=deps, emit=emit)


def invoke(config: Config, *args: str, runner: Any = None, client: Any = None, **obj: Any):
    context = {
        "home": config.home,
        "guard_client": client or HubClient(config),
        "guard_worker": runner,
        "platform": obj.pop("platform", "darwin"),
        **obj,
    }
    env = {"TAU_DATA_DIR": str(config.data_dir), **obj.pop("env", {})}
    return CliRunner().invoke(guard, list(args), obj=context, env=env)


@pytest.fixture
def model_ok(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Pretend the pinned SFace file is installed (the real one is 39 MB)."""
    installs: list[Any] = []
    monkeypatch.setattr(cli_face, "model_state", lambda path, expected: "ok")
    return installs


def fresh(tmp_path: Path) -> Config:
    """A home with no guard yet (no marker, nothing in [component.guard])."""
    return cli_config(tmp_path, active=False)


# -- setup ---------------------------------------------------------------------------------------


def test_setup_refuses_off_macos_and_over_ssh(tmp_path: Path) -> None:
    config = fresh(tmp_path)
    result = invoke(config, "setup", runner=InProcess(), platform="linux")
    assert result.exit_code == 2 and t("guard.cli.unsupported") in result.output
    os.environ["SSH_CONNECTION"] = "100.x.y.z 50000 100.x.y.z 22"
    result = invoke(config, "setup", runner=InProcess())
    assert result.exit_code == 2 and t("guard.cli.ssh_refused") in result.output
    for command in ("enroll", "forget"):
        assert invoke(config, command, runner=InProcess()).exit_code == 2


def test_setup_refuses_a_model_file_with_the_wrong_checksum(tmp_path: Path) -> None:
    config = fresh(tmp_path)
    bogus = tmp_path / "model.onnx"
    bogus.write_bytes(b"this is not SFace")
    runner = InProcess()
    result = invoke(config, "setup", "--model-file", str(bogus), runner=runner)
    assert result.exit_code == 1
    assert SFACE_SHA256 in result.output and "sha256" in result.output
    models = config.data_dir / "guard" / "models"
    assert list(models.iterdir()) == []  # not kept
    assert runner.calls == []  # nothing enrolled


def test_setup_downloads_enrolls_verifies_and_enables(tmp_path: Path, model_ok: list) -> None:
    config = fresh(tmp_path)
    installs: list[Any] = []

    def install(data_dir: Path, *, source: Path | None = None) -> Path:
        installs.append((data_dir, source))
        return data_dir / "guard" / "models" / "sface.onnx"

    runner = InProcess()
    result = invoke(config, "setup", runner=runner, guard_install=install)
    assert result.exit_code == 0, result.output
    assert installs == []  # model_state says the pinned file is already there
    output = result.output
    assert t("guard.cli.local") in output
    assert t("guard.progress.turn_left") in output or t("guard.progress.turn_right") in output
    assert t("guard.cli.enroll.done_first") in output
    assert t("guard.cli.setup.restart") in output and t("guard.cli.setup.remote") in output
    assert [op for op, _ in runner.calls] == ["enroll", "verify"]
    enroll_request = runner.calls[0][1]
    assert enroll_request["reason_text"] == t("guard.cli.la.enroll")
    assert enroll_request["add"] is False
    toml = tomllib.loads((config.home / "tau.toml").read_text())
    assert toml["component"]["guard"]["enabled"] is True
    assert Config.load(config.home).component("guard") == {"enabled": True}
    assert (config.data_dir / "guard" / MARKER_FILE).is_file()
    events = [
        json.loads(line)["event"]
        for line in (config.data_dir / "guard" / "audit.jsonl").read_text().splitlines()
    ]
    assert events == ["camera_open", "enroll", "camera_open", "verify"]


def test_setup_installs_the_model_when_it_is_missing(tmp_path: Path) -> None:
    config = fresh(tmp_path)
    source = tmp_path / "sface.onnx"
    source.write_bytes(b"model")
    seen: list[Any] = []

    def install(data_dir: Path, *, source: Path | None = None) -> Path:
        seen.append(source)
        raise __import__("tau_guard.engine", fromlist=["ModelError"]).ModelError(
            "download", "no network"
        )

    result = invoke(
        config, "setup", "--model-file", str(source), runner=InProcess(), guard_install=install
    )
    assert result.exit_code == 1 and "no network" in result.output and seen == [source]
    result = invoke(config, "setup", runner=InProcess(), guard_install=install)
    assert t("guard.cli.model.downloading") in result.output and seen[-1] is None


def test_setup_stops_when_the_check_fails(tmp_path: Path, model_ok: list) -> None:
    config = fresh(tmp_path)
    runner = InProcess(users=[SimulatedUser(duration=25), SimulatedUser(embedding=STRANGER)])
    result = invoke(config, "setup", runner=runner)
    assert result.exit_code == 1
    assert t("guard.cli.setup.verify_failed") in result.output
    assert "enabled" not in (config.home / "tau.toml").read_text()


# -- enroll ----------------------------------------------------------------------------------------


def test_enroll_needs_the_model(tmp_path: Path) -> None:
    config = fresh(tmp_path)
    result = invoke(config, "enroll", runner=InProcess())
    assert result.exit_code == 1 and t("guard.cli.no_model") in result.output


def test_enroll_again_and_add_locally(tmp_path: Path, model_ok: list) -> None:
    config = fresh(tmp_path)
    runner = InProcess()
    assert invoke(config, "enroll", runner=runner).exit_code == 0
    result = invoke(config, "enroll", runner=runner)
    assert result.exit_code == 0 and t("guard.cli.enroll.done_again") in result.output
    result = invoke(config, "enroll", "--add", runner=runner)
    assert result.exit_code == 0 and t("guard.cli.enroll.done_add") in result.output
    assert runner.calls[-1][1]["add"] is True


def test_a_failed_enrollment_says_why(tmp_path: Path, model_ok: list) -> None:
    config = fresh(tmp_path)
    runner = InProcess(auth=FakeLocalAuth("failed"))
    result = invoke(config, "enroll", runner=runner)
    assert result.exit_code == 1 and t("guard.verdict.touch_id_failed") in result.output
    runner = InProcess(users=[SimulatedUser(duration=25, amplitude=0.05)])
    result = invoke(config, "enroll", runner=runner)
    assert t("guard.cli.enroll.reason.timeout") in result.output


def test_enroll_through_a_running_hub(tmp_path: Path, model_ok: list) -> None:
    config = cli_config(tmp_path)
    runs = [
        [
            {"progress": "touch_id"},
            {"sleep": 0.3},
            {"progress": "look", "hint": "too_dark"},
            {"sleep": 0.3},
            {"progress": "turn_left"},
            {"sleep": 0.3},
            {"progress": "turn_more"},
            {"sleep": 0.3},
            match(liveness=None),
        ]
    ]
    with running_hub(tmp_path, config=config, runs=runs) as running:
        local = InProcess()
        result = invoke(config, "enroll", "--add", runner=local, client=running.client)
        assert result.exit_code == 0, result.output
        assert t("guard.cli.via_hub") in result.output
        assert t("guard.cli.enroll.local_auth") in result.output  # Touch ID or the password
        assert t("guard.progress.touch_id") not in result.output
        assert t("guard.progress.turn_more") in result.output
        assert t("guard.verdict.too_dark") in result.output
        assert t("guard.cli.enroll.done_add") in result.output
        assert local.calls == []  # the hub's worker did it
        (request,) = read_requests(running.script)
        assert request["op"] == "enroll" and request["request"]["add"] is True


# -- verify ----------------------------------------------------------------------------------------


def test_verify_explain_prints_every_frame_and_saves_nothing(
    tmp_path: Path, model_ok: list
) -> None:
    config = fresh(tmp_path)
    runner = InProcess()
    assert invoke(config, "enroll", runner=runner).exit_code == 0
    before = {p for p in (config.data_dir).rglob("*") if p.is_file()}
    result = invoke(config, "verify", "--explain", runner=runner)
    assert result.exit_code == 0, result.output
    rows = [line for line in result.output.splitlines() if "det=" in line]
    assert len(rows) > 20
    assert all("eyes=" in r and "light=" in r and "sharp=" in r and "yaw=" in r for r in rows)
    assert any("match=0." in r for r in rows)
    assert t("guard.cli.verify.nothing_saved") in result.output
    assert runner.calls[-1][1]["explain"] is True
    after = {p for p in (config.data_dir).rglob("*") if p.is_file()}
    assert {p.name for p in after - before} <= set()  # only audit.jsonl grew
    turkish = invoke(config, "verify", "--explain", runner=runner, env={"TAU_LANG": "tr"})
    label = t("guard.cli.verify.explain_row", "tr").split("{score}")[0].split()[-1]
    assert label in turkish.output and "det=" not in turkish.output


def test_verify_through_a_running_hub(tmp_path: Path) -> None:
    config = cli_config(tmp_path)
    with running_hub(
        tmp_path, config=config, runs=[[{"progress": "turn_left"}, match()]]
    ) as running:
        result = invoke(config, "verify", runner=InProcess(), client=running.client)
        assert result.exit_code == 0, result.output
        assert t("guard.cli.via_hub") in result.output
        assert t("guard.cli.verify.passed") in result.output


def test_verify_without_a_hub_runs_locally_and_unlocks_nothing(
    tmp_path: Path, model_ok: list
) -> None:
    config = fresh(tmp_path)
    runner = InProcess()
    invoke(config, "enroll", runner=runner)
    result = invoke(config, "verify", runner=runner)
    assert result.exit_code == 0 and t("guard.cli.verify.local") in result.output
    runner.users = [SimulatedUser(embedding=STRANGER)]
    result = invoke(config, "verify", runner=runner)
    assert result.exit_code == 1 and t("guard.verdict.no_match") in result.output


# -- forget ----------------------------------------------------------------------------------------


def test_forget_turns_the_guard_off(tmp_path: Path, model_ok: list) -> None:
    config = fresh(tmp_path)
    runner = InProcess()
    assert invoke(config, "setup", runner=runner).exit_code == 0
    refused = InProcess(auth=FakeLocalAuth("failed"))
    refused.keys = runner.keys
    result = invoke(config, "forget", runner=refused)
    assert result.exit_code == 1 and (config.data_dir / "guard" / MARKER_FILE).exists()
    result = invoke(config, "forget", runner=runner)
    assert result.exit_code == 0, result.output
    assert not (config.data_dir / "guard" / MARKER_FILE).exists()
    assert runner.keys.key is None
    assert tomllib.loads((config.home / "tau.toml").read_text())["component"]["guard"] == {
        "enabled": False
    }
    assert t("guard.cli.forget.done") in result.output
    assert runner.calls[-1][1]["reason_text"] == t("guard.cli.la.forget")
    again = invoke(config, "forget", runner=runner)
    assert again.exit_code == 0 and t("guard.cli.forget.nothing") in again.output


def test_forget_with_a_stuck_keychain_still_turns_the_guard_off(
    tmp_path: Path, model_ok: list
) -> None:
    config = fresh(tmp_path)
    runner = InProcess()
    assert invoke(config, "setup", runner=runner).exit_code == 0

    class StuckKeys(MemoryKeyStore):
        def delete(self) -> bool:
            from tau_guard.store import KeyUnavailable

            raise KeyUnavailable("the Keychain did not answer within 30 s")

    stuck = InProcess()
    stuck.keys = StuckKeys(runner.keys.key)
    result = invoke(config, "forget", runner=stuck)
    assert result.exit_code == 1
    assert not (config.data_dir / "guard" / MARKER_FILE).exists()
    assert tomllib.loads((config.home / "tau.toml").read_text())["component"]["guard"] == {
        "enabled": False
    }
    assert t("guard.cli.forget.key_left") in result.output
    assert t("guard.cli.forget.failed", reason="x").split(":")[0] not in result.output
    again = invoke(config, "forget", runner=runner)  # the Keychain answers again
    assert again.exit_code == 0 and runner.keys.key is None


# -- doctor ----------------------------------------------------------------------------------------


def selftest_answer(**details: Any) -> dict[str, Any]:
    base = {
        "opencv": "4.14.0",
        "opencv_verified": True,
        "yunet": "ok",
        "sface": "ok",
        "keychain": "ok",
        "template": "ok",
        "camera": {"device": "MacBook Pro Camera", "others": 1, "permission": 3},
    }
    return {
        "type": "verdict",
        "ok": True,
        "reason": None,
        "checks": {"platform": True, "cv2": True},
        "details": {**base, **details},
    }


def doctor(config: Config, answer: dict[str, Any], **obj: Any):
    calls: list[dict[str, Any]] = []

    def runner(op, request, **kwargs):
        calls.append(request)
        assert op == "selftest" and request["deep"] is True
        return answer

    result = invoke(config, "doctor", runner=runner, guard_app=lambda pid: "Terminal", **obj)
    return result, calls


def test_doctor_covers_every_item(tmp_path: Path) -> None:
    config = cli_config(tmp_path)
    marker = config.data_dir / "guard" / MARKER_FILE
    marker.write_text(
        json.dumps({"v": 1, "enrollment": "E1", "model": SFACE_SHA256, "created": "x"})
    )
    from tau_guard.audit import AuditLog

    AuditLog(config.data_dir / "guard").record("verify", ok=False, reason="no_match")
    AuditLog(config.data_dir / "guard").record("verify", ok=False, reason="camera_denied")
    result, calls = doctor(config, selftest_answer())
    assert result.exit_code == 0, result.output
    names = [line.split(":")[0].split(None, 1)[1] for line in result.output.splitlines()]
    assert names == [
        "platform",
        "opencv",
        "yunet",
        "sface",
        "enrollment",
        "template",
        "keychain",
        "modes",
        "camera",
        "camera permission",
        "hub camera",
        "touch id",
        "failures",
    ]
    assert "Terminal" in result.output and t("guard.cli.doctor.tcc.3") in result.output
    assert t("guard.cli.doctor.hub_none") in result.output
    assert t("guard.cli.doctor.failures", count=1) in result.output
    assert calls[0]["data_dir"] == str(config.data_dir)


def test_doctor_reports_problems(tmp_path: Path) -> None:
    config = cli_config(tmp_path)
    toml = config.home / "tau.toml"
    toml.write_text(toml.read_text() + 'unlock_liveness = "none"\n')
    answer = selftest_answer(
        sface="missing",
        opencv="5.0.0",
        opencv_verified=False,
        keychain="unavailable",
        template="key_unavailable",
        camera={"device": None, "others": 0, "permission": 2},
    )
    result, _ = doctor(Config.load(config.home), answer)
    assert result.exit_code == 1
    out = result.output
    assert "fail sface:" in out and "warn opencv:" in out and "fail keychain:" in out
    assert "warn liveness:" in out and "fail camera:" in out and "warn camera permission:" in out
    assert t("guard.verdict.key_unavailable") in out
    assert t("guard.cli.doctor.keychain_unavailable") in out  # says how to answer macOS's prompt
    result, _ = doctor(config, selftest_answer(keychain="invalid", template="key_unavailable"))
    assert "fail keychain:" in result.output
    assert t("guard.cli.doctor.keychain_invalid") in result.output


def test_doctor_names_the_hubs_app(tmp_path: Path) -> None:
    config = cli_config(tmp_path)
    with running_hub(tmp_path, config=config) as running:
        result, _ = doctor(config, selftest_answer(), client=running.client)
        assert "hub camera:" in result.output and "Terminal" in result.output
        assert t("guard.cli.doctor.hub_none") not in result.output


def test_doctor_off_macos(tmp_path: Path) -> None:
    config = cli_config(tmp_path)
    result, calls = doctor(config, selftest_answer(), platform="linux")
    assert result.exit_code == 1 and "fail platform:" in result.output and calls == []


def test_responsible_app_walks_up_to_an_app_bundle() -> None:
    table = {
        500: (400, "/usr/bin/python3"),
        400: (300, "-zsh"),
        300: (1, "/Applications/iTerm.app/Contents/MacOS/iTerm2"),
    }
    assert responsible_app(500, ps=table.get) == "iTerm"
    assert responsible_app(400, ps={400: (1, "/usr/sbin/cron")}.get) == "launchd"
    assert responsible_app(7, ps=lambda pid: None) == "unknown"


# -- the local runner ------------------------------------------------------------------------------


def test_run_local_speaks_the_worker_protocol(tmp_path: Path) -> None:
    script = write_script(
        tmp_path / "script.json",
        [
            [
                {"progress": "look", "hint": "too_dark"},
                {"raw": json.dumps({"type": "explain", "phase": "look", "t": 0.1, "faces": 1})},
                match(),
            ]
        ],
    )
    progress: list[Any] = []
    rows: list[Any] = []
    answer = run_local(
        tmp_path / "guard",
        "verify",
        {"v": 1},
        on_progress=progress.append,
        on_explain=rows.append,
        timeout=30,
        command=fake_worker_command(script),
    )
    assert answer["ok"] is True and answer["method"] == "face"
    assert progress[0].step == "look" and progress[0].hint == "too_dark"
    assert rows[0]["faces"] == 1 and rows[0]["score"] is None
    assert (tmp_path / "guard" / "worker.log").exists()


@pytest.mark.parametrize(
    "steps",
    [
        [{"raw": "garbage"}],
        [{"raw": json.dumps({"type": "explain", "phase": "look", "score": [0.1] * 128})}],
        [{"progress": "look", "hint": "sunny"}],
        [{"verdict": {"ok": True, "reason": "no_match", "method": "face"}}],
        [{"exit": 0}],
    ],
)
def test_run_local_refuses_a_broken_answer(tmp_path: Path, steps: list[dict]) -> None:
    script = write_script(tmp_path / "script.json", [steps])
    with pytest.raises(LocalWorkerError):
        run_local(
            tmp_path / "guard",
            "verify",
            {},
            on_explain=lambda row: None,
            timeout=30,
            command=fake_worker_command(script),
        )


def test_run_local_stops_a_hanging_worker(tmp_path: Path) -> None:
    script = write_script(tmp_path / "script.json", [[{"hang": True}]])
    started = time.monotonic()
    with pytest.raises(LocalWorkerError):
        run_local(
            tmp_path / "guard", "verify", {}, timeout=1.0, command=fake_worker_command(script)
        )
    assert time.monotonic() - started < 10
    pid = read_requests(script)[0]["pid"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("the worker outlived its timeout")


def test_run_local_reads_forget_and_selftest_answers(tmp_path: Path) -> None:
    script = write_script(
        tmp_path / "script.json",
        [[{"verdict": {"ok": True, "reason": None, "removed": ["enrolled", 3]}}]],
    )
    answer = run_local(
        tmp_path / "g", "forget", {}, timeout=30, command=fake_worker_command(script)
    )
    assert answer["ok"] is True and answer["removed"] == ["enrolled"]
