"""The hub's doorbell: a small WebSocket client for a spine's ``GET /hub/ws`` (§5, §6.1).

The doorbell only says "look now". The spine sends ``{"type": "hello", "depth": n}`` when the
hub connects and ``{"type": "mail", "depth": n}`` after every queued envelope; the hub then
fetches with ``GET /hub/updates?timeout=0`` and acknowledges over HTTP as before. Waiting on
it costs the spine almost nothing: its ``Mailbox`` Durable Object hibernates between
envelopes, and it answers the hub's keepalive ``ping`` with ``pong`` without waking up.

- :class:`Doorbell` is the seam: :meth:`~Doorbell.connect`, :meth:`~Doorbell.wait` (``True``
  when mail was announced, which includes the hello of every (re)connect) and
  :meth:`~Doorbell.close`. :class:`tau_net.testing.FakeDoorbell` is the offline stand-in.
- :class:`WebSocketDoorbell` is RFC 6455 over ``socket`` and ``ssl`` from the standard
  library, only as much of it as the doorbell needs: the opening handshake with the bearer
  token and a checked ``Sec-WebSocket-Accept``, masked client frames, text/ping/pong/close
  frames in (with 16- and 64-bit lengths, fragments reassembled), a text ``ping`` every
  30 s and the closing handshake. No extensions, no subprotocols, no proxy: a hub that cannot
  reach the spine directly falls back to the long poll, which honours the proxy variables.

The token is sent only in the handshake and never appears in a repr, a log line or an
exception message.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import threading
import time
import urllib.parse
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol

__all__ = [
    "DOORBELL_PATH",
    "IDLE_TIMEOUT",
    "PING_INTERVAL",
    "Doorbell",
    "DoorbellClosed",
    "DoorbellError",
    "DoorbellUnauthorized",
    "DoorbellUnsupported",
    "Frame",
    "WebSocketDoorbell",
    "accept_key",
    "decode_frame",
    "encode_frame",
]

DOORBELL_PATH = "/hub/ws"
PING_INTERVAL = 30.0
"""Seconds between the hub's text ``ping`` frames."""
IDLE_TIMEOUT = 75.0
"""Seconds without any frame from the spine after which the connection counts as dead (two
missed ``pong`` answers and some slack)."""
CONNECT_TIMEOUT = 10.0
MAX_MESSAGE_BYTES = 64 * 1024
MAX_HANDSHAKE_BYTES = 16 * 1024
USER_AGENT = "tau-net/0.1.0"
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
"""RFC 6455 §1.3: appended to ``Sec-WebSocket-Key`` for ``Sec-WebSocket-Accept``."""

OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA
_CONTROL = frozenset({OP_CLOSE, OP_PING, OP_PONG})
_KNOWN = frozenset({OP_CONTINUATION, OP_TEXT, OP_BINARY, *_CONTROL})
CLOSE_NORMAL = 1000
CLOSE_PROTOCOL_ERROR = 1002


class DoorbellError(ConnectionError):
    """The doorbell could not be used. ``status`` is the HTTP status of a refused upgrade, or
    0 when no answer came or the connection failed later."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


class DoorbellUnsupported(DoorbellError):
    """The spine has no doorbell (``404`` or ``426`` on the upgrade): an older spine."""


class DoorbellUnauthorized(DoorbellError):
    """The spine rejected the hub token (``401``)."""


class DoorbellClosed(DoorbellError):
    """The connection ended: closed by the spine, dropped, or silent for too long."""


class Doorbell(Protocol):
    """What the ``net`` service waits on. Every method blocks; the service calls them from
    worker threads."""

    def connect(self) -> None:
        """Open the connection; :class:`DoorbellError` (or ``OSError``) when that fails."""
        ...

    def wait(self, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds: ``True`` as soon as mail is announced (the hello of
        a new connection included), ``False`` when the time passed quietly.
        :class:`DoorbellClosed` when the connection is gone."""
        ...

    def close(self) -> None:
        """Close the connection; safe to call twice and from another thread."""
        ...


# -- frames (RFC 6455 §5) ------------------------------------------------------------------------


@dataclass(frozen=True)
class Frame:
    fin: bool
    opcode: int
    payload: bytes
    masked: bool = False


def accept_key(key: str) -> str:
    """``Sec-WebSocket-Accept`` for a ``Sec-WebSocket-Key``."""
    digest = hashlib.sha1((key + GUID).encode("ascii")).digest()  # noqa: S324 - RFC 6455
    return base64.b64encode(digest).decode("ascii")


