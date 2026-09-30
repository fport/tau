"""Persona files, dynamic context and system prompt assembly (issue 005).

Everything runs offline: prompts are inspected through ``FakeModel.calls[i].system_prompt``.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from tau_core import Config, ConfigError, Tier, build_agent, tau_tool
from tau_core.persona import (
    NO_USER_FILE,
    TIMEZONE,
    UNKNOWN,
    DynamicContext,
    PersonaHook,
    PersonaLoader,
    default_context_factory,
)
from tau_core.testing import FakeModel, ToolCall

ROOT = Path(__file__).resolve().parents[3]
REPO_PERSONA = ROOT / "persona"

LOGGER = "tau_core.persona"


def rewrite(path: Path, text: str | bytes) -> None:
    """Write ``path`` and make sure its mtime moves forward, even on coarse-clock filesystems."""
    before = path.stat().st_mtime_ns if path.exists() else 0
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    after = path.stat()
    if after.st_mtime_ns <= before:
        os.utime(path, ns=(after.st_atime_ns, before + 1_000_000))


def make_persona_dir(tmp_path: Path, persona: str | None, user: str | None = None) -> Path:
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir(parents=True, exist_ok=True)
    if persona is not None:
        (persona_dir / "persona.md").write_text(persona, encoding="utf-8")
    if user is not None:
        (persona_dir / "user.md").write_text(user, encoding="utf-8")
    return persona_dir


def ctx(now: datetime, **values) -> DynamicContext:
    return DynamicContext(now=now, profile="home", role="hub", **values)


def first_line_of_prompt(messages, system_prompt: str | None) -> str:
    """A FakeModel reply that repeats the first line of the system prompt."""
    return (system_prompt or "").splitlines()[0]


def warnings_from(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        r.getMessage() for r in caplog.records if r.name == LOGGER and r.levelno >= logging.WARNING
    ]


@tau_tool(tier=Tier.READ)
def ping() -> str:
    """Sınama aracı: 'pong' döner."""
    return "pong"


# --- prompt assembly -----------------------------------------------------------------------


def test_prompt_layout_is_exact(tmp_path: Path, fixed_now: datetime) -> None:
    persona_dir = make_persona_dir(tmp_path, "Sen tau'sun.\n", "- Hitap: siz\n")
    prompt = PersonaLoader(persona_dir).build_system_prompt(ctx(fixed_now))
    assert prompt == (
        "Sen tau'sun.\n"
        "\n"
        "## User\n"
        "- Hitap: siz\n"
        "\n"
        "## Now\n"
        "- Date and time: 29.09.2026 15:30, Tuesday (Europe/Istanbul)\n"
        "- Profile: home\n"
        "- Host role: hub\n"
        "- Live nodes: unknown\n"
        "- Budget: unknown"
    )


@pytest.mark.parametrize(
    "user",
    [None, "", "   \n\n", "<!-- yalnızca bir not -->\n"],
    ids=["missing", "empty", "blank", "comment-only"],
)
def test_no_user_facts_defaults_to_formal_address(
    tmp_path: Path, fixed_now: datetime, user
) -> None:
    persona_dir = make_persona_dir(tmp_path, "Sen tau'sun.\n", user)
    loader = PersonaLoader(persona_dir)
    assert loader.read().user is None
    prompt = loader.build_system_prompt(ctx(fixed_now))
    assert f"## User\n{NO_USER_FILE}\n\n## Now\n" in prompt
    assert NO_USER_FILE.endswith("Address the user formally.")


def test_html_comments_never_reach_the_model(tmp_path: Path, fixed_now: datetime) -> None:
    persona_dir = make_persona_dir(
        tmp_path,
        "<!--\ngeliştirici notu\n-->\n# tau\n\nSen tau'sun.<!-- satır içi -->\n\n\n\nKibarsın.\n",
        "<!-- şablon notu -->\n- Hitap: efendim\n",
    )
    loader = PersonaLoader(persona_dir)
    assert loader.read().persona == "# tau\n\nSen tau'sun.\n\nKibarsın."
    assert loader.read().user == "- Hitap: efendim"
    prompt = loader.build_system_prompt(ctx(fixed_now))
    assert "<!--" not in prompt and "notu" not in prompt


def test_utf8_bom_and_crlf_are_tolerated(tmp_path: Path) -> None:
    persona_dir = make_persona_dir(tmp_path, None)
    (persona_dir / "persona.md").write_bytes("﻿Sen tau'sun.\r\nKibarsın.\r\n".encode())
    assert PersonaLoader(persona_dir).read().persona == "Sen tau'sun.\nKibarsın."


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, "Persona file not found"),
        ("  \n<!-- boş -->\n", "Persona file is empty"),
        (b"\xff\xfe\xfa bozuk", "Persona file could not be read"),
    ],
    ids=["missing", "empty", "undecodable"],
)
def test_unusable_persona_fails_on_first_read(tmp_path: Path, content, message: str) -> None:
    persona_dir = make_persona_dir(tmp_path, None, "- Hitap: siz\n")
    if content is not None:
        rewrite(persona_dir / "persona.md", content)
    with pytest.raises(ConfigError, match=message):
        PersonaLoader(persona_dir).read()


def test_build_agent_fails_early_without_persona(config: Config) -> None:
    (config.persona_dir / "persona.md").unlink()
    with pytest.raises(ConfigError, match="Persona file not found"):
        build_agent(config=config, model=FakeModel(), tools=[])


# --- reload semantics ----------------------------------------------------------------------


def test_reload_follows_mtime_and_size(tmp_path: Path) -> None:
    persona_dir = make_persona_dir(tmp_path, "bir\n")
    persona_file = persona_dir / "persona.md"
    loader = PersonaLoader(persona_dir)
    assert loader.read().persona == "bir"
    old = persona_file.stat()

    # Same size and the old mtime: the (st_mtime_ns, st_size) stamp is unchanged → cached text.
    persona_file.write_text("iki\n", encoding="utf-8")
    os.utime(persona_file, ns=(old.st_atime_ns, old.st_mtime_ns))
    assert loader.read().persona == "bir"

    # Only the mtime moves → reloaded.
    os.utime(persona_file, ns=(old.st_atime_ns, old.st_mtime_ns + 1_000_000))
    assert loader.read().persona == "iki"

    # Only the size changes (mtime put back) → reloaded as well.
    persona_file.write_text("üç kere\n", encoding="utf-8")
    os.utime(persona_file, ns=(old.st_atime_ns, old.st_mtime_ns + 1_000_000))
    assert loader.read().persona == "üç kere"


def test_unchanged_files_are_not_reread(
    tmp_path: Path, fixed_now: datetime, monkeypatch: pytest.MonkeyPatch
) -> None:
    persona_dir = make_persona_dir(tmp_path, "Sen tau'sun.\n", "- Hitap: siz\n")
    reads: list[str] = []
    original = Path.read_text

    def counting_read_text(self: Path, *args, **kwargs) -> str:
        reads.append(self.name)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    loader = PersonaLoader(persona_dir)
    for _ in range(3):
        loader.build_system_prompt(ctx(fixed_now))
    assert sorted(reads) == ["persona.md", "user.md"]

    rewrite(persona_dir / "user.md", "- Hitap: efendim\n")
    loader.build_system_prompt(ctx(fixed_now))
    assert sorted(reads) == ["persona.md", "user.md", "user.md"]


def test_persona_that_disappears_keeps_last_version(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    persona_dir = make_persona_dir(tmp_path, "eski persona\n")
    persona_file = persona_dir / "persona.md"
    loader = PersonaLoader(persona_dir)
    assert loader.read().persona == "eski persona"

    persona_file.unlink()
    assert loader.read().persona == "eski persona"
    assert loader.read().persona == "eski persona"
    assert len(warnings_from(caplog)) == 1  # logged once, not on every model call

    rewrite(persona_file, "")  # an editor truncating before it writes
    assert loader.read().persona == "eski persona"

    rewrite(persona_file, "yeni persona\n")
    assert loader.read().persona == "yeni persona"


def test_unreadable_files_keep_last_version(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    persona_dir = make_persona_dir(tmp_path, "persona\n", "- Hitap: efendim\n")
    loader = PersonaLoader(persona_dir)
    loader.read()

    rewrite(persona_dir / "persona.md", b"\xff\xfe\xfa bozuk")
    rewrite(persona_dir / "user.md", b"\xff\xfe\xfa bozuk")
    current = loader.read()
    assert (current.persona, current.user) == ("persona", "- Hitap: efendim")
    loader.read()
    assert len(warnings_from(caplog)) == 2  # one per file, once

    rewrite(persona_dir / "persona.md", "düzeldi\n")
    rewrite(persona_dir / "user.md", "- Hitap: siz\n")
    current = loader.read()
    assert (current.persona, current.user) == ("düzeldi", "- Hitap: siz")


def test_user_file_can_come_and_go(tmp_path: Path) -> None:
    persona_dir = make_persona_dir(tmp_path, "persona\n")
    user_file = persona_dir / "user.md"
    loader = PersonaLoader(persona_dir)
    assert loader.read().user is None
    rewrite(user_file, "- Hitap: efendim\n")
    assert loader.read().user == "- Hitap: efendim"
    user_file.unlink()
    assert loader.read().user is None  # deleted on purpose: back to "siz"


async def test_persona_edit_changes_the_next_reply(config: Config, fixed_now: datetime) -> None:
    model = FakeModel([first_line_of_prompt] * 4)
    agent = build_agent(config=config, model=model, tools=[], clock=lambda: fixed_now)
    persona_file = config.persona_dir / "persona.md"
    user_file = config.persona_dir / "user.md"

    assert await agent.ask("merhaba") == "You are tau: a polite assistant who keeps replies short."

    rewrite(persona_file, "Sen tau'sun ve bugün çok resmisin.\n")
    rewrite(user_file, "- Hitap: efendim\n")
    assert await agent.ask("nasılsın?") == "Sen tau'sun ve bugün çok resmisin."

    user_file.unlink()
    await agent.ask("beni tanıyor musun?")

    prompts = [call.system_prompt or "" for call in model.calls]
    assert "## User\nAddress the user formally.\n" in prompts[0]
    assert prompts[1].startswith("Sen tau'sun ve bugün çok resmisin.\n\n## User\n")
    assert "## User\n- Hitap: efendim\n" in prompts[1]
    assert f"## User\n{NO_USER_FILE}\n" in prompts[2]
    # Same agent, same conversation: the history kept growing while the prompt changed.
    assert [len(call.messages) for call in model.calls] == [1, 3, 5]
    assert agent.agent.system_prompt == prompts[2]


async def test_prompt_is_rebuilt_before_every_model_call_in_a_turn(
    config: Config, fixed_now: datetime
) -> None:
    ticks = iter(range(100))

    def clock() -> datetime:
        return fixed_now + timedelta(minutes=next(ticks))

    def edit_then_call_tool(messages, system_prompt):
        rewrite(config.persona_dir / "persona.md", "Araçtan sonra değişen persona.\n")
        return [ToolCall("ping", {})]

    model = FakeModel([edit_then_call_tool, "pong geldi"])
    # An explicit session id keeps build_agent from reading the clock for it.
    agent = build_agent(
        config=config, model=model, tools=[ping], clock=clock, session_id="s-rebuild"
    )
    assert await agent.ask("ping at") == "pong geldi"

    first, second = (call.system_prompt or "" for call in model.calls)
    assert first.startswith("You are tau")
    assert second.startswith("Araçtan sonra değişen persona.")
    # tick 0 is build_agent's eager prompt; each model call reads the clock again.
    assert "- Date and time: 29.09.2026 15:31, Tuesday" in first
    assert "- Date and time: 29.09.2026 15:32, Tuesday" in second


async def test_hook_keeps_previous_prompt_when_assembly_fails(
    config: Config, fixed_now: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    calls = {"n": 0}

    def flaky_clock() -> datetime:
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("saat bozuk")
        return fixed_now

    model = FakeModel(["bir", "iki"])
    agent = build_agent(
        config=config, model=model, tools=[], clock=flaky_clock, session_id="s-flaky"
    )
    initial = agent.agent.system_prompt
    assert await agent.ask("merhaba") == "bir"
    assert await agent.ask("tekrar") == "iki"
    assert [call.system_prompt for call in model.calls] == [initial, initial]
    assert len(warnings_from(caplog)) == 1


def test_persona_hook_sets_system_prompt(tmp_path: Path, fixed_now: datetime) -> None:
    persona_dir = make_persona_dir(tmp_path, "Sen tau'sun.\n")
    hook = PersonaHook(PersonaLoader(persona_dir), lambda: ctx(fixed_now, budget="3 $"))

    class FakeAgent:
        system_prompt = "eski"

    class FakeEvent:
        agent = FakeAgent()

    hook._before_model_call(FakeEvent())  # type: ignore[arg-type]
    blocks = FakeEvent.agent.system_prompt
    assert isinstance(blocks, list) and len(blocks) == 3
    assert blocks[0]["text"].startswith("Sen tau'sun.\n\n## User\n")
    assert blocks[1] == {"cachePoint": {"type": "default"}}
    assert blocks[2]["text"].startswith("## Now\n")
    assert blocks[2]["text"].endswith("- Budget: 3 $")


def test_build_system_content_is_three_blocks_with_a_cache_point(
    tmp_path: Path, fixed_now: datetime
) -> None:
    """Persona + user facts (stable) | cachePoint | ## Now (changes every minute)."""
    persona_dir = make_persona_dir(tmp_path, "Sen tau'sun.\n", "- Address: efendim\n")
    loader = PersonaLoader(persona_dir)
    context = ctx(fixed_now, budget="3 $")

    blocks = loader.build_system_content(context)

    assert blocks[0] == {"text": "Sen tau'sun.\n\n## User\n- Address: efendim\n"}
    assert blocks[1] == {"cachePoint": {"type": "default"}}
    assert blocks[2] == {"text": "## Now\n" + context.render()}
    # The SDK joins text blocks with one newline: the string form is the classic prompt.
    joined = "\n".join(block["text"] for block in blocks if "text" in block)
    assert joined == loader.build_system_prompt(context)


