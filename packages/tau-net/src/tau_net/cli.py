"""``tau net``: the owner's commands for the tau network (``tau.commands`` entry point ``net``).

Every command reads ``tau.toml`` and ``.env`` like the rest of tau (``--home``, ``TAU_HOME``,
``TAU_DATA_DIR``). Output lines go through ``tau_core.i18n`` in the configured UI language;
help texts and error lines are English. Exit codes: 0 ok, 1 error with one line on stderr,
2 when the configuration itself cannot be loaded.

Nothing here writes ``tau.toml``: the card name (``tau net init --name``, ``tau net name``) and
the universe membership (``tau net universe join|leave``) are the owner's profile in the
network store (:mod:`tau_net.profile`).

Tests pass a transport through the click context object (``obj={"net_transport": ...}``);
``net_env`` and ``net_model_factory`` work the same way, and ``spine_runner`` /
``spine_environ`` replace the program runner and the environment of ``tau net spine deploy``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn

import click
from tau_core import LANGUAGES, Config, ConfigError, t
from tau_core.cli import help_option
from tau_core.config import resolve_home
from tau_core.i18n import DEFAULT_LANGUAGE

from tau_net import spine_strings as _spine_strings  # noqa: F401  (registers the spine keys)
from tau_net import strings as _strings  # noqa: F401  (registers the message keys)
from tau_net.config import NetConfigError
from tau_net.contacts import PENDING_IN, ContactError
from tau_net.encoding import AddressError, is_valid_handle, parse_target
from tau_net.envelope import EnvelopeError
from tau_net.identity import (
    IDENTITY_ENV,
    IdentityError,
    IdentityExists,
    create_identity,
    identity_path,
)
from tau_net.node import NetError, NetNode, open_node
from tau_net.peers import CardError
from tau_net.service import doctor_check
from tau_net.spine import SpineError
from tau_net.spine_kit import SpineKitError, deploy_project, init_project, is_workers_dev
from tau_net.universe import MalformedRequest, UniverseError, tau_links, tau_subs

__all__ = ["net"]

logger = logging.getLogger(__name__)

ERRORS = (
    NetError,
    ContactError,
    AddressError,
    CardError,
    SpineError,
    IdentityError,
    NetConfigError,
    EnvelopeError,
    UniverseError,
    MalformedRequest,
)


def _obj(ctx: click.Context) -> dict[str, Any]:
    return ctx.find_object(dict) or {}


def _config(ctx: click.Context) -> Config:
    obj = _obj(ctx)
    try:
        config = Config.load(obj.get("home"))
    except ConfigError as exc:
        click.echo(str(exc), err=True)
        ctx.exit(2)
    if obj.get("profile"):
        config = config.with_overrides(profile=obj["profile"])
    return config


def _fail(ctx: click.Context, error: BaseException) -> NoReturn:
    message = " ".join(str(error).split()) or type(error).__name__
    click.echo(f"tau net: {message}", err=True)
    ctx.exit(1)
    raise AssertionError("unreachable")  # pragma: no cover


def _node(ctx: click.Context, config: Config) -> NetNode:
    obj = _obj(ctx)
    try:
        return open_node(
            config,
            env=obj.get("net_env"),
            transport=obj.get("net_transport"),
            model_factory=obj.get("net_model_factory"),
        )
    except ERRORS as exc:
        _fail(ctx, exc)


def _run(ctx: click.Context, action: Callable[[], Any]) -> Any:
    try:
        return action()
    except ERRORS as exc:
        _fail(ctx, exc)


class _Say:
    def __init__(self, config: Config):
        self.language = config.ui.language

    def __call__(self, message: str, /, **kwargs: Any) -> None:
        click.echo(t(message, self.language, **kwargs))


PUBLIC_NOTE_TEMPLATE = """<!--
Your public note for other taus (ADR 0007). When a contact's tau writes to yours, the network
turn reads this file instead of persona/user.md: it is everything your tau may share about you
with another tau. Write only what you would tell a colleague's assistant, for example the name
to use, your time zone, when you are usually free, the languages you speak. Leave out anything
private. An empty note (only this comment) shares nothing. HTML comments never reach the model.
-->
"""


@click.group(
    name="net",
    help="The tau network: your tau's identity, card and contacts, and messages to other taus.",
    short_help="Talk to other taus (identity, contacts, messages).",
)
@help_option()
def net() -> None:
    pass


# -- identity and card -------------------------------------------------------------------------


@net.command(
    name="init",
    help="Create this tau's network identity (an Ed25519 signing key and an X25519 box key) "
    "under TAU_DATA_DIR/net/identity.json. An existing identity is never overwritten. "
    "--name sets the display name on the card in the network profile (never tau.toml).",
    short_help="Create the network identity.",
)
@help_option()
@click.option("--name", metavar="NAME", help='Display name on the card, e.g. "Alice\'s tau".')
@click.pass_context
def init_command(ctx: click.Context, name: str | None) -> None:
    config = _config(ctx)
    say = _Say(config)
    node = _node(ctx, config)
    path = identity_path(config.data_dir)
    if node.identity is not None and node.identity.source == "env":
        say("net.init.env")
        identity = node.identity
    else:
        try:
            identity = create_identity(path)
            say("net.init.created", path=path)
        except IdentityExists:
            say("net.init.kept", path=path)
            identity = node.identity
            if identity is None:
                _fail(ctx, IdentityError(f"{path} exists but cannot be read"))
        except OSError as exc:
            _fail(ctx, NetError(f"cannot write {path}: {exc.strerror or exc}"))
    if name is not None:
        profile = _run(ctx, lambda: node.update_profile(name=name))
        say("net.name.saved", name=profile.name, store=node.store.describe())
    say("net.keys.sign", key=identity.sign_key)
    say("net.keys.box", key=identity.box_key)
    note = config.persona_dir / node.settings.public_note
    if not note.exists():
        with contextlib.suppress(OSError):
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(PUBLIC_NOTE_TEMPLATE, encoding="utf-8")
            say("net.init.note_written", path=note)
    click.echo()
    say("net.init.next")
    if node.spine is None:
        say("net.init.step_env")
    say("net.init.step_note", note=node.settings.public_note)
    say("net.init.step_publish")


@net.command(
    name="name",
    help="Set the display name on the card (1 to 80 characters). It is kept in the network "
    "profile under TAU_DATA_DIR/net (net.profile on the spine in cloud mode), never in "
    "tau.toml, and wins over [component.net] name. Publish it with `tau net publish`.",
    short_help="Set the card's display name.",
)
@help_option()
@click.argument("name", nargs=-1, required=True)
@click.pass_context
def name_command(ctx: click.Context, name: tuple[str, ...]) -> None:
    config = _config(ctx)
    say = _Say(config)
    node = _node(ctx, config)
    profile = _run(ctx, lambda: node.update_profile(name=" ".join(name)))
    say("net.name.saved", name=profile.name, store=node.store.describe())
    say("net.name.publish")


def _display_name(node: NetNode) -> str:
    try:
        return node.display_name()
    except SpineError:
        return node.settings.name


@net.command(
    name="status",
    help="Show the identity, the spine's health, whether the published card matches, the "
    "contacts by state and where the network state is stored.",
    short_help="Show the network status.",
)
@help_option()
@click.pass_context
def status_command(ctx: click.Context) -> None:
    config = _config(ctx)
    say = _Say(config)
    node = _node(ctx, config)
    say("net.status.name", name=_display_name(node))
    if node.identity is None:
        say("net.status.identity_missing")
    else:
        source = node.identity.source
        say("net.status.identity", source=IDENTITY_ENV if source == "env" else source[5:])
        say("net.keys.sign", key=node.identity.sign_key)
        say("net.keys.box", key=node.identity.box_key)
    if node.spine is None:
        say("net.status.spine_missing")
    else:
        try:
            health = node.spine.health()
            say(
                "net.status.spine",
                url=node.spine.url,
                address=health.get("address"),
                mode=health.get("mode"),
                mailbox=health.get("mailbox"),
            )
            if node.identity is not None:
                card = node.spine.card()
                if card is None:
                    say("net.status.card_missing")
                elif node.card_matches(card):
                    say("net.status.card_matches")
                else:
                    say("net.status.card_differs")
        except SpineError as exc:
            say("net.status.spine_error", url=node.spine.url, error=exc)
    try:
        counts = node.contacts.counts()
        say("net.status.contacts", **counts)
    except SpineError as exc:
        say("net.status.spine_error", url=node.spine.url if node.spine else "-", error=exc)
    say("net.status.store", store=node.store.describe())
    check = doctor_check(config, node.env, None)
    say("net.status.doctor", status=check.status, detail=check.detail)


@net.command(
    name="card",
    help="Print the card the spine serves at /.well-known/tau.json, or the fields `tau net "
    "publish` would send when there is none (or no spine).",
    short_help="Print the card.",
)
@help_option()
@click.pass_context
def card_command(ctx: click.Context) -> None:
    config = _config(ctx)
    say = _Say(config)
    node = _node(ctx, config)
    card = _run(ctx, node.spine.card) if node.spine is not None else None
    if card is None:
        fields = _run(ctx, node.wanted_card)
        say("net.card.local")
        card = fields
    click.echo(json.dumps(card, ensure_ascii=False, indent=2))


@net.command(
    name="publish",
    help="Publish the card (the name from the network profile, `tau net name`, else "
    "[component.net] name in tau.toml; the public keys) on the "
    "spine with PUT /hub/card.",
    short_help="Publish the card.",
)
@help_option()
@click.pass_context
def publish_command(ctx: click.Context) -> None:
    config = _config(ctx)
    node = _node(ctx, config)
    card = _run(ctx, node.publish_card)
    _Say(config)("net.publish.done", address=card.get("address"), name=card.get("name"))


# -- contacts ----------------------------------------------------------------------------------


@net.command(
    name="contacts",
    help="List the contacts and the pending requests.",
    short_help="List contacts.",
)
@help_option()
@click.pass_context
def contacts_command(ctx: click.Context) -> None:
    config = _config(ctx)
    say = _Say(config)
    node = _node(ctx, config)
    contacts = _run(ctx, node.contacts.all)
    if not contacts:
        say("net.contacts.none")
        return
    width = max(len(t(f"net.state.{c.state}", say.language)) for c in contacts)
    for contact in contacts:
        state = t(f"net.state.{contact.state}", say.language)
        name = f"  {contact.name}" if contact.name else ""
        click.echo(f"{state:<{width}}  {contact.address}{name}")
        if contact.note and contact.state == PENDING_IN:
            say("net.contacts.note", note=" ".join(contact.note.split())[:200])


@net.command(
    name="add",
    help="Ask another tau to become a contact: fetch its card, remember it as pending and "
    "send a signed, encrypted contact request. If it had asked already, this accepts it. "
    "ADDRESS is a host (tau.example.com) or a hosted tau (tau.example.com/@alice).",
    short_help="Ask another tau to become a contact.",
)
@help_option()
@click.argument("address")
@click.option("--note", default="", metavar="TEXT", help="An introduction sent with the request.")
@click.pass_context
def add_command(ctx: click.Context, address: str, note: str) -> None:
    config = _config(ctx)
    node = _node(ctx, config)
    contact = _run(ctx, lambda: node.add(address, note))
    key = "net.add.accepted" if contact.state == "accepted" else "net.add.sent"
    _Say(config)(key, address=contact.address)


@net.command(
    name="accept",
    help="Accept a pending contact request: pin its keys and send a contact_accept.",
    short_help="Accept a contact request.",
)
@help_option()
@click.argument("address")
@click.pass_context
def accept_command(ctx: click.Context, address: str) -> None:
    config = _config(ctx)
    node = _node(ctx, config)
    contact = _run(ctx, lambda: node.accept(address))
    _Say(config)("net.accept.done", address=contact.address)


@net.command(
    name="block",
    help="Block an address: nothing it sends is read or answered.",
    short_help="Block an address.",
)
@help_option()
@click.argument("address")
@click.pass_context
def block_command(ctx: click.Context, address: str) -> None:
    config = _config(ctx)
    node = _node(ctx, config)
    contact = _run(ctx, lambda: node.block(address))
    _Say(config)("net.block.done", address=contact.address)


@net.command(
    name="remove",
    help="Forget a contact (its log and session stay).",
    short_help="Forget a contact.",
)
@help_option()
@click.argument("address")
@click.pass_context
def remove_command(ctx: click.Context, address: str) -> None:
    config = _config(ctx)
    node = _node(ctx, config)
    removed = _run(ctx, lambda: node.remove(address))
    key = "net.remove.done" if removed else "net.remove.none"
    _Say(config)(key, address=address.strip().lower())


# -- messages ----------------------------------------------------------------------------------


def _log_party(entry: dict[str, Any]) -> str:
    """The other side of a log entry: ``address``, ``address/sub`` when the other tau's
    sub-tau took part, and `` (/sub)`` when one of this tau's sub-taus did."""
    address = str(entry.get("address"))
    peer_sub, own_sub = entry.get("peer_sub"), entry.get("own_sub")
    if isinstance(peer_sub, str) and peer_sub:
        return f"{address}/{peer_sub}"
    if isinstance(own_sub, str) and own_sub:
        return f"{address} (/{own_sub})"
    return address


