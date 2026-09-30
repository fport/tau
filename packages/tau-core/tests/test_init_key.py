"""``tau init`` asks for the provider key (ADR 0013 §7, issue 154).

Offline: the prompts read CliRunner's input, the key check is a fake passed through the click
context object (``obj={"init_key_check": ...}``) or a fake opener, and nothing reaches the
network. Every key here is a made-up test value; the tests also prove it never reaches the
output."""

from __future__ import annotations

import io
import stat
import urllib.error
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result
from tau_core import Config, t
from tau_core.builder import (
    KEY_NAMES,
    KeyCheck,
    check_provider_key,
    model_ids,
    write_env_key,
)
from tau_core.cli import cli

KEY = "sk-test-not-a-real-key-0123456789"
UNSET = {
    name: None
    for name in (
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "AWS_PROFILE",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_BEARER_TOKEN_BEDROCK",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "TAU_PROFILE",
        "TAU_ROLE",
        "TAU_HUB_PORT",
        "TAU_LANG",
    )
}


class FakeChecker:
    """Records every check and answers with ``answer``."""

    def __init__(self, answer: KeyCheck | None = None):
        self.answer = answer or KeyCheck("ok", status=200)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, provider: str, key: str) -> KeyCheck:
        self.calls.append((provider, key))
        return self.answer


def run(
    args: list[str],
    tmp_path: Path,
    *,
    stdin: str | None = None,
    checker: FakeChecker | None = None,
    env: dict[str, str] | None = None,
) -> Result:
    full: dict[str, str | None] = dict(UNSET)
    full["TAU_DATA_DIR"] = str(tmp_path / "data")
    full["TAU_HOME"] = str(tmp_path / "nowhere")
    full["HOME"] = str(tmp_path / "userhome")
    full.update(env or {})
    obj: dict[str, Any] = {}
    if checker is not None:
        obj["init_key_check"] = checker
    return CliRunner().invoke(cli, args, env=full, input=stdin, prog_name="tau", obj=obj)


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# -- the interactive run -----------------------------------------------------------------------


def test_asks_provider_and_hidden_key_checks_it_and_writes_env_0600(tmp_path: Path) -> None:
    home = tmp_path / "fresh"
    checker = FakeChecker()
    result = run(
        ["init", "--home", str(home), "--language", "en"],
        tmp_path,
        stdin=f"openai\n{KEY}\n",
        checker=checker,
    )
    assert result.exit_code == 0, result.output
    assert KEY not in result.output  # hidden input, never echoed or printed
    assert t("init.provider.none", "en", path=home / ".env") in result.output
    assert "Provider (anthropic, openai, gemini) [anthropic]: openai" in result.output
    assert t("init.key.prompt", "en", name="OPENAI_API_KEY") in result.output
    assert t("init.key.checking", "en", provider="openai") in result.output
    assert t("init.key.ok", "en", provider="openai") in result.output
    assert checker.calls == [("openai", KEY)]
    dotenv = home / ".env"
    assert dotenv.read_text("utf-8") == f"OPENAI_API_KEY={KEY}\n"
    assert mode(dotenv) == 0o600
    assert t("init.key.written", "en", name="OPENAI_API_KEY", path=dotenv) in result.output
    config = Config.load(home, env={})
    assert config.roles["brain"].provider == "openai"
    assert config.roles["fast"].provider == "openai"
    assert config.roles["brain"].model_id == model_ids("openai")["brain"]


def test_language_is_asked_first_and_prompts_follow_it(tmp_path: Path) -> None:
    home = tmp_path / "tr"
    checker = FakeChecker()
    result = run(["init", "--home", str(home)], tmp_path, stdin=f"tr\n\n{KEY}\n", checker=checker)
    assert result.exit_code == 0, result.output
    output = result.output
    assert output.index("UI language") < output.index(t("init.provider.prompt", "tr"))
    assert t("init.provider.none", "tr", path=home / ".env") in output
    assert t("init.key.prompt", "tr", name="ANTHROPIC_API_KEY") in output
    assert t("init.key.ok", "tr", provider="anthropic") in output
    assert checker.calls == [("anthropic", KEY)]  # the default provider
    assert Config.load(home, env={}).ui.language == "tr"
    assert KEY not in output