async def test_model_receives_the_cache_point(config: Config, fixed_now: datetime) -> None:
    model = FakeModel(["tamam"])
    agent = build_agent(config=config, model=model, tools=[], clock=lambda: fixed_now)
    await agent.ask("merhaba")

    call = model.calls[0]
    assert call.system_prompt_content is not None
    assert [list(block) for block in call.system_prompt_content] == [
        ["text"],
        ["cachePoint"],
        ["text"],
    ]
    assert call.system_prompt_content[1] == {"cachePoint": {"type": "default"}}
    expected = PersonaLoader(config.persona_dir).build_system_prompt(
        DynamicContext(now=fixed_now, profile="home", role="hub")
    )
    assert call.system_prompt == expected
    assert agent.agent.system_prompt == expected
    assert agent.agent.system_prompt_content == call.system_prompt_content


# --- dynamic context -----------------------------------------------------------------------


def test_unknown_sources_render_unknown(fixed_now: datetime) -> None:
    lines = ctx(fixed_now).render().splitlines()
    assert lines[-2:] == [f"- Live nodes: {UNKNOWN}", f"- Budget: {UNKNOWN}"]
    assert UNKNOWN == "unknown"


def test_known_values_render(fixed_now: datetime) -> None:
    rendered = ctx(fixed_now, nodes=["mac", "arm"], budget="2,40 $ kaldı").render()
    assert "- Live nodes: mac, arm" in rendered
    assert "- Budget: 2,40 $ kaldı" in rendered
    # Known to be empty is not the same as unknown.
    assert "- Live nodes: none" in ctx(fixed_now, nodes=[]).render()


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 9, 29, 12, 30, tzinfo=UTC), "29.09.2026 15:30, Tuesday"),
        (datetime(2026, 9, 28, 22, 30, tzinfo=UTC), "29.09.2026 01:30, Tuesday"),
        (
            datetime(2026, 9, 29, 8, 30, tzinfo=ZoneInfo("America/New_York")),
            "29.09.2026 15:30, Tuesday",
        ),
        (datetime(2026, 9, 29, 15, 30), "29.09.2026 15:30, Tuesday"),  # naive = Istanbul time
        (datetime(2026, 10, 4, 9, 5, tzinfo=TIMEZONE), "04.10.2026 09:05, Sunday"),
    ],
    ids=["utc", "utc-previous-day", "new-york", "naive", "sunday"],
)
def test_time_is_always_europe_istanbul(config: Config, now: datetime, expected: str) -> None:
    context = default_context_factory(config, clock=lambda: now)()
    assert context.now.tzinfo is TIMEZONE
    assert context.now.utcoffset() == timedelta(hours=3)
    assert f"- Date and time: {expected} (Europe/Istanbul)" in context.render()
    # DynamicContext built by hand renders the same way.
    assert f"- Date and time: {expected} " in ctx(now).render()


