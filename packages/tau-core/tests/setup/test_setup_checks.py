"""Check steps in ``tau setup`` (issue 173): remote access in the wizard and the JSON protocol.

The check commands (``tau remote tailscale|ssh|phone --json``) are answered by the fake host with
check objects; nothing runs, and the command an action shows is never run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result
from setup_fakes import TAU, FakeHost
from tau_core.cli import cli
from tau_core.setup import CatalogError, load_catalog, parse_catalog
from tau_core.setup.checks import Action, CheckItem, CheckResult, parse_check, render_action
from tau_core.setup.engine import render_user_md
from tau_core.setup.state import take_snapshot

HOST = "my-mac.tailXXXXXX.ts.net"
COMMAND = "bash ~/.local/share/tau/remote/setup-all.sh"
TS_OK = CheckResult(
    True,
    f"Tailscale is connected as {HOST}",
    (CheckItem("connected", "Logged in and connected", "ok", HOST),),
    values={"host": HOST},
)
TS_MISSING = CheckResult(
    False,
    "Tailscale is not installed",
    (CheckItem("installed", "Tailscale installed", "fail", "not found"),),
    Action("install", "Install Tailscale ...", url="https://tailscale.com/download/mac"),
)
SSH_TODO = CheckResult(
    False,
    "2 problem(s) with SSH, mosh or tmux",
    (
        CheckItem("sshd", "SSH server", "fail", "off (Remote Login)"),
        CheckItem("tmux", "tmux", "ok", "/opt/homebrew/bin/tmux"),
    ),
    Action(
        "sudo",
        "Run this in your own terminal, as yourself and not with sudo.",
        command=COMMAND,
        sudo=True,
        changes=("installs tmux and mosh with Homebrew",),
        script="/somewhere/setup-all.sh",
    ),
)
SSH_OK = CheckResult(True, "SSH takes keys only", (CheckItem("sshd", "SSH server", "ok", "on"),))
PHONE_OK = CheckResult(
    True,
    "In Termius, add a host with these values",
    (CheckItem("host", "Address", "info", HOST),),
    values={"host": HOST, "user": "alice", "port": 22},
)


def answers(**checks: list[CheckResult]) -> dict[tuple[str, ...], list[tuple[int, str]]]:
    return {
        ("remote", step): [(0 if r.ok else 1, r.dumps()) for r in results]
        for step, results in checks.items()
    }


def ready_host(tmp_path: Path, **kwargs: Any) -> FakeHost:
    host = FakeHost(tmp_path, **kwargs)
    host.write_config()
    (host.home / "persona" / "user.md").write_text(render_user_md(name="Deniz"), encoding="utf-8")
    return host


def check_calls(host: FakeHost) -> list[list[str]]:
    return [argv[1:] for argv in host.captures if argv[0] == TAU and argv[-1] == "--json"]


def invoke(host: FakeHost, args: list[str], stdin: str | None = None) -> Result:
    return CliRunner().invoke(
        cli, ["setup", *args], input=stdin, obj={"setup_host": host}, prog_name="tau"
    )


def events(host: FakeHost, args: list[str]) -> list[dict[str, Any]]:
    result = invoke(host, args)
    parsed = [json.loads(line) for line in result.output.splitlines() if line.strip()]
    assert parsed[-1]["event"] in ("done", "error")
    expected = 0 if parsed[-1]["event"] == "done" and parsed[-1].get("ok") else 1
    assert result.exit_code == expected, result.output
    return parsed


# -- the catalog -----------------------------------------------------------------------------------


MINIMAL = """
schema = 1
docs = "https://docs.example.com/"

