"""Public sub-taus over the tau network (ADR 0012, issue 150): the ``sub`` field, routing to a
public sub-tau's narrow network turn, dropping private and unknown ones, the limits, universe
reports and ``tau net send ADDRESS/NAME``. Offline, over the fake network.

Tests that need real sub-tau definitions use tau-sub through the ``tau.subs`` entry point, as a
hub does; the rest use :class:`FakeSubs`, so tau-net's rules are tested on their own."""

from __future__ import annotations

import ast
import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pytest
from click.testing import CliRunner
from net_helpers import ALICE, BOB, UNIVERSE, USER_SECRET, Pair, Tau, connect, make_tau, poll
from net_helpers import send_raw as send_envelope
from tau_core import Decision, Tier, ToolFinished, build_agent
from tau_core.testing import FakeModel, ScriptedApprover, ToolCall
from tau_net import tools
from tau_net.cli import net
from tau_net.encoding import AddressError, is_valid_sub_name, parse_target
from tau_net.envelope import (
    BoxError,
    Envelope,
    Payload,
    build_envelope,
    open_box,
    open_verified,
    parse_content,
)
from tau_net.node import open_node, sub_is_ours
from tau_net.subs import SUBS_GROUP, find_sub_directory, universe_subs
from tau_net.testing import FakeNetwork, FakeUniverse
from tau_net.tools import TOOLS
from tau_net.turns import SUB_FRAME, build_frame

COACH_PERSONA = "You plan the owner's workouts: three short sessions a week."
COACH_NOTE = "- Public: the owner runs 5 km on Sunday mornings (coach's public note)."
MAIN_NOTE = "- Public: the owner likes short meetings on weekday mornings."
COACH_HEADER = "You are /coach, a specialist of your owner's tau"


def write_sub(
    tau: Tau,
    name: str = "coach",
    *,
    public: bool = True,
    note: str | None = COACH_NOTE,
    about: str = "A strict but kind workout coach.",
    persona: str = COACH_PERSONA,
) -> None:
    """A sub-tau definition in ``tau``'s persona/subs/, the way the owner writes one."""
    subs = tau.config.persona_dir / "subs"
    subs.mkdir(exist_ok=True)
    lines = [
        "+++",
        f"about = {json.dumps(about)}",
        "tools = []",
        f"public = {'true' if public else 'false'}",
    ]
    if note is not None:
        lines.append(f'public_note = "{name}.public.md"')
        (subs / f"{name}.public.md").write_text(note + "\n", encoding="utf-8")
    lines.append("+++")
    (subs / f"{name}.md").write_text("\n".join(lines) + "\n\n" + persona + "\n", encoding="utf-8")


def payloads_for(tau: Tau, sender: Tau) -> list[tuple[Payload, dict[str, str]]]:
    """The envelopes waiting in ``tau``'s spine from ``sender``, with their opened content."""
    found = []
    for mail in tau.spine.pending():
        payload = open_verified(Envelope.from_json(mail["envelope"]), sender.identity.sign_key)
        content = parse_content(payload.kind, open_box(payload.box, tau.identity, payload.aad))
        found.append((payload, content))
    return found


def last_prompt(tau: Tau) -> str:
    return tau.model.calls[-1].messages[-1]["content"][0]["text"]


@dataclass(frozen=True)
class FakeSub:
    name: str
    about: str
    role: str
    persona_file: Path
    public_note_file: Path | None


class FakeSubs:
    """A sub-tau directory without tau-sub: ``subs`` maps a name to ``(sub, public)``."""

    def __init__(self, *subs: tuple[FakeSub, bool]):
        self.subs = {sub.name: (sub, public) for sub, public in subs}
        self.lookups: list[str] = []

    def public(self, name: str) -> FakeSub | None:
        self.lookups.append(name)
        sub, public = self.subs.get(name, (None, False))
        return sub if public else None

    def public_subs(self) -> list[FakeSub]:
        return [sub for name, (sub, public) in sorted(self.subs.items()) if public]


