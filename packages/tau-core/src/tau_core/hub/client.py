"""``HubClient``: a caller of the hub's control API that checks who answered (ADR 0008).

Loopback only, never through a proxy. For a protected path it reads ``hub_dir/control.token``
on every request (a restarted hub writes a new one; clients never cache it), retries once
after a 403, always sends a fresh ``X-Tau-Nonce`` and verifies the ``X-Tau-Proof`` of the
answer, so a process that bound the port while the hub was down cannot answer for it.
"""

from __future__ import annotations

import hmac
import http.client
import json
import secrets
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlencode

from tau_core.config import Config
from tau_core.hub.control import HOST, OPEN_PATHS, TOKEN_FILE, read_token, response_proof

__all__ = ["HubClient", "HubError", "HubUnavailable"]


class HubUnavailable(Exception):
    """No trustworthy hub answered. ``reason``: ``no_hub`` (nothing listens, or no token file),
    ``timeout``, ``bad_proof`` or ``bad_response``."""

    def __init__(self, reason: str, message: str) -> None:
        self.reason = reason
        super().__init__(message)


class HubError(Exception):
    """The hub answered with a non-2xx status (``payload`` is its JSON body, if any)."""

    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self.payload = payload
        super().__init__(f"the hub answered {status}: {payload!r}"[:300])


class HubClient:
    """JSON over HTTP to ``127.0.0.1:<[hub] control_port>``; blocking (run it in a thread)."""

    def __init__(self, config: Config, *, port: int | None = None) -> None:
        self.port = config.hub.control_port if port is None else port
        self.token_path = config.hub_dir / TOKEN_FILE
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(self, path: str, *, timeout: float, query: Mapping[str, str] | None = None) -> Any:
        """``GET path`` → the JSON payload of a 2xx answer."""
        return self._request("GET", path, None, timeout=timeout, query=query)

    def post(self, path: str, body: Any, *, timeout: float) -> Any:
        """``POST path`` with ``body`` as JSON → the JSON payload of a 2xx answer."""
        return self._request("POST", path, body, timeout=timeout, query=None)

    def _request(
        self,
        method: str,
        path: str,
        body: Any,
        *,
        timeout: float,
        query: Mapping[str, str] | None,
    ) -> Any:
        protected = path not in OPEN_PATHS
        url = f"http://{HOST}:{self.port}{path}"
        if query:
            url += "?" + urlencode(dict(query))
        data = json.dumps(body).encode("utf-8") if method != "GET" else None
        for attempt in range(2):
            token = read_token(self.token_path) if protected else None
            if protected and token is None:
                raise HubUnavailable("no_hub", f"no control token in {self.token_path}")
            nonce = secrets.token_hex(16)
            headers = {"Accept": "application/json", "X-Tau-Nonce": nonce}
            if token is not None:
                headers["X-Tau-Token"] = token
            if data is not None:
                headers["Content-Type"] = "application/json"
            status, raw, proof = self._send(url, method, data, headers, timeout)
            if not (protected and status == 403 and attempt == 0):
                break  # a 403 on the first try: the hub may have restarted; re-read the token
        payload = self._parse(raw)
        if protected and status == 403:
            raise HubError(status, None if isinstance(payload, _Unparsable) else payload)
        if protected:
            assert token is not None
            expected = response_proof(token, nonce, method, path, status, raw)
            if not proof or not hmac.compare_digest(proof.encode(), expected.encode()):
                raise HubUnavailable(
                    "bad_proof", f"the answer to {method} {path} has no valid proof"
                )
        if isinstance(payload, _Unparsable):
            raise HubUnavailable("bad_response", f"the answer to {method} {path} is not JSON")
        if not 200 <= status < 300:
            raise HubError(status, payload)
        return payload

    def _send(
        self, url: str, method: str, data: bytes | None, headers: dict[str, str], timeout: float
    ) -> tuple[int, bytes, str | None]:
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with self._opener.open(request, timeout=timeout) as response:
                return response.status, response.read(), response.headers.get("X-Tau-Proof")
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, exc.read(), exc.headers.get("X-Tau-Proof")
        except TimeoutError as exc:
            raise HubUnavailable("timeout", f"the hub did not answer {method} in time") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise HubUnavailable("timeout", f"the hub did not answer {method} in time") from exc
            raise HubUnavailable("no_hub", f"no hub answers on {url}: {exc.reason}") from exc
        except (OSError, http.client.HTTPException) as exc:
            raise HubUnavailable("no_hub", f"no hub answers on {url}: {exc}") from exc

    @staticmethod
    def _parse(raw: bytes) -> Any:
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return _Unparsable()


class _Unparsable:
    """Marks a body that is not JSON (kept apart from a JSON ``null``)."""
