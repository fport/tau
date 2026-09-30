"""A real hub process for the ``kill -9`` test.

Usage: ``python hub_process.py <tmp> <script> <port-file>``.

It runs ``Hub`` with the ``ControlApi`` on port 0 and the guard service (the real clock and
reflex loop, a fake presence source that says the owner is at the Mac, the fake worker), and
writes the bound port to ``<port-file>``.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from tau_core.hub import ControlApi, Hub
from tau_core.testing import test_config
from tau_guard.service import GuardService
from tau_guard.testing import FakePresence, fake_worker_command


def main(tmp: str, script: str, port_file: str) -> int:
    config = test_config(Path(tmp), component_tables={"guard": {"enabled": True}})
    hub = Hub(config)
    api = ControlApi(0, hub.status)
    service = GuardService(
        config,
        presence=FakePresence(),
        worker_command=fake_worker_command(Path(script)),
        platform="darwin",
    )
    hub.add_service(api)
    hub.add_service(service, optional=True)

    def announce() -> None:
        while api.port == 0 or service.mode == "idle":
            time.sleep(0.02)
        Path(port_file).write_text(str(api.port))

    threading.Thread(target=announce, daemon=True).start()
    return hub.run()


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:4]))
