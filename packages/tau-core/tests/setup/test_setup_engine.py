"""``tau setup``'s catalog, message keys, detection and engine (issue 169).

Offline: a :class:`FakeHost` stands for the machine, every path is under ``tmp_path``."""

from __future__ import annotations

import json
import os
import stat
import string
from pathlib import Path

import pytest
from setup_fakes import UV, FakeHost
from tau_core.builder import template_text
from tau_core.i18n import MESSAGES, t
from tau_core.setup import CatalogError, load_catalog, parse_catalog
from tau_core.setup.engine import (
    ResumeError,
    install_plan,
    parse_ids,
    preflight,
    read_state,
    render_user_md,
    step_argv,
    store_secrets,
    write_state,
    write_user_md,
)
from tau_core.setup.state import about_done, read_receipt, take_snapshot
from tau_core.setup.strings import SETUP_MESSAGES

# -- the catalog -----------------------------------------------------------------------------------


def test_the_shipped_catalog_loads() -> None:
    catalog = load_catalog()
    assert catalog.ids() == (
        "tui",
        "app",
        "sub",
        "telegram",
        "remote",
        "guard",
        "net",
        "autostart",
        "cloud",
    )
    assert catalog.packages() == ("tau-tui", "tau-sub", "tau-guard", "tau-net", "tau-cloud")
    guard = catalog.get("guard")
    assert guard is not None
    assert guard.platforms == ("darwin",) and guard.permissions == ("camera",)
    assert [s.id for s in guard.steps] == ["doctor", "setup", "restart"]
    assert guard.steps[1].local_only and guard.steps[1].interactive
    assert catalog.get("autostart").default_on == ("darwin",)  # type: ignore[union-attr]
    assert catalog.get("tui").default_on == ("darwin", "linux")  # type: ignore[union-attr]
    for off in ("telegram", "remote", "guard", "net", "cloud"):
        assert catalog.get(off).default_on == ()  # type: ignore[union-attr]
    assert catalog.with_requires(["cloud"]) == ["net", "cloud"]
    assert catalog.docs_url(guard, "tr") == "https://docs.tau.getporti.com/tr/guides/guard/"


def test_no_step_runs_anything_but_tau() -> None:
    for feature in load_catalog().features:
        for step in feature.steps:
            assert "sudo" not in step.command
            if step.kind == "command":
                assert step.command[0] in {"guard", "net", "hub", "telegram", "sub", "cloud"}


def test_every_setup_message_has_both_languages_and_the_same_fields() -> None:
    fields = string.Formatter()
    for key, templates in SETUP_MESSAGES.items():
        assert set(templates) == {"en", "tr"}, key
        names = {
            language: {name for _, name, _, _ in fields.parse(text) if name}
            for language, text in templates.items()
        }
        assert names["en"] == names["tr"], key
        assert MESSAGES[key] == templates  # registered into the table


def test_every_catalog_text_is_translated() -> None:
    catalog = load_catalog()
    keys = []
    for feature in catalog.features:
        keys += [feature.label, feature.description, feature.unavailable]
        keys += [feature.keep_while_configured]
        for step in feature.steps:
            keys += [step.label, step.text, step.unavailable, step.needs_text]
            keys += [item.label for item in step.inputs]
    for key in filter(None, keys):
        assert t(key, "en") != t(key, "tr") or key.endswith(".telegram"), key


MINIMAL = """
schema = 1
docs = "https://docs.example.com/"

[[feature]]
id = "one"
label = "setup.feature.tui"
description = "setup.feature.tui.about"
platforms = ["darwin", "linux"]
"""


