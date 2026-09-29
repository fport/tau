"""Test fixture: a hub service (``tau.hub_services``) and a context source (``tau.context``)."""

from __future__ import annotations

from typing import Any

from tau_core import Config, ContextSource
from tau_core.hub import ControlApi, ControlRequest, Hub


class ExampleService:
    """Adds ``/status`` keys and a control API route once the hub has started it."""

    name = "example"

    def __init__(self, config: Config):
        self.config = config
        self.started = False
        self.stopped = False

    async def start(self, hub: Hub) -> None:
        self.started = True
        hub.add_status_source(lambda: {"example": {"profile": self.config.profile}})
        api = hub.find_service(ControlApi.name)
        if isinstance(api, ControlApi):
            api.add_route("GET", "/example", self._example)

    async def stop(self) -> None:
        self.stopped = True

    def _example(self, request: ControlRequest) -> tuple[int, Any]:
        return 200, {"example": True, "component": self.config.component("example")}


def make_service(config: Config) -> ExampleService:
    return ExampleService(config)


def make_context_source(config: Config) -> ContextSource:
    """Reports the nodes listed in ``[component.example] nodes``; none configured = unknown."""
    nodes = config.component("example").get("nodes")
    return lambda: {"nodes": nodes}
