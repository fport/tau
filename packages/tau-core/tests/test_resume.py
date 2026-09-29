"""Record and resume: sessions survive a restart and ``/devam`` brings the context back."""

from __future__ import annotations

import itertools
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner
from tau_core import Config, Decision, Tier, build_agent, models, tau_tool
from tau_core.approval import AutoRejectApprover
from tau_core.cli import cli
from tau_core.config import RoleConfig, SessionsConfig
from tau_core.sessions import FileSessionStore, open_session_store
from tau_core.testing import FakeModel, ScriptedApprover, ToolCall, test_config

relay_calls: list[str] = []


@tau_tool(tier=Tier.READ)
def room_temperature() -> str:
    """Oda sıcaklığını söyler."""
    return "22 derece"


@tau_tool(tier=Tier.PHYSICAL, effect="Salondaki rölenin durumunu değiştirir.")
def relay(state: str) -> str:
    """Salondaki röleyi açar veya kapatır.

    Args:
        state: "on" ya da "off".
    """
    relay_calls.append(state)
    return f"röle {state}"


@pytest.fixture(autouse=True)
def _reset_relay() -> None:
    relay_calls.clear()


@pytest.fixture
def file_config(tmp_path: Path) -> Config:
    return test_config(tmp_path, sessions=SessionsConfig(backend="file"))


def texts(messages: list) -> list[str]:
    """The text blocks of a message list, in order (tool blocks are skipped)."""
    return [block["text"] for m in messages for block in m["content"] if "text" in block]


# -- record and resume through build_agent ----------------------------------------------------


async def test_record_and_resume_across_a_restart(file_config: Config) -> None:
    store = open_session_store(file_config)
    assert isinstance(store, FileSessionStore)
    first = build_agent(
        config=file_config,
        model=FakeModel([[ToolCall("room_temperature", {})], "Salon 22 derece, efendim."]),
        tools=[room_temperature],
        session_store=store,
    )
    session_id = first.session_id
    assert await first.ask("Salon kaç derece?") == "Salon 22 derece, efendim."
    first.close()

    # A new process: a fresh store object on the same directory, a fresh agent.
    model = FakeModel(["Salonun sıcaklığını sordunuz."])
    second = build_agent(
        config=file_config,
        model=model,
        tools=[room_temperature],
        session_store=open_session_store(file_config),
        session_id=session_id,
    )
    assert second.messages == first.messages
    assert len(second.messages) == 4  # user, tool use, tool result, reply
    await second.ask("Ne sormuştum?")

    sent = model.calls[0].messages
    assert texts(sent) == ["Salon kaç derece?", "Salon 22 derece, efendim.", "Ne sormuştum?"]
    assert any("toolUse" in block for m in sent for block in m["content"])

    reopened = open_session_store(file_config)
    summary = reopened.list_sessions()[0]
    assert summary.session_id == session_id
    assert summary.title == "Salon kaç derece?"
    assert summary.message_count == 6
    assert (summary.channel, summary.profile) == ("terminal", "ev")
    messages_dir = file_config.sessions_dir / session_id / "agents" / "tau" / "messages"
    assert sorted(p.name for p in messages_dir.iterdir()) == [f"{i:06d}.json" for i in range(6)]


async def test_tool_calls_and_approvals_are_recorded(file_config: Config) -> None:
    store = open_session_store(file_config)
    approver = ScriptedApprover([Decision.APPROVED])  # then exhausted → rejected
    agent = build_agent(
        config=file_config,
        model=FakeModel(
            [
                [ToolCall("room_temperature", {})],
                [ToolCall("relay", {"state": "on"})],
                "Röleyi açtım.",
                [ToolCall("relay", {"state": "off"})],
                "Kapatmadım.",
            ]
        ),
        tools=[room_temperature, relay],
        approver=approver,
        session_store=store,
    )
    await agent.ask("Sıcaklık kaç, sonra röleyi aç.")
    await agent.ask("Röleyi kapat.")
    agent.close()
    assert relay_calls == ["on"]  # the rejected call never ran
    assert [r.tool for r in approver.requests] == ["relay", "relay"]

    lines = (file_config.sessions_dir / agent.session_id / "events.jsonl").read_text("utf-8")
    records = [json.loads(line) for line in lines.splitlines()]
    assert all(r["session_id"] == agent.session_id for r in records)
    calls = [r["data"] for r in records if r["kind"] == "tool_call"]
    assert [(c["tool"], c["tier"], c["status"], c["approval"]) for c in calls] == [
        ("room_temperature", 0, "ok", None),
        ("relay", 2, "ok", "approved"),
        ("relay", 2, "rejected", "rejected"),
    ]
    assert calls[1]["arguments"] == {"state": "on"}
    assert calls[1]["result_summary"] == "röle on"
    approvals = [r["data"] for r in records if r["kind"] == "approval"]
    assert [(a["tool"], a["decision"], a["arguments"]) for a in approvals] == [
        ("relay", "approved", {"state": "on"}),
        ("relay", "rejected", {"state": "off"}),
    ]
    assert approvals[0]["effect"] == "Salondaki rölenin durumunu değiştirir."

    # The same records come back through the store API after a restart.
    events = open_session_store(file_config).read_events(agent.session_id)
    assert [e.kind for e in events] == [r["kind"] for r in records]


