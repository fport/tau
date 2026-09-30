"""The guard service in a real hub: ``ControlApi`` on port 0, the fake worker, and tau-core's
``HubGuard``/``HubClient`` as the client (signed requests, response proofs)."""

from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from guard_helpers import TURN, Running, guard_config, running_hub, until, until_async
from tau_core import Guard, GuardVerdict, Tier
from tau_core.approval import ApprovalRequest
from tau_core.hub import HubError
from tau_guard.routes import POLICY_FIELDS, SCHEMAS
from tau_guard.testing import FakePresence, match, read_requests

REQUEST = ApprovalRequest("r1", "lamp", Tier.PHYSICAL, {"state": "on"}, "", "s1", "tui")
LOOK = [{"progress": "look"}, {"sleep": 0.1}, {"progress": "turn_left"}, {"sleep": 0.1}]
NO_MATCH = {"verdict": {"ok": False, "reason": "no_match", "score": 0.2}}
PASSIVE = match(liveness="passive")


def body_for(route: tuple[str, str]) -> dict[str, Any]:
    """A valid request body (or query) for each route."""
    return {
        ("GET", "/guard/status"): {},
        ("POST", "/guard/admit"): {"channel": "tui", "session_id": "s1", "client_id": "c1"},
        ("POST", "/guard/verify"): {"channel": "tui", "client_id": "c1", "kind": "unlock"},
        ("POST", "/guard/cancel"): {"client_id": "c1"},
        ("POST", "/guard/lock"): {"channel": "tui", "client_id": "c1", "trigger": "command"},
        ("POST", "/guard/enroll"): {"client_id": "c1"},
    }[route]


def call(running: Running, method: str, path: str, body: Any = None, **query: str) -> Any:
    client = running.client
    if method == "GET":
        return client.get(path, timeout=10, query=query or None)
    return client.post(path, body, timeout=10)


def gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def worker_pid(running: Running) -> int:
    until(lambda: bool(read_requests(running.script)))
    return int(read_requests(running.script)[-1]["pid"])


async def worker_pid_async(running: Running) -> int:
    await until_async(lambda: bool(read_requests(running.script)))
    return int(read_requests(running.script)[-1]["pid"])


# -- admission, unlock, step-up, lock ------------------------------------------------------------


async def test_admit_unlock_step_up_and_lock_through_hub_guard(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[*LOOK, match()]]) as running:
        guard = running.guard
        assert await guard.admit(TURN) == type(await guard.admit(TURN))(False, "locked")
        steps: list[str] = []
        verdict = await guard.unlock(
            channel="tui", client_id="c1", on_progress=lambda p: steps.append(p.step)
        )
        assert verdict == GuardVerdict(True, "match", "face")
        assert steps[0] == "starting" and "look" in steps and "turn_left" in steps
        assert (await guard.admit(TURN)).allowed is True
        status = await guard.status()
        assert (status.state, status.method, status.enrolled) == ("unlocked", "face", True)
        assert status.since is not None and status.expires_at is not None
        assert status.face_seen_at is not None
        running.script_runs([match()])
        assert await guard.step_up(REQUEST, client_id="c1") is True
        await guard.lock(channel="tui", client_id="c1")
        status = await guard.status()
        assert (status.state, status.lock_trigger) == ("locked", "command")
        assert (await guard.admit(TURN)).reason == "locked"
        assert call(running, "POST", "/guard/lock", body_for(("POST", "/guard/lock"))) == {
            "state": "locked"
        }  # idempotent
        requests = read_requests(running.script)
        assert [r["request"]["kind"] for r in requests] == ["unlock", "step_up"]
        step_up = requests[1]["request"]
        assert step_up["policy"] == {"step_up": "face", "unlock_liveness": "challenge"}
        assert step_up["challenge_fresh"] is True  # the unlock passed the challenge just now
        assert step_up["data_dir"] == str(running.config.data_dir)


