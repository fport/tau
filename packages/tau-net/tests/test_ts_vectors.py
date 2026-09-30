"""tau-net and the protocol's TypeScript half (``cloud/shared/net``) stay byte-compatible (158).

- ``cloud/shared/net/vectors.json`` is what ``scripts/make_ts_vectors.py`` writes today; vitest
  in ``cloud/shared`` checks the TypeScript against it.
- ``cloud/shared/net/ts-vectors.json`` was written by the TypeScript (``bun run vectors``):
  tau-net must load its keys, verify and open its envelopes and verify its universe requests,
  and must itself encode, sign and seal the same bytes from the same inputs.

Kinds, fields and addresses this tau-net does not know yet (``visit``, ``claim``,
``host/@handle``) are checked with its primitives; once it knows them, the full parsers run too.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from tau_net.encoding import b64u_decode, is_valid_address
from tau_net.envelope import (
    KINDS,
    Box,
    Envelope,
    Payload,
    aad_for,
    open_box,
    open_verified,
    parse_content,
    seal,
    sign_payload,
    verify_signature,
)
from tau_net.identity import Identity
from tau_net.universe import (
    UNIVERSE_KINDS,
    SignedRequest,
    build_request,
    encode_payload,
    parse_request,
    verify_request,
)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "make_ts_vectors.py"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_ts_vectors", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up
    spec.loader.exec_module(module)
    return module


generator = _load_generator()
TS_VECTORS: dict[str, Any] = json.loads(generator.TS_VECTORS_PATH.read_text(encoding="utf-8"))
IDENTITIES: dict[str, Any] = TS_VECTORS["identities"]


def _identity(label: str) -> Identity:
    return Identity.from_json(IDENTITIES[label]["identity"])


def test_vectors_json_is_fresh() -> None:
    recorded = json.loads(generator.VECTORS_PATH.read_text(encoding="utf-8"))
    assert recorded == generator.make_vectors(), (
        "cloud/shared/net/vectors.json is stale: run "
        "`uv run python packages/tau-net/scripts/make_ts_vectors.py` and commit it"
    )


def test_the_check_flag_agrees() -> None:
    assert generator.main(["--check"]) == 0


# -- TypeScript → Python -----------------------------------------------------------------------


@pytest.mark.parametrize("label", sorted(IDENTITIES))
def test_typescript_identities_load(label: str) -> None:
    entry = IDENTITIES[label]
    identity = Identity.from_json(entry["identity"])
    assert (identity.sign_key, identity.box_key) == (entry["sign_key"], entry["box_key"])
    assert identity.to_env_value() == entry["env_value"]
    assert Identity.from_env_value(entry["env_value"]).to_json() == entry["identity"]


@pytest.mark.parametrize("vector", TS_VECTORS["envelopes"], ids=lambda vector: vector["name"])
def test_typescript_envelopes_verify_open_and_match_byte_for_byte(vector: dict[str, Any]) -> None:
    sender, recipient = _identity(vector["sender"]), _identity(vector["recipient"])
    envelope = Envelope.from_json(vector["envelope"])
    payload_bytes = envelope.payload_bytes
    verify_signature(sender.sign_key, payload_bytes, envelope.sig_bytes)
    data = json.loads(payload_bytes)
    assert data == vector["payload"]

    aad = aad_for(data["id"], data["kind"], data["from"], data["to"])
    content = open_box(Box.from_json(data["box"]), recipient, aad)
    assert content == vector["input"]["content"]

    # tau-net writes the same payload bytes, signature and box from the same inputs.
    payload = Payload(
        id=data["id"],
        kind=data["kind"],
        sender=data["from"],
        recipient=data["to"],
        ts=data["ts"],
        thread=data["thread"],
        reply_to=data["reply_to"],
        hops=data["hops"],
        box=Box.from_json(data["box"]),
    )
    assert payload.to_bytes() == payload_bytes
    assert sign_payload(sender, payload_bytes) == envelope.sig_bytes
    inputs = vector["input"]
    with generator.pinned_randomness(
        b64u_decode(inputs["ephemeral_secret"]), b64u_decode(inputs["nonce"])
    ):
        resealed = seal(inputs["content"], recipient.box_key, aad)
    assert resealed.to_json() == data["box"]

    # Where this tau-net knows the kind and both addresses, its full path agrees too.
    if data["kind"] in KINDS and is_valid_address(data["from"]) and is_valid_address(data["to"]):
        verified = open_verified(envelope, sender.sign_key)
        parse_content(verified.kind, open_box(verified.box, recipient, verified.aad))


def _plain_addresses(payload: dict[str, Any]) -> bool:
    peers = [link["peer"] for link in payload.get("links", [])]
    return all(is_valid_address(address) for address in [payload["address"], *peers])


@pytest.mark.parametrize("vector", TS_VECTORS["universe"], ids=lambda vector: vector["name"])
def test_typescript_universe_requests_verify_and_match(vector: dict[str, Any]) -> None:
    signer = _identity(vector["signer"])
    request = SignedRequest(**vector["request"])
    verify_request(signer.sign_key, request.payload_bytes, request.sig_bytes)
    assert json.loads(request.payload_bytes) == vector["payload"]
    assert encode_payload(vector["payload"]) == request.payload_bytes
    assert build_request(signer, vector["payload"]) == request

    payload = vector["payload"]
    if payload["kind"] in UNIVERSE_KINDS and _plain_addresses(payload):
        assert parse_request(request.to_bytes()).payload == payload


def test_typescript_claim_link_carries_the_signed_claim() -> None:
    link = TS_VECTORS["claim_link"]
    prefix = f"https://{generator.UNIVERSE}/claim#"
    assert link["link"].startswith(prefix)
    fragment = b64u_decode(link["link"][len(prefix) :])
    request = SignedRequest(**json.loads(fragment))
    assert request.to_json() == link["request"]
    assert request.to_bytes() == fragment
    claim = json.loads(request.payload_bytes)
    assert claim["kind"] == "claim" and claim["universe"] == generator.UNIVERSE
    verify_request(IDENTITIES["hub"]["sign_key"], request.payload_bytes, request.sig_bytes)