def test_a_minimal_catalog_parses() -> None:
    catalog = parse_catalog(MINIMAL)
    assert catalog.ids() == ("one",)
    assert catalog.get("one").default_on == ()  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("extra", "error"),
    [
        ("surprise = 1\n", "unknown keys surprise"),
        ('package = "tau-core"\n', "invalid package"),
        ('permissions = ["keychain"]\n', "unknown permissions"),
        ('requires = ["nothing"]\n', "requires unknown"),
        ("lockstep = true\n", "`lockstep` needs a package"),
        ('docs = "https://elsewhere/"\n', "relative"),
        (
            '[[feature.step]]\nid = "x"\nlabel = "setup.step.guard.setup"\n'
            'command = ["sudo", "rm"]\n',
            "invalid command word",
        ),
        (
            '[[feature.step]]\nid = "x"\nlabel = "setup.step.guard.setup"\ncommand = ["a"]\n'
            '[[feature.step.input]]\nname = "k"\nlabel = "setup.input.owner"\n'
            'secret = true\nflag = "--key"\n',
            "a secret never reaches argv",
        ),
        (
            '[[feature.step]]\nid = "x"\nlabel = "setup.step.guard.setup"\ncommand = ["a"]\n'
            '[[feature.step.input]]\nname = "k"\nlabel = "setup.input.owner"\nsecret = true\n',
            "a secret needs `env`",
        ),
        (
            '[[feature.step]]\nid = "x"\nlabel = "setup.no.such.key"\ncommand = ["a"]\n',
            "no message `setup.no.such.key`",
        ),
        (
            '[[feature.step]]\nid = "x"\nkind = "note"\nlabel = "setup.step.guard.setup"\n'
            'text = "setup.note.guard.restart"\ncommand = ["a"]\n',
            "a note has only",
        ),
        (
            '[[feature.step]]\nid = "x"\nlabel = "setup.step.guard.setup"\ncommand = ["a"]\n'
            'when_command = ["a"]\n',
            "`when_command` needs `unavailable`",
        ),
    ],
)
def test_catalog_mistakes_are_refused(extra: str, error: str) -> None:
    with pytest.raises(CatalogError, match=error):
        parse_catalog(MINIMAL + extra)


def test_a_feature_missing_a_platform_says_why() -> None:
    text = MINIMAL.replace('platforms = ["darwin", "linux"]', 'platforms = ["darwin"]')
    with pytest.raises(CatalogError, match="needs `unavailable`"):
        parse_catalog(text)


def test_requires_must_not_form_a_cycle_and_come_first() -> None:
    two = MINIMAL + (
        'requires = ["two"]\n\n[[feature]]\nid = "two"\nlabel = "setup.feature.sub"\n'
        'description = "setup.feature.sub.about"\nplatforms = ["darwin", "linux"]\n'
    )
    with pytest.raises(CatalogError, match="must come after"):
        parse_catalog(two)
    cycle = two + 'requires = ["one"]\n'
    with pytest.raises(CatalogError, match="must come after|cycle"):
        parse_catalog(cycle)


def test_parse_ids() -> None:
    assert parse_ids(["tui,sub", " net ", "sub"]) == ["tui", "sub", "net"]


# -- detection -------------------------------------------------------------------------------------