def test_an_existing_env_keeps_its_lines_and_gets_the_key_appended(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    dotenv = home / ".env"
    dotenv.write_text("# my settings\nTAU_PROFILE=travel\nTELEGRAM_ALLOWED_CHAT_IDS=1", "utf-8")
    dotenv.chmod(0o644)
    result = run(
        ["init", "--home", str(home), "--language", "en", "--provider", "gemini"],
        tmp_path,
        stdin=f"{KEY}\n",
        checker=FakeChecker(),
    )
    assert result.exit_code == 0, result.output
    assert dotenv.read_text("utf-8") == (
        f"# my settings\nTAU_PROFILE=travel\nTELEGRAM_ALLOWED_CHAT_IDS=1\nGEMINI_API_KEY={KEY}\n"
    )
    assert mode(dotenv) == 0o600
    assert Config.load(home, env={}).roles["brain"].provider == "gemini"


def test_a_key_already_in_env_is_found_and_nothing_is_asked(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / ".env").write_text("OTHER=1\nANTHROPIC_API_KEY=sk-already-there\n", "utf-8")
    checker = FakeChecker()
    result = run(
        ["init", "--home", str(home), "--language", "en"], tmp_path, stdin="", checker=checker
    )
    assert result.exit_code == 0, result.output
    assert "Provider: anthropic. ANTHROPIC_API_KEY was found" in result.output
    assert "Provider (anthropic, openai, gemini)" not in result.output
    assert checker.calls == []
    assert (home / ".env").read_text("utf-8") == "OTHER=1\nANTHROPIC_API_KEY=sk-already-there\n"


def test_no_check_skips_the_request(tmp_path: Path) -> None:
    home = tmp_path / "home"
    checker = FakeChecker(KeyCheck("refused", status=401))  # would fail if it were asked
    result = run(
        ["init", "--home", str(home), "--language", "en", "--provider", "openai", "--no-check"],
        tmp_path,
        stdin=f"{KEY}\n",
        checker=checker,
    )
    assert result.exit_code == 0, result.output
    assert checker.calls == []
    assert t("init.key.unchecked", "en") in result.output
    assert (home / ".env").read_text("utf-8") == f"OPENAI_API_KEY={KEY}\n"


@pytest.mark.parametrize(
    ("answer", "key", "fields"),
    [
        (KeyCheck("refused", status=401), "init.key.refused", {"status": 401}),
        (KeyCheck("http", status=529), "init.key.http", {"status": 529}),
        (KeyCheck("unreachable", error="URLError: timed out"), "init.key.unreachable", {}),
    ],
)
def test_a_failed_check_explains_itself_and_writes_nothing(
    tmp_path: Path, answer: KeyCheck, key: str, fields: dict[str, Any]
) -> None:
    home = tmp_path / "home"
    result = run(
        ["init", "--home", str(home), "--language", "en"],
        tmp_path,
        stdin=f"anthropic\n{KEY}\n",
        checker=FakeChecker(answer),
    )
    assert result.exit_code == 1
    if answer.code == "unreachable":
        fields = {"error": answer.error}
    assert t(key, "en", provider="anthropic", **fields) in result.output
    assert "nothing was written" in result.output
    assert KEY not in result.output
    assert not (home / "tau.toml").exists()
    assert not (home / ".env").exists()


def test_an_empty_key_skips_and_still_writes_the_config(tmp_path: Path) -> None:
    home = tmp_path / "home"
    checker = FakeChecker()
    result = run(
        ["init", "--home", str(home), "--language", "en"],
        tmp_path,
        stdin="openai\n\n",
        checker=checker,
    )
    assert result.exit_code == 0, result.output
    assert checker.calls == []
    skipped = t(
        "init.key.skipped", "en", name="OPENAI_API_KEY", path=home / ".env", provider="openai"
    )
    assert skipped in result.output
    assert not (home / ".env").exists()
    assert Config.load(home, env={}).roles["brain"].provider == "openai"


def test_a_key_with_spaces_is_refused_before_the_check(tmp_path: Path) -> None:
    home = tmp_path / "home"
    checker = FakeChecker()
    result = run(
        ["init", "--home", str(home), "--language", "en", "--provider", "openai"],
        tmp_path,
        stdin="sk-one two\n",
        checker=checker,
    )
    assert result.exit_code == 1
    assert t("init.key.invalid", "en") in result.output
    assert checker.calls == [] and not (home / "tau.toml").exists()


def test_yes_keeps_the_old_behaviour(tmp_path: Path) -> None:
    home = tmp_path / "home"
    checker = FakeChecker()
    result = run(["init", "--home", str(home), "--yes"], tmp_path, stdin="", checker=checker)
    assert result.exit_code == 0, result.output
    assert "Provider: fake." in result.output
    assert "Provider (anthropic, openai, gemini)" not in result.output
    assert checker.calls == [] and not (home / ".env").exists()
    # --yes with an explicit key provider asks nothing either
    result = run(
        ["init", "--home", str(home), "--yes", "--force", "--provider", "openai"],
        tmp_path,
        stdin="",
        checker=checker,
    )
    assert result.exit_code == 0, result.output
    assert checker.calls == [] and not (home / ".env").exists()
    assert Config.load(home, env={}).roles["brain"].provider == "openai"


def test_bedrock_and_fake_never_ask_for_a_key(tmp_path: Path) -> None:
    for provider in ("fake", "bedrock"):
        home = tmp_path / provider
        checker = FakeChecker()
        result = run(
            ["init", "--home", str(home), "--language", "en", "--provider", provider],
            tmp_path,
            stdin="",
            checker=checker,
        )
        assert result.exit_code == 0, result.output
        assert checker.calls == []


# -- write_env_key -----------------------------------------------------------------------------


def test_write_env_key_creates_0600(tmp_path: Path) -> None:
    assert write_env_key(tmp_path, "OPENAI_API_KEY", f"  {KEY}\n")
    assert (tmp_path / ".env").read_text("utf-8") == f"OPENAI_API_KEY={KEY}\n"
    assert mode(tmp_path / ".env") == 0o600


def test_write_env_key_keeps_a_set_value_and_fills_an_empty_one(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("A=1\nOPENAI_API_KEY=sk-old\n", "utf-8")
    assert not write_env_key(tmp_path, "OPENAI_API_KEY", KEY)
    assert dotenv.read_text("utf-8") == "A=1\nOPENAI_API_KEY=sk-old\n"

    dotenv.write_text("A=1\nGEMINI_API_KEY=\n# B=2\n", "utf-8")
    assert write_env_key(tmp_path, "GEMINI_API_KEY", KEY)
    assert dotenv.read_text("utf-8") == f"A=1\nGEMINI_API_KEY={KEY}\n# B=2\n"
    assert mode(dotenv) == 0o600


def test_write_env_key_quotes_odd_values_and_refuses_broken_ones(tmp_path: Path) -> None:
    from dotenv import dotenv_values

    assert write_env_key(tmp_path, "ANTHROPIC_API_KEY", "abc#def")
    assert dotenv_values(tmp_path / ".env")["ANTHROPIC_API_KEY"] == "abc#def"
    with pytest.raises(ValueError) as caught:
        write_env_key(tmp_path, "OPENAI_API_KEY", "sk secret")
    assert "secret" not in str(caught.value)
    with pytest.raises(ValueError):
        write_env_key(tmp_path, "BAD NAME", KEY)


# -- check_provider_key ------------------------------------------------------------------------


class _Response:
    def __init__(self, status: int):
        self.status = status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeOpener:
    """An opener that records the request and answers with a status or raises."""

    def __init__(self, status: int = 200, error: BaseException | None = None):
        self.status = status
        self.error = error
        self.requests: list[Any] = []

    def open(self, request: Any, timeout: float) -> _Response:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.status != 200:
            raise urllib.error.HTTPError(
                request.full_url, self.status, "nope", {}, io.BytesIO(b"{}")
            )
        return _Response(200)


@pytest.mark.parametrize(
    ("provider", "host", "header"),
    [
        ("anthropic", "api.anthropic.com", "X-api-key"),
        ("openai", "api.openai.com", "Authorization"),
        ("gemini", "generativelanguage.googleapis.com", "X-goog-api-key"),
    ],
)
def test_the_check_puts_the_key_only_in_a_header(provider: str, host: str, header: str) -> None:
    opener = FakeOpener()
    assert check_provider_key(provider, KEY, opener=opener) == KeyCheck("ok", status=200)
    (request,) = opener.requests
    assert request.get_method() == "GET"
    assert request.host == host
    assert KEY not in request.full_url
    assert KEY in request.get_header(header)
    assert set(KEY_NAMES) == {"anthropic", "openai", "gemini"}


def test_the_check_maps_answers_without_the_key() -> None:
    assert check_provider_key("openai", KEY, opener=FakeOpener(401)).code == "refused"
    assert check_provider_key("openai", KEY, opener=FakeOpener(403)).code == "refused"
    assert check_provider_key("openai", KEY, opener=FakeOpener(500)) == KeyCheck("http", 500)
    down = check_provider_key(
        "openai", KEY, opener=FakeOpener(error=urllib.error.URLError("timed out"))
    )
    assert down.code == "unreachable" and "timed out" in down.error and KEY not in down.error
    with pytest.raises(ValueError):
        check_provider_key("bedrock", KEY, opener=FakeOpener())
