"""``tau remote`` on the command line, over a fake system (issue 173)."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner, Result
from remote_fakes import HOST, USER, FakeSystem
from tau_core.cli import cli
from tau_core.setup.checks import parse_check


def invoke(system: FakeSystem, args: list[str]) -> Result:
    return CliRunner().invoke(
        cli, ["remote", *args], obj={"remote_system": system}, prog_name="tau"
    )


def test_help_lists_the_checks(tmp_path: Path) -> None:
    result = invoke(FakeSystem(tmp_path), ["--help"])
    assert result.exit_code == 0
    for command in ("status", "tailscale", "ssh", "phone"):
        assert command in result.output


def test_ssh_json_is_one_check_object(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path, programs=("ssh", "brew"))
    result = invoke(system, ["ssh", "--json"])
    assert result.exit_code == 1
    [line] = result.output.splitlines()
    check = parse_check(line)
    assert not check.ok and check.action is not None
    assert check.action.command == "bash ~/.local/share/tau/remote/setup-all.sh"
    assert check.action.sudo and check.action.kind == "sudo"


def test_ssh_for_a_person(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path, programs=("ssh", "brew"))
    result = invoke(system, ["ssh"])
    assert result.exit_code == 1
    out = result.output
    assert out.startswith("SSH and mosh\n")
    assert "  ✗ SSH server: off (Remote Login)" in out
    assert "\n      bash ~/.local/share/tau/remote/setup-all.sh\n" in out
    assert "What it changes:" in out and "Read it first if you like:" in out
    assert out.rstrip().endswith("✗ 6 problem(s) with SSH, mosh or tmux")


def test_tailscale_in_turkish(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path, platform="linux", environ={"TAU_LANG": "tr"})
    result = invoke(system, ["tailscale"])
    assert result.exit_code == 1
    assert "Bu makinede Tailscale" in result.output
    assert "✗ Tailscale kurulu değil" in result.output
    assert "curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up" in result.output


def test_phone_prints_the_termius_values(tmp_path: Path) -> None:
    system = FakeSystem(tmp_path).ready()
    result = invoke(system, ["phone"])
    assert result.exit_code == 0, result.output
    assert f"  · Address: {HOST}" in result.output
    assert f"  · Username: {USER}" in result.output
    assert "  · Startup Snippet: tau-attach" in result.output


def test_status(tmp_path: Path) -> None:
    ready = invoke(FakeSystem(tmp_path).ready(), ["status"])
    assert ready.exit_code == 0, ready.output
    for title in ("Tailscale on this machine", "SSH and mosh", "Your phone (Termius)"):
        assert f"{title}\n" in ready.output
    assert ready.output.rstrip().endswith(f"✓ Remote access is ready: ssh {USER}@{HOST}")
    as_json = invoke(FakeSystem(tmp_path).ready(), ["status", "--json"])
    assert as_json.exit_code == 0 and parse_check(as_json.output).ok
    other = tmp_path / "fresh"
    other.mkdir()
    fresh = invoke(FakeSystem(other), ["status"])
    assert fresh.exit_code == 1
    assert "`tau setup run remote` walks you through them." in fresh.output
