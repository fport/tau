"""The whole guard path in one hub (ADR 0008): ``assemble_hub`` loads the guard service from its
``tau.hub_services`` entry point (with a fake worker and fake presence), ``build_agent`` resolves
``HubGuard`` over it, and Telegram's ``/guard lock`` reaches the in-hub service.

The channel tests run against ``FakeGuard`` and the service tests drive ``HubGuard`` by hand; this
test catches a mismatch between the two. The control port is a freshly bound ephemeral port, never
the live hub's.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import tau_guard.service as guard_service
from guard_helpers import free_port
from tau_core import Config, Decision, HubGuard, MemorySessionStore
from tau_core.agent import ToolFinished, TurnEnd, build_agent
from tau_core.builtin_tools import demo_physical_action
from tau_core.channels.telegram import ChatState, cmd_guard
from tau_core.guard import ENROLLED_MARKER, process_client_id, reset_guards, resolve_guard
from tau_core.hub.cli import assemble_hub
from tau_core.testing import FakeModel, ScriptedApprover, ToolCall, test_config
from tau_guard.testing import (
    FakeClock,
    FakePresence,
    fake_worker_command,
    match,
    read_requests,
    write_script,
)

LIVE_PORT = 7877
NO_MATCH = {"verdict": {"ok": False, "reason": "no_match", "score": 0.2}}


def make_config(tmp: Path, port: int) -> Config:
    config = test_config(tmp)
    toml = (config.home / "tau.toml").read_text(encoding="utf-8")
    toml = toml.replace("control_port = 7877", f"control_port = {port}")
    toml += '\n[components.hub]\nservices = ["guard", "telegram"]\n'
    toml += "\n[component.guard]\nenabled = true\n"
    (config.home / "tau.toml").write_text(toml, encoding="utf-8")
    config = Config.load(config.home, env={"TAU_DATA_DIR": str(tmp / "data")})
    assert config.hub.control_port == port != LIVE_PORT
    marker = config.data_dir / ENROLLED_MARKER
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({"v": 1, "enrollment": "E1"}), encoding="utf-8")
    return config


class RealHub:
    def __init__(self, tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.port = free_port()
        self.config = make_config(tmp, self.port)
        work = tmp / "worker"
        work.mkdir()
        self.script = write_script(work / "script.json", [[]])
        self.services: dict[str, guard_service.GuardService] = {}

        def make_service(config: Config) -> guard_service.GuardService:
            service = guard_service.GuardService(
                config,
                clock=FakeClock(),
                presence=FakePresence(),
                worker_command=fake_worker_command(self.script),
                platform="darwin",
                reflex_loop=False,
                attempt_timeout=10,
            )
            self.services["guard"] = service
            return service

        # the entry point `guard = "tau_guard.service:make_service"` resolves this attribute
        monkeypatch.setattr(guard_service, "make_service", make_service)
        self.hub, self.api = assemble_hub(self.config)
        self.thread = threading.Thread(target=self.hub.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 15
        while not (
            self.api.port == self.port
            and "guard" in self.services
            and self.services["guard"].mode != "idle"
        ):
            if time.monotonic() > deadline:
                raise AssertionError("the hub did not start")
            time.sleep(0.02)
        assert self.services["guard"].mode == "active", self.services["guard"].reason

    def runs(self, *runs: list[dict]) -> None:
        write_script(self.script, list(runs))

    def kinds(self) -> list[str]:
        return [record["request"]["kind"] for record in read_requests(self.script)]

    def stop(self) -> None:
        self.hub.request_stop()
        self.thread.join(timeout=15)


@pytest.fixture
def real_hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[RealHub]:
    # v1 is macOS-only: build_agent's DISCOVER resolves the guard for sys.platform, so the test
    # runs as the hub Mac would on CI's Linux runners too
    monkeypatch.setattr(sys, "platform", "darwin")
    reset_guards()
    hub = RealHub(tmp_path, monkeypatch)
    try:
        yield hub
    finally:
        hub.stop()
        reset_guards()


async def collect(agent, prompt: str) -> list:
    return [event async for event in agent.stream(prompt)]


async def test_agent_through_a_real_hub(real_hub: RealHub) -> None:
    config = real_hub.config
    guard = resolve_guard(config)
    assert isinstance(guard, HubGuard) and guard.client.port == real_hub.port
    assert resolve_guard(config) is guard

    model = FakeModel(
        [
            [ToolCall("demo_physical_action", {"action": "wave"})],
            "Waved.",
            [ToolCall("demo_physical_action", {"action": "wave again"})],
            "Refused.",
        ]
    )
    approver = ScriptedApprover([Decision.APPROVED, Decision.APPROVED])
    agent = build_agent(
        config=config,
        model=model,
        tools=[demo_physical_action],
        approver=approver,
        channel="terminal",
        session_store=MemorySessionStore(),
    )
    assert agent.guard is guard and agent.client_id == process_client_id()

    # 1. every hub start is locked: the turn is refused and nothing reaches the model
    events = await collect(agent, "hi")
    assert isinstance(events[-1], TurnEnd) and events[-1].stop_reason == "locked", events
    assert model.calls == []

    # 2. an unlock through the worker, with its progress
    real_hub.runs([{"progress": "look"}, {"sleep": 0.05}, match()])
    steps: list[str] = []
    verdict = await guard.unlock(
        channel="terminal",
        client_id=process_client_id(),
        on_progress=lambda progress: steps.append(progress.step),
    )
    assert verdict.ok is True and verdict.method == "face", verdict
    assert "look" in steps
    assert (await guard.status()).state == "unlocked"

    # 3. the turn is admitted; the tier-2 call needs the approval and then a step-up
    real_hub.runs([match()])
    events = await collect(agent, "wave")
    finished = [event for event in events if isinstance(event, ToolFinished)]
    assert finished and finished[0].status == "ok", events
    assert isinstance(events[-1], TurnEnd) and events[-1].stop_reason == "end_turn", events
    assert len(approver.requests) == 1
    assert real_hub.kinds() == ["unlock", "step_up"]

    # 4. a step-up that sees another face refuses the approved call and locks the guard
    real_hub.runs([NO_MATCH])
    events = await collect(agent, "again")
    finished = [event for event in events if isinstance(event, ToolFinished)]
    assert finished and finished[0].status != "ok", events
    assert real_hub.kinds()[-1] == "step_up"
    status = await guard.status()
    assert (status.state, status.lock_trigger) == ("locked", "step_up_failed"), status
    real_hub.runs([match()])
    assert (await guard.unlock(channel="terminal", client_id=process_client_id())).ok

    # 5. Telegram's /guard lock reaches the in-hub service, and the next turn is refused
    telegram = real_hub.hub.find_service("telegram")
    assert telegram is not None and telegram.guard() is real_hub.services["guard"]
    chat = ChatState(chat_id=1, language="en")
    await cmd_guard(telegram, chat, "lock")
    status = await guard.status()
    assert (status.state, status.lock_trigger) == ("locked", "telegram"), status
    before = len(model.calls)
    events = await collect(agent, "after lock")
    assert events[-1].stop_reason == "locked"
    assert len(model.calls) == before
    agent.close()
