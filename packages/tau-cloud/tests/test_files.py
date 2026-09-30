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
    LocalFile,
    Refused,
    check_name,
    cloud_config,
    delete_remote,
    download,
    is_sub_file,
    list_remote,
    read_local,
    remote_listing,
    scan_subs,
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
    odd = (".env", "persona/../.env", "tools/x.py", "persona/other.md", "/etc/passwd")
    subs = ("persona/subs/.hidden.md", "persona/subs/x.txt", "persona/subs/a/b.md")
    subs += ("persona/subs/../user.md", "persona/subs/Bad Name.md", "persona/subs/")
    for name in (*odd, *subs):
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


# -- sub-tau files (persona/subs/*.md) -----------------------------------------------------------


def test_sub_file_names() -> None:
    for name in ("coach.md", "coach.public.md", "A1_b-c.d.md", "x" * 81 + ".md"):
        assert is_sub_file(f"persona/subs/{name}"), name
        assert check_name(f"persona/subs/{name}") == f"persona/subs/{name}"
    for name in (".hidden.md", "-x.md", "x.txt", "x.md.bak", "a/b.md", "x" * 82 + ".md", ""):
        assert not is_sub_file(f"persona/subs/{name}"), name
    assert not is_sub_file("persona/coach.md")
    assert not is_sub_file("subs/coach.md")


def test_scan_subs_sends_md_files_and_refuses_the_rest(tmp_path: Path) -> None:
    assert scan_subs(tmp_path) == ([], [])
    subs = tmp_path / "persona" / "subs"
    subs.mkdir(parents=True)
    for name in ("coach.md", "coach.public.md", "Bad Name.md", ".hidden.md", "x.txt"):
        (subs / name).write_text("x\n", encoding="utf-8")
    (subs / "drafts").mkdir()
    (subs / "drafts" / "inner.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "persona" / "user.md").write_text("private\n", encoding="utf-8")
    (subs / "linked.md").symlink_to(tmp_path / "persona" / "user.md")
    names, refused = scan_subs(tmp_path)
    assert names == ["persona/subs/coach.md", "persona/subs/coach.public.md"]
    assert refused == [
        Refused("persona/subs/.hidden.md", "name"),
        Refused("persona/subs/Bad Name.md", "name"),
        Refused("persona/subs/drafts", "not_file"),
        Refused("persona/subs/linked.md", "link"),
        Refused("persona/subs/x.txt", "name"),
    ]
    with pytest.raises(FileError, match="symbolic link"):
        read_local(tmp_path, "persona/subs/linked.md")


def test_sub_files_go_up_and_come_down_private(
    spine: FakeSpine, client: SpineClient, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    (source / "persona" / "subs").mkdir(parents=True)
    (source / "persona" / "subs" / "coach.md").write_text("+++\n+++\nCoach.\n", encoding="utf-8")
    file = read_local(source, "persona/subs/coach.md")
    assert file is not None
    assert upload(client, file).name == "persona/subs/coach.md"
    upload(client, LocalFile("tau.toml", source / "tau.toml", "[ui]\n"))
    assert [entry.name for entry in list_remote(client)] == ["tau.toml", "persona/subs/coach.md"]

    target = tmp_path / "target"
    text = download(client, "persona/subs/coach.md")
    assert text == "+++\n+++\nCoach.\n"
    written = write_local(target, "persona/subs/coach.md", text)
    assert written.outcome == "written"
    assert stat.S_IMODE(written.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(written.path.parent.stat().st_mode) == 0o700

    assert delete_remote(client, "persona/subs/coach.md") is True
    assert delete_remote(client, "persona/subs/coach.md") is False
    assert [entry.name for entry in list_remote(client)] == ["tau.toml"]


def test_the_listing_ignores_names_outside_the_set(spine: FakeSpine, client: SpineClient) -> None:
    spine.files["persona/subs/coach.md"] = {"text": "x", "updated_at": 1}
    spine.files["persona/subs/../../evil.md"] = {"text": "x", "updated_at": 1}
    spine.files["tools/x.py"] = {"text": "x", "updated_at": 1}
    listing = remote_listing(client)
    assert [entry.name for entry in listing.files] == ["persona/subs/coach.md"]
    assert listing.ignored == ["persona/subs/../../evil.md", "tools/x.py"]