@net.command(
    name="send",
    help="Send a message in your name to an accepted contact (signed and end-to-end "
    "encrypted, at most 8000 characters). ADDRESS is a host (tau.example.com) or a hosted "
    "tau (tau.example.com/@alice). ADDRESS/NAME writes to that tau's public sub-tau /NAME, "
    "e.g. tau.example.com/coach or tau.example.com/@alice/coach; its answer comes back from "
    "/NAME.",
    short_help="Send a message to a contact.",
)
@help_option()
@click.argument("address", metavar="ADDRESS[/NAME]")
@click.argument("text", nargs=-1, required=True)
@click.pass_context
def send_command(ctx: click.Context, address: str, text: tuple[str, ...]) -> None:
    config = _config(ctx)
    node = _node(ctx, config)
    _, sub = _run(ctx, lambda: parse_target(address))
    delivery = _run(ctx, lambda: node.send(address, " ".join(text)))
    target = f"{delivery.address}/{sub}" if sub else delivery.address
    _Say(config)("net.send.done", address=target, status=delivery.status)


@net.command(
    name="log",
    help="Show the network log (messages and requests in and out), oldest first.",
    short_help="Show the network log.",
)
@help_option()
@click.option("--address", metavar="ADDRESS", help="Only entries with this address.")
@click.option("-n", "limit", type=click.IntRange(1, 500), default=20, show_default=True)
@click.pass_context
def log_command(ctx: click.Context, address: str | None, limit: int) -> None:
    from datetime import datetime

    from tau_core.persona import TIMEZONE

    config = _config(ctx)
    node = _node(ctx, config)
    wanted = address.strip().lower() if address else None
    entries = _run(ctx, lambda: node.store.log(address=wanted, limit=limit))
    if not entries:
        _Say(config)("net.log.empty")
        return
    for entry in entries:
        ts = entry.get("ts")
        when = (
            f"{datetime.fromtimestamp(ts, TIMEZONE):%d.%m.%Y %H:%M}" if isinstance(ts, int) else "?"
        )
        arrow = "←" if entry.get("direction") == "in" else "→"
        text = " ".join(str(entry.get("text") or "").split())
        line = f"{when}  {arrow} {_log_party(entry)}  {entry.get('kind')}"
        click.echo(f"{line}  {text}" if text else line)