def _xor(data: bytes, mask: bytes) -> bytes:
    if not data:
        return b""
    repeated = (mask * (len(data) // 4 + 1))[: len(data)]
    return (int.from_bytes(data, "big") ^ int.from_bytes(repeated, "big")).to_bytes(
        len(data), "big"
    )


def encode_frame(
    opcode: int, payload: bytes = b"", *, mask: bytes | None = None, fin: bool = True
) -> bytes:
    """One frame. A client masks every frame (RFC 6455 §5.3): ``mask=None`` draws a random
    masking key, four bytes use that key, and ``b""`` sends it unmasked (what a server does)."""
    if mask is None:
        mask = os.urandom(4)
    if mask and len(mask) != 4:
        raise ValueError("a masking key is 4 bytes")
    if opcode in _CONTROL and (len(payload) > 125 or not fin):
        raise ValueError("a control frame is one frame of at most 125 bytes")
    head = bytes([(0x80 if fin else 0) | opcode])
    bit = 0x80 if mask else 0
    size = len(payload)
    if size < 126:
        head += bytes([bit | size])
    elif size < 1 << 16:
        head += bytes([bit | 126]) + struct.pack("!H", size)
    else:
        head += bytes([bit | 127]) + struct.pack("!Q", size)
    return head + mask + _xor(payload, mask) if mask else head + payload


def decode_frame(
    buffer: bytes | bytearray, *, max_payload: int = MAX_MESSAGE_BYTES
) -> tuple[Frame, int] | None:
    """The first frame of ``buffer`` and the number of bytes it took, or ``None`` while it is
    incomplete. A masked frame is unmasked (``Frame.masked`` says it was). Raises
    :class:`DoorbellError` for reserved bits, an unknown opcode, a bad control frame or a
    payload over ``max_payload``."""
    if len(buffer) < 2:
        return None
    first, second = buffer[0], buffer[1]
    if first & 0x70:
        raise DoorbellError("WebSocket protocol error: reserved bits set")
    fin, opcode = bool(first & 0x80), first & 0x0F
    if opcode not in _KNOWN:
        raise DoorbellError(f"WebSocket protocol error: unknown opcode {opcode:#x}")
    masked, size = bool(second & 0x80), second & 0x7F
    offset = 2
    if size == 126:
        if len(buffer) < 4:
            return None
        (size,) = struct.unpack_from("!H", buffer, 2)
        offset = 4
    elif size == 127:
        if len(buffer) < 10:
            return None
        (size,) = struct.unpack_from("!Q", buffer, 2)
        offset = 10
    if opcode in _CONTROL and (size > 125 or not fin):
        raise DoorbellError("WebSocket protocol error: bad control frame")
    if size > max_payload:
        raise DoorbellError(f"WebSocket message larger than {max_payload} bytes")
    mask = b""
    if masked:
        if len(buffer) < offset + 4:
            return None
        mask = bytes(buffer[offset : offset + 4])
        offset += 4
    end = offset + size
    if len(buffer) < end:
        return None
    payload = bytes(buffer[offset:end])
    return Frame(fin, opcode, _xor(payload, mask) if masked else payload, masked), end


# -- the client ----------------------------------------------------------------------------------


def _error_code(body: bytes) -> str:
    """The ``error`` field of a JSON error body, or ``""``."""
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return ""
    code = data.get("error") if isinstance(data, dict) else None
    return str(code)[:64] if isinstance(code, str) else ""


class WebSocketDoorbell:
    """The doorbell of the spine at ``url`` (``http(s)://host[:port]``), authenticated with
    the hub token. One connection at a time; :meth:`connect` again after it dropped."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        path: str = DOORBELL_PATH,
        ping_interval: float = PING_INTERVAL,
        idle_timeout: float = IDLE_TIMEOUT,
        connect_timeout: float = CONNECT_TIMEOUT,
        ssl_context: ssl.SSLContext | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("the spine URL must be http(s)://host[:port]")
        self.secure = parts.scheme == "https"
        self.host = parts.hostname
        self.port = parts.port or (443 if self.secure else 80)
        self.netloc = parts.netloc.rsplit("@", 1)[-1]
        self.path = parts.path.rstrip("/") + path
        self._token = token
        self.ping_interval = ping_interval
        self.idle_timeout = idle_timeout
        self.connect_timeout = connect_timeout
        self._ssl_context = ssl_context
        self._clock = clock
        self._sock: socket.socket | None = None
        self._buffer = bytearray()
        self._fragments: list[bytes] = []
        self._fragment_opcode = 0
        self._send_lock = threading.Lock()
        self._close_sent = False
        self._waiting = False
        self._last_heard = 0.0
        self._last_ping = 0.0
        self.last_depth: int | None = None

    def __repr__(self) -> str:
        scheme = "wss" if self.secure else "ws"
        return f"WebSocketDoorbell({scheme}://{self.netloc}{self.path}, token=<hidden>)"

    @property
    def connected(self) -> bool:
        return self._sock is not None

    # -- the opening handshake -------------------------------------------------------------------

    def connect(self) -> None:
        self.close()
        where = f"{'wss' if self.secure else 'ws'}://{self.netloc}{self.path}"
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
        except OSError as exc:
            raise DoorbellError(f"{where}: cannot connect ({type(exc).__name__})") from None
        try:
            if self.secure:
                context = self._ssl_context or ssl.create_default_context()
                try:
                    sock = context.wrap_socket(sock, server_hostname=self.host)
                except OSError as exc:
                    raise DoorbellError(f"{where}: TLS failed ({type(exc).__name__})") from None
            rest = self._handshake(sock, where)
        except BaseException:
            with suppress(OSError):
                sock.close()
            raise
        now = self._clock()
        self._sock, self._buffer = sock, bytearray(rest)
        self._fragments, self._close_sent = [], False
        self._last_heard = self._last_ping = now

    def _handshake(self, sock: socket.socket, where: str) -> bytes:
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.netloc}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Authorization: Bearer {self._token}\r\n"
            f"User-Agent: {USER_AGENT}\r\n"
            "\r\n"
        )
        try:
            sock.sendall(request.encode("latin-1"))
            data = b""
            while b"\r\n\r\n" not in data:
                if len(data) > MAX_HANDSHAKE_BYTES:
                    raise DoorbellError(f"{where}: the upgrade answer is too large")
                chunk = sock.recv(4096)
                if not chunk:
                    raise DoorbellError(f"{where}: the connection closed during the upgrade")
                data += chunk
        except DoorbellError:
            raise
        except (OSError, UnicodeError) as exc:
            raise DoorbellError(f"{where}: the upgrade failed ({type(exc).__name__})") from None
        head, _, rest = data.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        status_line = lines[0].split(" ", 2)
        try:
            status = int(status_line[1])
        except (IndexError, ValueError):
            raise DoorbellError(f"{where}: not an HTTP answer") from None
        headers: dict[str, str] = {}
        for line in lines[1:]:
            name, sep, value = line.partition(":")
            if sep:
                headers[name.strip().lower()] = value.strip()
        if status != 101:
            code = _error_code(rest)
            text = f"{where}: the spine answered {status}{f' {code}' if code else ''}"
            if status == 401:
                raise DoorbellUnauthorized(text, status)
            if status in (404, 426):
                raise DoorbellUnsupported(text, status)
            raise DoorbellError(text, status)
        if headers.get("upgrade", "").lower() != "websocket":
            raise DoorbellError(f"{where}: the answer does not upgrade to websocket", status)
        if "upgrade" not in headers.get("connection", "").lower():
            raise DoorbellError(f"{where}: the answer does not say Connection: Upgrade", status)
        if headers.get("sec-websocket-accept") != accept_key(key):
            raise DoorbellError(f"{where}: wrong Sec-WebSocket-Accept", status)
        if headers.get("sec-websocket-extensions") or headers.get("sec-websocket-protocol"):
            raise DoorbellError(f"{where}: the spine chose an extension or protocol", status)
        return rest

    # -- waiting ---------------------------------------------------------------------------------

    def wait(self, timeout: float) -> bool:
        sock = self._sock
        if sock is None:
            raise DoorbellClosed("the doorbell is not connected")
        self._waiting = True
        try:
            return self._wait(sock, self._clock() + max(0.0, timeout))
        finally:
            self._waiting = False
            if self._sock is not sock:  # dropped meanwhile, here or by close()
                with suppress(OSError):
                    sock.close()

    def _wait(self, sock: socket.socket, deadline: float) -> bool:
        while True:
            decoded = decode_frame(self._buffer)
            if decoded is not None:
                frame, used = decoded
                del self._buffer[:used]
                if self._handle(frame):
                    return True
                continue
            now = self._clock()
            if now - self._last_heard >= self.idle_timeout:
                self._drop()
                raise DoorbellClosed(f"no answer from the spine for {self.idle_timeout:.0f} s")
            if now - self._last_ping >= self.ping_interval:
                self._send(OP_TEXT, b"ping")
                self._last_ping = now
            if now >= deadline:
                return False
            wake = min(
                deadline,
                self._last_ping + self.ping_interval,
                self._last_heard + self.idle_timeout,
            )
            try:
                sock.settimeout(max(0.01, wake - now))
                data = sock.recv(65536)
            except TimeoutError:
                continue
            except OSError as exc:
                self._drop()
                raise DoorbellClosed(f"the doorbell dropped ({type(exc).__name__})") from None
            if not data:
                self._drop()
                raise DoorbellClosed("the spine closed the connection")
            self._buffer += data
            self._last_heard = self._clock()

    def _handle(self, frame: Frame) -> bool:
        """``True`` for an announcement of mail (or the hello)."""
        if frame.masked:  # RFC 6455 §5.1: a server never masks
            self._fail("a masked frame from the server")
        if frame.opcode == OP_PING:
            self._send(OP_PONG, frame.payload)
            return False
        if frame.opcode == OP_PONG:
            return False
        if frame.opcode == OP_CLOSE:
            code = struct.unpack("!H", frame.payload[:2])[0] if len(frame.payload) >= 2 else None
            if not self._close_sent:
                with suppress(OSError):
                    self._send(OP_CLOSE, frame.payload[:2])
            self._drop()
            raise DoorbellClosed(
                f"the spine closed the doorbell{f' ({code})' if code is not None else ''}"
            )
        if frame.opcode == OP_CONTINUATION:
            if not self._fragments:
                self._fail("a continuation frame without a start")
            self._fragments.append(frame.payload)
        else:
            if self._fragments:
                self._fail("a new message inside a fragmented one")
            self._fragment_opcode = frame.opcode
            self._fragments = [frame.payload]
        if sum(len(part) for part in self._fragments) > MAX_MESSAGE_BYTES:
            self._fail("a message over the size limit")
        if not frame.fin:
            return False
        message, opcode = b"".join(self._fragments), self._fragment_opcode
        self._fragments = []
        return opcode == OP_TEXT and self._announces_mail(message)

    def _announces_mail(self, message: bytes) -> bool:
        if message == b"pong":
            return False
        try:
            data = json.loads(message.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return False
        if not isinstance(data, dict) or data.get("type") not in ("hello", "mail"):
            return False
        depth = data.get("depth")
        self.last_depth = depth if isinstance(depth, int) and not isinstance(depth, bool) else None
        return True

    def _fail(self, reason: str) -> None:
        with suppress(OSError):
            self._send(OP_CLOSE, struct.pack("!H", CLOSE_PROTOCOL_ERROR))
        self._drop()
        raise DoorbellError(f"WebSocket protocol error: {reason}")

    def _send(self, opcode: int, payload: bytes) -> None:
        sock = self._sock
        if sock is None:
            raise DoorbellClosed("the doorbell is not connected")
        with self._send_lock:
            if opcode == OP_CLOSE:
                if self._close_sent:
                    return
                self._close_sent = True
            try:
                sock.sendall(encode_frame(opcode, payload))
            except OSError as exc:
                self._drop()
                raise DoorbellClosed(f"the doorbell dropped ({type(exc).__name__})") from None

    # -- closing ---------------------------------------------------------------------------------

    def close(self) -> None:
        """The closing handshake (RFC 6455 §7): send a close frame and, unless another thread
        is waiting on the socket, read up to a second for the spine's answer; then close."""
        sock = self._sock
        if sock is None:
            return
        with suppress(DoorbellError, OSError):
            self._send(OP_CLOSE, struct.pack("!H", CLOSE_NORMAL))
        if not self._waiting and self._sock is sock:
            deadline = self._clock() + 1.0
            with suppress(OSError, DoorbellError):
                while self._clock() < deadline:
                    decoded = decode_frame(self._buffer)
                    if decoded is not None:
                        frame, used = decoded
                        del self._buffer[:used]
                        if frame.opcode == OP_CLOSE:
                            break
                        continue
                    sock.settimeout(max(0.01, deadline - self._clock()))
                    data = sock.recv(4096)
                    if not data:
                        break
                    self._buffer += data
        self._drop()

    def _drop(self) -> None:
        """Forget the connection and shut the socket down, which wakes a thread waiting on
        it. That thread closes the socket itself when it wakes: closing a descriptor another
        thread is polling does not reliably wake it."""
        sock, self._sock = self._sock, None
        if sock is None:
            return
        with suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)
        if not self._waiting:
            with suppress(OSError):
                sock.close()
