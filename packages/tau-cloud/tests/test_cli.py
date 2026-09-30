"""``tau cloud push|pull|status`` through click's CliRunner, over the fake spine (no sockets)."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from cloud_helpers import SECRET, USER_FACT, invoke, make_home, spine_env
from tau_cloud.testing import FakeCloud
from tau_net.testing import DEFAULT_HUB_TOKEN, FakeSpine

PUBLIC = ["persona/net.md", "persona/persona.md", "tau.toml"]
EVERYTHING = sorted([*PUBLIC, "persona/user.md"])


def stored(spine: FakeSpine) -> list[str]:
    return sorted(spine.files)


# -- push --------------------------------------------------------------------------------------


def test_push_with_yes_leaves_user_md_out(tmp_path: Path, spine: FakeSpine) -> None:
    home = make_home(tmp_path)
    result = invoke(spine, home, "push", "--yes")
    assert result.exit_code == 0, result.output
    assert stored(spine) == PUBLIC
    assert "Uploaded tau.toml (" in result.output
    assert "persona/user.md was not uploaded. To upload it: tau cloud push --include-user" in (
        result.output
    )
    assert "apply from its next start" in result.output
    assert spine.files["tau.toml"]["text"] == (home / "tau.toml").read_text(encoding="utf-8")


def test_push_without_a_terminal_needs_yes(tmp_path: Path, spine: FakeSpine) -> None:
    home = make_home(tmp_path)
    result = invoke(spine, home, "push", "--include-user")
    assert result.exit_code == 1
    assert "tau cloud: nothing was uploaded: pass --yes" in result.output
    assert stored(spine) == []


def test_push_include_user(tmp_path: Path, spine: FakeSpine) -> None:
    home = make_home(tmp_path)
    result = invoke(spine, home, "push", "--yes", "--include-user")
    assert result.exit_code == 0, result.output
    assert stored(spine) == EVERYTHING
    assert spine.files["persona/user.md"]["text"] == USER_FACT + "\n"
    assert "was not uploaded" not in result.output


def test_env_is_never_sent(tmp_path: Path, spine: FakeSpine) -> None:
    home = make_home(tmp_path)
    (home / "tools").mkdir()
    (home / "tools" / "mine.py").write_text("SECRET = 1\n", encoding="utf-8")
    result = invoke(spine, home, "push", "--yes", "--include-user")
    assert result.exit_code == 0, result.output
    assert all(".env" not in path and "tools" not in path for _, path in spine.requests)
    assert not any(SECRET in entry["text"] for entry in spine.files.values())
    assert SECRET not in result.output


def test_push_reads_the_spine_from_dotenv(tmp_path: Path, spine: FakeSpine) -> None:
    home = make_home(tmp_path)
    with (home / ".env").open("a", encoding="utf-8") as handle:
        handle.write(f"TAU_SPINE_URL={spine.url}\nTAU_SPINE_TOKEN={DEFAULT_HUB_TOKEN}\n")
    from click.testing import CliRunner
    from tau_cloud.cli import cloud

    result = CliRunner().invoke(
        cloud, ["push", "--yes"], obj={"home": home, "cloud_transport": spine}
    )
    assert result.exit_code == 0, result.output
    assert stored(spine) == PUBLIC


def test_push_asks_in_a_terminal(tmp_path: Path, spine: FakeSpine) -> None:
    home = make_home(tmp_path)
    no = invoke(spine, home, "push", interactive=True, input="n\n")
    assert no.exit_code == 1 and "Nothing was uploaded." in no.output
    assert stored(spine) == []

    keep_user = invoke(spine, home, "push", interactive=True, input="y\nn\n")
    assert keep_user.exit_code == 0, keep_user.output
    assert f"These files go to the spine at {spine.url}, in your own Cloudflare account" in (
        keep_user.output
    )
    assert "persona/user.md holds what tau knows about you" in keep_user.output
    assert "stored in your own Cloudflare account (D1 and KV" in keep_user.output
    assert stored(spine) == PUBLIC

    with_user = invoke(spine, home, "push", interactive=True, input="y\ny\n")
    assert with_user.exit_code == 0, with_user.output
    assert stored(spine) == EVERYTHING


def test_push_with_yes_asks_nothing_in_a_terminal(tmp_path: Path, spine: FakeSpine) -> None:
    home = make_home(tmp_path)
    result = invoke(spine, home, "push", "--yes", interactive=True)
    assert result.exit_code == 0, result.output
    assert "[y/N]" not in result.output
    assert stored(spine) == PUBLIC


def test_push_without_a_net_note_or_user_file(tmp_path: Path, spine: FakeSpine) -> None:
    home = make_home(tmp_path, net_note=False, user=False)
    result = invoke(spine, home, "push", "--yes")
    assert result.exit_code == 0, result.output
    assert stored(spine) == ["persona/persona.md", "tau.toml"]
    assert "user.md" not in result.output and "net.md" not in result.output


def test_push_needs_a_cloud_spine(tmp_path: Path, spine: FakeSpine) -> None:
    home = make_home(tmp_path)
    spine.mode = "local"
    result = invoke(spine, home, "push", "--yes")
    assert result.exit_code == 1
    assert f"the spine at {spine.url} runs in local mode" in result.output
    assert stored(spine) == []


def test_push_needs_the_spine_variables(tmp_path: Path, spine: FakeSpine) -> None:
    home = make_home(tmp_path)
    result = invoke(spine, home, "push", "--yes", env={})
    assert result.exit_code == 1
    assert "TAU_SPINE_URL and TAU_SPINE_TOKEN must be set" in result.output


def test_push_refuses_a_broken_tau_toml(tmp_path: Path, spine: FakeSpine) -> None:
    home = make_home(tmp_path)
    (home / "tau.toml").write_text("[sessions]\nbackend = 3\n", encoding="utf-8")
    result = invoke(spine, home, "push", "--yes")
    assert result.exit_code == 2
    assert "[sessions] 'backend' must be a string" in result.output
    assert stored(spine) == []


def test_push_without_tau_toml(tmp_path: Path, spine: FakeSpine) -> None:
    result = invoke(spine, tmp_path / "empty", "push", "--yes")
    assert result.exit_code == 1
    assert "tau.toml does not exist; run `tau init` first" in result.output


def test_push_refuses_a_file_too_large(tmp_path: Path, spine: FakeSpine) -> None:
    home = make_home(tmp_path)
    (home / "persona" / "net.md").write_text("x" * (512 * 1024 + 1), encoding="utf-8")
    result = invoke(spine, home, "push", "--yes")
    assert result.exit_code == 1
    assert "net.md is larger than 512 KiB" in result.output
    assert stored(spine) == []


# -- pull --------------------------------------------------------------------------------------


def test_pull_into_a_new_home_then_never_overwrite(tmp_path: Path, spine: FakeSpine) -> None:
    source = make_home(tmp_path / "source")
    assert invoke(spine, source, "push", "--yes", "--include-user").exit_code == 0

    target = tmp_path / "new"
    first = invoke(spine, target, "pull")
    assert first.exit_code == 0, first.output
    for name in EVERYTHING:
        assert (target / name).read_text(encoding="utf-8") == (source / name).read_text(
            encoding="utf-8"
        )
        assert f"Wrote {target / name}." in first.output
    assert stat.S_IMODE((target / "persona" / "user.md").stat().st_mode) == 0o600
    assert not (target / ".env").exists()

    persona = target / "persona" / "persona.md"
    persona.write_text("My own local persona.\n", encoding="utf-8")
    again = invoke(spine, target, "pull")
    assert again.exit_code == 1
    assert f"Kept {persona}: it differs from the spine's copy." in again.output
    assert f"{target / 'tau.toml'} is already up to date." in again.output
    assert "tau cloud pull --force" in again.output
    assert persona.read_text(encoding="utf-8") == "My own local persona.\n"

    forced = invoke(spine, target, "pull", "--force")
    assert forced.exit_code == 0, forced.output
    assert f"Wrote {persona}." in forced.output
    assert persona.read_text(encoding="utf-8") == (source / "persona" / "persona.md").read_text(
        encoding="utf-8"
    )


def test_pull_from_an_empty_spine(tmp_path: Path, spine: FakeSpine) -> None:
    result = invoke(spine, tmp_path / "new", "pull")
    assert result.exit_code == 1
    assert "The spine holds no files yet. Upload them first: tau cloud push" in result.output
    assert not (tmp_path / "new").exists()


def test_pull_needs_a_cloud_spine(tmp_path: Path, spine: FakeSpine) -> None:
    spine.mode = "local"
    result = invoke(spine, tmp_path / "new", "pull")
    assert result.exit_code == 1 and "runs in local mode" in result.output


# -- status ------------------------------------------------------------------------------------


def test_status_with_files_and_brain_states(
    tmp_path: Path, spine: FakeSpine, cloud: FakeCloud
) -> None:
    home = make_home(tmp_path)
    assert invoke(spine, home, "push", "--yes").exit_code == 0

    down = invoke(spine, home, "status")
    assert down.exit_code == 0, down.output
    assert f"spine:  {spine.url}: address spine.example, mode cloud, version 0.1.0" in down.output
    assert "files:\n  tau.toml  " in down.output
    assert "  persona/net.md  " in down.output and "user.md" not in down.output
    assert "brain:  unavailable" in down.output

    cloud.brain = {"ok": True, "version": "0.1.0", "hub": None}
    starting = invoke(spine, home, "status")
    assert "brain:  running (tau-cloud 0.1.0); the hub is not answering yet" in starting.output

    cloud.brain = lambda: {"ok": True, "version": "0.1.0", "hub": {"pid": 7, "uptime_s": 3.5}}
    running = invoke(spine, home, "status")
    assert "brain:  running (tau-cloud 0.1.0); hub pid 7, up 3.5 s" in running.output

    spine.fail("GET", "/hub/brain", TimeoutError("timed out"))  # a cold start
    slow = invoke(spine, home, "status")
    assert slow.exit_code == 0 and "brain:  unavailable" in slow.output


def test_status_of_an_empty_cloud_spine(tmp_path: Path, spine: FakeSpine, cloud: FakeCloud) -> None:
    result = invoke(spine, tmp_path, "status")
    assert result.exit_code == 0, result.output
    assert "files:  none yet (tau cloud push)" in result.output


def test_status_explains_local_mode(tmp_path: Path, spine: FakeSpine, cloud: FakeCloud) -> None:
    spine.mode = "local"
    result = invoke(spine, tmp_path, "status")
    assert result.exit_code == 1
    assert "mode local" in result.output
    assert "The spine runs in local mode, so it keeps no files, sessions or brain." in (
        result.output
    )
    assert "bun run configure --cloud" in result.output


def test_status_in_turkish(tmp_path: Path, spine: FakeSpine, cloud: FakeCloud) -> None:
    result = invoke(spine, tmp_path, "status", env=spine_env(spine, TAU_LANG="tr"))
    assert result.exit_code == 0, result.output
    assert "beyin:  ulaşılamıyor" in result.output


@pytest.mark.parametrize("token", ["", "wrong"])
def test_status_with_a_bad_token(tmp_path: Path, spine: FakeSpine, token: str) -> None:
    env = {"TAU_SPINE_URL": spine.url, "TAU_SPINE_TOKEN": token}
    result = invoke(spine, tmp_path, "status", env=env)
    assert result.exit_code == 1
    if token:
        assert "spine answered 401 unauthorized" in result.output
        assert "wrong" not in result.output
    else:
        assert "must be set" in result.output


# -- sub-tau files (persona/subs/*.md, ADR 0012) ------------------------------------------------

COACH = '+++\nabout = "A coach."\npublic = true\npublic_note = "coach.public.md"\n+++\n\nCoach.\n'
COACH_NOTE = "- Public: the owner runs on Sundays.\n"
SUBS = ["persona/subs/coach.md", "persona/subs/coach.public.md"]


def add_subs(home: Path) -> Path:
    """``persona/subs/`` with a definition, its public note and entries a push must refuse."""
    subs = home / "persona" / "subs"
    subs.mkdir(mode=0o700)
    (subs / "coach.md").write_text(COACH, encoding="utf-8")
    (subs / "coach.public.md").write_text(COACH_NOTE, encoding="utf-8")
    for odd in ("Bad Name.md", ".hidden.md", "notes.txt"):
        (subs / odd).write_text("x\n", encoding="utf-8")
    (subs / "drafts").mkdir()
    (subs / "drafts" / "landing.md").write_text("x\n", encoding="utf-8")
    (subs / "leak.md").symlink_to(home / "persona" / "user.md")
    return subs


def test_push_carries_sub_taus_and_refuses_odd_names(tmp_path: Path, spine: FakeSpine) -> None:
    home = make_home(tmp_path)
    add_subs(home)
    result = invoke(spine, home, "push", "--yes")
    assert result.exit_code == 0, result.output
    assert stored(spine) == sorted([*PUBLIC, *SUBS])
    assert spine.files["persona/subs/coach.md"]["text"] == COACH
    assert spine.files["persona/subs/coach.public.md"]["text"] == COACH_NOTE
    assert "Uploaded persona/subs/coach.md (" in result.output
    for name in ("Bad Name.md", ".hidden.md", "notes.txt"):
        assert f"Skipped persona/subs/{name}: only .md files with a plain name" in result.output
    assert "Skipped persona/subs/drafts: not a regular file." in result.output
    assert "Skipped persona/subs/leak.md: a symbolic link" in result.output
    assert USER_FACT not in str(spine.files)  # the link to user.md never went up
    assert all("drafts" not in path and "Bad" not in path for _, path in spine.requests)


def test_push_removes_sub_taus_that_are_gone_here(tmp_path: Path, spine: FakeSpine) -> None:
    home = make_home(tmp_path)
    subs = add_subs(home)
    assert invoke(spine, home, "push", "--yes").exit_code == 0
    (subs / "coach.public.md").unlink()

    asked = invoke(spine, home, "push", interactive=True, input="n\n")
    assert asked.exit_code == 1
    assert (
        "These sub-tau files are gone here and are removed from the spine: "
        "persona/subs/coach.public.md"
    ) in asked.output
    assert "persona/subs/coach.public.md" in spine.files

    result = invoke(spine, home, "push", "--yes")
    assert result.exit_code == 0, result.output
    assert "Removed persona/subs/coach.public.md from the spine." in result.output
    assert stored(spine) == sorted([*PUBLIC, "persona/subs/coach.md"])


def test_push_without_a_subs_directory_keeps_the_spines(tmp_path: Path, spine: FakeSpine) -> None:
    home = make_home(tmp_path)
    add_subs(home)
    assert invoke(spine, home, "push", "--yes").exit_code == 0
    other = make_home(tmp_path / "other")  # a machine that never had sub-taus
    result = invoke(spine, other, "push", "--yes")
    assert result.exit_code == 0, result.output
    assert "persona/subs/ does not exist here; the spine keeps its 2 sub-tau files." in (
        result.output
    )
    assert stored(spine) == sorted([*PUBLIC, *SUBS])


def test_pull_writes_sub_taus_privately_and_only_valid_names(
    tmp_path: Path, spine: FakeSpine
) -> None:
    source = make_home(tmp_path / "source")
    add_subs(source)
    assert invoke(spine, source, "push", "--yes").exit_code == 0
    spine.files["persona/subs/../../escape.md"] = {"text": "x", "updated_at": 1}
    spine.files["tools/evil.py"] = {"text": "x", "updated_at": 1}

    target = tmp_path / "new"
    result = invoke(spine, target, "pull")
    assert result.exit_code == 0, result.output
    for name in SUBS:
        assert (target / name).read_text(encoding="utf-8") == (source / name).read_text(
            encoding="utf-8"
        )
        assert f"Wrote {target / name}." in result.output
        assert stat.S_IMODE((target / name).stat().st_mode) == 0o600
    assert stat.S_IMODE((target / "persona" / "subs").stat().st_mode) == 0o700
    assert "Skipped persona/subs/../../escape.md: not a name of the cloud-mode file set." in (
        result.output
    )
    assert "Skipped tools/evil.py" in result.output
    assert not (tmp_path / "escape.md").exists() and not (target / "escape.md").exists()
    assert not (target / "tools").exists()
    assert sorted(p.name for p in (target / "persona" / "subs").iterdir()) == [
        "coach.md",
        "coach.public.md",
    ]

    # A pull never deletes: a local sub-tau the spine does not hold stays.
    (target / "persona" / "subs" / "mine.md").write_text("x\n", encoding="utf-8")
    again = invoke(spine, target, "pull")
    assert again.exit_code == 0, again.output
    assert (target / "persona" / "subs" / "mine.md").is_file()


def test_status_lists_sub_tau_files(tmp_path: Path, spine: FakeSpine, cloud: FakeCloud) -> None:
    home = make_home(tmp_path)
    add_subs(home)
    assert invoke(spine, home, "push", "--yes").exit_code == 0
    result = invoke(spine, home, "status")
    assert result.exit_code == 0, result.output
    assert "  persona/subs/coach.md  " in result.output
    assert "  persona/subs/coach.public.md  " in result.output
