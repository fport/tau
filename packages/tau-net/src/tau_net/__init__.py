"""tau-net: the tau network (ADR 0007, protocol v1 in docs/reference/tau-network.md).

A tau talks to other taus through its **spine** (a Worker in its owner's Cloudflare account):
identity keys on the hub, envelopes signed by the sender and sealed to the recipient, contacts
the owner accepts, the ``net`` hub service that long-polls the spine, network turns with a
reduced agent, the owner's tools and ``tau net``. An owner may also list the tau in a
**universe**, an opt-in public directory (ADR 0010, docs/reference/tau-universe.md).

Public API (other packages import these names, ``tau_net.spine`` and ``tau_net.testing``)::

    b64u_encode, b64u_decode, parse_address, validate_address, is_valid_address, base_url,
    parse_host, is_valid_host, parse_target, split_address, AddressError, EncodingError
    Identity, IdentityError, IdentityExists, create_identity, load_identity, load_or_none,
    identity_path, IDENTITY_ENV
    Envelope, Payload, Box, build_envelope, open_verified, open_box, parse_content,
    peek_sender, seal, EnvelopeError, MalformedEnvelope, BadSignature, BoxError,
    EnvelopeTooLarge, KINDS, MAX_ENVELOPE_BYTES, MAX_MESSAGE_CHARS
    Transport, UrllibTransport, TransportError, SpineClient, SpineResponse, SpineError,
    SpineUnreachable, Update
    PeerClient, PeerCard, CardError, Delivery, DeliveryError
    NetStore, FileBackend, SpineBackend
    Contact, ContactBook, ContactError, Transition
    NetSettings, NetConfigError, SPINE_URL_ENV, SPINE_TOKEN_ENV
    NetworkTurns, FRAME, build_frame, sanitize, is_no_reply
    UniverseClient, UniverseError, UniverseUnreachable, DEFAULT_UNIVERSE, UNIVERSE_CONTEXT
    NetNode, Handled, NetError, NetNotConfigured, UniverseSync, open_node
    NetProfile
    NetService, make_service, doctor_check
    TOOLS
"""

from __future__ import annotations

from tau_net.config import (
    SPINE_TOKEN_ENV,
    SPINE_URL_ENV,
    NetConfigError,
    NetSettings,
)
from tau_net.contacts import Contact, ContactBook, ContactError, Transition
from tau_net.encoding import (
    AddressError,
    EncodingError,
    b64u_decode,
    b64u_encode,
    base_url,
    is_valid_address,
    is_valid_host,
    parse_address,
    parse_host,
    parse_target,
    split_address,
    validate_address,
)
from tau_net.envelope import (
    KINDS,
    MAX_ENVELOPE_BYTES,
    MAX_MESSAGE_CHARS,
    BadSignature,
    Box,
    BoxError,
    Envelope,
    EnvelopeError,
    EnvelopeTooLarge,
    MalformedEnvelope,
    Payload,
    build_envelope,
    open_box,
    open_verified,
    parse_content,
    peek_sender,
    seal,
)
from tau_net.identity import (
    IDENTITY_ENV,
    Identity,
    IdentityError,
    IdentityExists,
    create_identity,
    identity_path,
    load_identity,
    load_or_none,
)
from tau_net.node import Handled, NetError, NetNode, NetNotConfigured, UniverseSync, open_node
from tau_net.peers import CardError, Delivery, DeliveryError, PeerCard, PeerClient
from tau_net.profile import NetProfile
from tau_net.service import NetService, doctor_check, make_service
from tau_net.spine import (
    SpineClient,
    SpineError,
    SpineResponse,
    SpineUnreachable,
    Transport,
    TransportError,
    Update,
    UrllibTransport,
)
from tau_net.store import FileBackend, NetStore, SpineBackend
from tau_net.tools import TOOLS
from tau_net.turns import FRAME, NetworkTurns, build_frame, is_no_reply, sanitize
from tau_net.universe import (
    DEFAULT_UNIVERSE,
    UNIVERSE_CONTEXT,
    UniverseClient,
    UniverseError,
    UniverseUnreachable,
)

__version__ = "0.2.0"

__all__ = [
    "DEFAULT_UNIVERSE",
    "FRAME",
    "IDENTITY_ENV",
    "KINDS",
    "MAX_ENVELOPE_BYTES",
    "MAX_MESSAGE_CHARS",
    "SPINE_TOKEN_ENV",
    "SPINE_URL_ENV",
    "TOOLS",
    "UNIVERSE_CONTEXT",
    "AddressError",
    "BadSignature",
    "Box",
    "BoxError",
    "CardError",
    "Contact",
    "ContactBook",
    "ContactError",
    "Delivery",
    "DeliveryError",
    "EncodingError",
    "Envelope",
    "EnvelopeError",
    "EnvelopeTooLarge",
    "FileBackend",
    "Handled",
    "Identity",
    "IdentityError",
    "IdentityExists",
    "MalformedEnvelope",
    "NetConfigError",
    "NetError",
    "NetNode",
    "NetNotConfigured",
    "NetProfile",
    "NetService",
    "NetSettings",
    "NetStore",
    "NetworkTurns",
    "Payload",
    "PeerCard",
    "PeerClient",
    "SpineBackend",
    "SpineClient",
    "SpineError",
    "SpineResponse",
    "SpineUnreachable",
    "Transition",
    "Transport",
    "TransportError",
    "UniverseClient",
    "UniverseError",
    "UniverseSync",
    "UniverseUnreachable",
    "Update",
    "UrllibTransport",
    "__version__",
    "b64u_decode",
    "b64u_encode",
    "base_url",
    "build_envelope",
    "build_frame",
    "create_identity",
    "doctor_check",
    "identity_path",
    "is_no_reply",
    "is_valid_address",
    "is_valid_host",
    "load_identity",
    "load_or_none",
    "make_service",
    "open_box",
    "open_node",
    "open_verified",
    "parse_address",
    "parse_content",
    "parse_host",
    "parse_target",
    "peek_sender",
    "sanitize",
    "seal",
    "split_address",
    "validate_address",
]