def test_default_clock_is_istanbul_now(config: Config) -> None:
    context = default_context_factory(config)()
    assert context.now.tzinfo is TIMEZONE
    assert abs(context.now - datetime.now(UTC)) < timedelta(minutes=1)


def test_profile_and_role_come_from_config(config: Config, fixed_now: datetime) -> None:
    config = config.with_overrides(profile="sport", role="node")
    rendered = default_context_factory(config, clock=lambda: fixed_now)().render()
    assert "- Profile: sport\n- Host role: node\n" in rendered


# --- context sources -----------------------------------------------------------------------


def test_sources_merge_in_order(config: Config, fixed_now: datetime) -> None:
    sources: list[Callable[[], dict]] = [
        lambda: {"nodes": ["mac"], "budget": "5 $"},
        lambda: {"nodes": ["mac", "arm"]},  # later wins
        lambda: {"budget": None},  # explicit None: back to unknown
    ]
    context = default_context_factory(config, clock=lambda: fixed_now, sources=sources)()
    assert context.nodes == ["mac", "arm"]
    assert context.budget is None
    assert "- Budget: unknown" in context.render()


def test_sources_are_read_on_every_call(config: Config, fixed_now: datetime) -> None:
    spent = iter(["1 $", "2 $"])
    factory = default_context_factory(
        config, clock=lambda: fixed_now, sources=[lambda: {"budget": next(spent)}]
    )
    assert factory().budget == "1 $"
    assert factory().budget == "2 $"