def test_a_fresh_machine(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-tui": "0.4.0"})
    snapshot = take_snapshot(host, load_catalog())
    assert snapshot.version == "0.4.0"
    assert snapshot.home == host.home and snapshot.data == host.data.resolve()
    assert not snapshot.config and not snapshot.about and not snapshot.ssh and snapshot.uv_tool
    states = {s.feature.id: s.state for s in snapshot.features}
    assert states == {
        "tui": "done",
        "app": "available",
        "sub": "missing",
        "telegram": "available",
        "remote": "available",
        "guard": "missing",
        "net": "missing",
        "autostart": "available",
        "cloud": "missing",
    }


def test_linux_has_no_guard_and_no_app(tmp_path: Path) -> None:
    snapshot = take_snapshot(FakeHost(tmp_path, platform="linux"), load_catalog())
    assert snapshot.get("guard").state == "unavailable"  # type: ignore[union-attr]
    assert snapshot.get("app").state == "unavailable"  # type: ignore[union-attr]


def test_configured_rules(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-guard": "0.4.0", "tau-net": "0.1.0"}, ssh=True)
    host.write_config()
    catalog = load_catalog()
    before = take_snapshot(host, catalog)
    assert before.ssh
    assert before.get("guard").state == "installed"  # type: ignore[union-attr]
    assert before.get("net").state == "installed"  # type: ignore[union-attr]
    (host.data / "guard").mkdir(parents=True)
    (host.data / "guard" / "enrolled").write_text("{}", encoding="utf-8")
    (host.data / "net").mkdir(parents=True)
    (host.data / "net" / "identity.json").write_text("{}", encoding="utf-8")
    (host.home / ".env").write_text(
        "TELEGRAM_BOT_TOKEN=1:x\nTELEGRAM_ALLOWED_CHAT_IDS=1\n", encoding="utf-8"
    )
    agents = host.user / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "com.tau.hub.plist").write_text("<plist/>", encoding="utf-8")
    after = take_snapshot(host, catalog)
    for fid in ("guard", "net", "telegram", "autostart"):
        assert after.get(fid).state == "done", fid  # type: ignore[union-attr]


def test_about_is_done_only_with_own_facts(tmp_path: Path) -> None:
    home = tmp_path / "home"
    assert not about_done(home)
    (home / "persona").mkdir(parents=True)
    user = home / "persona" / "user.md"
    user.write_text(template_text("user.example.md"), encoding="utf-8")
    assert not about_done(home)
    user.write_text("<!-- only a comment -->\n", encoding="utf-8")
    assert not about_done(home)
    user.write_text(render_user_md(name="Deniz"), encoding="utf-8")
    assert about_done(home)


def test_the_receipt(tmp_path: Path) -> None:
    (tmp_path / "uv-receipt.toml").write_text(
        """[tool]
requirements = [
    { name = "tau-core", specifier = "==0.4.0" },
    { name = "tau-tui" },
    { name = "extra-plugin", extras = ["fast"], specifier = ">=1" },
    { name = "local-plugin", path = "/tmp/local_plugin-1.0-py3-none-any.whl" },
    { name = "git-plugin", git = "https://example.com/x.git" },
]
python = "3.12"
""",
        encoding="utf-8",
    )
    receipt = read_receipt(tmp_path)
    assert receipt is not None and receipt.python == "3.12"
    assert [(r.name, r.spec) for r in receipt.requirements] == [
        ("tau-core", "tau-core==0.4.0"),
        ("tau-tui", "tau-tui"),
        ("extra-plugin", "extra-plugin[fast]>=1"),
        ("local-plugin", "/tmp/local_plugin-1.0-py3-none-any.whl"),
        ("git-plugin", None),
    ]
    assert read_receipt(tmp_path / "nowhere") is None


# -- the install plan ------------------------------------------------------------------------------


def test_the_install_pins_lockstep_packages_and_keeps_the_rest(tmp_path: Path) -> None:
    receipt = """[tool]
requirements = [
    { name = "tau-core" },
    { name = "tau-tui" },
    { name = "my-plugin", specifier = ">=2" },
]
python = "3.12"
"""
    host = FakeHost(tmp_path, installed={"tau-tui": "0.4.0"}, receipt=receipt)
    catalog = load_catalog()
    plan = install_plan(catalog, take_snapshot(host, catalog), host, add=["guard", "net", "tui"])
    assert plan.uv == UV
    assert plan.added == ("tau-guard", "tau-net") and plan.removed == ()
    assert plan.packages == ("tau-tui", "tau-guard", "tau-net")
    assert list(plan.argv) == [
        UV,
        "tool",
        "install",
        "--force",
        "--python",
        "3.12",
        "tau-core==0.4.0",
        "--with",
        "tau-tui==0.4.0",
        "--with",
        "tau-guard==0.4.0",
        "--with",
        "tau-net",
        "--with",
        "my-plugin>=2",
    ]


def test_remove_and_upgrade(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-tui": "0.4.0", "tau-sub": "0.1.0"})
    catalog = load_catalog()
    snapshot = take_snapshot(host, catalog)
    removal = install_plan(catalog, snapshot, host, remove=["tui"])
    assert removal.removed == ("tau-tui",)
    assert removal.argv[-3:] == ("tau-core==0.4.0", "--with", "tau-sub")
    upgrade = install_plan(catalog, snapshot, host, upgrade=True)
    assert "--upgrade" in upgrade.argv
    assert upgrade.argv[-5:] == ("tau-core", "--with", "tau-tui", "--with", "tau-sub")


def test_no_uv_no_command(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, programs=())
    catalog = load_catalog()
    plan = install_plan(catalog, take_snapshot(host, catalog), host, add=["sub"])
    assert plan.uv is None and plan.argv == () and plan.added == ("tau-sub",)


# -- the resume file -------------------------------------------------------------------------------


def test_the_resume_file_is_private_and_read_once() -> None:
    path = write_state({"language": "tr", "features": ["guard"], "yes": False})
    try:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert read_state(path) == {"v": 1, "language": "tr", "features": ["guard"], "yes": False}
        assert not path.exists() and not path.parent.exists()
    finally:
        path.unlink(missing_ok=True)


def test_a_resume_file_others_can_read_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"v": 1}), encoding="utf-8")
    os.chmod(path, 0o644)
    with pytest.raises(ResumeError, match="open to other users"):
        read_state(path)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    with pytest.raises(ResumeError):
        read_state(link)  # O_NOFOLLOW: a symlink is never followed
    assert path.exists()
    os.chmod(path, 0o600)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ResumeError, match="not a tau setup state"):
        read_state(path)
    with pytest.raises(ResumeError):
        read_state(tmp_path / "missing.json")