def fake_sub(tau: Tau, name: str = "coach", *, note: Path | None = None) -> FakeSub:
    persona = tau.config.data_dir / f"{name}.persona.md"
    persona.write_text(f"You are /{name}, a test specialist.\n", encoding="utf-8")
    return FakeSub(name, f"The {name}.", "brain", persona, note)


# -- the field ---------------------------------------------------------------------------------


def test_the_sub_field_is_optional_and_checked() -> None:
    assert parse_content("message", {"text": "hi"}) == {"text": "hi"}
    assert parse_content("message", {"text": "hi", "sub": None}) == {"text": "hi"}
    assert parse_content("message", {"text": "hi", "sub": "coach"}) == {
        "text": "hi",
        "sub": "coach",
    }
    for bad in ("Coach", "c", "9lives", "co ach", "a" * 32, "coach/x", 7, ["coach"], ""):
        with pytest.raises(BoxError):
            parse_content("message", {"text": "hi", "sub": bad})
    # only a message carries it; the other kinds ignore it, like any key they do not know
    assert parse_content("contact_accept", {"name": "Bob", "sub": "Bad Name"}) == {"name": "Bob"}
    assert is_valid_sub_name("landing-page") and not is_valid_sub_name("-x")


def test_an_older_hub_reads_a_message_with_sub_as_one_for_the_main_tau() -> None:
    # Protocol v1 stays compatible: a hub that predates `sub` reads the sealed content with
    # the fields it knows and ignores the rest, and the signed header has not changed at all.
    assert parse_content("message", {"text": "hi", "sub": "coach", "later": {"x": 1}}) == {
        "text": "hi",
        "sub": "coach",
    }
    content = {"text": "hi", "sub": "coach"}
    known_before_150 = {key: content[key] for key in ("text",)}
    assert known_before_150 == {"text": "hi"}
    header = Payload.from_json(
        {
            "v": 1,
            "id": "0123456789abcdefABCD",
            "kind": "message",
            "from": ALICE,
            "to": BOB,
            "ts": 1,
            "thread": "0123456789abcdefABCD",
            "reply_to": None,
            "hops": 0,
            "box": {"epk": "AAAA", "nonce": "AAAA", "ct": "AAAA"},
            "unknown": "ignored",
        }
    )
    assert "sub" not in header.to_json()


def test_build_envelope_refuses_a_bad_sub(tmp_path: Path, network: FakeNetwork) -> None:
    a = make_tau(tmp_path, network, ALICE)
    b = make_tau(tmp_path, network, BOB)
    with pytest.raises(BoxError):
        build_envelope(
            a.identity,
            sender=ALICE,
            recipient=BOB,
            recipient_box_key=b.identity.box_key,
            kind="message",
            content={"text": "hi", "sub": "../user"},
        )


def test_targets_and_whose_sub_it_is() -> None:
    assert parse_target("bob.example") == ("bob.example", None)
    assert parse_target(" https://Bob.Example/Coach/ ") == ("bob.example", "coach")
    assert parse_target("127.0.0.1:8862/coach") == ("127.0.0.1:8862", "coach")
    assert parse_target("bob.example/") == ("bob.example", None)
    for bad in ("bob.example/Co ach", "bob.example/x", "bob.example/a/b", "/coach", "bob/../x"):
        with pytest.raises(AddressError):
            parse_target(bad)
    assert sub_is_ours(0) and not sub_is_ours(1) and sub_is_ours(2)


def test_tau_net_never_imports_tau_sub() -> None:
    import tau_net

    package = Path(tau_net.__file__).parent
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not any(name.split(".")[0] == "tau_sub" for name in names), path.name


# -- routing with real sub-taus (tau-sub through the tau.subs entry point) ----------------------


@pytest.fixture
def pair(tmp_path: Path, network: FakeNetwork) -> Pair:
    pytest.importorskip("tau_sub")
    a = make_tau(tmp_path, network, ALICE, replies=["Thanks, coach! What about Thursday?"])
    b = make_tau(
        tmp_path,
        network,
        BOB,
        replies=["Run 5 km on Sunday, then rest.", "Thursday: 20 minutes of intervals."],
    )
    a_node, b_node = connect(a, b)
    return Pair(a, b, a_node, b_node, network)


