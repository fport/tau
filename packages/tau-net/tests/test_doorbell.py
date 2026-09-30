"""The doorbell client (:mod:`tau_net.doorbell`): frames, and the handshake and the waiting
against a small WebSocket server on a loopback socket, written here."""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
from collections.abc import Callable

import pytest
from tau_net.doorbell import (
    OP_BINARY,
    OP_CLOSE,
    OP_CONTINUATION,
    OP_PING,
    OP_PONG,
    OP_TEXT,
    DoorbellClosed,
    DoorbellError,
    DoorbellUnauthorized,
    DoorbellUnsupported,
    Frame,
    WebSocketDoorbell,
    accept_key,
    decode_frame,
    encode_frame,
)
from tau_net.spine import SpineClient

TOKEN = "secret-hub-token-for-tests"

# -- frames ------------------------------------------------------------------------------------


def test_accept_key_matches_rfc_6455() -> None:
    assert accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_frames_match_the_rfc_examples() -> None:
    # RFC 6455 §5.7
    hello = bytes([0x81, 0x05]) + b"Hello"
    masked = bytes([0x81, 0x85, 0x37, 0xFA, 0x21, 0x3D, 0x7F, 0x9F, 0x4D, 0x51, 0x58])
    assert encode_frame(OP_TEXT, b"Hello", mask=b"") == hello
    assert encode_frame(OP_TEXT, b"Hello", mask=bytes([0x37, 0xFA, 0x21, 0x3D])) == masked
    assert decode_frame(hello) == (Frame(True, OP_TEXT, b"Hello"), 7)
    assert decode_frame(masked) == (Frame(True, OP_TEXT, b"Hello", masked=True), 11)
    first = bytes([0x01, 0x03]) + b"Hel"
    last = bytes([0x80, 0x02]) + b"lo"
    assert decode_frame(first + last) == (Frame(False, OP_TEXT, b"Hel"), 5)
    assert decode_frame(last) == (Frame(True, OP_CONTINUATION, b"lo"), 4)
    ping = bytes([0x89, 0x05]) + b"Hello"
    assert encode_frame(OP_PING, b"Hello", mask=b"") == ping
    assert decode_frame(ping) == (Frame(True, OP_PING, b"Hello"), 7)


@pytest.mark.parametrize(
    ("size", "header"),
    [(0, 2), (125, 2), (126, 4), (65_535, 4), (65_536, 10)],
)
def test_lengths_round_trip(size: int, header: int) -> None:
    payload = bytes(range(256)) * (size // 256) + bytes(size % 256)
    for mask in (b"", b"\x01\x02\x03\x04"):
        frame = encode_frame(OP_BINARY, payload, mask=mask)
        assert len(frame) == header + len(mask) + size
        decoded = decode_frame(frame, max_payload=1 << 20)
        assert decoded == (Frame(True, OP_BINARY, payload, masked=bool(mask)), len(frame))
        # Every prefix is incomplete, never an error.
        for cut in {0, 1, header - 1, header, len(frame) - 1} - {len(frame)}:
            if cut >= 0:
                assert decode_frame(frame[:cut], max_payload=1 << 20) is None


def test_client_frames_are_masked_with_a_fresh_key() -> None:
    one, two = encode_frame(OP_TEXT, b"ping"), encode_frame(OP_TEXT, b"ping")
    assert one[1] & 0x80 and two[1] & 0x80
    assert decode_frame(one) == (Frame(True, OP_TEXT, b"ping", masked=True), 10)
    assert one[2:6] != two[2:6] or one[2:6] != encode_frame(OP_TEXT, b"ping")[2:6]


def test_protocol_errors() -> None:
    with pytest.raises(DoorbellError, match="reserved"):
        decode_frame(bytes([0xC1, 0x00]))
    with pytest.raises(DoorbellError, match="opcode"):
        decode_frame(bytes([0x83, 0x00]))
    with pytest.raises(DoorbellError, match="control"):
        decode_frame(bytes([0x09, 0x00]))  # a fragmented ping
    with pytest.raises(DoorbellError, match="control"):
        decode_frame(bytes([0x89, 126, 0, 200]) + bytes(200))
    with pytest.raises(DoorbellError, match="larger"):
        decode_frame(bytes([0x81, 127]) + struct.pack("!Q", 1 << 40))
    with pytest.raises(ValueError):
        encode_frame(OP_PING, bytes(126))
    with pytest.raises(ValueError):
        encode_frame(OP_TEXT, b"x", mask=b"12")


# -- a loopback WebSocket server -----------------------------------------------------------------


class Peer:
    """The server side of one connection."""

    def __init__(self, conn: socket.socket):
        self.conn = conn
        self.buffer = b""
        self.request: str = ""
        self.headers: dict[str, str] = {}

    def read_request(self) -> None:
        while b"\r\n\r\n" not in self.buffer:
            chunk = self.conn.recv(4096)
            assert chunk, "the client closed before its request"
            self.buffer += chunk
        head, _, self.buffer = self.buffer.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        self.request = lines[0]
        for line in lines[1:]:
            name, _, value = line.partition(":")
            self.headers[name.strip().lower()] = value.strip()

    def upgrade(self, *, accept: str | None = None, extra: str = "") -> None:
        key = self.headers["sec-websocket-key"]
        self.conn.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept or accept_key(key)}\r\n"
                f"{extra}\r\n"
            ).encode()
        )

    def refuse(self, status: int, code: str) -> None:
        body = json.dumps({"error": code}).encode()
        self.conn.sendall(
            f"HTTP/1.1 {status} X\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n\r\n".encode()
            + body
        )

    def send(self, opcode: int, payload: bytes = b"", *, fin: bool = True) -> None:
        self.conn.sendall(encode_frame(opcode, payload, mask=b"", fin=fin))

    def text(self, data: object) -> None:
        self.send(OP_TEXT, json.dumps(data).encode())

    def frame(self) -> Frame:
        while True:
            decoded = decode_frame(self.buffer)
            if decoded is not None:
                frame, used = decoded
                self.buffer = self.buffer[used:]
                return frame
            chunk = self.conn.recv(4096)
            assert chunk, "the client closed the connection"
            self.buffer += chunk


