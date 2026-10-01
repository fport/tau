"""``cloud/universe/public/install.sh``, the one-line installer (issue 169).

The script runs for real under ``sh`` (and ``dash`` when present) in a temporary HOME, with a
fake ``uv``, ``curl`` and ``uname`` first on PATH: nothing is downloaded or installed, the fakes
only log how they were called. shellcheck runs when it is installed; the test is skipped (and
says so) otherwise.
"""

from __future__ import annotations

import os
import pty
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "cloud" / "universe" / "public" / "install.sh"
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

pytestmark = pytest.mark.skipif(not SCRIPT.is_file(), reason="not a repository checkout")

FAKE_UV = """#!/bin/sh
echo "uv $*" >> "$FAKE_LOG"
case "$1 $2" in
  "tool list") [ -n "${FAKE_TOOL_LIST:-}" ] && printf '%s\\n' "$FAKE_TOOL_LIST"; exit 0 ;;
  "tool dir") printf '%s\\n' "$FAKE_TOOL_BIN"; exit 0 ;;
  "tool install")
    mkdir -p "$FAKE_TOOL_BIN"
    printf '#!/bin/sh\\necho "tau $*" >> "%s"\\n' "$FAKE_LOG" > "$FAKE_TOOL_BIN/tau"
    chmod +x "$FAKE_TOOL_BIN/tau"
    exit "${FAKE_INSTALL_CODE:-0}" ;;
esac
exit 3
"""

FAKE_CURL = """#!/bin/sh
echo "curl $*" >> "$FAKE_LOG"
cat <<'EOF'
#!/bin/sh
mkdir -p "$HOME/.local/bin"
cp "$FAKE_UV_SOURCE" "$HOME/.local/bin/uv"
chmod +x "$HOME/.local/bin/uv"
echo "installer ran" >> "$FAKE_LOG"
EOF
"""


def shells() -> list[str]:
    found = ["/bin/sh"]
    dash = shutil.which("dash")
    if dash:
        found.append(dash)
    return found