async def test_default_rejection_is_recorded(file_config: Config) -> None:
    store = open_session_store(file_config)
    agent = build_agent(
        config=file_config,
        model=FakeModel([[ToolCall("relay", {"state": "on"})], "Yapmadım."]),
        tools=[relay],
        approver=AutoRejectApprover(),
        session_store=store,
    )
    await agent.ask("Röleyi aç.")
    events = store.read_events(agent.session_id)
    assert [(e.kind, e.data.get("decision") or e.data.get("approval")) for e in events] == [
        ("approval", "rejected"),
        ("tool_call", "rejected"),
    ]
    assert relay_calls == []


async def test_sessions_listed_newest_first(
    file_config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    start = datetime(2030, 1, 1, tzinfo=UTC)
    tick = itertools.count()
    monkeypatch.setattr(
        "tau_core.sessions.file.utc_now_iso",
        lambda: (start + timedelta(seconds=next(tick))).isoformat(),
    )
    store = open_session_store(file_config)
    agents = {}
    for name in ("bir", "iki", "üç"):
        agents[name] = build_agent(
            config=file_config, model=FakeModel(), tools=[], session_store=store
        )
        await agents[name].ask(f"{name} numaralı soru")
    await agents["bir"].ask("bir, tekrar")  # the oldest session becomes the newest

    listed = store.list_sessions()
    assert [s.title for s in listed] == [
        "bir numaralı soru",
        "üç numaralı soru",
        "iki numaralı soru",
    ]
    assert [s.session_id for s in listed][0] == agents["bir"].session_id


# -- the terminal channel: quit, restart, /devam ----------------------------------------------

FILE_TOML = """\
[models.roles.brain]
provider = "fake"
model_id = "fake-brain"

[sessions]
backend = "file"
"""

CLEAN_ENV = {
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
        "TAU_PROFILE",
        "TAU_ROLE",
        "TAU_HUB_PORT",
    )
}


