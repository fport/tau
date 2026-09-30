"""tau-cloud: tau's cloud mode (ADR 0007, §5 of docs/reference/tau-network.md).

In cloud mode the same Python hub runs as a Cloudflare Container that the owner's spine Worker
manages, and its life data lives in the spine: sessions in D1, ``tau.toml`` and the persona
files in KV. This package is the Python side of that:

- the ``spine`` session backend (``[sessions] backend = "spine"``);
- ``tau cloud push|pull|status``, which move the config and persona files (sub-tau files in
  ``persona/subs/`` included) between the owner's machine and the spine;
- ``tau cloud run``, the brain container's entrypoint.

Public API (other packages import these names and ``tau_cloud.testing``)::

    SpineSessionStore, SpineStoreError, make_store, validate_id
    FILE_NAMES, SUBS_DIR, USER_FILE, FileError, LocalFile, RemoteFile, WriteResult,
    read_local, write_local, upload, download, list_remote, delete_remote, scan_subs,
    is_sub_file, cloud_config
    HealthServer, hub_status_reader
    cloud (the click group), HubRunner, run_hub
"""

from __future__ import annotations

from tau_cloud._version import __version__
from tau_cloud.cli import HubRunner, cloud, run_hub
from tau_cloud.files import (
    FILE_NAMES,
    SUBS_DIR,
    USER_FILE,
    FileError,
    LocalFile,
    RemoteFile,
    WriteResult,
    cloud_config,
    delete_remote,
    download,
    is_sub_file,
    list_remote,
    read_local,
    scan_subs,
    upload,
    write_local,
)
from tau_cloud.health import HealthServer, hub_status_reader
from tau_cloud.sessions import SpineSessionStore, SpineStoreError, make_store, validate_id

__all__ = [
    "FILE_NAMES",
    "SUBS_DIR",
    "USER_FILE",
    "FileError",
    "HealthServer",
    "HubRunner",
    "LocalFile",
    "RemoteFile",
    "SpineSessionStore",
    "SpineStoreError",
    "WriteResult",
    "__version__",
    "cloud",
    "cloud_config",
    "delete_remote",
    "download",
    "hub_status_reader",
    "is_sub_file",
    "list_remote",
    "make_store",
    "read_local",
    "run_hub",
    "scan_subs",
    "upload",
    "validate_id",
    "write_local",
]