async def test_progress_reaches_status_as_seq_changes(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[*LOOK, match()]]) as running:
        started = call(running, "POST", "/guard/verify", body_for(("POST", "/guard/verify")))
        attempt, seq = started["attempt"], started["seq"]
        seen: list[tuple[int, str]] = []
        while True:
            payload = call(
                running, "GET", "/guard/status", since=str(seq), wait="5", attempt=attempt
            )
            record = payload["attempt"]
            assert record["id"] == attempt
            seq = payload["seq"]
            seen.append((record["seq"], record["step"]))
            if record["done"]:
                break
        assert [s for s, _ in seen] == sorted({s for s, _ in seen})  # seq grows every time
        steps = [step for _, step in seen]
        assert "look" in steps and "turn_left" in steps and steps[-1] == "done"
        assert payload["state"] == "unlocked" and payload["enrollment"] == "E1"
        assert record["ok"] is True and record["reason"] == "match"
        assert record["method"] == "face"


async def test_concurrent_unlocks_share_one_attempt(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[{"sleep": 0.5}, match()]]) as running:
        first, second = await asyncio.gather(
            running.guard.unlock(channel="tui", client_id="c1"),
            running.guard.unlock(channel="chat", client_id="c2"),
        )
        assert first == second == GuardVerdict(True, "match", "face")
        assert len(read_requests(running.script)) == 1  # one worker, one verdict


async def test_step_up_while_locked_never_starts_a_worker(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[match()]]) as running:
        assert await running.guard.step_up(REQUEST, client_id="c1") is False
        verdict = await running.guard.unlock(channel="tui", client_id="c1", kind="recheck")
        assert (verdict.ok, verdict.reason) == (False, "locked")
        assert read_requests(running.script) == []


async def test_a_failed_step_up_locks(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[match()], [NO_MATCH]]) as running:
        assert (await running.guard.unlock(channel="tui", client_id="c1")).ok
        assert await running.guard.step_up(REQUEST, client_id="c1") is False
        status = await running.guard.status()
        assert (status.state, status.lock_trigger, status.failures) == (
            "locked",
            "step_up_failed",
            1,
        )


async def test_step_up_queues_behind_a_running_check(tmp_path: Path) -> None:
    runs = [[match()], [{"sleep": 0.6}, PASSIVE], [match()]]
    with running_hub(tmp_path, runs=runs) as running:
        assert (await running.guard.unlock(channel="tui", client_id="c1")).ok
        recheck = asyncio.ensure_future(
            running.guard.unlock(channel="tui", client_id="c1", kind="recheck")
        )
        await until_async(lambda: len(read_requests(running.script)) == 2)
        steps: list[str] = []
        step_up = asyncio.ensure_future(
            running.guard.step_up(
                REQUEST, client_id="c2", on_progress=lambda p: steps.append(p.step)
            )
        )
        assert (await recheck).ok
        assert await step_up is True
        assert steps[0] == "starting"  # reported while it waited in the queue
        kinds = [r["request"]["kind"] for r in read_requests(running.script)]
        assert kinds == ["unlock", "recheck", "step_up"]


# -- cancel, lock, timeout, bad workers ----------------------------------------------------------


async def test_cancel_kills_the_worker(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[{"hang": True}]]) as running:
        task = asyncio.ensure_future(running.guard.unlock(channel="tui", client_id="c1"))
        pid = await worker_pid_async(running)
        task.cancel()  # HubGuard posts /guard/cancel and re-raises
        with pytest.raises(asyncio.CancelledError):
            await task
        await until_async(lambda: gone(pid), timeout=5)
        status = await running.guard.status()
        assert status.state == "locked" and status.attempt is None
        assert status.last_verdict == "cancelled"


async def test_hub_guard_cancel_by_client(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[{"hang": True}]]) as running:
        task = asyncio.ensure_future(running.guard.unlock(channel="tui", client_id="c1"))
        pid = await worker_pid_async(running)
        await running.guard.cancel(client_id="c1")
        verdict = await task
        assert (verdict.ok, verdict.reason) == (False, "cancelled")
        await until_async(lambda: gone(pid), timeout=5)


async def test_a_lock_during_verifying_kills_a_stubborn_worker(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[{"ignore_term": True}, {"hang": True}]]) as running:
        task = asyncio.ensure_future(running.guard.unlock(channel="tui", client_id="c1"))
        pid = await worker_pid_async(running)
        await asyncio.sleep(0.2)
        began = time.monotonic()
        await running.guard.lock(channel="telegram", client_id="t1", trigger="telegram")
        verdict = await task
        assert (verdict.ok, verdict.reason) == (False, "cancelled")
        await until_async(lambda: gone(pid), timeout=5)
        assert time.monotonic() - began >= 1.0  # SIGTERM was ignored: SIGKILL after 1 s
        status = await running.guard.status()
        assert (status.state, status.lock_trigger) == ("locked", "telegram")


