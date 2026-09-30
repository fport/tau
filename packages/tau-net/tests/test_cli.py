"""``tau net`` through click's CliRunner, over the fake network (no sockets)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from net_helpers import ALICE, BOB, Tau, make_tau
from tau_core import Config
from tau_core.cli import cli
from tau_net.cli import net
from tau_net.identity import IDENTITY_ENV, Identity, identity_path


@pytest.fixture
def invoke(monkeypatch: pytest.MonkeyPatch):
    def run(tau: Tau, *args: str, env: dict[str, str] | None = None) -> Result:
        monkeypatch.setenv("TAU_DATA_DIR", str(tau.config.data_dir))
        obj = {
            "home": tau.config.home,
            "net_env": tau.env if env is None else env,
            "net_transport": tau.network,
            "net_model_factory": lambda: tau.model,
        }
        return CliRunner().invoke(net, list(args), obj=obj)

    return run


def test_init_creates_keeps_and_names(tmp_path: Path, network, invoke) -> None:
    tau = make_tau(tmp_path, network, ALICE, with_identity=False)
    result = invoke(tau, "init")
    assert result.exit_code == 0, result.output
    path = identity_path(tau.config.data_dir)
    assert f"Created the network identity at {path}." in result.output
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "sign_key  " in result.output and "box_key   " in result.output
    assert "persona/net.md" in result.output and "tau net publish" in result.output
    before = path.read_bytes()
    again = invoke(tau, "init", "--name", "Alice's own tau")
    assert again.exit_code == 0
    assert f"An identity already exists at {path}; it was kept." in again.output
    assert path.read_bytes() == before
    config = Config.load(tau.config.home, env={"TAU_DATA_DIR": str(tau.config.data_dir)})
    assert config.component("net")["name"] == "Alice's own tau"


def test_init_with_an_identity_from_the_environment(tmp_path: Path, network, invoke) -> None:
    tau = make_tau(tmp_path, network, ALICE, with_identity=False)
    identity = Identity.generate()
    result = invoke(tau, "init", env={**tau.env, IDENTITY_ENV: identity.to_env_value()})
    assert result.exit_code == 0
    assert "The identity comes from TAU_NET_IDENTITY" in result.output
    assert identity.sign_key in result.output
    assert not identity_path(tau.config.data_dir).exists()


def test_publish_card_and_status(tmp_path: Path, network, invoke) -> None:
    tau = make_tau(tmp_path, network, ALICE)
    before = invoke(tau, "status")
    assert before.exit_code == 0, before.output
    assert "card:     not published" in before.output
    assert "address alice.example, mode local" in before.output
    published = invoke(tau, "publish")
    assert published.output.strip() == "Published the card of alice.example as Alice's tau."
    card = invoke(tau, "card")
    assert json.loads(card.output)["sign_key"] == tau.identity.sign_key
    status = invoke(tau, "status")
    assert "card:     published, matches this identity" in status.output
    assert "contacts: 0 accepted, 0 asking you, 0 waiting, 0 blocked" in status.output
    assert f"store:    file ({tau.config.data_dir / 'net'})" in status.output
    assert "check:    ok configured" in status.output
    assert "test-hub-token" not in status.output


def test_the_whole_conversation_from_the_command_line(tmp_path: Path, network, invoke) -> None:
    a = make_tau(tmp_path, network, ALICE)
    b = make_tau(tmp_path, network, BOB, replies=["Bob is free on Friday."])
    assert invoke(a, "publish").exit_code == 0 and invoke(b, "publish").exit_code == 0

    added = invoke(a, "add", "bob.example", "--note", "Alice would like to plan a hike.")
    assert added.output.strip() == (
        "Sent a contact request to bob.example. It becomes a contact once they accept."
    )
    assert invoke(b, "poll", "--once").output.strip() == "1 handled, 0 dropped, 0 replied."
    listing = invoke(b, "contacts").output
    assert "asks you  alice.example  Alice's tau" in listing
    assert "note: Alice would like to plan a hike." in listing
    assert invoke(b, "accept", "alice.example").output.strip() == "alice.example is a contact now."
    invoke(a, "poll", "--once")
    assert "contact  bob.example  Bob's tau" in invoke(a, "contacts").output

    sent = invoke(a, "send", "bob.example", "When", "is", "Bob", "free?")
    assert sent.output.strip() == "Sent to bob.example (queued)."
    assert invoke(b, "poll", "--once").output.strip() == "1 handled, 0 dropped, 1 replied."
    [call] = b.model.calls
    assert "When is Bob free?" in call.messages[-1]["content"][0]["text"]
    invoke(a, "poll", "--once")
    log = invoke(a, "log", "--address", "bob.example", "-n", "2").output.splitlines()
    assert len(log) == 2
    assert "← bob.example  message  Bob is free on Friday." in log[0]
    assert "→ bob.example  message" in log[1]  # A's own network turn answered in turn


def test_block_remove_and_errors(tmp_path: Path, network, invoke) -> None:
    a = make_tau(tmp_path, network, ALICE)
    invoke(a, "publish")
    blocked = invoke(a, "block", "Eve.Example")
    assert blocked.output.strip() == "Blocked eve.example: nothing from it is read or answered."
    assert invoke(a, "remove", "eve.example").output.strip() == "Removed eve.example."
    assert invoke(a, "remove", "eve.example").output.strip() == "eve.example was not a contact."

    result = invoke(a, "send", "carol.example", "hi")
    assert result.exit_code == 1
    assert result.stderr.strip() == (
        "tau net: carol.example is not an accepted contact (not a contact)"
    )
    result = invoke(a, "add", "nobody.example")
    assert result.exit_code == 1
    assert "card of nobody.example unavailable" in result.stderr
    result = invoke(a, "accept", "bob.example")
    assert (result.exit_code, result.stderr.strip()) == (
        1,
        "tau net: no contact request from bob.example",
    )
    result = invoke(a, "add", "not an address")
    assert result.exit_code == 1 and "not a tau address" in result.stderr


def test_without_a_spine(tmp_path: Path, network, invoke) -> None:
    a = make_tau(tmp_path, network, ALICE)
    status = invoke(a, "status", env={})
    assert status.exit_code == 0
    assert "spine:    not configured" in status.output
    assert "check:    info not configured (TAU_SPINE_URL is not set)" in status.output
    card = invoke(a, "card", env={})
    assert "`tau net publish` would send" in card.output
    result = invoke(a, "publish", env={})
    assert result.exit_code == 1
    assert "TAU_SPINE_URL and TAU_SPINE_TOKEN are not both set" in result.stderr
    assert invoke(a, "contacts", env={}).output.strip() == (
        "No contacts yet. Add one with `tau net add <address>`."
    )


def test_output_follows_the_ui_language(tmp_path: Path, network, invoke, monkeypatch) -> None:
    a = make_tau(tmp_path, network, ALICE)
    monkeypatch.setenv("TAU_LANG", "tr")
    assert invoke(a, "contacts").output.strip() == "Henüz kişi yok. `tau net add <adres>` ile ekle."
    assert (
        invoke(a, "publish").output.strip() == "alice.example kartı Alice's tau adıyla yayımlandı."
    )


def test_mounted_under_the_tau_command(tmp_path: Path, network, monkeypatch) -> None:
    a = make_tau(tmp_path, network, ALICE)
    monkeypatch.setenv("TAU_DATA_DIR", str(a.config.data_dir))
    obj = {"net_env": a.env, "net_transport": network}
    result = CliRunner().invoke(cli, ["--home", str(a.config.home), "net", "publish"], obj=obj)
    assert result.exit_code == 0, result.output
    assert "Published the card of alice.example" in result.output
    help_text = CliRunner().invoke(cli, ["net", "--help"]).output
    assert "send" in help_text and "poll" in help_text