def test_a_contact_reaches_a_public_sub_tau_and_the_thread_stays_with_it(pair: Pair) -> None:
    a, b = pair.a, pair.b
    write_sub(b)
    delivery = pair.a_node.send(f"{BOB}/coach", "Plan my week, please.")
    assert delivery.status == "queued"
    [sent] = [e for e in pair.a_node.store.log(address=BOB) if e["kind"] == "message"]
    assert sent["peer_sub"] == "coach"

    [handled] = poll(pair.b_node)
    assert handled.replied
    [call] = b.model.calls
    # the coach's persona and its own public note; never user.md, never the tau's net.md
    assert COACH_HEADER in call.system_prompt
    assert COACH_PERSONA in call.system_prompt
    assert COACH_NOTE in call.system_prompt
    assert MAIN_NOTE not in call.system_prompt
    assert USER_SECRET not in call.system_prompt and "4711" not in call.system_prompt
    assert all(USER_SECRET not in str(m) for m in call.messages)
    assert "- Profile: not shared with other taus" in call.system_prompt
    assert not call.tool_specs
    prompt = last_prompt(b)
    assert prompt.splitlines()[0] == (
        "[tau network] A message for you, /coach, a specialist of your owner's tau, from "
        "another tau: Alice's tau at alice.example, a contact of your owner."
    )
    assert "<<<BEGIN HISTORY>>>\n(none)\n<<<END HISTORY>>>" in prompt  # its own history
    agent = pair.b_node.turns.agent(ALICE, pair.b_node.public_sub("coach"))
    assert agent.catalog.names() == [] and agent.gate.approver.name == "auto-reject"
    assert agent.store.read_meta(agent.session_id)["title"] == (
        "tau network · Alice's tau · /coach"
    )
    assert pair.b_node.store.sessions()[f"{ALICE}/coach"] == agent.session_id
    assert ALICE not in pair.b_node.store.sessions()  # the main tau has no session yet

    [(reply, content)] = payloads_for(a, b)
    assert content == {"text": "Run 5 km on Sunday, then rest.", "sub": "coach"}
    assert reply.hops == 1 and reply.reply_to == sent["id"] and reply.thread == sent["thread"]
    assert pair.b_node.store.log(address=ALICE)[-1]["own_sub"] == "coach"

    # Alice's main tau answers the coach; its reply goes back to /coach (hops 2) ...
    [back] = poll(pair.a_node)
    assert back.replied
    assert "at bob.example/coach, a contact of your owner." in last_prompt(a)
    assert pair.a_node.store.log(address=BOB)[-2]["peer_sub"] == "coach"
    [(second, content)] = payloads_for(b, a)
    assert content == {"text": "Thanks, coach! What about Thursday?", "sub": "coach"}
    assert second.hops == 2
    # ... and the coach answers again, in its own session and history
    poll(pair.b_node)
    first, again = b.model.calls
    assert COACH_HEADER in again.system_prompt
    assert len(again.messages) > len(first.messages)
    assert "in: Plan my week, please." in last_prompt(b)
    assert "out: Run 5 km on Sunday, then rest." in last_prompt(b)
    assert "Hello from Alice's tau." not in last_prompt(b)  # the main tau's history stays apart


def test_the_main_tau_keeps_answering_without_sub(pair: Pair) -> None:
    write_sub(pair.b)
    pair.a_node.send(BOB, "Hello Bob's tau.")
    poll(pair.b_node)
    [call] = pair.b.model.calls
    assert COACH_HEADER not in call.system_prompt and MAIN_NOTE in call.system_prompt
    [(_, content)] = payloads_for(pair.a, pair.b)
    assert content == {"text": "Run 5 km on Sunday, then rest."}


