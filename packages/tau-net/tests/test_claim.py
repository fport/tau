"""Handle claims (ADR 0013 §6, issue 157): the signed ``claim`` request, the link ``tau net
universe claim`` prints and the handle ``tau net universe status`` shows.

The wire bytes are pinned by the test vector of ``docs/reference/tau-universe.md`` §1, which the
universe Worker verifies too."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from net_helpers import ALICE, UNIVERSE, Tau, published, universe_tau
from tau_net.cli import net
from tau_net.encoding import b64u_decode
from tau_net.identity import Identity
from tau_net.universe import (
    CLAIM_VALID_SECONDS,
    MalformedRequest,
    UniverseClient,
    build_request,
    claim_link,
    make_payload,
    parse_request,
    verify_request,
)

VECTOR_IDENTITY = Identity(bytes(range(32)), bytes(range(32, 64)))
VECTOR_NONCE = "AAECAwQFBgcICQoLDA0ODw"
VECTOR_JSON = (
    '{"v":1,"kind":"claim","universe":"universe.example","address":"alice.example",'
    '"ts":1790000000,"nonce":"AAECAwQFBgcICQoLDA0ODw"}'
)
VECTOR_PAYLOAD = (
    "eyJ2IjoxLCJraW5kIjoiY2xhaW0iLCJ1bml2ZXJzZSI6InVuaXZlcnNlLmV4YW1wbGUiLCJhZGRyZXNzIjoiYWxp"
    "Y2UuZXhhbXBsZSIsInRzIjoxNzkwMDAwMDAwLCJub25jZSI6IkFBRUNBd1FGQmdjSUNRb0xEQTBPRHcifQ"
)
VECTOR_SIG = (
    "xjRvteuZfBpQauW_R1YeTz39uUEoeJJ70tcSoijYj2VByWoajzkHXTc4MTEjyIU_w7R6M8nOug60xfykdQTlDg"
)
VECTOR_LINK = (
    "https://universe.example/claim#eyJwYXlsb2FkIjoiZXlKMklqb3hMQ0pyYVc1a0lqb2lZMnhoYVcwaUxDSjF"
    "ibWwyWlhKelpTSTZJblZ1YVhabGNuTmxMbVY0WVcxd2JHVWlMQ0poWkdSeVpYTnpJam9pWVd4cFkyVXVaWGhoYlhC"
    "c1pTSXNJblJ6SWpveE56a3dNREF3TURBd0xDSnViMjVqWlNJNklrRkJSVU5CZDFGR1FtZGpTVU5SYjB4RVFUQlBS"
    "SGNpZlEiLCJzaWciOiJ4alJ2dGV1WmZCcFFhdVdfUjFZZVR6Mzl1VUVvZUpKNzB0Y1NvaWpZajJWQnlXb2FqemtI"
    "WFRjNE1URWp5SVVfdzdSNk04bk91ZzYweGZ5a2RRVGxEZyJ9"
)


def test_the_claim_vector() -> None:
    payload = make_payload(
        "claim",
        universe="universe.example",
        address="alice.example",
        ts=1_790_000_000,
        nonce=VECTOR_NONCE,
    )
    request = build_request(VECTOR_IDENTITY, payload)
    assert b64u_decode(request.payload).decode() == VECTOR_JSON
    assert request.payload == VECTOR_PAYLOAD and request.sig == VECTOR_SIG
    verify_request(VECTOR_IDENTITY.sign_key, request.payload_bytes, request.sig_bytes)
    link = claim_link(
        VECTOR_IDENTITY,
        universe="universe.example",
        address="alice.example",
        ts=1_790_000_000,
        nonce=VECTOR_NONCE,
    )
    assert link == VECTOR_LINK
    # the fragment is b64u of the wire JSON, the same shape as a join
    wire = b64u_decode(link.split("#", 1)[1])
    assert json.loads(wire) == {"payload": VECTOR_PAYLOAD, "sig": VECTOR_SIG}
    assert parse_request(wire).payload == json.loads(VECTOR_JSON)
    assert CLAIM_VALID_SECONDS == 3600


def test_claims_have_a_fresh_nonce_and_accept_handle_addresses() -> None:
    client = UniverseClient(UNIVERSE, clock=lambda: 1_790_000_000)
    first = client.claim_link(VECTOR_IDENTITY, "tau.example.com/@alice")
    second = client.claim_link(VECTOR_IDENTITY, "tau.example.com/@alice")
    assert first.startswith(f"https://{UNIVERSE}/claim#") and first != second
    payload = parse_request(b64u_decode(first.split("#", 1)[1])).payload
    assert payload["address"] == "tau.example.com/@alice" and len(payload["nonce"]) == 24
    # the client's ts never repeats, like the other requests
    assert payload["ts"] < parse_request(b64u_decode(second.split("#", 1)[1])).payload["ts"]
    assert list(payload) == ["v", "kind", "universe", "address", "ts", "nonce"]


@pytest.mark.parametrize("nonce", ["", "short", "x" * 65, "not base64url!!!!!!!", None])
def test_a_claim_needs_a_nonce(nonce) -> None:
    payload = {
        "v": 1,
        "kind": "claim",
        "universe": UNIVERSE,
        "address": ALICE,
        "ts": 1,
        "nonce": nonce,
    }
    body = build_request(VECTOR_IDENTITY, payload).to_bytes()
    with pytest.raises(MalformedRequest, match="nonce"):
        parse_request(body)


# -- the commands -------------------------------------------------------------------------------


def invoke(tau: Tau, *args: str) -> Result:
    obj = {"home": tau.config.home, "net_env": tau.env, "net_transport": tau.network}
    env = {"TAU_DATA_DIR": str(tau.config.data_dir), "TAU_LANG": "en"}
    return CliRunner().invoke(net, list(args), obj=obj, env=env)


def test_claim_prints_a_signed_link(tmp_path: Path, network, universe) -> None:
    alice = universe_tau(tmp_path, network, ALICE)
    result = invoke(alice, "universe", "claim")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    # the card was missing, so it is published first (the universe verifies against it)
    assert lines[0] == f"Published the card of {ALICE} as Alice's tau."
    assert lines[1].startswith("Open this link within an hour and sign in with GitHub there;")
    link = lines[2]
    assert link.startswith(f"https://{UNIVERSE}/claim#")
    request = parse_request(b64u_decode(link.split("#", 1)[1]))
    assert request.payload["kind"] == "claim" and request.payload["address"] == ALICE
    assert request.payload["universe"] == UNIVERSE
    verify_request(alice.identity.sign_key, request.payload_bytes, request.sig)
    assert "do not share it" in lines[3]
    assert "not in the universe yet" in lines[4]
    assert universe.bodies() == []  # nothing was sent


def test_status_shows_the_handle_once_claimed(tmp_path: Path, network, universe) -> None:
    alice = universe_tau(tmp_path, network, ALICE)
    node = published(alice)
    node.update_profile(universe_join=True)
    node.universe_join()
    result = invoke(alice, "universe", "status")
    assert "handle:   none yet" in result.output
    universe.handles[ALICE] = "alice"
    result = invoke(alice, "universe", "status")
    assert result.exit_code == 0, result.output
    assert f"handle:   @alice  https://{UNIVERSE}/@alice" in result.output
    claim = invoke(alice, "universe", "claim")
    assert "not in the universe yet" not in claim.output
    universe.handles[ALICE] = "Not A Handle"
    assert "handle:   none yet" in invoke(alice, "universe", "status").output


def test_claim_speaks_turkish(tmp_path: Path, network, universe) -> None:
    alice = universe_tau(tmp_path, network, ALICE)
    published(alice)
    obj = {"home": alice.config.home, "net_env": alice.env, "net_transport": network}
    env = {"TAU_DATA_DIR": str(alice.config.data_dir), "TAU_LANG": "tr"}
    result = CliRunner().invoke(net, ["universe", "claim"], obj=obj, env=env)
    assert result.exit_code == 0, result.output
    assert "Bu bağlantıyı bir saat içinde aç" in result.output