class Server:
    """Accepts one connection on 127.0.0.1 and runs ``script`` on it in a thread."""

    def __init__(self, script: Callable[[Peer], None]):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.errors: list[BaseException] = []
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._serve, args=(script,), daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _serve(self, script: Callable[[Peer], None]) -> None:
        conn, _ = self.sock.accept()
        conn.settimeout(5)
        try:
            peer = Peer(conn)
            peer.read_request()
            script(peer)
        except BaseException as exc:
            self.errors.append(exc)
        finally:
            self.done.set()
            conn.close()
            self.sock.close()

    def finish(self) -> None:
        assert self.done.wait(5), "the server script did not finish"
        if self.errors:
            raise self.errors[0]


def doorbell(server: Server, **kwargs: float) -> WebSocketDoorbell:
    return WebSocketDoorbell(server.url, TOKEN, **kwargs)


# -- the handshake -------------------------------------------------------------------------------


def test_handshake_hello_mail_and_quiet() -> None:
    seen: dict[str, str] = {}

    def script(peer: Peer) -> None:
        seen.update(peer.headers, request=peer.request)
        peer.upgrade()
        peer.text({"type": "hello", "depth": 2})
        assert peer.frame() == Frame(True, OP_TEXT, b"ping", masked=True)
        peer.text({"type": "mail", "depth": 3})
        close = peer.frame()
        assert close.opcode == OP_CLOSE and close.masked
        assert struct.unpack("!H", close.payload)[0] == 1000
        peer.send(OP_CLOSE, close.payload)

    server = Server(script)
    bell = doorbell(server, ping_interval=0.2)
    bell.connect()
    assert bell.wait(2) is True and bell.last_depth == 2
    assert bell.wait(2) is True and bell.last_depth == 3  # after the ping went out
    started = time.monotonic()
    assert bell.wait(0.1) is False
    assert time.monotonic() - started < 1
    bell.close()
    assert not bell.connected
    server.finish()
    assert seen["request"] == "GET /hub/ws HTTP/1.1"
    assert seen["host"] == f"127.0.0.1:{server.port}"
    assert seen["authorization"] == f"Bearer {TOKEN}"
    assert seen["upgrade"] == "websocket" and seen["connection"] == "Upgrade"
    assert seen["sec-websocket-version"] == "13"
    assert len(seen["sec-websocket-key"]) == 24


def test_frames_already_in_the_handshake_answer_are_not_lost() -> None:
    def script(peer: Peer) -> None:
        key = peer.headers["sec-websocket-key"]
        peer.conn.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                f"Connection: upgrade\r\nSec-WebSocket-Accept: {accept_key(key)}\r\n\r\n"
            ).encode()
            + encode_frame(OP_TEXT, b'{"type":"hello","depth":0}', mask=b"")
        )
        peer.frame()  # the close

    server = Server(script)
    bell = doorbell(server)
    bell.connect()
    assert bell.wait(1) is True
    bell.close()
    server.finish()


@pytest.mark.parametrize(
    ("status", "code", "error"),
    [
        (401, "unauthorized", DoorbellUnauthorized),
        (404, "not_found", DoorbellUnsupported),
        (426, "upgrade_required", DoorbellUnsupported),
        (503, "not_configured", DoorbellError),
    ],
)
def test_a_refused_upgrade(status: int, code: str, error: type[DoorbellError]) -> None:
    server = Server(lambda peer: peer.refuse(status, code))
    bell = doorbell(server)
    with pytest.raises(error) as caught:
        bell.connect()
    server.finish()
    assert caught.value.status == status and code in str(caught.value)
    if error is DoorbellError:
        assert not isinstance(caught.value, DoorbellUnsupported | DoorbellUnauthorized)
    assert TOKEN not in str(caught.value) and TOKEN not in repr(bell)
    assert not bell.connected