[[feature]]
id = "one"
label = "setup.feature.tui"
description = "setup.feature.tui.about"
platforms = ["darwin", "linux"]
"""


def test_remote_is_three_check_steps() -> None:
    remote = load_catalog().get("remote")
    assert remote is not None
    assert [(s.id, s.command, s.check) for s in remote.steps] == [
        ("tailscale", ("remote", "tailscale"), True),
        ("ssh", ("remote", "ssh"), True),
        ("phone", ("remote", "phone"), True),
    ]
    assert remote.configured is not None
    assert remote.configured.command == ("remote", "status")


def test_check_steps_and_command_rules_parse() -> None:
    catalog = parse_catalog(
        MINIMAL + '[feature.configured]\ncommand = ["one", "status"]\n'
        '[[feature.step]]\nid = "x"\nlabel = "setup.step.remote.ssh"\ncommand = ["one"]\n'
        "check = true\n"
    )
    feature = catalog.get("one")
    assert feature is not None and feature.steps[0].check
    assert feature.configured is not None and feature.configured.command == ("one", "status")


@pytest.mark.parametrize(
    ("extra", "error"),
    [
        (
            '[[feature.step]]\nid = "x"\nkind = "note"\nlabel = "setup.step.remote.ssh"\n'
            'text = "setup.note.guard.restart"\ncheck = true\n',
            "`check` is for command steps",
        ),
        (
            '[[feature.step]]\nid = "x"\nlabel = "setup.step.remote.ssh"\ncommand = ["a"]\n'
            "check = true\ninteractive = true\n",
            "a check is neither interactive",
        ),
        ('[feature.configured]\ncommand = ["sudo", "x"]\n', "invalid command word"),
    ],
)
def test_check_mistakes_are_refused(extra: str, error: str) -> None:
    with pytest.raises(CatalogError, match=error):
        parse_catalog(MINIMAL + extra)


def test_remote_is_set_up_when_tau_remote_status_passes(tmp_path: Path) -> None:
    catalog = load_catalog()
    assert take_snapshot(FakeHost(tmp_path), catalog).get("remote").state == "available"  # type: ignore[union-attr]
    host = FakeHost(tmp_path, codes={("remote", "status"): 0})
    assert take_snapshot(host, catalog).get("remote").state == "done"  # type: ignore[union-attr]
    assert [TAU, "remote", "status"] in host.captures
    other = FakeHost(tmp_path, platform="win32", codes={("remote", "status"): 0})
    assert take_snapshot(other, catalog).get("remote").state == "unavailable"  # type: ignore[union-attr]
    assert [TAU, "remote", "status"] not in other.captures


def test_the_check_object_round_trips_and_refuses_junk() -> None:
    assert parse_check(SSH_TODO.dumps()) == SSH_TODO
    for junk in (
        "",
        "{}",
        '{"check": 1, "ok": "yes"}',
        '{"check": 1, "ok": false, "checks": [{"status": "odd"}]}',
    ):
        with pytest.raises(ValueError):
            parse_check(junk)
    bad_url = SSH_TODO.as_json()
    bad_url["action"]["url"] = "http://example.com/"
    with pytest.raises(ValueError):
        parse_check(json.dumps(bad_url))
    assert SSH_TODO.action is not None
    lines = render_action(SSH_TODO.action, "en")
    assert f"      {COMMAND}" in lines and "    What it changes:" in lines
    brief = render_action(SSH_TODO.action, "en", brief=True)
    assert f"      {COMMAND}" in brief and "    What it changes:" not in brief


# -- the terminal wizard ---------------------------------------------------------------------------


def test_the_wizard_shows_the_one_command_and_checks_again(tmp_path: Path) -> None:
    host = ready_host(
        tmp_path,
        checks=answers(tailscale=[TS_OK], ssh=[SSH_TODO, SSH_OK], phone=[PHONE_OK]),
    )
    result = invoke(host, ["run", "remote"], stdin="\n")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "▸ Tailscale on this machine: checking…" in out
    assert f"  ✓ Logged in and connected: {HOST}" in out
    assert "  ✗ SSH server: off (Remote Login)" in out
    assert f"\n      {COMMAND}\n" in out
    assert "What it changes:" in out and "Read it first if you like: /somewhere/setup-all.sh" in out
    assert "When you are done press Enter to check again, or type skip" in out
    assert "▸ SSH and mosh: checking again…" in out and "✓ SSH and mosh" in out
    assert f"  · Address: {HOST}" in out
    assert host.runs == []  # nothing ran with the terminal, and certainly not the command
    assert check_calls(host) == [
        ["remote", "tailscale", "--json"],
        ["remote", "ssh", "--json"],
        ["remote", "ssh", "--json"],
        ["remote", "phone", "--json"],
    ]


def test_the_wizard_can_skip_a_check(tmp_path: Path) -> None:
    host = ready_host(tmp_path, checks=answers(tailscale=[TS_OK], ssh=[SSH_TODO], phone=[PHONE_OK]))
    result = invoke(host, ["run", "remote"], stdin="what\natla\nskip\n")
    assert result.exit_code == 0, result.output
    assert "Press Enter (or type done) to check again, or type skip." in result.output
    assert "– SSH and mosh: skipped" in result.output
    assert check_calls(host)[-1] == ["remote", "phone", "--json"]


def test_the_wizard_opens_the_download_page_on_request(tmp_path: Path) -> None:
    host = ready_host(
        tmp_path, checks=answers(tailscale=[TS_MISSING], ssh=[SSH_OK], phone=[PHONE_OK])
    )
    host.environ["TAU_LANG"] = "tr"
    result = invoke(host, ["run", "remote"], stdin="e\natla\n")
    assert result.exit_code == 0, result.output
    assert "https://tailscale.com/download/mac tarayıcıda açılsın mı? [e/H]" in result.output
    assert host.opened == ["https://tailscale.com/download/mac"]


def test_yes_reports_what_needs_the_owner(tmp_path: Path) -> None:
    host = ready_host(tmp_path, checks=answers(tailscale=[TS_OK], ssh=[SSH_TODO], phone=[PHONE_OK]))
    result = invoke(host, ["--yes", "--features", "remote"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert (
        "– SSH and mosh: needs you: 2 problem(s) with SSH, mosh or tmux. Run `tau setup run "
        "remote` at a terminal"
    ) in out
    assert COMMAND not in out  # --yes asks nothing and shows no command to wait for
    assert "partly set up" in out
    assert host.tau_runs() == [["doctor"]]


def test_a_check_that_says_nothing_fails_and_the_rest_go_on(tmp_path: Path) -> None:
    host = ready_host(tmp_path, checks={("remote", "tailscale"): [(3, "Traceback ...")]})
    host.checks.update(answers(ssh=[SSH_OK], phone=[PHONE_OK]))
    result = invoke(host, ["run", "remote"])
    assert result.exit_code == 1
    assert "✗ Tailscale on this machine: gave no check result (exit code 3)" in result.output
    assert "✓ Your phone (Termius)" in result.output


# -- JSON mode -------------------------------------------------------------------------------------


def test_status_marks_the_check_steps(tmp_path: Path) -> None:
    result = invoke(FakeHost(tmp_path), ["status", "--json"])
    features = {f["id"]: f for f in json.loads(result.output)["features"]}
    remote = features["remote"]
    assert remote["state"] == "available" and not remote["configured"]
    assert [(s["id"], s["check"], s["command"]) for s in remote["steps"]] == [
        ("tailscale", True, ["remote", "tailscale"]),
        ("ssh", True, ["remote", "ssh"]),
        ("phone", True, ["remote", "phone"]),
    ]
    assert features["guard"]["steps"][0]["check"] is False


def test_json_stops_at_the_one_command_and_resumes(tmp_path: Path) -> None:
    host = FakeHost(
        tmp_path, checks=answers(tailscale=[TS_OK], ssh=[SSH_TODO, SSH_OK], phone=[PHONE_OK])
    )
    stream = events(host, ["run", "remote", "--json"])
    assert [e["event"] for e in stream] == [
        "progress",
        "check",
        "progress",
        "progress",
        "check",
        "needs_ui",
        "done",
    ]
    assert stream[0] == {
        "event": "progress",
        "feature": "remote",
        "step": "tailscale",
        "status": "checking",
        "label": "Tailscale on this machine",
        "command": ["remote", "tailscale"],
    }
    check = stream[1]
    assert check["feature"] == "remote" and check["step"] == "tailscale" and check["ok"]
    assert "check" not in check and check["values"] == {"host": HOST}
    assert stream[2]["status"] == "done"
    needs = stream[5]
    assert needs == {
        "event": "needs_ui",
        "feature": "remote",
        "step": "ssh",
        "label": "SSH and mosh",
        "summary": "2 problem(s) with SSH, mosh or tmux",
        "action": {
            "kind": "sudo",
            "text": "Run this in your own terminal, as yourself and not with sudo.",
            "command": COMMAND,
            "sudo": True,
            "url": None,
            "changes": ["installs tmux and mosh with Homebrew"],
            "script": "/somewhere/setup-all.sh",
        },
    }
    done = stream[-1]
    assert done["ok"] is True and done["configured"] is False
    assert done["pending"] == ["ssh", "phone"]  # the check first: running it again re-checks
    assert done["results"] == [
        {"step": "tailscale", "status": "done", "code": 0},
        {"step": "ssh", "status": "needs_ui"},
    ]
    assert host.runs == []
    # The owner ran the command; the app runs the pending steps again.
    host.stdin = json.dumps({"steps": done["pending"]})
    again = events(host, ["run", "remote", "--json"])
    assert [e["event"] for e in again] == ["progress", "check", "progress"] * 2 + ["done"]
    assert again[-1]["ok"] is True and again[-1]["pending"] == []
    assert host.runs == []


def test_json_a_check_without_an_action_fails(tmp_path: Path) -> None:
    broken = CheckResult(False, "Remote access is set up on macOS and Linux only.")
    host = FakeHost(tmp_path, checks=answers(tailscale=[broken], ssh=[SSH_OK], phone=[PHONE_OK]))
    host.stdin = json.dumps({"steps": ["tailscale"]})
    stream = events(host, ["run", "remote", "--json"])
    failed = stream[2]
    assert failed["status"] == "failed" and failed["reason"] == "check"
    assert failed["detail"] == "Remote access is set up on macOS and Linux only."
    assert stream[-1]["ok"] is False