async def test_a_timeout_kills_the_worker(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[{"hang": True}]], attempt_timeout=0.5) as running:
        verdict = await running.guard.unlock(channel="tui", client_id="c1")
        assert (verdict.ok, verdict.reason) == (False, "timeout")
        pid = worker_pid(running)
        await until_async(lambda: gone(pid), timeout=5)


@pytest.mark.parametrize(
    "run",
    [[{"raw": "{not json"}], [{"progress": "look"}, {"exit": 0}], [{"raw": '{"type": "x"}'}]],
    ids=["garbage", "no-verdict", "unknown-type"],
)
async def test_bad_worker_output_gives_error(tmp_path: Path, run: list[dict]) -> None:
    with running_hub(tmp_path, runs=[run]) as running:
        verdict = await running.guard.unlock(channel="tui", client_id="c1")
        assert (verdict.ok, verdict.reason) == (False, "error")
        assert (await running.guard.status()).state == "locked"


async def test_worker_stderr_lands_in_worker_log_only(
    tmp_path: Path, capfd: pytest.CaptureFixture
) -> None:
    with running_hub(tmp_path, runs=[[{"stderr": "AVFoundation chatter"}, match()]]) as running:
        assert (await running.guard.unlock(channel="tui", client_id="c1")).ok
        log = running.config.data_dir / "guard" / "worker.log"
        assert "AVFoundation chatter" in log.read_text()
    captured = capfd.readouterr()
    assert "AVFoundation chatter" not in captured.err + captured.out


# -- cooldown and reflex locks -------------------------------------------------------------------


async def test_cooldown_after_three_failures(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[NO_MATCH]]) as running:
        for _ in range(3):
            verdict = await running.guard.unlock(channel="tui", client_id="c1")
            assert (verdict.ok, verdict.reason) == (False, "no_match")
        verdict = await running.guard.unlock(channel="tui", client_id="c1")
        assert (verdict.ok, verdict.reason, verdict.retry_after) == (False, "cooldown", 30.0)
        assert (await running.guard.admit(TURN)).reason == "cooldown"
        with pytest.raises(HubError) as caught:
            call(running, "POST", "/guard/verify", body_for(("POST", "/guard/verify")))
        assert caught.value.status == 429
        assert caught.value.payload == {"reason": "cooldown", "retry_after": 30.0}
        assert len(read_requests(running.script)) == 3
        status = await running.guard.status()
        assert status.failures == 3 and status.cooldown_until is not None
        running.advance(30)
        running.script_runs([match()])
        assert (await running.guard.unlock(channel="tui", client_id="c1")).ok
        assert (await running.guard.status()).failures == 3  # shown on the next unlock


async def unlocked_hub(running: Running) -> None:
    assert (await running.guard.unlock(channel="tui", client_id="c1")).ok
    assert (await running.guard.admit(TURN)).allowed


async def test_idle_locks_inline_at_admission(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[match()]]) as running:
        await unlocked_hub(running)
        running.presence.idle_seconds = 600
        assert (await running.guard.admit(TURN)).reason == "locked"  # no tick needed
        assert (await running.guard.status()).lock_trigger == "idle"


async def test_screen_lock_locks(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[match()]]) as running:
        await unlocked_hub(running)
        running.presence.screen_locked = True
        running.service.tick()
        status = await running.guard.status()
        assert (status.state, status.lock_trigger) == ("locked", "screen_lock")


async def test_sleep_locks(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[match()]]) as running:
        await unlocked_hub(running)
        running.clock.sleep(3600)
        assert (await running.guard.admit(TURN)).reason == "locked"
        assert (await running.guard.status()).lock_trigger == "sleep"


async def test_max_age_locks(tmp_path: Path) -> None:
    config = guard_config(tmp_path, max_unlock_hours=1)
    with running_hub(tmp_path, config=config, runs=[[match()]]) as running:
        await unlocked_hub(running)
        running.advance(3598)
        assert (await running.guard.status()).state == "unlocked"
        running.advance(2)
        status = await running.guard.status()
        assert (status.state, status.lock_trigger) == ("locked", "max_age")