@pytest.mark.parametrize(
    ("accept", "extra", "match"),
    [
        ("d3Jvbmc=", "", "Accept"),
        (None, "Sec-WebSocket-Extensions: permessage-deflate\r\n", "extension"),
    ],
)
def test_a_bad_upgrade_answer(accept: str | None, extra: str, match: str) -> None:
    server = Server(lambda peer: peer.upgrade(accept=accept, extra=extra))
    with pytest.raises(DoorbellError, match=match):
        doorbell(server).connect()
    server.finish()


def test_no_server() -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # nothing listens there now
    bell = WebSocketDoorbell(f"http://127.0.0.1:{port}", TOKEN, connect_timeout=2)
    with pytest.raises(DoorbellError, match="cannot connect") as caught:
        bell.connect()
    assert caught.value.status == 0
    with pytest.raises(DoorbellClosed):
        bell.wait(0.1)


# -- waiting -------------------------------------------------------------------------------------


def test_protocol_ping_gets_a_pong_and_fragments_are_joined() -> None:
    def script(peer: Peer) -> None:
        peer.upgrade()
        peer.send(OP_PING, b"are you there")
        pong = peer.frame()
        assert (pong.opcode, pong.payload, pong.masked) == (OP_PONG, b"are you there", True)
        body = json.dumps({"type": "mail", "depth": 1, "pad": "x" * 300}).encode()
        peer.send(OP_TEXT, body[:200], fin=False)  # 16-bit length
        peer.send(OP_PING, b"")  # a control frame between fragments is allowed
        peer.send(OP_CONTINUATION, body[200:])
        assert peer.frame().opcode == OP_PONG
        peer.send(OP_TEXT, b"pong")  # the auto-response to a ping: not mail
        peer.send(OP_BINARY, b"\x00")  # ignored
        peer.text({"type": "something else"})
        peer.frame()  # the close

    server = Server(script)
    bell = doorbell(server)
    bell.connect()
    assert bell.wait(3) is True and bell.last_depth == 1
    assert bell.wait(0.3) is False
    bell.close()
    server.finish()


def test_the_spine_closes_the_doorbell() -> None:
    def script(peer: Peer) -> None:
        peer.upgrade()
        peer.send(OP_CLOSE, struct.pack("!H", 1008) + b"replaced")
        echo = peer.frame()
        assert echo.opcode == OP_CLOSE and echo.payload == struct.pack("!H", 1008)

    server = Server(script)
    bell = doorbell(server)
    bell.connect()
    with pytest.raises(DoorbellClosed, match="1008"):
        bell.wait(3)
    assert not bell.connected
    server.finish()


def test_a_dropped_connection() -> None:
    server = Server(lambda peer: peer.upgrade())  # then the server closes the socket
    bell = doorbell(server)
    bell.connect()
    server.finish()
    with pytest.raises(DoorbellClosed):
        bell.wait(3)


def test_a_silent_spine_counts_as_dead() -> None:
    released = threading.Event()

    def script(peer: Peer) -> None:
        peer.upgrade()
        released.wait(5)  # reads nothing, answers no ping

    server = Server(script)
    bell = doorbell(server, ping_interval=0.1, idle_timeout=0.4)
    bell.connect()
    started = time.monotonic()
    with pytest.raises(DoorbellClosed, match="no answer"):
        bell.wait(5)
    assert 0.3 < time.monotonic() - started < 3
    released.set()
    server.finish()


def test_a_masked_server_frame_is_a_protocol_error() -> None:
    def script(peer: Peer) -> None:
        peer.upgrade()
        peer.conn.sendall(encode_frame(OP_TEXT, b'{"type":"mail"}', mask=b"abcd"))
        close = peer.frame()
        assert struct.unpack("!H", close.payload)[0] == 1002

    server = Server(script)
    bell = doorbell(server)
    bell.connect()
    with pytest.raises(DoorbellError, match="masked"):
        bell.wait(3)
    assert not bell.connected
    server.finish()


def test_close_from_another_thread_ends_a_wait() -> None:
    released = threading.Event()

    def script(peer: Peer) -> None:
        peer.upgrade()
        released.wait(5)

    server = Server(script)
    bell = doorbell(server)
    bell.connect()
    outcome: list[BaseException | bool] = []

    def waiter() -> None:
        try:
            outcome.append(bell.wait(30))
        except DoorbellError as exc:
            outcome.append(exc)

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    time.sleep(0.2)
    started = time.monotonic()
    bell.close()
    thread.join(5)
    assert time.monotonic() - started < 2
    assert outcome and isinstance(outcome[0], DoorbellClosed)
    released.set()
    server.finish()


def test_the_spine_client_builds_its_doorbell() -> None:
    client = SpineClient("https://tau.example.com/", TOKEN)
    bell = client.doorbell()
    assert (bell.secure, bell.host, bell.port, bell.path) == (
        True,
        "tau.example.com",
        443,
        "/hub/ws",
    )
    assert repr(bell) == "WebSocketDoorbell(wss://tau.example.com/hub/ws, token=<hidden>)"
    local = SpineClient("http://127.0.0.1:8831", TOKEN).doorbell()
    assert (local.secure, local.port, local.netloc) == (False, 8831, "127.0.0.1:8831")