@net.command(
    name="poll",
    help="Handle what the spine holds right now, without a running hub: the same code path "
    "as the net hub service, network turns included. Do not run it while the hub polls.",
    short_help="Handle queued envelopes once.",
)
@help_option()
@click.option("--once", is_flag=True, required=True, help="Handle what is queued, then exit.")
@click.pass_context
def poll_command(ctx: click.Context, once: bool) -> None:
    config = _config(ctx)
    node = _node(ctx, config)

    async def main() -> list:
        try:
            return await node.poll_once(timeout=0)
        finally:
            node.close()

    handled = _run(ctx, lambda: asyncio.run(main()))
    counts = {
        "handled": sum(1 for h in handled if h.outcome == "handled"),
        "dropped": sum(1 for h in handled if h.outcome != "handled"),
        "replied": sum(1 for h in handled if h.replied),
    }
    _Say(config)("net.poll.done", **counts)


# -- the universe ------------------------------------------------------------------------------


@net.group(
    name="universe",
    help="The tau universe: an opt-in public directory of taus at the [component.net] "
    "universe host (default tau.getporti.com). A listed tau shows its card name, the owner and "
    "about lines you choose, and the links to contacts that are listed too and report you "
    "back. Message contents and unlisted contacts never leave the hub.",
    short_help="Join or leave the tau universe.",
)
@help_option()
def universe() -> None:
    pass


@universe.command(
    name="join",
    help="List this tau in the universe: sets universe_join in the network profile (with "
    "--owner, --about and --links/--no-links), publishes the card when it is missing or "
    "different, sends a signed join and then a report, and prints this tau's universe page. "
    "While the profile says joined, the hub reports every universe_report_minutes.",
    short_help="List this tau in the universe.",
)
@help_option()
@click.option("--owner", metavar="NAME", help="Your display name there (0 to 60 characters).")
@click.option("--about", metavar="TEXT", help="One line about your tau (0 to 200 characters).")
@click.option(
    "--links/--no-links",
    default=None,
    help="Report (or not) mutual links, with message counts, to contacts the universe lists. "
    "Default: [component.net] universe_links.",
)
@click.pass_context
def universe_join_command(
    ctx: click.Context, owner: str | None, about: str | None, links: bool | None
) -> None:
    config = _config(ctx)
    say = _Say(config)
    node = _node(ctx, config)
    client = _run(ctx, node.universe)
    changes: dict[str, Any] = {"universe_join": True}
    for key, value in (("universe_owner", owner), ("universe_about", about)):
        if value is not None:
            changes[key] = value
    if links is not None:
        changes["universe_links"] = links
    profile = _run(ctx, lambda: node.update_profile(**changes))
    if _run(ctx, node.ensure_card):
        say("net.publish.done", address=node.address(), name=node.display_name())
    try:
        answer = node.universe_join(profile)
    except ERRORS as exc:
        _fail(ctx, NetError(f"the join failed: {exc}"))
    address = node.address()
    url = answer.get("url")
    if not isinstance(url, str) or not url.startswith(("https://", "http://")):
        url = client.url_for(address)
    say("net.universe.joined", universe=client.host, url=url)
    try:
        sent = node.universe_links(profile)
        report = node.universe_report(profile, links=sent)
    except ERRORS as exc:
        _fail(ctx, NetError(f"joined, but the report failed: {exc}"))
    visible = report.get("visible_links")
    visible = visible if isinstance(visible, int) else 0
    if node.universe_links_enabled(profile):
        say("net.universe.reported", links=len(sent), visible=visible)
    else:
        say("net.universe.reported_off")
    subs = node.universe_subs()
    if subs:
        say("net.universe.subs", subs=", ".join(f"/{sub['name']}" for sub in subs))


@universe.command(
    name="leave",
    help="Leave the universe: sets universe_join off in the network profile (the hub stops "
    "reporting) and sends a signed leave, which removes this tau and its links from the "
    "directory.",
    short_help="Leave the universe.",
)
@help_option()
@click.pass_context
def universe_leave_command(ctx: click.Context) -> None:
    config = _config(ctx)
    say = _Say(config)
    node = _node(ctx, config)
    client = _run(ctx, node.universe)
    _run(ctx, lambda: node.update_profile(universe_join=False))
    try:
        node.universe_leave()
    except UniverseError as exc:
        if exc.code != "not_joined":
            _fail(ctx, NetError(f"universe_join is off, but the leave failed: {exc}"))
        say("net.universe.left_unlisted", universe=client.host)
        return
    except ERRORS as exc:
        _fail(ctx, NetError(f"universe_join is off, but the leave failed: {exc}"))
    say("net.universe.left", universe=client.host)


@universe.command(
    name="status",
    help="Show the universe host, whether the profile says joined, the links setting, and "
    "whether the universe lists this tau, with its handle, visible links and public "
    "sub-taus (and today's visitor turns of those with a web page).",
    short_help="Show the universe status.",
)
@help_option()
@click.pass_context
def universe_status_command(ctx: click.Context) -> None:
    from datetime import datetime

    from tau_core.persona import TIMEZONE

    config = _config(ctx)
    say = _Say(config)
    node = _node(ctx, config)
    settings = node.settings
    if not settings.universe:
        say("net.universe.status.off")
        return
    profile = _run(ctx, node.profile)
    say("net.universe.status.host", universe=settings.universe)
    if profile.universe_join:
        say("net.universe.status.joined", minutes=settings.universe_report_minutes)
    else:
        say("net.universe.status.not_joined")
    if node.universe_links_enabled(profile):
        say("net.universe.status.links_on")
    else:
        say("net.universe.status.links_off")
    if profile.universe_owner:
        say("net.universe.status.owner", owner=profile.universe_owner)
    if profile.universe_about:
        say("net.universe.status.about", about=profile.universe_about)
    client = node.universe()
    address = _run(ctx, node.address)
    entry = _run(ctx, lambda: client.tau(address))
    if entry is None:
        say("net.universe.status.unlisted")
        return
    tau = entry["tau"] if isinstance(entry.get("tau"), dict) else entry
    seen = tau.get("last_seen")
    when = (
        f"{datetime.fromtimestamp(seen, TIMEZONE):%d.%m.%Y %H:%M}" if isinstance(seen, int) else "?"
    )
    online = tau.get("online") is True
    say("net.universe.status.online" if online else "net.universe.status.offline", when=when)
    say("net.universe.status.url", url=client.url_for(address))
    handle = tau.get("handle")
    if isinstance(handle, str) and is_valid_handle(handle):
        say("net.universe.status.handle", handle=handle, url=f"{client.base}/@{handle}")
    else:
        say("net.universe.status.no_handle")
    links = tau_links(entry, address)
    if not links:
        say("net.universe.status.no_links")
    for peer, messages in links:
        say("net.universe.status.link", peer=peer, messages=messages)
    today = time.strftime("%Y-%m-%d", time.gmtime(node.clock()))
    visits = _run(ctx, lambda: node.store.visits(today))
    for sub in tau_subs(entry):
        if sub["web"]:
            say(
                "net.universe.status.sub_web",
                name=sub["name"],
                about=sub["about"],
                visits=visits.get(sub["name"], 0),
            )
        else:
            say("net.universe.status.sub", name=sub["name"], about=sub["about"])