async def test_unknown_screen_caps_the_unlock(tmp_path: Path) -> None:
    presence = FakePresence(screen_locked=None)
    with running_hub(tmp_path, presence=presence, runs=[[match()]]) as running:
        await unlocked_hub(running)
        payload = call(running, "GET", "/guard/status")
        assert payload["screen"] == "unknown"
        status_block = json.load(urllib.request.urlopen(f"{running.api.url}/status"))["guard"]
        assert status_block["reason"] == "screen_unknown"
        running.advance(600)
        status = await running.guard.status()
        assert (status.state, status.lock_trigger) == ("locked", "max_age")


async def test_admission_refuses_when_the_reflex_loop_stalls(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[match()]]) as running:
        await unlocked_hub(running)
        running.clock.advance(7)  # no tick for 7 s
        assert (await running.guard.admit(TURN)).reason == "unavailable"
        running.service.tick()
        assert (await running.guard.admit(TURN)).allowed


async def test_the_real_reflex_loop_ticks(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[match()]], reflex_loop=True, reflex_interval=0.05) as r:
        await unlocked_hub(r)
        r.presence.screen_locked = True
        await until_async(
            lambda: r.service.machine is not None and r.service.machine.state == "locked"
        )
        assert (await r.guard.status()).lock_trigger == "screen_lock"


async def test_recheck_after_idle_since_the_face(tmp_path: Path) -> None:
    runs = [[match()], [PASSIVE], [NO_MATCH]]
    with running_hub(tmp_path, runs=runs) as running:
        await unlocked_hub(running)
        running.presence.idle_seconds = 180
        running.advance(180)
        assert (await running.guard.admit(TURN)).reason == "recheck"
        running.presence.idle_seconds = 0
        verdict = await running.guard.unlock(channel="tui", client_id="c1", kind="recheck")
        assert verdict == GuardVerdict(True, "match", "face")
        assert (await running.guard.admit(TURN)).allowed
        assert read_requests(running.script)[-1]["request"]["kind"] == "recheck"
        running.presence.idle_seconds = 200
        running.advance(200)
        assert (await running.guard.admit(TURN)).reason == "recheck"
        verdict = await running.guard.unlock(channel="tui", client_id="c1", kind="recheck")
        assert (verdict.ok, verdict.reason) == (False, "no_match")
        status = await running.guard.status()
        assert (status.state, status.lock_trigger) == ("locked", "step_up_failed")


async def test_recheck_after_presence_recheck_minutes(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[match()]]) as running:
        await unlocked_hub(running)
        running.advance(1798)
        assert (await running.guard.admit(TURN)).allowed
        running.advance(2)
        assert (await running.guard.admit(TURN)).reason == "recheck"


# -- the route contract --------------------------------------------------------------------------


FORBIDDEN = {
    "ok",
    "verdict",
    "result",
    "match",
    "matched",
    "reason",
    "method",
    "score",
    "liveness",
    "image",
    "frame",
    "frames",
    "photo",
    "embedding",
    "embeddings",
    "template",
    "vector",
    "face",
    "unlocked",
    "state",
    "allowed",
}


def test_every_route_is_listed_and_no_field_takes_a_verdict(tmp_path: Path) -> None:
    with running_hub(tmp_path) as running:
        registered = {key for key in running.api.routes if key[1].startswith("/guard/")}
        assert registered == set(SCHEMAS) == set(running.service.routes)
        for route, schema in SCHEMAS.items():
            for name, spec in schema.items():
                assert name not in FORBIDDEN, (route, name)
                assert spec.kind in ("text", "choice", "int", "number", "policy"), (route, name)
                assert spec.kind != "number" or name == "wait", (route, name)
        assert set(POLICY_FIELDS) == {"step_up", "unlock_liveness"}
        assert all(spec.kind == "choice" for spec in POLICY_FIELDS.values())