class Setup:
    def __init__(self, tmp_path: Path, *, with_uv: bool = True):
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.fake = tmp_path / "fakebin"
        self.fake.mkdir()
        self.log = tmp_path / "log"
        self.log.write_text("", encoding="utf-8")
        self.tool_bin = tmp_path / "tool-bin"
        source = tmp_path / "uv-source"
        source.write_text(FAKE_UV, encoding="utf-8")
        source.chmod(0o755)
        self.uv_source = source
        if with_uv:
            shutil.copy(source, self.fake / "uv")
        curl = self.fake / "curl"
        curl.write_text(FAKE_CURL, encoding="utf-8")
        curl.chmod(0o755)
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{self.fake}:{SYSTEM_PATH}",
            "TMPDIR": str(tmp_path),
            "FAKE_LOG": str(self.log),
            "FAKE_TOOL_BIN": str(self.tool_bin),
            "FAKE_UV_SOURCE": str(source),
        }

    def fake_uname(self, system: str, machine: str) -> None:
        uname = self.fake / "uname"
        uname.write_text(
            f'#!/bin/sh\ncase "$1" in -s) echo {system} ;; -m) echo {machine} ;; esac\n',
            encoding="utf-8",
        )
        uname.chmod(0o755)

    def run(
        self, shell: str, *, env: dict[str, str] | None = None, terminal: bool = False
    ) -> subprocess.CompletedProcess[str]:
        environment = {**self.env, **(env or {})}
        if terminal:
            main, secondary = pty.openpty()
            try:
                return subprocess.run(
                    [shell, str(SCRIPT)],
                    env=environment,
                    stdin=secondary,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    start_new_session=True,
                )
            finally:
                os.close(main)
                os.close(secondary)
        # like `curl ... | sh`: the script on stdin, and no controlling terminal
        return subprocess.run(
            [shell],
            env=environment,
            input=SCRIPT.read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
            timeout=60,
            start_new_session=True,
        )

    def calls(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("shell", shells())
def test_it_installs_tau_and_starts_setup_on_the_terminal(tmp_path: Path, shell: str) -> None:
    setup = Setup(tmp_path)
    result = setup.run(shell, terminal=True)
    assert result.returncode == 0, result.stderr
    assert setup.calls() == [
        "uv tool list",
        "uv tool install tau-core --with tau-tui",
        "uv tool dir --bin",
        "tau setup --help",
        "tau setup",
    ]
    assert "This will:" in result.stdout and "Nothing here runs with sudo." in result.stdout
    assert "install uv" not in result.stdout


@pytest.mark.parametrize("shell", shells())
def test_piped_without_a_terminal_it_says_how_to_go_on(tmp_path: Path, shell: str) -> None:
    setup = Setup(tmp_path)
    result = setup.run(shell)
    assert result.returncode == 0, result.stderr
    assert setup.calls()[-1] == "tau setup --help"  # no `tau setup` without a terminal
    assert "run `tau setup` yourself" in result.stdout
    assert f"Note: {setup.tool_bin} is not on your PATH yet" in result.stdout


def test_a_version_and_no_setup(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    env = {"TAU_INSTALL_VERSION": "1.2.3", "TAU_INSTALL_NO_SETUP": "1"}
    result = setup.run("/bin/sh", env=env, terminal=True)
    assert result.returncode == 0, result.stderr
    assert "uv tool install tau-core==1.2.3 --with tau-tui==1.2.3" in setup.calls()
    assert "tau setup" not in setup.calls()
    assert "Run `tau setup` when you are ready." in result.stdout
    assert "start tau setup" not in result.stdout


@pytest.mark.parametrize("version", ["1.0; rm -rf ~", "latest", "../1", "1 2"])
def test_a_bad_version_is_refused(tmp_path: Path, version: str) -> None:
    setup = Setup(tmp_path)
    result = setup.run("/bin/sh", env={"TAU_INSTALL_VERSION": version})
    assert result.returncode == 1
    assert "is not a version like 0.4.0" in result.stderr
    assert setup.calls() == []


def test_it_installs_uv_when_missing(tmp_path: Path) -> None:
    setup = Setup(tmp_path, with_uv=False)
    result = setup.run("/bin/sh", env={"TAU_INSTALL_NO_SETUP": "1"})
    assert result.returncode == 0, result.stderr
    assert setup.calls() == [
        "curl -fsSL https://astral.sh/uv/install.sh",
        "installer ran",
        "uv tool list",
        "uv tool install tau-core --with tau-tui",
        "uv tool dir --bin",
        "tau setup --help",
    ]
    assert "install uv, the Python package manager" in result.stdout
    assert "Astral's official installer" in result.stdout
    assert (setup.home / ".local" / "bin" / "uv").is_file()
    assert not list(tmp_path.glob("tau-uv-installer.*"))  # the downloaded installer is gone


def test_an_existing_tau_is_left_alone(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    setup.tool_bin.mkdir()
    (setup.tool_bin / "tau").write_text(
        f'#!/bin/sh\necho "tau $*" >> "{setup.log}"\n', encoding="utf-8"
    )
    (setup.tool_bin / "tau").chmod(0o755)
    result = setup.run("/bin/sh", env={"FAKE_TOOL_LIST": "tau-core v0.4.0"}, terminal=True)
    assert result.returncode == 0, result.stderr
    assert setup.calls() == ["uv tool list", "uv tool dir --bin", "tau setup --help", "tau setup"]
    assert "tau setup --upgrade upgrades tau" in result.stdout


def test_a_tau_without_setup_is_upgraded_first(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    setup.tool_bin.mkdir()
    # tau 0.4.0: every command works except `tau setup`
    (setup.tool_bin / "tau").write_text(
        f'#!/bin/sh\necho "tau $*" >> "{setup.log}"\n[ "$1" = setup ] && exit 2\nexit 0\n',
        encoding="utf-8",
    )
    (setup.tool_bin / "tau").chmod(0o755)
    result = setup.run("/bin/sh", env={"FAKE_TOOL_LIST": "tau-core v0.4.0"}, terminal=True)
    assert result.returncode == 0, result.stderr
    assert setup.calls() == [
        "uv tool list",
        "uv tool dir --bin",
        "tau setup --help",
        "uv tool upgrade --refresh tau-core",
        "tau setup --help",
        "uv tool install --force --refresh tau-core --with tau-tui",
        "tau setup --help",
        "tau setup",
    ]
    assert "older than 0.5.0" in result.stdout


def test_a_failed_install_stops(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    result = setup.run("/bin/sh", env={"FAKE_INSTALL_CODE": "1"}, terminal=True)
    assert result.returncode == 1
    assert "uv tool install tau-core failed" in result.stderr
    assert "tau setup" not in setup.calls()


@pytest.mark.parametrize(
    ("system", "machine", "message"),
    [
        ("FreeBSD", "amd64", "tau runs on macOS and Linux; this system is FreeBSD."),
        ("MINGW64_NT-10.0", "x86_64", "this system is MINGW64_NT-10.0"),
        ("Linux", "armv7l", "tau needs a 64-bit x86 or ARM CPU; this one is armv7l."),
    ],
)
def test_other_systems_are_refused(tmp_path: Path, system: str, machine: str, message: str) -> None:
    setup = Setup(tmp_path)
    setup.fake_uname(system, machine)
    result = setup.run("/bin/sh")
    assert result.returncode == 1
    assert message in result.stderr
    assert setup.calls() == []


def test_linux_on_arm_is_fine(tmp_path: Path) -> None:
    setup = Setup(tmp_path)
    setup.fake_uname("Linux", "aarch64")
    result = setup.run("/bin/sh", env={"TAU_INSTALL_NO_SETUP": "1"})
    assert result.returncode == 0, result.stderr
    assert "tau installer · Linux aarch64" in result.stdout


def test_it_never_runs_sudo() -> None:
    code = [
        line
        for line in SCRIPT.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert not any("sudo " in line and "say " not in line for line in code)


def test_shellcheck() -> None:
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        pytest.skip("shellcheck is not installed (brew install shellcheck, or uvx shellcheck-py)")
    result = subprocess.run(
        [shellcheck, "--shell=sh", "--severity=style", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout
