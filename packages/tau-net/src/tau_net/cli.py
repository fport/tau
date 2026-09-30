"""``tau net``: the owner's commands for the tau network (``tau.commands`` entry point ``net``).

Every command reads ``tau.toml`` and ``.env`` like the rest of tau (``--home``, ``TAU_HOME``,
``TAU_DATA_DIR``). Output lines go through ``tau_core.i18n`` in the configured UI language;
help texts and error lines are English. Exit codes: 0 ok, 1 error with one line on stderr,
2 when the configuration itself cannot be loaded.

Nothing here writes ``tau.toml``: the card name (``tau net init --name``, ``tau net name``) and
the universe membership (``tau net universe join|leave``) are the owner's profile in the
network store (:mod:`tau_net.profile`).

Tests pass a transport through the click context object (``obj={"net_transport": ...}``);
``net_env`` and ``net_model_factory`` work the same way.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any, NoReturn

import click
from tau_core import Config, ConfigError, t
from tau_core.cli import help_option

from tau_net import strings as _strings  # noqa: F401  (registers the message keys)
from tau_net.config import NetConfigError
from tau_net.contacts import PENDING_IN, ContactError
from tau_net.encoding import AddressError
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
from tau_net.universe import MalformedRequest, UniverseError, tau_links

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
    click.echo()
    say("net.init.next")
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
    help="Publish the card (name from [component.net] in tau.toml, the public keys) on the "
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
    "send a signed, encrypted contact request. If it had asked already, this accepts it.",
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


@net.command(
    name="send",
    help="Send a message in your name to an accepted contact (signed and end-to-end "
    "encrypted, at most 8000 characters).",
    short_help="Send a message to a contact.",
)
@help_option()
@click.argument("address")
@click.argument("text", nargs=-1, required=True)
@click.pass_context
def send_command(ctx: click.Context, address: str, text: tuple[str, ...]) -> None:
    config = _config(ctx)
    node = _node(ctx, config)
    delivery = _run(ctx, lambda: node.send(address, " ".join(text)))
    _Say(config)("net.send.done", address=delivery.address, status=delivery.status)


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
        line = f"{when}  {arrow} {entry.get('address')}  {entry.get('kind')}"
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
    "whether the universe lists this tau, with its visible links.",
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
    links = tau_links(entry, address)
    if not links:
        say("net.universe.status.no_links")
    for peer, messages in links:
        say("net.universe.status.link", peer=peer, messages=messages)