@universe.command(
    name="claim",
    help="Print a link that claims a handle for this tau: a signed claim request (valid for "
    "one hour) in the fragment of https://<universe>/claim. Open it and sign in with GitHub "
    "there; the universe then binds your GitHub login as this tau's handle, so its page is "
    "/@<login>. Nothing is sent from here. Publishes the card first when it is missing or "
    "different, because the universe checks the signature against it.",
    short_help="Claim a handle with GitHub.",
)
@help_option()
@click.pass_context
def universe_claim_command(ctx: click.Context) -> None:
    config = _config(ctx)
    say = _Say(config)
    node = _node(ctx, config)
    client = _run(ctx, node.universe)
    identity = _run(ctx, node.require_identity)
    if _run(ctx, node.ensure_card):
        say("net.publish.done", address=node.address(), name=node.display_name())
    address = _run(ctx, node.address)
    link = _run(ctx, lambda: client.claim_link(identity, address))
    say("net.universe.claim.link", universe=client.host, address=address)
    click.echo(link)
    say("net.universe.claim.private")
    if not _run(ctx, node.profile).universe_join:
        say("net.universe.claim.not_joined")


# -- spine kit ---------------------------------------------------------------------------------


def _spine_say(ctx: click.Context) -> Callable[..., None]:
    """Output in the UI language without requiring a ``tau.toml`` (the spine usually comes
    before ``tau init``): ``--lang``/``TAU_LANG``, else ``[ui] language``, else English."""
    obj = _obj(ctx)
    language = obj.get("lang")
    if language not in LANGUAGES:
        try:
            language = Config.load(obj.get("home"), env=dict(os.environ)).ui.language
        except ConfigError:
            language = os.environ.get("TAU_LANG", "")
            language = language if language in LANGUAGES else DEFAULT_LANGUAGE

    def say(key: str, /, **kwargs: Any) -> None:
        click.echo(t(key, language, **kwargs))

    return say


