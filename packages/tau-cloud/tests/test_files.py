"""The file set helpers and the container's tau.toml patch."""

from __future__ import annotations

import os
import stat
import tomllib
from pathlib import Path

import pytest
from tau_cloud.files import (
    FILE_NAMES,
    FileError,
    check_name,
    cloud_config,
    download,
    list_remote,
    read_local,
    upload,
    write_local,
)
from tau_net.spine import SpineClient, SpineError
from tau_net.testing import FakeSpine

ORIGINAL = """\
# tau.toml of the owner's machine
[models.roles.brain]
provider = "fake"   # scripted
model_id = "fake-brain"

[sessions]
# where sessions live
backend = "file"   # on this machine

[ui]
language = "tr"
"""


def test_the_set_is_closed(tmp_path: Path) -> None:
    assert FILE_NAMES == ("tau.toml", "persona/persona.md", "persona/user.md", "persona/net.md")
    for name in (".env", "persona/../.env", "tools/x.py", "persona/other.md", "/etc/passwd"):
        with pytest.raises(FileError, match="is not one of the cloud-mode files"):
            check_name(name)
        with pytest.raises(FileError):
            read_local(tmp_path, name)
        with pytest.raises(FileError):
            write_local(tmp_path, name, "x")
    assert not any(tmp_path.iterdir())


def test_read_local_refuses_what_the_spine_would(tmp_path: Path) -> None:
    assert read_local(tmp_path, "tau.toml") is None
    (tmp_path / "tau.toml").mkdir()
    with pytest.raises(FileError, match="not a regular file"):
        read_local(tmp_path, "tau.toml")
    (tmp_path / "persona").mkdir()
    (tmp_path / "persona" / "persona.md").write_bytes(b"\xff\xfe")
    with pytest.raises(FileError, match="not UTF-8"):
        read_local(tmp_path, "persona/persona.md")


def test_write_local_modes_and_force(tmp_path: Path) -> None:
    created = write_local(tmp_path, "persona/user.md", "private\n")
    assert created.outcome == "written"
    assert stat.S_IMODE(created.path.stat().st_mode) == 0o600
    assert write_local(tmp_path, "persona/user.md", "private\n").outcome == "unchanged"
    assert write_local(tmp_path, "persona/user.md", "other\n").outcome == "kept"
    assert created.path.read_text(encoding="utf-8") == "private\n"
    os.chmod(created.path, 0o640)
    assert write_local(tmp_path, "persona/user.md", "other\n", force=True).outcome == "written"
    assert created.path.read_text(encoding="utf-8") == "other\n"
    assert stat.S_IMODE(created.path.stat().st_mode) == 0o640
    assert [p.name for p in (tmp_path / "persona").iterdir()] == ["user.md"]  # no temp files


def test_upload_download_list(spine: FakeSpine, client: SpineClient, tmp_path: Path) -> None:
    (tmp_path / "tau.toml").write_text('[ui]\nlanguage = "en"\n', encoding="utf-8")
    file = read_local(tmp_path, "tau.toml")
    assert file is not None
    remote = upload(client, file)
    assert remote.name == "tau.toml" and remote.size == file.size and remote.updated_at > 0
    assert download(client, "tau.toml") == file.text
    assert download(client, "persona/net.md") is None
    assert [entry.name for entry in list_remote(client)] == ["tau.toml"]
    spine.mode = "local"
    with pytest.raises(SpineError, match="cloud_mode_off"):
        download(client, "tau.toml")


def test_cloud_config_changes_two_keys_and_nothing_else() -> None:
    patched = cloud_config(ORIGINAL)
    assert patched == ORIGINAL.replace(
        'backend = "file"   # on this machine', 'backend = "spine" # set by tau cloud run'
    ) + ('\n[component.net]\nstore = "spine" # set by tau cloud run\n')
    data = tomllib.loads(patched)
    assert data["sessions"] == {"backend": "spine"}
    assert data["component"] == {"net": {"store": "spine"}}
    assert data["ui"] == {"language": "tr"}


def test_cloud_config_adds_missing_tables_and_keeps_others() -> None:
    text = '[models.roles.brain]\nprovider = "fake"\nmodel_id = "x"\n\n[component.net]\n'
    text += 'name = "Alice\'s tau"  # on the card\nstore = "file"\n\n[component.other]\nx = 1\n'
    data = tomllib.loads(cloud_config(text))
    assert data["sessions"] == {"backend": "spine"}
    assert data["component"] == {
        "net": {"name": "Alice's tau", "store": "spine"},
        "other": {"x": 1},
    }
    assert "# on the card" in cloud_config(text)
    dotted = tomllib.loads(cloud_config('sessions = { backend = "file" }\ncomponent.net.a = 1\n'))
    assert dotted["sessions"] == {"backend": "spine"}
    assert dotted["component"]["net"] == {"a": 1, "store": "spine"}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[sessions\n", "could not be read"),
        ('sessions = "file"\n', r"\[sessions\] must be a table"),
        ("component = 3\n", r"\[component\] must be a table"),
        ("[component]\nnet = 3\n", r"\[component.net\] must be a table"),
    ],
)
def test_cloud_config_refuses_what_it_cannot_patch(text: str, message: str) -> None:
    with pytest.raises(FileError, match=message):
        cloud_config(text)