def test_a_sub_tau_without_a_note_shares_the_tau_public_note_only(pair: Pair) -> None:
    write_sub(pair.b, note=None)
    pair.a_node.send(f"{BOB}/coach", "Who are you?")
    poll(pair.b_node)
    [call] = pair.b.model.calls
    assert COACH_HEADER in call.system_prompt and MAIN_NOTE in call.system_prompt
    assert USER_SECRET not in call.system_prompt


@pytest.mark.parametrize("setup", ["private", "unknown", "invalid"])
def test_private_unknown_or_invalid_sub_taus_are_dropped_unanswered(
    pair: Pair, setup: str, caplog: pytest.LogCaptureFixture
) -> None:
    if setup == "private":
        write_sub(pair.b, public=False)
    elif setup == "invalid":
        write_sub(pair.b)
        path = pair.b.config.persona_dir / "subs" / "coach.md"
        path.write_text(path.read_text().replace("tools = []", 'tools = ["no_such_tool"]'))
    caplog.set_level(logging.INFO, logger="tau_net.node")
    pair.a_node.send(f"{BOB}/coach", "Plan my week, please.")
    [handled] = poll(pair.b_node)
    assert handled.outcome == "dropped" and handled.reason == "no public sub-tau /coach"
    assert not handled.replied
    assert pair.b.model.calls == [] and pair.a.spine.pending() == []
    assert pair.b_node.store.log(address=ALICE)[-1]["kind"] != "message"  # not logged
    assert "no public sub-tau /coach" in caplog.text
    record = next(r for r in caplog.records if "no public sub-tau" in r.getMessage())
    assert record.levelno == logging.INFO  # like a stranger


def test_hop_limit_and_hourly_cap_apply_to_sub_taus(tmp_path: Path, network: FakeNetwork) -> None:
    pytest.importorskip("tau_sub")
    a = make_tau(tmp_path, network, ALICE)
    b = make_tau(tmp_path, network, BOB, component={"max_hops": 2, "max_auto_replies_per_hour": 2})
    a_node, b_node = connect(a, b)
    write_sub(b)
    send_envelope(a, b, "deep", hops=2, content={"text": "deep", "sub": "coach"})
    [handled] = poll(b_node)
    assert handled.outcome == "handled" and not handled.replied and b.model.calls == []
    assert b_node.store.log(address=ALICE)[-1]["own_sub"] == "coach"  # logged, not answered

    a_node.send(f"{BOB}/coach", "one")
    a_node.send(BOB, "two")  # the cap counts the contact, whoever answers
    a_node.send(f"{BOB}/coach", "three")
    handled = poll(b_node)
    assert [h.replied for h in handled] == [True, True, False]
    assert len(b.model.calls) == 2


def test_an_odd_hop_names_the_senders_sub_tau_never_ours(pair: Pair) -> None:
    # hops 1 is an answer from Alice's side, so `sub` is Alice's sub-tau: Bob's own coach
    # (private here) is never reached, and Bob's main tau answers back to /coach.
    write_sub(pair.b, public=False)
    send_envelope(
        pair.a, pair.b, "From Alice's coach.", hops=1, content={"text": "x", "sub": "coach"}
    )
    [handled] = poll(pair.b_node)
    assert handled.replied
    [call] = pair.b.model.calls
    assert COACH_HEADER not in call.system_prompt
    assert "at alice.example/coach, a contact of your owner." in last_prompt(pair.b)
    [(reply, content)] = payloads_for(pair.a, pair.b)
    assert content["sub"] == "coach" and reply.hops == 2