# -- steps -----------------------------------------------------------------------------------------

SECRET_CATALOG = (
    MINIMAL
    + """
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

[[feature.step.input]]
name = "dir"
label = "setup.input.spine_dir"
positional = true
path = true
default = "~/tau-spine"

[[feature.step.input]]
name = "name"
label = "setup.input.net_name"
flag = "--name"
"""
)


def test_step_argv_and_secrets(tmp_path: Path) -> None:
    step = parse_catalog(SECRET_CATALOG).features[0].steps[0]
    environ = {"HOME": str(tmp_path / "user")}
    assert step_argv(step, {}, environ) == ([], "token")
    argv, missing = step_argv(step, {"token": "123:secret", "name": "Alice's tau"}, environ)
    assert missing is None
    assert argv == [
        "telegram",
        "pair",
        str(tmp_path / "user" / "tau-spine"),
        "--name",
        "Alice's tau",
    ]
    assert "123:secret" not in argv
    home = tmp_path / "home"
    assert store_secrets(step, {"token": "123:secret"}, home) == [("TELEGRAM_BOT_TOKEN", True)]
    dotenv = home / ".env"
    assert dotenv.read_text(encoding="utf-8") == "TELEGRAM_BOT_TOKEN=123:secret\n"
    assert stat.S_IMODE(dotenv.stat().st_mode) == 0o600
    assert store_secrets(step, {"token": "other"}, home) == [("TELEGRAM_BOT_TOKEN", False)]


def test_preflight(tmp_path: Path) -> None:
    catalog = load_catalog()
    guard = catalog.get("guard")
    net = catalog.get("net")
    telegram = catalog.get("telegram")
    assert guard is not None and net is not None and telegram is not None
    local = FakeHost(tmp_path, commands=[["telegram", "pair"]], programs=("uv", "node"))
    assert preflight(guard.steps[1], guard, local) is None
    assert preflight(telegram.steps[0], telegram, local) is None
    assert preflight(net.steps[2], net, local) is None
    remote = FakeHost(tmp_path, ssh=True)
    skip = preflight(guard.steps[1], guard, remote)
    assert skip is not None and skip.reason == "ssh"
    skip = preflight(telegram.steps[0], telegram, remote)
    assert skip is not None and skip.reason == "missing_command"
    assert skip.text_key == "setup.note.telegram.manual"
    # deploying a spine needs no Node since issue 174: nothing to preflight
    assert preflight(net.steps[2], net, remote) is None
    linux = FakeHost(tmp_path, platform="linux")
    skip = preflight(guard.steps[0], guard, linux)
    assert skip is not None and skip.reason == "platform"


def test_user_md(tmp_path: Path) -> None:
    text = render_user_md(name=" Deniz\n", address="by first name, informal", languages="")
    assert text.endswith("- Name: Deniz\n- Form of address: by first name, informal\n")
    assert "Languages" not in text
    assert "<!--" in render_user_md(name="x") and "-->x" not in render_user_md(name="-->x")
    path = write_user_md(tmp_path / "home", text)
    assert path == tmp_path / "home" / "persona" / "user.md"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