@pytest.mark.parametrize("route", [r for r in SCHEMAS if r[0] == "POST"], ids=lambda r: r[1])
def test_no_route_accepts_a_verdict_an_image_or_an_embedding(
    tmp_path: Path, route: tuple[str, str]
) -> None:
    with running_hub(tmp_path, runs=[[match()]]) as running:
        body = body_for(route)
        payloads: list[dict[str, Any]] = [{**body, key: True} for key in sorted(FORBIDDEN)]
        payloads += [{**body, "embedding": [0.1] * 128}, {**body, "image": "aGVsbG8="}]
        payloads += [{**body, name: [0.1, 0.2, 0.3]} for name in body]
        if route == ("POST", "/guard/verify"):
            payloads.append({**body, "policy": {"step_up": "face", "ok": True}})
            payloads.append({**body, "policy": {"step_up": "none", "score": 0.99}})
        for payload in payloads:
            with pytest.raises(HubError) as caught:
                call(running, *route, payload)
            assert caught.value.status == 400, payload
            assert caught.value.payload["reason"] == "error"
        with pytest.raises(HubError) as caught:
            running.client.get("/guard/status", timeout=10, query={"verdict": "match"})
        assert caught.value.status == 400
        assert read_requests(running.script) == []
        assert call(running, "GET", "/guard/status")["state"] == "locked"


def test_every_route_needs_the_token_and_answers_with_a_proof(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[match()]]) as running:
        for method, path in running.service.routes:
            data = json.dumps(body_for((method, path))).encode() if method == "POST" else None
            request = urllib.request.Request(
                f"{running.api.url}{path}",
                data=data,
                method=method,
                headers={"Content-Type": "application/json"},
            )
            with pytest.raises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=10)
            assert caught.value.code == 403, path
            # HubClient signs the request and refuses any answer without a valid proof
            try:
                answer = call(running, method, path, body_for((method, path)))
            except HubError as exc:
                assert exc.status not in (403, 500), (path, exc.status)
            else:
                assert isinstance(answer, dict), path


def test_refusals_are_never_403(tmp_path: Path) -> None:
    with running_hub(tmp_path) as running:
        body = {"channel": "tui", "client_id": "c1", "kind": "step_up", "request_id": "r1"}
        with pytest.raises(HubError) as caught:
            call(running, "POST", "/guard/verify", body)
        assert caught.value.status == 409 and caught.value.payload == {"reason": "locked"}


def test_enroll_is_a_stub_until_112(tmp_path: Path) -> None:
    runs = [[{"verdict": {"ok": False, "reason": "not_enrolled"}}]]
    with running_hub(tmp_path, runs=runs) as running:
        started = call(running, "POST", "/guard/enroll", {"client_id": "c1"})
        until(
            lambda: (
                (
                    call(running, "GET", "/guard/status", attempt=started["attempt"])["attempt"]
                    or {}
                ).get("done")
                is True
            )
        )
        record = call(running, "GET", "/guard/status", attempt=started["attempt"])["attempt"]
        assert (record["kind"], record["ok"], record["reason"]) == ("enroll", False, "not_enrolled")
        assert read_requests(running.script)[0]["op"] == "enroll"


def test_status_attempt_records(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[NO_MATCH]]) as running:
        started = call(running, "POST", "/guard/verify", body_for(("POST", "/guard/verify")))
        until(
            lambda: call(running, "GET", "/guard/status", attempt=started["attempt"])["attempt"][
                "done"
            ]
        )
        payload = call(running, "GET", "/guard/status", attempt=started["attempt"])
        assert payload["attempt"]["reason"] == "no_match"
        assert call(running, "GET", "/guard/status")["attempt"] is None  # nothing running
        running.advance(61)
        assert call(running, "GET", "/guard/status", attempt=started["attempt"])["attempt"]
        running.advance(60)
        assert call(running, "GET", "/guard/status", attempt=started["attempt"])["attempt"] is None
        assert call(running, "GET", "/guard/status", attempt="nope")["attempt"] is None


def test_status_long_poll_waits_for_a_change(tmp_path: Path) -> None:
    with running_hub(tmp_path) as running:
        seq = call(running, "GET", "/guard/status")["seq"]
        began = time.monotonic()
        payload = call(running, "GET", "/guard/status", since=str(seq), wait="0.3")
        assert payload["seq"] == seq and time.monotonic() - began >= 0.25
        payload = call(running, "GET", "/guard/status", since=str(seq - 1), wait="5")
        assert time.monotonic() - began < 2
        # a seq from a hub that ran before this one is answered at once, not after the wait
        began = time.monotonic()
        payload = call(running, "GET", "/guard/status", since=str(seq + 500), wait="5")
        assert payload["seq"] == seq and time.monotonic() - began < 2


