"""The ``tau setup`` terminal wizard and its ``--yes`` form (issue 169).

Every run goes through a :class:`FakeHost`: steps are recorded instead of run, ``uv`` never
starts and ``execv`` only records the re-execution."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner, Result
from setup_fakes import TAU, UV, FakeHost
from tau_core.cli import cli
from tau_core.setup.engine import render_user_md, write_state


def invoke(host: FakeHost, args: list[str], stdin: str | None = None) -> Result:
    return CliRunner().invoke(
        cli, ["setup", *args], input=stdin, obj={"setup_host": host}, prog_name="tau"
    )


def own_facts(host: FakeHost) -> None:
    (host.home / "persona").mkdir(parents=True, exist_ok=True)
    (host.home / "persona" / "user.md").write_text(render_user_md(name="Deniz"), encoding="utf-8")


def test_yes_with_features_and_no_install_on_a_fresh_machine(tmp_path: Path) -> None:
    host = FakeHost(
        tmp_path,
        installed={"tau-tui": "0.4.0", "tau-sub": "0.1.0"},
        effects={("init",): lambda argv: host.init_effect(argv)},
    )
    result = invoke(host, ["--yes", "--features", "tui,sub", "--no-install"])
    assert result.exit_code == 0, result.output
    assert host.tau_runs() == [["init", "--language", "en", "--yes"], ["doctor"]]
    assert host.uv_runs() == [] and host.execs == []
    assert all(not captured for _, captured in host.runs)  # the steps get the terminal
    out = result.output
    assert "tau setup · tau-core 0.4.0 · macOS" in out
    assert "Summary" in out and "Terminal UI" in out and "Sub-taus" in out
    assert "on" in out and "tau chat" in out and "tau tui" in out


def test_the_first_interactive_run_installs_then_resumes(tmp_path: Path) -> None:
    host = FakeHost(
        tmp_path,
        installed={"tau-tui": "0.4.0"},
        effects={("init",): lambda argv: host.init_effect(argv)},
    )
    # language, then toggle the guard (6) on top of the defaults, Enter, confirm
    result = invoke(host, [], stdin="tr\n6\n\n\n")
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Özellikler" in out and "[x] Alt-tau'lar" in out and "[x] Oturum açılınca" in out
    assert " ✓  Terminal arayüzü" in out
    assert "Yüklenecek: tau-sub, tau-guard" in out
    assert host.environ["TAU_LANG"] == "tr"
    assert host.uv_runs() == [
        [
            UV,
            "tool",
            "install",
            "--force",
            "tau-core==0.4.0",
            "--with",
            "tau-tui==0.4.0",
            "--with",
            "tau-sub",
            "--with",
            "tau-guard==0.4.0",
        ]
    ]
    assert host.tau_runs() == []  # nothing configured before the re-execution
    [(path, argv)] = host.execs
    assert path == str(host.bin / "tau")
    assert argv[:3] == [path, "setup", "--resume"]
    state_file = Path(argv[3])
    assert json.loads(state_file.read_text(encoding="utf-8")) == {
        "v": 1,
        "language": "tr",
        "features": ["sub", "guard", "autostart"],
        "fresh": ["sub", "guard", "autostart"],
        "yes": False,
    }

    # The new environment: tau-sub and tau-guard are there now.
    host.installed.update({"tau-sub": "0.1.0", "tau-guard": "0.4.0"})
    host.effects[("guard", "setup")] = lambda argv: (
        (host.data / "guard").mkdir(parents=True, exist_ok=True),
        (host.data / "guard" / "enrolled").write_text("{}", encoding="utf-8"),
    )
    answers = "Deniz\nadımla, samimi\nTürkçe, İngilizce\n" + "\n\n\n"
    result = invoke(host, ["--resume", str(state_file)], stdin=answers)
    assert result.exit_code == 0, result.output
    assert not state_file.exists()
    assert host.tau_runs() == [
        ["init", "--language", "tr"],
        ["guard", "doctor"],
        ["guard", "setup"],
        ["hub", "install"],
        ["doctor"],
    ]
    user = (host.home / "persona" / "user.md").read_text(encoding="utf-8")
    assert (
        "- Name: Deniz\n- Form of address: adımla, samimi\n- Languages: Türkçe, İngilizce" in user
    )
    out = result.output
    assert "Yüklendi. tau setup yeni ortamda devam ediyor." in out
    assert "tau sub new coach" in out  # the sub-tau note
    assert "Hub'ı yeniden başlat" in out
    assert "Özet" in out and "Sahip koruması" in out and "açık" in out


def test_a_rerun_shows_what_is_set_up_and_never_asks_it_again(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-tui": "0.4.0", "tau-guard": "0.4.0"})
    host.write_config()
    own_facts(host)
    (host.data / "guard").mkdir(parents=True)
    (host.data / "guard" / "enrolled").write_text("{}", encoding="utf-8")
    result = invoke(host, [], stdin="1 6\n\n")
    assert result.exit_code == 0, result.output
    out = result.output
    rows = [line for line in out.splitlines() if line[:4].strip().isdigit()]
    assert len(rows) == 18 and not any("[x]" in row for row in rows)  # shown twice, none chosen
    assert "Terminal UI is already set up. To remove it: tau setup --remove tui" in out
    assert "Owner guard is already set up." in out
    assert "Nothing new to install or set up." in out
    assert host.tau_runs() == [["doctor"]]
    assert "Language" not in out  # tau.toml gives the language


def test_outside_a_uv_tool_install_nothing_is_reinstalled(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, uv_tool=False)
    host.write_config()
    own_facts(host)
    result = invoke(host, ["--yes", "--features", "net"])
    assert result.exit_code == 0, result.output
    assert host.uv_runs() == [] and host.execs == []
    assert "uv sync --all-packages" in result.output
    assert "tau-net is not installed" in result.output
    assert host.tau_runs() == [["doctor"]]


def test_the_guard_is_explained_away_on_linux(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, platform="linux", installed={"tau-guard": "0.4.0"})
    host.write_config()
    own_facts(host)
    result = invoke(host, ["--yes", "--features", "guard"])
    assert result.exit_code == 0, result.output
    assert "macOS only: the guard uses the Mac's built-in camera and Touch ID" in result.output
    assert "tau setup · tau-core 0.4.0 · Linux" in result.output
    assert not any(run[0] == "guard" for run in host.tau_runs())


def test_the_guard_setup_is_refused_over_ssh(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-guard": "0.4.0"}, ssh=True)
    host.write_config()
    own_facts(host)
    result = invoke(host, ["--features", "guard"], stdin="\n\n")  # go on, run the doctor
    assert result.exit_code == 0, result.output
    assert host.tau_runs() == [["guard", "doctor"], ["doctor"]]
    out = result.output
    assert "You are connected over SSH" in out
    assert "at the Mac only, not over SSH; run `tau guard setup` at the Mac" in out


def test_the_guard_doctor_failing_before_setup_is_expected(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-guard": "0.4.0"}, codes={("guard", "doctor"): 1})
    host.write_config()
    own_facts(host)
    result = invoke(host, ["--features", "guard"], stdin="\n\n\n")  # go on, doctor, setup
    assert result.exit_code == 0, result.output
    assert host.tau_runs() == [["guard", "doctor"], ["guard", "setup"], ["doctor"]]
    assert "reported problems (exit code 1)" in result.output


def test_telegram_without_pairing_explains_the_manual_way(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    host.write_config()
    own_facts(host)
    result = invoke(host, ["--yes", "--features", "telegram"])
    assert result.exit_code == 0, result.output
    assert "`tau telegram pair` is not available in this version" in result.output
    assert "@BotFather" in result.output
    assert host.tau_runs() == [["doctor"]]


def test_telegram_pairing_runs_when_the_command_exists(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, commands=[["telegram", "pair"]])
    host.write_config()
    own_facts(host)
    result = invoke(host, ["--features", "telegram"], stdin="\n\n")  # go on, pair
    assert result.exit_code == 0, result.output
    assert host.tau_runs() == [["telegram", "pair"], ["doctor"]]
    assert [captured for argv, captured in host.runs if argv[1:2] == ["telegram"]] == [False]
    # --yes never runs a step that needs the owner at the terminal
    host.runs.clear()
    result = invoke(host, ["--yes", "--features", "telegram"])
    assert host.tau_runs() == [["doctor"]]
    assert "needs you at the terminal; run `tau telegram pair` later" in result.output


def test_the_network_walkthrough(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-net": "0.1.0"})
    host.write_config()
    own_facts(host)
    # go on; net init (yes) and its name; universe (yes), owner, about (none); claim (no)
    answers = "\n" + "\n" + "Alice's tau\n" + "y\n" + "Alice\n" + "\n" + "\n"
    result = invoke(host, ["--features", "net"], stdin=answers)
    assert result.exit_code == 0, result.output
    assert host.tau_runs() == [
        ["net", "init", "--name", "Alice's tau"],
        ["net", "universe", "join", "--owner", "Alice"],
        ["doctor"],
    ]
    out = result.output
    assert "Node.js was not found" in out and "needs node on PATH" in out
    assert "a small Worker in your own Cloudflare account" in out
    assert "Claim a handle (a GitHub sign-in link): skipped" in out


def test_the_spine_steps_run_with_node(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-net": "0.1.0"}, programs=("uv", "node"))
    host.write_config()
    own_facts(host)
    # go on; net init (yes, no name), spine-init (yes, dir kept, address), spine-deploy
    # (yes), universe (no), claim (no)
    answers = "\n" + "\n\n" + "y\n\ntau.example.com\n" + "y\n" + "n\n" + "n\n"
    result = invoke(host, ["--features", "net"], stdin=answers)
    assert result.exit_code == 0, result.output
    spine = str(host.user / "tau-spine")
    assert host.tau_runs() == [
        ["net", "init"],
        ["net", "spine", "init", spine, "--address", "tau.example.com"],
        ["net", "spine", "deploy", spine],
        ["doctor"],
    ]


def test_a_failed_step_is_reported_and_the_others_go_on(tmp_path: Path) -> None:
    host = FakeHost(
        tmp_path,
        installed={"tau-sub": "0.1.0"},
        codes={("hub", "install"): 3},
    )
    host.write_config()
    own_facts(host)
    result = invoke(host, ["--yes", "--features", "autostart,sub,remote"])
    assert result.exit_code == 1, result.output
    assert host.tau_runs() == [["hub", "install"], ["doctor"]]
    out = result.output
    assert "✗ Install the launchd agent: exit code 3" in out
    assert "failed" in out and "Remote access" in out
    assert "Tailscale" in out


def test_an_install_that_fails_leaves_the_rest_running(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, codes={(UV,): 1})
    host.write_config()
    own_facts(host)
    result = invoke(host, ["--yes", "--features", "sub"])
    assert result.exit_code == 0, result.output
    assert len(host.uv_runs()) == 1 and host.execs == []
    assert "The install failed (uv exit code 1)" in result.output
    assert host.tau_runs() == [["doctor"]]


def test_remove(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-tui": "0.4.0", "tau-guard": "0.4.0"})
    host.write_config()
    (host.data / "guard").mkdir(parents=True)
    (host.data / "guard" / "enrolled").write_text("{}", encoding="utf-8")
    refused = invoke(host, ["--yes", "--remove", "guard"])
    assert refused.exit_code == 1
    assert "run `tau guard forget` at the Mac first" in refused.output
    assert host.uv_runs() == []
    declined = invoke(host, ["--remove", "tui"], stdin="n\n")
    assert declined.exit_code == 0 and host.uv_runs() == []
    removed = invoke(host, ["--remove", "tui"], stdin="y\n")
    assert removed.exit_code == 0, removed.output
    assert host.uv_runs() == [
        [UV, "tool", "install", "--force", "tau-core==0.4.0", "--with", "tau-guard==0.4.0"]
    ]
    assert "Removed tau-tui." in removed.output


def test_upgrade_drops_the_pins(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-tui": "0.4.0"})
    result = invoke(host, ["--upgrade", "--yes"])
    assert result.exit_code == 0, result.output
    assert host.uv_runs() == [
        [UV, "tool", "install", "--force", "--upgrade", "tau-core", "--with", "tau-tui"]
    ]


def test_without_a_terminal_the_wizard_says_how_to_script_it(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, tty=False)
    result = invoke(host, [])
    assert result.exit_code == 2
    assert "tau setup --yes --features tui,sub" in result.output
    assert host.runs == []


def test_unknown_features_are_refused(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    result = invoke(host, ["--yes", "--features", "tui,teleport"])
    assert result.exit_code == 2
    assert "Unknown feature: teleport." in result.output
    assert host.runs == []


def test_a_bad_resume_file_is_refused(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    loose = tmp_path / "state.json"
    loose.write_text('{"v": 1}', encoding="utf-8")
    loose.chmod(0o644)
    result = invoke(host, ["--resume", str(loose)])
    assert result.exit_code == 2
    assert "cannot be used (open to other users)" in result.output
    assert host.runs == []


def test_resume_keeps_yes_and_skips_optional_steps(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-net": "0.1.0"}, programs=("uv", "node"))
    host.write_config()
    own_facts(host)
    state = write_state({"language": "en", "features": ["net"], "yes": True})
    result = invoke(host, ["--resume", str(state)])
    assert result.exit_code == 0, result.output
    assert host.tau_runs() == [["net", "init"], ["doctor"]]
    assert "optional; not run with --yes" in result.output


def test_quit_changes_nothing(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    result = invoke(host, [], stdin="en\nq\n")
    assert result.exit_code == 0
    assert "Nothing changed." in result.output
    assert host.runs == []


def test_status_lists_the_features(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-tui": "0.4.0"})
    result = CliRunner().invoke(cli, ["setup", "status"], obj={"setup_host": host}, prog_name="tau")
    assert result.exit_code == 0, result.output
    assert "  tui        ✓  Terminal UI" in result.output
    assert "guard" in result.output and "(not installed)" in result.output


def test_run_one_feature_by_name(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-guard": "0.4.0"})
    host.write_config()
    result = CliRunner().invoke(
        cli, ["setup", "run", "guard"], input="\n\n", obj={"setup_host": host}, prog_name="tau"
    )
    assert result.exit_code == 0, result.output
    assert host.tau_runs() == [["guard", "doctor"], ["guard", "setup"]]
    assert TAU not in result.output


def test_turkish_answers_are_understood(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, installed={"tau-guard": "0.4.0"})
    host.write_config("tr")
    own_facts(host)
    # go on (e), the guard doctor (h: skip), the enrollment (x, then e)
    result = invoke(host, ["--features", "guard"], stdin="e\nh\nx\ne\n")
    assert result.exit_code == 0, result.output
    assert host.tau_runs() == [["guard", "setup"], ["doctor"]]
    out = result.output
    assert "Devam edilsin mi? [E/h]" in out and "e ya da h ile yanıtla." in out
    assert "– Korumanın ön koşullarını denetle: atlandı" in out
