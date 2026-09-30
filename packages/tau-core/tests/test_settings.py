"""``tau_core.settings`` (the bootstrap-config editor) and ``/settings`` in the terminal (083).

Everything runs on a temp home with the fake provider; no credential value is real, and the
tests check that none of them ever reaches the console output.
"""

from __future__ import annotations

import io
import re
import stat
from collections.abc import Callable
from pathlib import Path

import pytest
from rich.console import Console
from tau_core import Config, ConfigError, build_agent
from tau_core.builder import Check, template_text
from tau_core.channels.terminal import ReplState, run_repl
from tau_core.cli import cli
from tau_core.config import ConfigNotFound, RoleConfig, resolve_home
from tau_core.sessions import open_session_store
from tau_core.settings import (
    KEEP,
    check_document,
    clear_credential,
    configured_providers,
    credential_names_for,
    credential_present,
    credential_source,
    credential_status,
    default_home,
    describe_home,
    is_secret_name,
    known_env_names,
    known_providers,
    load_document,
    mask,
    masked_credential,
    report_lines,
    save_document,
    set_agent_option,
    set_credential,
    set_role,
    set_ui_language,
    status_text,
    tilde_path,
    validate,
)
from tau_core.testing import AutoRejectApprover, FakeModel, test_config

SECRET = "sk-test-not-a-real-key-0000abcd"
HUB_DOWN = Check(
    "hub", "info", "hub is not running (nothing answers on http://127.0.0.1:7877/health)"
)


@pytest.fixture(autouse=True)
def _no_hub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("tau_core.status.check_hub", lambda config: HUB_DOWN)


@pytest.fixture
def template_home(tmp_path: Path) -> Path:
    """A home with the shipped template (comments included) and a persona."""
    home = tmp_path / "home"
    (home / "persona").mkdir(parents=True)
    (home / "tau.toml").write_text(template_text("tau.toml"), encoding="utf-8")
    (home / "persona" / "persona.md").write_text("You are tau.\n", encoding="utf-8")
    return home


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# -- tau.toml round trips -----------------------------------------------------------------------


def test_set_role_keeps_comments_and_layout(template_home: Path) -> None:
    before = (template_home / "tau.toml").read_text(encoding="utf-8")
    doc = load_document(template_home)
    set_role(doc, "brain", "anthropic", "brain-x", max_tokens=2048, fallback=None)
    set_role(doc, "fast", "fake", "fast-x", fallback=("anthropic", "fb-x"))
    set_role(doc, "local", "fake", "local-x", max_tokens=None)
    save_document(template_home, doc)
    after = (template_home / "tau.toml").read_text(encoding="utf-8")

    # Comments survive: the header block, the provider comment, the [agent] comments.
    assert after.startswith("# tau.toml — static configuration read by tau_core.config.Config.")
    assert "# proxy | anthropic | bedrock | ollama | fake" in after
    assert "# per-turn loop guard, Strands Limits(turns=...)" in after
    assert "# hard cap of the role's proxy key" in after  # the budget table is untouched
    assert "[models.roles.brain.fallback]" not in after
    assert "[models.roles.fast.fallback]" in after  # added
    assert before.count("\n") <= after.count("\n") <= before.count("\n") + 4
    config = Config.load(template_home, env={})
    brain = config.roles["brain"]
    assert (brain.provider, brain.model_id, brain.max_tokens) == ("anthropic", "brain-x", 2048)
    assert brain.fallback is None and brain.budget is not None  # KEEP: budget untouched
    assert config.roles["fast"].fallback == RoleConfig("anthropic", "fb-x")
    assert config.roles["fast"].max_tokens == 1024  # KEEP: untouched
    assert config.roles["local"].max_tokens is None


