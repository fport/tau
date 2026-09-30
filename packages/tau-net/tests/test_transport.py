"""UrllibTransport against a loopback HTTP server: the one place a socket is unavoidable.

Redirects are never followed (they would carry the bearer token to another URL), HTTP errors
come back as statuses, oversized answers and dead ports raise ``TransportError``.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from tau_net.spine import SpineClient, SpineUnreachable, TransportError, UrllibTransport

SEEN: list[tuple[str, str | None]] = []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # quiet
        pass

    def do_GET(self) -> None:  # noqa: N802
        SEEN.append((self.path, self.headers.get("Authorization")))
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/target")
            self.end_headers()
        elif self.path == "/big":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"x" * 5000)
        elif self.path == "/hub/health":
            body = b'{"ok": true, "address": "127.0.0.1"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = b'{"error": "not_found"}'
            self.send_response(404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


@pytest.fixture
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    SEEN.clear()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_redirects_are_not_followed(server: str) -> None:
    transport = UrllibTransport()
    status, headers, _ = transport(
        "GET", f"{server}/redirect", {"Authorization": "Bearer t"}, None, 5
    )
    assert status == 302 and headers["location"] == "/target"
    assert [path for path, _ in SEEN] == ["/redirect"]


def test_statuses_sizes_and_dead_ports(server: str) -> None:
    transport = UrllibTransport(max_response_bytes=1000)
    status, _, body = transport("GET", f"{server}/missing", {}, None, 5)
    assert (status, body) == (404, b'{"error": "not_found"}')
    with pytest.raises(TransportError, match="larger than 1000"):
        transport("GET", f"{server}/big", {}, None, 5)
    spine = SpineClient(server, "the-token")
    assert spine.health()["ok"] is True
    assert SEEN[-1] == ("/hub/health", "Bearer the-token")
    dead = SpineClient("http://127.0.0.1:9", "the-token", timeout=2)
    with pytest.raises(SpineUnreachable) as caught:
        dead.health()
    assert "the-token" not in str(caught.value)