_ADDRESS_HELP = "The tau's address when it is a domain of yours, e.g. tau.example.com."


@net.group(
    name="spine",
    help="Your tau's spine, the Cloudflare Worker behind its address, from the kit inside "
    "tau-net: write a Wrangler project, then deploy it to your own Cloudflare account. The "
    "tau repository is not needed.",
    short_help="Set up and deploy your spine Worker.",
)
@help_option()
def spine_group() -> None:
    pass


@spine_group.command(
    name="init",
    help="Write a ready-to-deploy spine project into DIRECTORY, which must be new or empty: "
    "wrangler.jsonc (local mode), worker.js, package.json, .gitignore, a README and the D1 "
    "migrations when there are any. With --address HOST the Worker gets the ADDRESS variable "
    "and a custom-domain route for HOST (the zone must be on your Cloudflare account); "
    "without it, the address is tau-spine.<subdomain>.workers.dev.",
    short_help="Write a spine project.",
)
@help_option()
@click.argument("directory", type=click.Path(file_okay=False, path_type=Path))
@click.option("--address", metavar="HOST", help=_ADDRESS_HELP)
@click.pass_context
def spine_init_command(ctx: click.Context, directory: Path, address: str | None) -> None:
    say = _spine_say(ctx)
    try:
        result = init_project(directory, address=address)
    except SpineKitError as exc:
        _fail(ctx, exc)
    say("net.spine.init.done", version=result.version, path=result.path)
    if result.host is None:
        say("net.spine.init.no_address")
    elif is_workers_dev(result.host):
        say("net.spine.init.workers_dev_address", address=result.host)
    else:
        say("net.spine.init.address", address=result.host)
    click.echo()
    say("net.spine.next")
    say("net.spine.init.step_node")
    say("net.spine.init.step_deploy", path=directory)


@spine_group.command(
    name="deploy",
    help="Deploy the spine project in DIRECTORY (from `tau net spine init`) with Wrangler: "
    "check the Cloudflare login, npm install, wrangler deploy and, when the project has a D1 "
    "database, its migrations. Then set the Worker's HUB_TOKEN secret to TAU_SPINE_TOKEN from "
    "the hub's .env (generated when missing; passed on stdin, never printed) and write "
    "TAU_SPINE_URL there: https://HOST for a known address, else the workers.dev URL.",
    short_help="Deploy a spine project.",
)
@help_option()
@click.argument("directory", type=click.Path(file_okay=False, path_type=Path))
@click.option("--address", metavar="HOST", help=_ADDRESS_HELP)
@click.pass_context
def spine_deploy_command(ctx: click.Context, directory: Path, address: str | None) -> None:
    obj = _obj(ctx)
    say = _spine_say(ctx)
    try:
        result = deploy_project(
            directory,
            home=resolve_home(obj.get("home")),
            address=address,
            runner=obj.get("spine_runner"),
            say=say,
            echo=lambda line: click.echo(f"  {line}" if line else ""),
            environ=obj.get("spine_environ"),
        )
    except SpineKitError as exc:
        _fail(ctx, exc)
    click.echo()
    say("net.spine.deploy.done", url=result.url)
    say("net.spine.next")
    say("net.spine.deploy.step_init")
    say("net.spine.deploy.step_publish")
    say("net.spine.deploy.step_status")