def test_set_role_adds_a_fallback_table_and_validates(template_home: Path) -> None:
    doc = load_document(template_home)
    set_role(doc, "local", "fake", "local-x", fallback=("fake", "fb"))
    set_role(doc, "extra", "fake", "extra-x")
    save_document(template_home, doc)
    config = Config.load(template_home, env={})
    assert config.roles["local"].fallback == RoleConfig("fake", "fb")
    assert config.roles["extra"] == RoleConfig("fake", "extra-x")
    with pytest.raises(ConfigError, match="needs a 'provider'"):
        set_role(doc, "brain", "", "x")
    with pytest.raises(ConfigError, match="needs a 'model_id'"):
        set_role(doc, "brain", "fake", " ")
    with pytest.raises(ConfigError, match="max_tokens"):
        set_role(doc, "brain", "fake", "x", max_tokens=0)
    with pytest.raises(ConfigError, match="invalid role name"):
        set_role(doc, "no spaces", "fake", "x")
    assert KEEP is not None


PLANNED_REFUSED = (
    "provider 'futurebox' is not supported yet (issue 999); available: anthropic, bedrock, fake"
)
"""The refusal's text up to the built-in providers (an installed provider plugin adds to it)."""


@pytest.fixture
def planned(monkeypatch: pytest.MonkeyPatch) -> str:
    """A provider a later issue would build (none is planned in tau-core right now)."""
    import tau_core.models as models

    monkeypatch.setitem(models.PLANNED_PROVIDERS, "futurebox", "999")
    return "futurebox"


def refused(role: str) -> str:
    return re.escape(f"[models.roles.{role}] {PLANNED_REFUSED}")


def test_a_save_never_introduces_a_planned_provider(template_home: Path, planned: str) -> None:
    """``Config`` accepts a planned provider by name, but a role on it cannot start:
    ``set_role`` and ``check_document`` refuse a *new* use, while a role that already names it
    never blocks an unrelated save."""
    path = template_home / "tau.toml"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace(
            '[models.roles.local]\nprovider = "proxy"',
            '[models.roles.local]\nprovider = "futurebox"',
        ),
        encoding="utf-8",
    )
    doc = load_document(template_home)
    with pytest.raises(ConfigError, match=refused("brain")):
        set_role(doc, "brain", "futurebox", "f")
    with pytest.raises(ConfigError, match=r"\[models\.roles\.fast\.fallback\] "):
        set_role(doc, "fast", "bedrock", "x", fallback=("futurebox", "f"))
    assert doc["models"]["roles"]["brain"]["provider"] == "proxy"  # nothing half-written
    set_role(doc, "local", "futurebox", "f2")  # the role already sits on it: allowed
    set_ui_language(doc, "tr")
    save_document(template_home, doc)  # local = futurebox was on disk already
    assert validate(template_home, env={}).roles["local"].model_id == "f2"
    with pytest.raises(ConfigError, match=refused("local")):
        check_document(doc)  # without a previous document every use is new
    check_document(doc, previous=load_document(template_home))
    fresh = tomlkit_document('[models.roles.brain]\nprovider = "futurebox"\nmodel_id = "x"\n')
    with pytest.raises(ConfigError, match=re.escape(PLANNED_REFUSED)):
        save_document(template_home / "new", fresh)  # no file yet: strict
    assert not (template_home / "new" / "tau.toml").exists()


def tomlkit_document(text: str):
    import tomlkit

    return tomlkit.parse(text)


def test_ui_language_and_agent_options(template_home: Path) -> None:
    doc = load_document(template_home)
    set_ui_language(doc, "tr")
    set_agent_option(doc, "context", "summarize")
    set_agent_option(doc, "window_size", 30)
    set_agent_option(doc, "max_turns", 5)
    set_agent_option(doc, "max_total_tokens", 1000)
    save_document(template_home, doc)
    text = (template_home / "tau.toml").read_text(encoding="utf-8")
    assert 'language = "tr"' in text and "# en | tr: chrome of the terminal" in text
    config = validate(template_home, env={})
    assert config.ui.language == "tr"
    assert (config.agent.context, config.agent.window_size, config.agent.max_turns) == (
        "summarize",
        30,
        5,
    )
    assert config.agent.max_total_tokens == 1000
    set_agent_option(doc, "max_total_tokens", None)
    save_document(template_home, doc)
    assert validate(template_home, env={}).agent.max_total_tokens is None
    for key, value in (
        ("context", "auto"),
        ("window_size", 0),
        ("max_turns", "12"),
        ("max_total_tokens", True),
        ("nope", 1),
    ):
        with pytest.raises(ConfigError):
            set_agent_option(doc, key, value)
    with pytest.raises(ConfigError, match="language"):
        set_ui_language(doc, "de")