def test_open_status_carries_only_the_guard_block(tmp_path: Path) -> None:
    with running_hub(tmp_path) as running:
        status = json.load(urllib.request.urlopen(f"{running.api.url}/status", timeout=10))
        assert status["guard"] == {
            "state": "locked",
            "enrolled": True,
            "available": True,
            "reason": None,
        }


def test_active_but_broken_hub_reports_unavailable(tmp_path: Path) -> None:
    config = guard_config(tmp_path, idle_lock_minutes=500)
    with running_hub(tmp_path, config=config) as running:
        status = json.load(urllib.request.urlopen(f"{running.api.url}/status", timeout=10))
        assert status["guard"] == {
            "state": "unavailable",
            "enrolled": True,
            "available": False,
            "reason": "config",
        }
        assert call(running, "POST", "/guard/admit", body_for(("POST", "/guard/admit")))[
            "reason"
        ] == ("unavailable")


# -- hub lifecycle -------------------------------------------------------------------------------


async def test_find_service_gives_the_in_hub_guard(tmp_path: Path) -> None:
    with running_hub(tmp_path) as running:
        found = running.hub.find_service("guard")
        assert found is running.service and isinstance(found, Guard)


async def test_a_restart_comes_back_locked(tmp_path: Path) -> None:
    config = guard_config(tmp_path)
    with running_hub(tmp_path, config=config, runs=[[match()]]) as running:
        await unlocked_hub(running)
    with running_hub(tmp_path, config=config) as running:
        status = await running.guard.status()
        assert (status.state, status.lock_trigger) == ("locked", "startup")
        assert (await running.guard.admit(TURN)).reason == "locked"


async def test_stopping_the_hub_kills_a_running_worker(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[{"ignore_term": True}, {"hang": True}]]) as running:
        task = asyncio.ensure_future(running.guard.unlock(channel="tui", client_id="c1"))
        pid = await worker_pid_async(running)
        await asyncio.sleep(0.2)
        began = time.monotonic()
        running.stop()
        assert not running.thread.is_alive()
        assert time.monotonic() - began < 5  # well within `tau hub stop`'s 15 s
        assert gone(pid)
        verdict = await task
        assert not verdict.ok
    audit = (tmp_path / "data" / "guard" / "audit.jsonl").read_text().splitlines()
    assert json.loads(audit[-1])["trigger"] == "hub_stop"


# -- verification fixes ----------------------------------------------------------------------------


async def test_hub_guard_step_up_after_a_sleep_fails(tmp_path: Path) -> None:
    runs = [[match()], [{"sleep": 0.4}, match()]]
    with running_hub(tmp_path, runs=runs) as running:
        await unlocked_hub(running)
        step_up = asyncio.ensure_future(running.guard.step_up(REQUEST, client_id="c1"))
        await until_async(lambda: len(read_requests(running.script)) == 2)
        running.clock.sleep(120)  # the Mac slept while the check ran; no reflex tick since
        assert await step_up is False
        status = await running.guard.status()
        assert (status.state, status.lock_trigger) == ("locked", "sleep")


async def test_reading_an_attempt_runs_the_reflexes_first(tmp_path: Path) -> None:
    with running_hub(tmp_path, runs=[[match()]]) as running:
        await unlocked_hub(running)
        running.script_runs([match()])
        body = {**body_for(("POST", "/guard/verify")), "kind": "step_up"}
        attempt = call(running, "POST", "/guard/verify", body)["attempt"]
        machine = running.service.machine
        assert machine is not None
        until(lambda: (machine.record(attempt) or {}).get("done") is True)
        running.presence.screen_locked = True  # after the verdict, before any tick
        payload = call(running, "GET", "/guard/status", attempt=attempt)
        assert payload["attempt"]["ok"] is True  # the record is what the worker said, but
        assert (payload["state"], payload["lock_trigger"]) == ("locked", "screen_lock")
