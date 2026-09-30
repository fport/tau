"""Spend per proxy role: the tracker, the ``budget`` context line and the ``spend`` service."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from tau_core import Config
from tau_core.config import BudgetConfig, RoleConfig
from tau_core.hub.control import ControlApi, ControlRequest
from tau_core.persona import default_context_factory
from tau_core.spend import (
    RoleSpend,
    SpendService,
    SpendTracker,
    context_source,
    describe,
    note_spend,
    tracker_for,
)
from tau_core.testing import test_config

URL = "http://proxy.test"
ENV = {"TAU_PROXY_URL": URL, "TAU_PROXY_KEY_BRAIN": "sk-b", "TAU_PROXY_KEY_FAST": "sk-f"}
RESET = "2026-10-01T00:00:00+00:00"


def proxy_config(tmp_path: Path) -> Config:
    config = test_config(tmp_path)
    return config.with_overrides(
        roles={
            "brain": RoleConfig("proxy", "brain", budget=BudgetConfig(15.0, "1mo", "fast")),
            "fast": RoleConfig("proxy", "fast", budget=BudgetConfig(1.0, "1d")),
            "test": RoleConfig("fake", "fake"),
        }
    )


class FakeProxy:
    """``/key/info`` answers per key; ``fail`` makes one key's lookup raise."""

    def __init__(self) -> None:
        self.info: dict[str, dict[str, Any]] = {
            "sk-b": {"spend": 0.42, "max_budget": 15.0, "budget_duration": "1mo"},
            "sk-f": {"spend": 1.0, "max_budget": 1.0, "budget_duration": "1d"},
        }
        self.calls: list[tuple[str, str]] = []
        self.fail: set[str] = set()

    def __call__(self, base_url: str, api_key: str) -> dict:
        self.calls.append((base_url, api_key))
        if api_key in self.fail:
            raise OSError("connection refused")
        if api_key not in self.info:
            raise ValueError("unknown key")
        return {"budget_reset_at": RESET, **self.info[api_key]}


def test_refresh_reads_every_proxy_role(tmp_path: Path) -> None:
    proxy = FakeProxy()
    tracker = SpendTracker(proxy_config(tmp_path), ENV, fetch=proxy)
    spends = tracker.refresh()
    assert set(spends) == {"brain", "fast"}  # the fake role has no key
    assert proxy.calls == [(URL, "sk-b"), (URL, "sk-f")]
    brain, fast = spends["brain"], spends["fast"]
    assert (brain.spend, brain.max_budget, brain.period) == (0.42, 15.0, "1mo")
    assert brain.reset_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert not brain.exhausted and not brain.drifted and brain.degrade_to == "fast"
    assert fast.exhausted
    assert brain.to_json() == {
        "group": "brain",
        "spend_usd": 0.42,
        "max_budget_usd": 15.0,
        "period": "1mo",
        "reset_at": RESET,
        "exhausted": False,
        "configured": {"usd": 15.0, "period": "1mo", "degrade_to": "fast"},
        "error": None,
    }


def test_missing_key_failure_and_drift(tmp_path: Path) -> None:
    proxy = FakeProxy()
    env = {**ENV, "TAU_PROXY_KEY_FAST": ""}
    tracker = SpendTracker(proxy_config(tmp_path), env, fetch=proxy)
    spends = tracker.refresh()
    assert spends["fast"].error == "TAU_PROXY_KEY_FAST is not set" and not spends["fast"].known
    proxy.info["sk-b"]["max_budget"] = 20.0
    assert tracker.refresh()["brain"].drifted
    proxy.fail.add("sk-b")
    kept = tracker.refresh()["brain"]
    assert kept.spend == 0.42 and kept.error == "connection refused"  # last good numbers stay


def test_snapshot_never_blocks_and_refreshes_in_the_background(tmp_path: Path) -> None:
    release = threading.Event()
    started = threading.Event()
    proxy = FakeProxy()

    def slow(base_url: str, api_key: str) -> dict:
        started.set()
        release.wait(5)
        return proxy(base_url, api_key)

    now = [0.0]
    tracker = SpendTracker(proxy_config(tmp_path), ENV, fetch=slow, ttl=60, clock=lambda: now[0])
    first = tracker.snapshot()
    assert not first["brain"].known  # nothing yet, and no wait
    assert started.wait(5)
    tracker.snapshot()  # a refresh is running: no second one
    release.set()
    for _ in range(100):
        if tracker.snapshot()["brain"].known:
            break
        threading.Event().wait(0.02)
    assert tracker.snapshot()["brain"].spend == 0.42
    calls = len(proxy.calls)
    now[0] = 30.0
    tracker.snapshot()  # still fresh
    assert len(proxy.calls) == calls