class Chat:
    """Runs ``tau chat`` in-process against one home + data dir; records every FakeModel."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.home = tmp_path / "home"
        (self.home / "persona").mkdir(parents=True)
        (self.home / "tau.toml").write_text(FILE_TOML, encoding="utf-8")
        (self.home / "persona" / "persona.md").write_text("Sen tau'sun.\n", encoding="utf-8")
        self.data = tmp_path / "data"
        self.sessions_dir = self.data.resolve() / "sessions"
        self.models: list[FakeModel] = []
        monkeypatch.setitem(models.PROVIDERS, "fake", self._model)

    def _model(self, role_cfg: RoleConfig, env: Mapping[str, str]) -> FakeModel:
        model = FakeModel(default="Buyurun efendim.")
        self.models.append(model)
        return model

    def __call__(self, stdin: str, *args: str) -> str:
        env = dict(CLEAN_ENV, TAU_HOME=str(self.home), TAU_DATA_DIR=str(self.data))
        result = CliRunner().invoke(cli, ["chat", *args], env=env, input=stdin, prog_name="tau")
        assert result.exit_code == 0, result.output
        assert "Traceback" not in result.output
        return result.output

    def session_ids(self) -> list[str]:
        return sorted(p.name for p in self.sessions_dir.iterdir())

    def files(self) -> set[Path]:
        return {p.relative_to(self.sessions_dir) for p in self.sessions_dir.rglob("*")}


@pytest.fixture
def chat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Chat:
    return Chat(tmp_path, monkeypatch)


def test_quit_restart_and_devam_restores_context(chat: Chat) -> None:
    out = chat("Salon kaç derece?\n/çık\n")
    assert "tau> Buyurun efendim." in out
    [first] = chat.session_ids()
    before = chat.files()

    out = chat("/devam\nNe sormuştum?\n/oturum\n/çık\n")
    assert "Son oturumlar:" in out
    assert f" 1. {first}  " in out
    assert "  terminal  Salon kaç derece? (2 mesaj)" in out
    assert f"Devam ediliyor: Salon kaç derece? · {first} (2 mesaj yüklendi)." in out
    assert f"Oturum: {first}" in out
    assert "Mesaj sayısı: 4" in out
    assert "Depo: file (" in out

    sent = chat.models[-1].calls[-1].messages
    assert texts(sent) == ["Salon kaç derece?", "Buyurun efendim.", "Ne sormuştum?"]
    store = FileSessionStore(chat.sessions_dir)
    assert len(store.list_messages(first, "tau")) == 4
    assert store.read_meta(first)["title"] == "Salon kaç derece?"  # the title is kept

    assert before <= chat.files()  # nothing deleted, the empty start-up session is kept too
    assert len(chat.session_ids()) == 2


def test_devam_by_number_and_id(chat: Chat) -> None:
    chat("birinci konu\n/çık\n")
    chat("ikinci konu\n/çık\n")
    by_title = {s.title: s.session_id for s in FileSessionStore(chat.sessions_dir).list_sessions()}
    first, second = by_title["birinci konu"], by_title["ikinci konu"]

    out = chat("/devam 2\n/devam 9\n/devam 20200101-000000-0000\n/çık\n")
    assert f"Devam ediliyor: birinci konu · {first} (2 mesaj yüklendi)." in out
    assert "Listede 9 numaralı oturum yok (1-1)." in out  # the current one is not listed
    assert "Oturum bulunamadı: 20200101-000000-0000." in out
    assert "Son oturumlar:" not in out  # an argument resumes without listing

    out = chat(f"/devam {second}\n/devam {second}\n/devam ../dışarı\n/çık\n")
    assert f"Devam ediliyor: ikinci konu · {second} (2 mesaj yüklendi)." in out
    assert f"Zaten bu oturumdasınız: {second}." in out
    assert "Geçersiz oturum kimliği: '../dışarı'." in out


def test_resume_flag_and_yeni(chat: Chat) -> None:
    chat("eski konu\n/çık\n")
    [old] = chat.session_ids()

    out = chat("/yeni\nyeni konu\n/devam\n/çık\n", "--resume", old)
    assert f"Devam ediliyor: eski konu · {old} (2 mesaj yüklendi)." in out
    new_id = out.split("Yeni oturum: ", 1)[1].split(".", 1)[0]
    assert new_id != old
    store = FileSessionStore(chat.sessions_dir)
    assert store.read_meta(new_id)["title"] == "yeni konu"
    # /devam after /yeni lists the old session and the new one is current, so it resumes "eski".
    assert out.count(f"Devam ediliyor: eski konu · {old}") == 2
    assert len(store.list_messages(old, "tau")) == 2  # resuming alone adds nothing

    out = chat("/devam\n/çık\n", "--resume")
    assert "Son oturumlar:" in out
    assert "yeni konu (2 mesaj)" in out and "eski konu (2 mesaj)" in out


def test_devam_with_nothing_earlier(chat: Chat) -> None:
    out = chat("/devam\n/oturum\n/çık\n")
    assert "Devam edilecek önceki oturum yok." in out
    assert "Başlık: (başlıksız)" in out and "Mesaj sayısı: 0" in out


def test_invalid_session_option_exits_2(chat: Chat) -> None:
    env = dict(CLEAN_ENV, TAU_HOME=str(chat.home), TAU_DATA_DIR=str(chat.data))
    result = CliRunner().invoke(cli, ["chat", "--session", "../x"], env=env, input="")
    assert result.exit_code == 2
    assert "Geçersiz oturum kimliği: '../x'." in result.output
    assert "Traceback" not in result.output
