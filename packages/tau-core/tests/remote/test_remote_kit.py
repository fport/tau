"""The remote kit tau-core ships: a copy of ``infra/remote``, written where its command points.

Nothing here runs a kit script: ``bash -n`` only parses them."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest
from tau_core.remote.scripts import ENTRY, kit_files, shell_path, write_kit

ROOT = Path(__file__).resolve().parents[4]
INFRA = ROOT / "infra" / "remote"
PACKAGE = ROOT / "packages" / "tau-core"
KIT = PACKAGE / "src" / "tau_core" / "remote" / "kit"
NOT_SHIPPED = {"README.md"}
SYNC = (
    "rsync -a --delete --exclude README.md --exclude config.local.env "
    "infra/remote/ packages/tau-core/src/tau_core/remote/kit/"
)


def _tree(root: Path) -> dict[str, Path]:
    return {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.name not in NOT_SHIPPED
        and not path.name.endswith(".local.env")
    }


def test_the_kit_is_a_copy_of_infra_remote() -> None:
    infra, kit = _tree(INFRA), _tree(KIT)
    assert set(kit) == set(infra), f"copy infra/remote into the kit: {SYNC}"
    for name, path in infra.items():
        assert kit[name].read_bytes() == path.read_bytes(), f"{name} differs; run: {SYNC}"
        executable = bool(path.stat().st_mode & stat.S_IXUSR)
        assert bool(kit[name].stat().st_mode & stat.S_IXUSR) == executable, name
    assert set(kit_files()) == set(kit)


def test_the_one_command_dispatches_and_refuses_root() -> None:
    text = kit_files()[ENTRY].decode()
    assert "EUID -eq 0" in text
    darwin = text.index("Darwin)")
    assert darwin < text.index('bash "$here/setup.sh"') < text.index('bash "$here/setup-sudo.sh"')
    assert text.index("Linux)") < text.index('bash "$here/setup-linux.sh"')


def test_linux_hardens_before_it_installs_and_guards_the_last_session() -> None:
    text = kit_files()["setup-linux.sh"].decode()
    assert text.index('install -m 644 -o root -g root "$rendered"') < text.index("apt-get install")
    assert "SSH_CONNECTION" in text and "add yours first" in text
    assert text.index("sshd_config\\.d/") < text.index('"$sshd_bin" -t')


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash to parse the scripts")
def test_every_script_parses() -> None:
    for name in sorted(kit_files()):
        if name.endswith(".sh") or name == "bin/tau-attach":
            shell = "sh" if name == "bin/tau-attach" else "bash"
            done = subprocess.run([shell, "-n", str(KIT / name)], capture_output=True, text=True)
            assert done.returncode == 0, (name, done.stderr)


def test_write_kit_refreshes_and_keeps_local_settings(tmp_path: Path) -> None:
    target = tmp_path / "data" / "remote"
    write_kit(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    (target / "config.local.env").write_text("TAU_KEEPAWAKE=0\n", encoding="utf-8")
    (target / "lib.sh").write_text("tampered\n", encoding="utf-8")
    (target / "add-key.sh").chmod(0o644)
    elsewhere = tmp_path / "elsewhere.txt"
    elsewhere.write_text("keep me\n", encoding="utf-8")
    (target / "config.env").unlink()
    (target / "config.env").symlink_to(elsewhere)
    write_kit(target)
    files = kit_files()
    assert (target / "lib.sh").read_bytes() == files["lib.sh"]
    assert stat.S_IMODE((target / "add-key.sh").stat().st_mode) == 0o755
    assert not (target / "config.env").is_symlink()
    assert (target / "config.env").read_bytes() == files["config.env"]
    assert elsewhere.read_text(encoding="utf-8") == "keep me\n"
    assert (target / "config.local.env").read_text(encoding="utf-8") == "TAU_KEEPAWAKE=0\n"
    assert not [p for p in target.rglob(".*.tmp")]


def test_shell_path(tmp_path: Path) -> None:
    home = tmp_path / "me"
    assert shell_path(home / ".local" / "share" / "tau" / "remote" / ENTRY, home) == (
        "~/.local/share/tau/remote/setup-all.sh"
    )
    assert shell_path(home, home) == "~"
    spaced = home / "My Code" / "setup-all.sh"
    assert shell_path(spaced, home) == f"'{spaced}'"
    assert shell_path(Path("/opt/tau/setup-all.sh"), home) == "/opt/tau/setup-all.sh"


@pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv to build the wheel")
def test_the_kit_is_in_the_built_wheel_and_sdist(tmp_path: Path) -> None:
    build = subprocess.run(
        ["uv", "build", str(PACKAGE), "--out-dir", str(tmp_path), "--quiet"],
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "UV_NO_PROGRESS": "1"},
    )
    assert build.returncode == 0, build.stderr
    expected = {name: path.read_bytes() for name, path in _tree(KIT).items()}
    (wheel,) = tmp_path.glob("tau_core-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        shipped = {
            info.filename.removeprefix("tau_core/remote/kit/"): archive.read(info)
            for info in archive.infolist()
            if info.filename.startswith("tau_core/remote/kit/")
        }
        modes = {
            info.filename.removeprefix("tau_core/remote/kit/"): info.external_attr >> 16
            for info in archive.infolist()
            if info.filename.startswith("tau_core/remote/kit/")
        }
    assert shipped == expected
    assert modes[ENTRY] & stat.S_IXUSR
    (sdist,) = tmp_path.glob("tau_core-*.tar.gz")
    with tarfile.open(sdist) as archive:
        names = {name.split("/src/tau_core/remote/kit/", 1)[-1] for name in archive.getnames()}
    assert set(expected) <= names