def test_the_command_line_sends_to_a_sub_tau_and_logs_it(pair: Pair, monkeypatch) -> None:
    write_sub(pair.b)

    def invoke(tau: Tau, *args: str):
        monkeypatch.setenv("TAU_DATA_DIR", str(tau.config.data_dir))
        obj = {
            "home": tau.config.home,
            "net_env": tau.env,
            "net_transport": tau.network,
            "net_model_factory": lambda: tau.model,
        }
        return CliRunner().invoke(net, list(args), obj=obj)

    sent = invoke(pair.a, "send", f"{BOB}/coach", "Plan", "my", "week.")
    assert sent.exit_code == 0, sent.output
    assert sent.output.strip() == "Sent to bob.example/coach (queued)."
    assert invoke(pair.b, "poll", "--once").output.strip() == "1 handled, 0 dropped, 1 replied."
    log_b = invoke(pair.b, "log", "-n", "2").output.splitlines()
    assert "← alice.example (/coach)  message  Plan my week." in log_b[0]
    assert "→ alice.example (/coach)  message  Run 5 km on Sunday, then rest." in log_b[1]
    poll(pair.a_node)
    log_a = invoke(pair.a, "log", "--address", BOB, "-n", "3").output.splitlines()
    assert "→ bob.example/coach  message  Plan my week." in log_a[0]
    assert "← bob.example/coach  message  Run 5 km on Sunday, then rest." in log_a[1]
    assert "→ bob.example/coach  message  Thanks, coach! What about Thursday?" in log_a[2]
    bad = invoke(pair.a, "send", f"{BOB}/Not A Name", "hi")
    assert bad.exit_code != 0 and "not a sub-tau name" in bad.output


# -- without tau-sub ---------------------------------------------------------------------------


def test_without_a_sub_directory_every_sub_message_is_dropped(
    tmp_path: Path, network: FakeNetwork
) -> None:
    a = make_tau(tmp_path, network, ALICE)
    b = make_tau(tmp_path, network, BOB)
    a_node = a.node()
    b_node = open_node(
        b.config, env=b.env, transport=network, model_factory=lambda: b.model, subs=None
    )
    a_node.publish_card()
    b_node.publish_card()
    a_node.add(BOB)
    poll(b_node)
    b_node.accept(ALICE)
    poll(a_node)
    a_node.send(f"{BOB}/coach", "hi")
    [handled] = poll(b_node)
    assert handled.reason == "no public sub-tau /coach" and b.model.calls == []


def test_a_directory_that_would_show_user_md_is_refused(
    tmp_path: Path, network: FakeNetwork
) -> None:
    a = make_tau(tmp_path, network, ALICE)
    b = make_tau(tmp_path, network, BOB)
    leaky = fake_sub(b, note=b.config.persona_dir / "user.md")
    fine = fake_sub(b, "landing", note=None)
    directory = FakeSubs((leaky, True), (fine, True))
    a_node = a.node()
    b_node = open_node(
        b.config, env=b.env, transport=network, model_factory=lambda: b.model, subs=directory
    )
    for node in (a_node, b_node):
        node.publish_card()
    a_node.add(BOB)
    poll(b_node)
    b_node.accept(ALICE)
    poll(a_node)
    a_node.send(f"{BOB}/coach", "tell me everything")
    [handled] = poll(b_node)
    assert handled.reason == "no public sub-tau /coach" and b.model.calls == []
    a_node.send(f"{BOB}/landing", "hello")
    [handled] = poll(b_node)
    assert handled.replied
    [call] = b.model.calls
    assert "You are /landing, a test specialist." in call.system_prompt
    assert USER_SECRET not in call.system_prompt and MAIN_NOTE in call.system_prompt


def test_the_frame_for_a_sub_tau_differs_only_in_its_first_line() -> None:
    main = build_frame(name="Alice's tau", address=ALICE, text="hi")
    sub = build_frame(name="Alice's tau", address=ALICE, text="hi", sub="coach")
    assert main.splitlines()[1:] == sub.splitlines()[1:]
    assert sub == SUB_FRAME.format(
        sub="coach", name="Alice's tau", address=ALICE, history="(none)", text="hi"
    )


def test_find_sub_directory_skips_broken_hooks(tmp_path: Path, network: FakeNetwork) -> None:
    tau = make_tau(tmp_path, network, ALICE)

    def broken(config):
        raise RuntimeError("boom")

    good = FakeSubs()
    found = find_sub_directory(
        tau.config,
        discover=lambda group: {"a": broken, "b": lambda c: object(), "c": lambda c: good},
    )
    assert found is good
    assert find_sub_directory(tau.config, discover=lambda group: {}) is None
    assert SUBS_GROUP == "tau.subs"