def test_save_is_atomic_and_keeps_a_private_mode(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    home = config.home
    (home / "tau.toml").chmod(0o600)
    doc = load_document(home)
    set_ui_language(doc, "tr")
    path = save_document(home, doc)
    assert path == home / "tau.toml" and mode_of(path) == 0o600
    assert not list(home.glob(".tau.toml.*"))  # no temp file left behind
    (home / "tau.toml").chmod(0o644)
    save_document(home, doc)
    assert mode_of(home / "tau.toml") == 0o644  # a shared file stays shared


def test_validate_surfaces_a_broken_file(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    (config.home / "tau.toml").write_text("[agent]\nmax_turns = 0\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="max_turns"):
        validate(config.home, env={})
    with pytest.raises(ConfigError, match="not found"):
        load_document(tmp_path / "nowhere")
    (config.home / "tau.toml").write_text("[agent\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="could not be read"):
        load_document(config.home)


# -- .env ------------------------------------------------------------------------------------------


def test_set_and_clear_credential_keep_dotenv_private(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("EXAMPLE_TOKEN", raising=False)
    config = test_config(tmp_path)
    home = config.home
    path = set_credential(home, "EXAMPLE_TOKEN", SECRET)
    assert path == home / ".env" and mode_of(path) == 0o600
    assert credential_present(home, "EXAMPLE_TOKEN", env={})
    assert masked_credential(home, "EXAMPLE_TOKEN", env={}) == "sk-…abcd"
    assert "EXAMPLE_TOKEN" not in __import__("os").environ  # export=False
    set_credential(home, "EXAMPLE_TOKEN", SECRET + "2", export=True)
    assert __import__("os").environ["EXAMPLE_TOKEN"] == SECRET + "2"
    assert mode_of(path) == 0o600
    assert (home / ".env").read_text(encoding="utf-8").count("EXAMPLE_TOKEN=") == 1
    assert clear_credential(home, "EXAMPLE_TOKEN", export=True) is True
    assert "EXAMPLE_TOKEN" not in __import__("os").environ
    assert not credential_present(home, "EXAMPLE_TOKEN", env={})
    assert clear_credential(home, "EXAMPLE_TOKEN") is False
    assert clear_credential(tmp_path / "nowhere", "EXAMPLE_TOKEN") is False
    with pytest.raises(ValueError):
        set_credential(home, "not a name", "x")
    with pytest.raises(ValueError):
        set_credential(home, "EXAMPLE_TOKEN", "  ")
    with pytest.raises(ValueError):
        set_credential(home, "EXAMPLE_TOKEN", "\n\t ")  # blank after stripping: still refused


def test_set_credential_strips_the_value_and_creates_a_private_home(tmp_path: Path) -> None:
    home = tmp_path / "new-home"  # no directory yet
    path = set_credential(home, "EXAMPLE_TOKEN", f"  {SECRET}\n")
    assert path.read_text(encoding="utf-8") == f"EXAMPLE_TOKEN='{SECRET}'\n"  # no whitespace
    assert mode_of(path) == 0o600 and mode_of(home) == 0o700
    assert masked_credential(home, "EXAMPLE_TOKEN", env={}) == "sk-…abcd"


def test_credential_source_tells_the_shell_from_the_file(tmp_path: Path) -> None:
    """``Config.load`` never lets ``.env`` override a variable the shell already set, so the
    editor says where a value comes from (the value itself is never returned)."""
    config = test_config(tmp_path)
    home = config.home
    assert credential_source(home, "EXAMPLE_TOKEN", env={}) is None
    assert credential_source(home, "EXAMPLE_TOKEN", env={"EXAMPLE_TOKEN": "shell"}) == "environment"
    set_credential(home, "EXAMPLE_TOKEN", SECRET)
    assert credential_source(home, "EXAMPLE_TOKEN", env={}) == "dotenv"
    assert credential_source(home, "EXAMPLE_TOKEN", env={"EXAMPLE_TOKEN": SECRET}) == "dotenv"
    assert credential_source(home, "EXAMPLE_TOKEN", env={"EXAMPLE_TOKEN": "other"}) == "environment"
    assert credential_source(home, "EXAMPLE_TOKEN", env={"EXAMPLE_TOKEN": ""}) == "dotenv"


def test_is_secret_name() -> None:
    for name in (
        "ANTHROPIC_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_BEARER_TOKEN_BEDROCK",
        "AWS_SESSION_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "DB_PASSWORD",
        "TAU_HOST_FP",
        "needy_key",
    ):
        assert is_secret_name(name), name
    for name in (
        "AWS_REGION",
        "AWS_PROFILE",
        "ANTHROPIC_WORKSPACE_ID",
        "TAU_PROFILE",
        "TAU_HOME",
        "TAU_DATA_DIR",
        "TELEGRAM_ALLOWED_CHAT_IDS",
    ):
        assert not is_secret_name(name), name


def test_mask_shows_less_of_a_shorter_value() -> None:
    """Below 12 characters only the last two, 12–19 two and two, from 20 on three and four:
    a prefix like ``sk-`` is only shown when the rest still hides enough."""
    assert mask("") == ""
    assert mask("a") == "…a"
    assert mask("short") == "…rt"
    assert mask("abcdefghijk") == "…jk"  # 11: the last boundary of the shortest form
    assert mask("abcdefghijkl") == "ab…kl"  # 12
    assert mask("abcdefghijklmnopqrs") == "ab…rs"  # 19
    assert mask("abcdefghijklmnopqrst") == "abc…qrst"  # 20
    assert mask(SECRET) == "sk-…abcd"


def test_credential_status_cases(tmp_path: Path, planned: str) -> None:
    config = test_config(tmp_path)
    home = config.home
    fake = RoleConfig("fake", "x")
    assert credential_status(home, fake, env={}).state == "none"
    bedrock = RoleConfig("bedrock", "x", fallback=RoleConfig("anthropic", "y"))
    missing = credential_status(home, bedrock, env={})
    assert missing.state == "missing" and missing.missing == ["AWS_REGION", "AWS_PROFILE"]
    fallback = credential_status(home, bedrock, env={"ANTHROPIC_API_KEY": "k"})
    assert fallback.state == "fallback" and fallback.fallback_provider == "anthropic"
    ok = credential_status(home, bedrock, env={"AWS_REGION": "r", "AWS_BEARER_TOKEN_BEDROCK": "t"})
    assert ok.state == "ok" and ok.satisfied == ["AWS_REGION", "AWS_BEARER_TOKEN_BEDROCK"]
    set_credential(home, "ANTHROPIC_API_KEY", SECRET)  # the file counts, like Config.load
    from_file = credential_status(home, RoleConfig("anthropic", "y"), env={})
    assert from_file.state == "ok" and from_file.satisfied == ["ANTHROPIC_API_KEY"]
    later = credential_status(home, RoleConfig(planned, "x"), env={})
    assert later.state == "unavailable" and "issue 999" in later.detail
    assert credential_status(home, RoleConfig("ollama", "x"), env={}).state == "none"
    proxy = credential_status(home, RoleConfig("proxy", "fast"), env={})
    assert proxy.state == "missing" and proxy.missing == ["TAU_PROXY_KEY_FAST"]
    assert status_text(missing) == "missing AWS_REGION, AWS_PROFILE"
    assert (
        status_text(fallback, "tr")
        == "eksik: AWS_REGION, AWS_PROFILE · yedek anthropic kullanılıyor"
    )
    assert status_text(ok, "tr") == "kimlik bilgileri tamam"


def test_names_and_providers(tmp_path: Path, planned: str) -> None:
    config = test_config(tmp_path)
    home = config.home
    assert credential_names_for("anthropic") == [["ANTHROPIC_API_KEY"]]
    assert credential_names_for("fake") == [] and credential_names_for("ollama") == []
    assert credential_names_for("proxy") == [["TAU_PROXY_KEY_BRAIN"]]
    assert credential_names_for("no-such-provider") == []
    providers = dict(known_providers())
    assert providers["fake"] is False and providers["ollama"] is False
    assert providers["proxy"] is False and providers[planned] is True
    assert configured_providers(home) == ["fake"]
    (home / ".env.example").write_text(
        "# MY_TOKEN=...\nOTHER=1\n# TAU_PROFILE=home\n", encoding="utf-8"
    )
    set_credential(home, "ONLY_IN_ENV", "1")
    names = known_env_names(home)
    assert names[:3] == ["ANTHROPIC_API_KEY", "AWS_REGION", "AWS_PROFILE"]  # providers first
    assert names[-4:] == ["MY_TOKEN", "OTHER", "TAU_PROFILE", "ONLY_IN_ENV"]
    assert known_env_names(home, providers=["anthropic"])[:1] == ["ANTHROPIC_API_KEY"]
    assert len(set(names)) == len(names)


def test_home_helpers(tmp_path: Path, monkeypatch) -> None:
    config = test_config(tmp_path)
    files = describe_home(config.home)
    assert files.config == config.home / "tau.toml" and files.exists("config")
    assert not files.exists("dotenv")
    labels = [label for label, _, _ in files.rows()]
    assert labels == ["tau.toml", ".env", ".env.example", "persona/persona.md", "persona/user.md"]
    monkeypatch.setenv("TAU_HOME", str(config.home))
    assert default_home() == config.home == resolve_home()
    monkeypatch.chdir(tmp_path)  # no tau.toml here, so the default is ~/.tau
    assert default_home({}) == Path("~/.tau").expanduser().resolve()
    monkeypatch.chdir(config.home)
    assert default_home({}) == config.home  # a tau.toml in the current directory wins
    with pytest.raises(ConfigNotFound) as info:
        Config.load(tmp_path / "missing", env={})
    assert info.value.home == (tmp_path / "missing").resolve()
    assert isinstance(info.value, ConfigError)


def test_report_lines_hide_values_and_paths(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    set_credential(config.home, "ANTHROPIC_API_KEY", SECRET)
    lines = report_lines(config, env={}, show_paths=False)
    text = "\n".join(lines)
    assert lines[0] == "Settings · <home>" and lines[1] == "Model roles:"
    assert lines[2] == "  brain  fake · fake-brain · no credentials needed"
    assert "UI language: en · profile: home" in lines
    assert "Context: sliding, window 60 · max_turns 12 · max_total_tokens none" in lines
    assert "  .env                <home>/.env · present" in lines
    assert "/settings language en|tr" in lines[-1] and "F10" in lines[-1]
    assert SECRET not in text and "abcd" not in text and str(tmp_path) not in text
    with_paths = report_lines(config, env={})
    assert str(config.home / "tau.toml") in "\n".join(with_paths)  # not under ~: as it is


def test_report_lines_print_paths_relative_to_the_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The docs show ``Settings · ~/.tau`` and ``~/.tau/tau.toml``: the report shortens a path
    under the user's home the way ``/session`` does."""
    monkeypatch.setenv("HOME", str(tmp_path))  # Path.home() follows HOME
    config = test_config(tmp_path)
    assert tilde_path(config.home / "tau.toml") == "~/home/tau.toml"
    assert tilde_path(Path("/elsewhere/tau.toml")) == "/elsewhere/tau.toml"
    lines = report_lines(config, env={})
    assert lines[0] == "Settings · ~/home"
    assert "  tau.toml            ~/home/tau.toml · present" in lines
    assert str(tmp_path) not in "\n".join(lines)


# -- /settings in the terminal --------------------------------------------------------------------


def feed(lines: list[str]) -> Callable[[str], str]:
    remaining = list(lines)

    def read(prompt: str) -> str:
        if not remaining:
            raise EOFError
        return remaining.pop(0)

    return read


def make_state(config: Config, *, replies: list | None = None) -> ReplState:
    approver = AutoRejectApprover()
    store = open_session_store(config)
    agent = build_agent(
        config=config,
        role="brain",
        model=FakeModel(replies or []),
        tools=[],
        approver=approver,
        session_store=store,
        channel="terminal",
    )
    console = Console(
        file=io.StringIO(), markup=False, emoji=False, highlight=False, soft_wrap=True, width=200
    )
    return ReplState(
        config=config,
        store=store,
        approver=approver,
        agent=agent,
        console=console,
        language=config.ui.language,
    )


def run(state: ReplState, lines: list[str]) -> str:
    run_repl(state, input_func=feed(lines))
    return state.console.file.getvalue()


def test_settings_report_in_the_repl(tmp_path: Path) -> None:
    state = make_state(test_config(tmp_path))
    out = run(state, ["/settings", "/ayarlar"])
    assert out.count("Model roles:") == 2
    assert "  brain  fake · fake-brain · no credentials needed" in out
    assert "UI language: en · profile: home" in out
    assert str(state.config.home / "tau.toml") in out
    assert "Change: /settings language en|tr" in out


def test_settings_language_and_profile_setters(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TAU_PROFILE", raising=False)
    config = test_config(tmp_path)
    state = make_state(config)
    agent = state.agent
    out = run(state, ["/settings language tr", "/settings profile travel", "/settings"])
    assert "Settings saved." in out and "Arayüz dili: tr." in out
    assert validate(config.home, env={}).ui.language == "tr"
    assert state.language == "tr"
    assert "Ayarlar kaydedildi; model yeniden yüklendi." in out
    assert (config.home / ".env").read_text(encoding="utf-8") == "TAU_PROFILE=travel\n"
    assert mode_of(config.home / ".env") == 0o600
    assert state.config.profile == "travel"
    assert state.agent is not agent and state.agent.session_id == agent.session_id
    assert "Arayüz dili: tr · profil: travel" in out


def test_settings_model_setter_rebuilds_on_the_same_session(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    state = make_state(config)
    session_id = state.agent.session_id
    out = run(state, ["/settings model brain fake fake-brain-2", "/settings model brain nope x"])
    assert "Settings saved; model reloaded." in out
    assert validate(config.home, env={}).roles["brain"].model_id == "fake-brain-2"
    assert state.config.roles["brain"].model_id == "fake-brain-2"
    assert state.agent.session_id == session_id
    assert state.agent.agent.model.get_config()["model_id"] == "fake"  # the fake provider
    # An unknown provider is refused before anything is written (check_document).
    assert "Not saved: tau.toml: unknown provider for role 'brain': 'nope'." in out
    assert validate(config.home, env={}).roles["brain"].provider == "fake"


def test_settings_model_refuses_a_planned_provider(tmp_path: Path, planned: str) -> None:
    """A planned provider loads by name but cannot start; ``/settings model`` refuses it so the
    next ``tau chat`` does not exit 2 (set_role, before anything is written)."""
    config = test_config(tmp_path)
    state = make_state(config)
    before = (config.home / "tau.toml").read_text(encoding="utf-8")
    out = run(state, [f"/settings model brain {planned} f"])
    assert f"Not saved: tau.toml: [models.roles.brain] {PLANNED_REFUSED}" in out
    assert (config.home / "tau.toml").read_text(encoding="utf-8") == before
    assert state.config.roles["brain"].provider == "fake"


def test_settings_set_reads_the_value_with_getpass(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    prompts: list[str] = []

    def fake_getpass(prompt: str = "") -> str:
        prompts.append(prompt)
        return SECRET if len(prompts) == 1 else ""

    monkeypatch.setattr("getpass.getpass", fake_getpass)
    config = test_config(tmp_path)
    state = make_state(config)
    out = run(
        state,
        [
            "/settings set ANTHROPIC_API_KEY",
            "/settings set ANTHROPIC_API_KEY",
            "/settings clear ANTHROPIC_API_KEY",
            "/settings clear ANTHROPIC_API_KEY",
            "/settings set bad name",
            "/settings nonsense",
        ],
    )
    assert prompts == ["Value for ANTHROPIC_API_KEY (not echoed): "] * 2
    assert SECRET not in out and "abcd" not in out
    assert "ANTHROPIC_API_KEY set in .env." in out
    assert "Settings saved; model reloaded." in out
    assert "Nothing entered; ANTHROPIC_API_KEY is unchanged." in out
    assert "ANTHROPIC_API_KEY removed from .env." in out
    assert "ANTHROPIC_API_KEY is not in .env." in out
    assert "Usage: /settings [language en|tr | profile NAME" in out
    assert "ANTHROPIC_API_KEY" not in (config.home / ".env").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY" not in __import__("os").environ


def test_settings_set_strips_the_typed_value(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("EXAMPLE_TOKEN", raising=False)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": f"  {SECRET}  ")
    config = test_config(tmp_path)
    state = make_state(config)
    out = run(state, ["/settings set EXAMPLE_TOKEN"])
    assert "EXAMPLE_TOKEN set in .env." in out and SECRET not in out
    assert (config.home / ".env").read_text(encoding="utf-8") == f"EXAMPLE_TOKEN='{SECRET}'\n"
    assert __import__("os").environ["EXAMPLE_TOKEN"] == SECRET
    monkeypatch.setattr("getpass.getpass", lambda prompt="": " \t ")
    out = run(state, ["/settings set EXAMPLE_TOKEN"])
    assert "Nothing entered; EXAMPLE_TOKEN is unchanged." in out


def test_settings_invalid_values_are_refused(tmp_path: Path) -> None:
    config = test_config(tmp_path)
    state = make_state(config)
    before = (config.home / "tau.toml").read_text(encoding="utf-8")
    out = run(state, ["/settings language de", "/settings model brain fake"])
    assert "Not saved: tau.toml: [ui] 'language' must be one of en, tr, not 'de'." in out
    assert "Usage: /settings" in out
    assert (config.home / "tau.toml").read_text(encoding="utf-8") == before


def test_settings_through_tau_chat(tmp_path: Path, monkeypatch) -> None:
    """``tau chat`` end to end with CliRunner: the report, a setter, nothing echoed."""
    from click.testing import CliRunner

    monkeypatch.setattr("getpass.getpass", lambda prompt="": SECRET)
    home = tmp_path / "home"
    (home / "persona").mkdir(parents=True)
    (home / "tau.toml").write_text(
        '[models.roles.brain]\nprovider = "fake"\nmodel_id = "fake-brain"\n', encoding="utf-8"
    )
    (home / "persona" / "persona.md").write_text("You are tau.\n", encoding="utf-8")
    env = {
        "TAU_HOME": str(home),
        "TAU_DATA_DIR": str(tmp_path / "data"),
        "TAU_PROFILE": None,
        "TAU_LANG": None,
        "ANTHROPIC_API_KEY": None,
    }
    result = CliRunner().invoke(
        cli,
        ["chat"],
        env=env,
        input="/settings\n/settings set EXAMPLE_KEY\n/settings language tr\n/quit\n",
        prog_name="tau",
    )
    assert result.exit_code == 0, result.output
    assert "Model roles:" in result.output and "  brain  fake · fake-brain" in result.output
    assert "EXAMPLE_KEY set in .env." in result.output
    assert SECRET not in result.output
    assert "Arayüz dili: tr." in result.output
    assert mode_of(home / ".env") == 0o600
    assert Config.load(home, env={}).ui.language == "tr"