def test_source_values_are_normalized(config: Config, fixed_now: datetime) -> None:
    sources = [
        lambda: {"nodes": ("mac", 5), "budget": 2.5, "unknown_key": "yok sayılır"},
        lambda: None,  # nothing to add
    ]
    context = default_context_factory(config, clock=lambda: fixed_now, sources=sources)()
    assert context.nodes == ["mac", "5"]
    assert context.budget == "2.5"
    single = default_context_factory(
        config, clock=lambda: fixed_now, sources=[lambda: {"nodes": "mac"}]
    )()
    assert single.nodes == ["mac"]


def test_bad_sources_are_skipped_and_logged_once(
    config: Config, fixed_now: datetime, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    state = {"broken": True}

    def nodes_source() -> dict:
        if state["broken"]:
            raise ConnectionError("zenoh yok")
        return {"nodes": ["mac"]}

    sources = [
        nodes_source,
        lambda: ["liste", "değil"],
        lambda: {"nodes": 5},  # not iterable
        lambda: {"budget": "4 $"},
    ]
    factory = default_context_factory(config, clock=lambda: fixed_now, sources=sources)
    for _ in range(3):
        context = factory()
        assert context.nodes is None
        assert context.budget == "4 $"
    assert len(warnings_from(caplog)) == 3  # one per broken source, not one per call

    state["broken"] = False
    assert factory().nodes == ["mac"]
    state["broken"] = True
    factory()
    assert len(warnings_from(caplog)) == 4  # broke again after recovering: logged again


async def test_live_sources_reach_the_model(config: Config, fixed_now: datetime) -> None:
    live = {"nodes": None}
    model = FakeModel(["bir", "iki"])
    agent = build_agent(
        config=config,
        model=model,
        tools=[],
        clock=lambda: fixed_now,
        context_sources=[lambda: dict(live), lambda: {"budget": "2,40 $ kaldı"}],
    )
    await agent.ask("durum?")
    live["nodes"] = ["mac", "arm"]
    await agent.ask("şimdi?")
    first, second = (call.system_prompt or "" for call in model.calls)
    assert "- Live nodes: unknown" in first
    assert "- Live nodes: mac, arm" in second
    assert "- Budget: 2,40 $ kaldı" in first and "- Budget: 2,40 $ kaldı" in second


# --- the tracked persona files -------------------------------------------------------------


def tracked_persona() -> str:
    return PersonaLoader(REPO_PERSONA, user_file="user.example.md").read().persona


@pytest.mark.parametrize(
    "rule",
    [
        "Jarvis tarzındasın",
        "Varsayılan dilin Türkçe.",
        "Kullanıcı hangi dilde yazarsa o dilde yanıt verirsin",
        "Kibarsın.",
        "Kuru, ölçülü bir mizahın var",
        "Bildirimlerde ve sesli yanıtlarda en fazla iki cümle kurarsın.",
        "Onay isterken şaka yapmazsın",
        "Kullanıcı hakkında bilgi uydurmazsın.",
        '"User" bölümünde yazan hitapla seslenirsin',
        'hitap yazmıyorsa "siz" dersin',
        '"Now" bölümüne bakarsın',
        '"unknown" yazan bir şeyi tahmin etmezsin',
    ],
)
def test_tracked_persona_encodes_the_jarvis_rules(rule: str) -> None:
    assert rule in " ".join(tracked_persona().split())


def test_tracked_persona_files_assemble(fixed_now: datetime) -> None:
    loader = PersonaLoader(REPO_PERSONA, user_file="user.example.md")
    prompt = loader.build_system_prompt(ctx(fixed_now))
    assert prompt.startswith("# tau\n\nSen tau'sun")
    assert '\n\n## User\n- Form of address: "siz"' in prompt
    assert "\n\n## Now\n- Date and time: 29.09.2026 15:30, Tuesday" in prompt
    assert "<!--" not in prompt
    assert prompt.count("\n## User\n") == 1 and prompt.count("\n## Now\n") == 1
    # The persona must not point at headings that no longer exist.
    assert 'Kullanıcı" bölüm' not in prompt and 'Şu an" bölüm' not in prompt
    assert '"bilinmiyor"' not in prompt


@pytest.mark.parametrize("name", ["persona.md", "user.example.md"])
def test_tracked_persona_files_hold_nothing_personal(name: str) -> None:
    text = (REPO_PERSONA / name).read_text(encoding="utf-8")
    patterns = {
        "email": r"[\w.+-]+@[\w-]+\.[\w.]+",
        "ipv4": r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
        "tailnet": r"\.ts\.net\b",
        "home path": r"/(?:Users|home)/\w",
    }
    found = {label: re.findall(p, text) for label, p in patterns.items() if re.search(p, text)}
    assert found == {}


def test_user_file_is_gitignored() -> None:
    try:
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", "persona/user.md"], cwd=ROOT, timeout=30
        ).returncode
        tracked = subprocess.run(
            ["git", "ls-files", "persona"], cwd=ROOT, capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git is not available")
    if tracked.returncode != 0:
        pytest.skip("not a git checkout")
    assert ignored == 0
    assert sorted(tracked.stdout.split()) == ["persona/persona.md", "persona/user.example.md"]