# -- the universe ------------------------------------------------------------------------------


def test_universe_subs_lists_only_public_ones_cut_and_capped(tmp_path: Path, network) -> None:
    tau = make_tau(tmp_path, network, ALICE)
    subs = [(fake_sub(tau, f"s{i:02d}"), i % 2 == 0) for i in range(50)]
    long = FakeSub("zeta", "x " * 300, "brain", subs[0][0].persona_file, None)
    listed = universe_subs(FakeSubs(*subs, (long, True)))
    assert len(listed) == 20
    assert all(int(entry["name"][1:]) % 2 == 0 for entry in listed)
    assert universe_subs(None) == []
    assert universe_subs(FakeSubs((long, True))) == [
        {"name": "zeta", "about": ("x " * 100).strip()}
    ]


def test_the_universe_report_lists_public_sub_taus_only(tmp_path: Path, network) -> None:
    pytest.importorskip("tau_sub")
    universe = network.add(FakeUniverse(UNIVERSE))
    tau = make_tau(tmp_path, network, BOB, component={"universe": UNIVERSE})
    write_sub(tau, "coach", about="A strict but kind workout coach.")
    write_sub(tau, "landing", about="Writes landing-page copy.", note=None)
    write_sub(tau, "diary", public=False, about="Private diary helper.")
    node = tau.node()
    node.publish_card()
    node.update_profile(universe_join=True)
    node.universe_join()
    node.universe_report()
    [report] = universe.payloads("report")
    assert report["subs"] == [
        {"name": "coach", "about": "A strict but kind workout coach."},
        {"name": "landing", "about": "Writes landing-page copy."},
    ]
    [entry] = universe.snapshot()["taus"]
    assert [sub["name"] for sub in entry["subs"]] == ["coach", "landing"]
    assert "diary" not in json.dumps(universe.payloads())
    # a sub-tau made private leaves the universe with the next report
    write_sub(tau, "landing", public=False, note=None)
    write_sub(tau, "coach", public=False)
    node.universe_report()
    assert "subs" not in universe.payloads("report")[-1]
    assert universe.snapshot()["taus"][0]["subs"] == []


def test_a_report_without_public_sub_taus_is_unchanged(tmp_path: Path, network) -> None:
    universe = network.add(FakeUniverse(UNIVERSE))
    tau = make_tau(tmp_path, network, BOB, component={"universe": UNIVERSE})
    node = tau.node()
    node.publish_card()
    node.universe_join()
    node.universe_report()
    [report] = universe.payloads("report")
    assert set(report) == {"v", "kind", "universe", "address", "ts", "links"}


# -- the owner's tool --------------------------------------------------------------------------


@pytest.mark.parametrize("decision", [Decision.APPROVED, Decision.REJECTED])
def test_net_send_reaches_a_sub_tau_only_after_an_approval(pair: Pair, decision) -> None:
    write_sub(pair.b)
    tools.node_factory = lambda: pair.a_node
    call = ToolCall("net_send", {"address": f"{BOB}/coach", "text": "Plan my week."})
    model = FakeModel([[call], "Done."])
    approver = ScriptedApprover([decision])
    agent = build_agent(config=pair.a.config, model=model, tools=TOOLS, approver=approver)

    async def collect() -> list:
        return [event async for event in agent.stream("Ask Bob's coach for a plan.")]

    [finished] = [e for e in asyncio.run(collect()) if isinstance(e, ToolFinished)]
    [request] = approver.requests
    assert request.tool == "net_send" and request.tier is Tier.PHYSICAL
    if decision is Decision.REJECTED:
        assert finished.status == "rejected" and pair.b.spine.pending() == []
        return
    assert finished.status == "ok" and finished.summary == f"Sent to {BOB}/coach."
    [(payload, content)] = payloads_for(pair.b, pair.a)
    assert content == {"text": "Plan my week.", "sub": "coach"} and payload.hops == 0