def test_note_updates_known_spend_only(tmp_path: Path) -> None:
    tracker = SpendTracker(proxy_config(tmp_path), ENV, fetch=FakeProxy())
    tracker.note("brain", 3.0)
    assert not tracker.snapshot()["brain"].known  # an unread key is not invented
    tracker.refresh()
    tracker.note("brain", 3.0)
    assert tracker.snapshot()["brain"].spend == 3.0


def test_tracker_for_is_shared_and_note_spend_finds_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tau_core import proxy

    proxy_fake = FakeProxy()
    monkeypatch.setattr(proxy, "fetch_key_info", lambda url, key, **kw: proxy_fake(url, key))
    config = proxy_config(tmp_path)
    tracker = tracker_for(config, ENV)
    assert tracker_for(config, dict(ENV)) is tracker
    tracker.refresh()
    note_spend(URL + "/", "fast", 0.5)
    assert tracker.snapshot()["fast"].spend == 0.5
    note_spend("http://other", "fast", 0.9)
    assert tracker.snapshot()["fast"].spend == 0.5


def test_describe() -> None:
    reset = datetime(2026, 10, 1, tzinfo=UTC)
    spends = {
        "brain": RoleSpend("brain", "brain", 0.42, 15.0, "1mo", reset, 15.0, "1mo", "fast"),
        "fast": RoleSpend("fast", "fast", 1.0, 1.0, "1d", reset, 1.0, "1d"),
        "local": RoleSpend("local", "local"),
        "free": RoleSpend("free", "free", 0.1),
    }
    assert describe(spends) == (
        "brain $0.42 of $15.00 per 1mo (resets 01.10.2026 03:00); "
        "fast $1.00 of $1.00 per 1d, spent (resets 01.10.2026 03:00); "
        "free $0.10 (no cap)"
    )
    spends["brain"] = RoleSpend("brain", "brain", 16.0, 15.0, "1mo", None, 15.0, "1mo", "fast")
    assert describe({"brain": spends["brain"]}) == (
        "brain $16.00 of $15.00 per 1mo, spent, fast answers instead (resets ?)"
    )
    assert describe({"local": RoleSpend("local", "local")}) is None


def test_context_source_puts_the_budget_under_now(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = proxy_config(tmp_path)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    tracker_for(config)._fetch = FakeProxy()  # type: ignore[attr-defined]
    tracker_for(config).refresh()
    factory = default_context_factory(config, sources=[context_source(config)])
    rendered = factory().render()
    assert "- Budget: brain $0.42 of $15.00 per 1mo (resets 01.10.2026 03:00); fast" in rendered
    assert context_source(test_config(tmp_path / "plain"))() == {}


def test_spend_service_adds_status_and_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = proxy_config(tmp_path)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    service = SpendService(config)
    service.tracker._fetch = FakeProxy()  # type: ignore[attr-defined]
    api = ControlApi(0, lambda: {})
    sources: list = []

    class Hub:
        def add_status_source(self, source) -> None:
            sources.append(source)

        def find_service(self, name: str):
            return api if name == "control-api" else None

    import asyncio

    asyncio.run(service.start(Hub()))  # type: ignore[arg-type]
    assert not api.is_open("GET", "/spend")  # protected: the token is needed over HTTP
    code, payload = api.handle(ControlRequest("GET", "/spend"))
    assert code == 200 and payload["proxy"] == URL
    assert payload["roles"]["brain"]["spend_usd"] == 0.42
    assert payload["roles"]["fast"]["exhausted"] is True
    (source,) = sources
    assert source()["spend"]["roles"]["brain"]["spend_usd"] == 0.42  # the refreshed cache


def test_spend_needs_the_control_token_over_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import json
    import urllib.error
    import urllib.request

    from tau_core.hub.control import auth_headers

    config = proxy_config(tmp_path)
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    service = SpendService(config)
    service.tracker._fetch = FakeProxy()  # type: ignore[attr-defined]
    api = ControlApi(0, lambda: {}, hub_dir=tmp_path / "hub")

    class Hub:
        def add_status_source(self, source) -> None:
            pass

        def find_service(self, name: str):
            return api if name == "control-api" else None

    asyncio.run(service.start(Hub()))  # type: ignore[arg-type]
    token = api.write_token()
    api.serve()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(headers: dict[str, str]) -> int:
        request = urllib.request.Request(f"{api.url}/spend", headers=headers)
        try:
            with opener.open(request, timeout=5) as response:
                assert json.loads(response.read())["proxy"] == URL
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code

    try:
        assert get({}) == 403
        assert get({"X-Tau-Token": token}) == 403  # the raw token is never accepted
        assert get(auth_headers(token, "GET", "/spend")) == 200
    finally:
        api.shutdown()
