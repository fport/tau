"""The Cloudflare Access check: defense in depth behind the tunnel (ADR 0006 §1).

With ``[component.web] access_aud`` and ``access_team`` set, every request must carry a valid
``Cf-Access-Jwt-Assertion``: RS256, signed by one of the team's keys
(``https://<team>.cloudflareaccess.com/cdn-cgi/access/certs``), for this application's
audience, from the team's issuer, not expired. Off on the tailnet (Tailscale Serve sends no
such header), where the paired-device key is the door.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import jwt

logger = logging.getLogger(__name__)

HEADER = "cf-access-jwt-assertion"

KeyResolver = Callable[[str], Any]
"""``token → signing key``; the default fetches and caches the team's JWKS."""


class AccessVerifier:
    def __init__(self, team: str, audience: str, *, key_for: KeyResolver | None = None) -> None:
        self.issuer = f"https://{team}.cloudflareaccess.com"
        self.audience = audience
        if key_for is None:
            client = jwt.PyJWKClient(f"{self.issuer}/cdn-cgi/access/certs", cache_keys=True)

            def key_for(token: str) -> Any:
                return client.get_signing_key_from_jwt(token).key

        self._key_for = key_for

    def _check(self, token: str) -> bool:
        try:
            jwt.decode(
                token,
                self._key_for(token),
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "aud", "iss"]},
            )
        except Exception as exc:  # any doubt refuses: bad signature, audience, expiry, keys
            logger.info("web: Access token refused: %s", type(exc).__name__)
            return False
        return True

    async def verify(self, token: str | None) -> bool:
        if not token:
            return False
        return await asyncio.to_thread(self._check, token)
