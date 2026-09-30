"""tau-cloud: tau's cloud mode (ADR 0007, §5 of docs/reference/tau-network.md).

In cloud mode the same Python hub runs as a Cloudflare Container that the owner's spine Worker
manages, and its life data lives in the spine: sessions in D1, ``tau.toml`` and the persona
files in KV. This package is the Python side of that; so far the ``spine`` session backend
(``[sessions] backend = "spine"``).

Public API (other packages import these names and ``tau_cloud.testing``)::

    SpineSessionStore, SpineStoreError, make_store, validate_id
"""

from __future__ import annotations

from tau_cloud._version import __version__
from tau_cloud.sessions import SpineSessionStore, SpineStoreError, make_store, validate_id

__all__ = [
    "SpineSessionStore",
    "SpineStoreError",
    "__version__",
    "make_store",
    "validate_id",
]
