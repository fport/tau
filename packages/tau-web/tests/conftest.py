"""Shared fixtures for tau-web: a test config, a file session store, a fake hub, and a running
web service on a random loopback port. Everything is offline (``FakeModel``); approvals come
only from the tests' own HTTP calls, never from an auto-approver."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterable
from pathlib import Path
from typing import Any

import httpx
import pytest
from tau_core import Config, Tier, build_agent, tau_tool
from tau_core.sessions import FileSessionStore
from tau_core.testing import FakeGuard, FakeModel, test_config
from tau_web.service import WebService
from tau_web.settings import WebSettings


@tau_tool(tier=Tier.READ)
def clock_tool(city: str) -> str:
    """Tells the time in a city."""
    return f"15:30 in {city}"


@tau_tool(tier=Tier.PHYSICAL, effect="Switches the test lamp.")
def lamp_tool(on: bool) -> str:
    """Switches the test lamp."""
    return "on" if on else "off"


TOOLS = [clock_tool, lamp_tool]


class FakeHub:
    """What a hub service needs from the hub: services by name, the started ones, status."""

    def __init__(self, services: Iterable[Any] = ()) -> None:
        self.services = {getattr(service, "name", "?"): service for service in services}
        self.sources: list[Callable[[], dict[str, Any]]] = []

    def find_service(self, name: str) -> Any:
        return self.services.get(name)

    def started_services(self) -> list[Any]:
        return list(self.services.values())

    def add_status_source(self, source: Callable[[], dict[str, Any]]) -> None:
        self.sources.append(source)


class GuardService(FakeGuard):
    """A ``FakeGuard`` registered as the hub's ``guard`` service, with ``subscribe``."""

    name = "guard"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.subscribers: list[Callable[[Any], None]] = []

    def subscribe(self, callback: Callable[[Any], None]) -> Callable[[], None]:
        self.subscribers.append(callback)
        return lambda: self.subscribers.remove(callback)

    def lock(self) -> None:
        self.set_state("locked", trigger="command")
        status = type("Status", (), {"state": "locked"})()
        for callback in list(self.subscribers):
            callback(status)


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return test_config(tmp_path)


@pytest.fixture
def store(config: Config) -> FileSessionStore:
    return FileSessionStore(config.sessions_dir)


def factory(model: FakeModel, tools: list[Any] | None = None) -> Callable[..., Any]:
    def build(**kwargs: Any) -> Any:
        return build_agent(model=model, tools=TOOLS if tools is None else tools, **kwargs)

    return build


class Web:
    """A running web service and an HTTP client that talks to it like the app would."""

    def __init__(self, service: WebService, client: httpx.AsyncClient, guard: GuardService):
        self.service = service
        self.client = client
        self.guard = guard
        self.base = str(client.base_url)

    @property
    def origin(self) -> dict[str, str]:
        return {"origin": self.base.rstrip("/")}

    async def pair(self, name: str = "phone") -> dict[str, Any]:
        code = self.service.devices.start_pairing(name)
        response = await self.client.post("/api/pair", json={"code": code}, headers=self.origin)
        assert response.status_code == 200, response.text
        return response.json()["device"]

    async def turn_lines(
        self, text: str, session: str | None = None
    ) -> AsyncIterator[dict[str, Any]]:
        body = {"text": text, **({"session": session} if session else {})}
        async with self.client.stream("POST", "/api/turns", json=body, headers=self.origin) as r:
            assert r.status_code == 200, await r.aread()
            assert r.headers["content-type"].startswith("application/x-ndjson")
            async for line in r.aiter_lines():
                if line.strip():
                    yield json.loads(line)

    async def turn(self, text: str, session: str | None = None) -> list[dict[str, Any]]:
        return [event async for event in self.turn_lines(text, session)]

    async def decide(self, request: str, decision: str) -> httpx.Response:
        return await self.client.post(
            f"/api/approvals/{request}", json={"decision": decision}, headers=self.origin
        )


@pytest.fixture
def model() -> FakeModel:
    return FakeModel()


@pytest.fixture
def guard() -> GuardService:
    return GuardService(state="unlocked", step_ups=[True] * 20)


@pytest.fixture
def settings() -> WebSettings:
    return WebSettings(port=0, approval_timeout=5.0, turn_keep=60.0)


@pytest.fixture
async def web(
    config: Config,
    store: FileSessionStore,
    model: FakeModel,
    guard: GuardService,
    settings: WebSettings,
) -> AsyncIterator[Web]:
    service = WebService(config, settings=settings, store=store, agent_factory=factory(model))
    hub = FakeHub([guard])
    await service.start(hub)
    hub.services["web"] = service
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{service.port}", timeout=10) as client:
        yield Web(service, client, guard)
    await service.stop()
