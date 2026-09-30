# 110 · Guard seams in tau-core: `HubGuard`, admission, tier-2 step-up and lock checks, protected control routes with a response proof

Status: done
Type: AFK
Layer: L10 · Guard
Packages: tau-core, tau-net
Blocked by: none

## What to build

tau-core gets everything a guarded channel needs, without importing a camera library:

- the `Guard` protocol and its value types, a fail-closed `LockedGuard`, and a `HubGuard` that talks to the hub's `/guard/*` routes;
- turn admission in `TauAgent.stream`, with the new stop reason `locked`;
- a lock check and a tier-2 step-up in `TierGate`;
- a control API whose routes are protected by default and whose answers carry a proof;
- `FakeGuard` for tests.

An install without a guard does not change: `resolve_guard` returns `None`, and every existing test keeps passing. The decisions are in [ADR 0008](../../docs/adr/0008-owner-guard.md) (decisions 3–8 and 17). The guard service is 111; the lock screens and `/guard` in the channels are 113. Keep each diff to an existing tau-core file small, additive and in its own block: other sessions edit `agent.py`, `builder.py`, `status.py` and `i18n.py`.

### `tau_core/guard.py` (new, exported from `tau_core`)

```python
GuardState = Literal["off", "locked", "verifying", "unlocked", "unavailable"]

VERDICT_REASONS = ("match", "no_match", "no_face", "multiple_faces", "spoof", "timeout", "cancelled",
    "too_dark", "face_too_small", "camera_busy", "camera_unavailable", "camera_denied",
    "permission_pending", "not_enrolled", "template_invalid", "model_changed", "key_unavailable",
    "cooldown", "locked", "touch_id_unavailable", "touch_id_failed", "unsupported_platform",
    "unavailable", "busy", "error")
ADMISSION_REASONS = ("ok", "locked", "recheck", "not_enrolled", "cooldown", "unavailable",
    "unsupported_platform", "error")
LOCK_TRIGGERS = ("command", "idle", "screen_lock", "sleep", "max_age", "hub_stop", "telegram",
    "step_up_failed", "startup")
PROGRESS_STEPS = ("starting", "look", "turn_left", "turn_right", "center", "touch_id", "done")
ALLOWED_WHILE_LOCKED = frozenset({"help", "lang", "quit", "guard"})

@dataclass(frozen=True)
class GuardProgress:
    step: str                      # PROGRESS_STEPS
    seq: int                       # grows with every change of the attempt
    deadline: datetime | None      # UTC; when the current step times out
    hint: str | None = None        # a VERDICT_REASONS value used as a live hint ("too_dark")

@dataclass(frozen=True)
class GuardVerdict:
    ok: bool
    reason: str                    # VERDICT_REASONS
    method: str | None = None      # "face" | "touch_id"
    retry_after: float | None = None   # seconds, with "cooldown"

@dataclass(frozen=True)
class GuardTurn:
    channel: str
    session_id: str | None
    client_id: str                 # secrets.token_hex(8) per process; an audit label, never a claim

@dataclass(frozen=True)
class Admission:
    allowed: bool
    reason: str = "ok"             # ADMISSION_REASONS; an unknown value is treated as "error"

@dataclass(frozen=True)
class GuardStatus:
    state: GuardState
    enrolled: bool = False
    method: str | None = None
    since: datetime | None = None
    expires_at: datetime | None = None
    face_seen_at: datetime | None = None
    seq: int = 0
    attempt: GuardProgress | None = None   # while verifying
    last_verdict: str | None = None
    lock_trigger: str | None = None        # LOCK_TRIGGERS
    failures: int = 0                      # failed attempts since the last unlock
    cooldown_until: datetime | None = None
    camera: str | None = None              # "ok" | "denied" | "not_determined" | "unavailable"
    reason: str | None = None              # why "unavailable"

@runtime_checkable
class Guard(Protocol):
    name: str
    async def status(self) -> GuardStatus: ...
    async def watch(self, since: int, *, wait: float = 25.0) -> GuardStatus: ...
    async def admit(self, turn: GuardTurn) -> Admission: ...
    async def unlock(self, *, channel: str, client_id: str, kind: str = "unlock",
                     on_progress: Callable[[GuardProgress], None] | None = None) -> GuardVerdict: ...
    async def cancel(self, *, client_id: str) -> None: ...
    async def lock(self, *, channel: str, client_id: str, trigger: str = "command") -> None: ...
    async def step_up(self, request: ApprovalRequest, *, client_id: str,
                      on_progress: Callable[[GuardProgress], None] | None = None) -> bool: ...
```

`kind` is `"unlock"` (the full policy) or `"recheck"` (a passive quick check). Every method fails closed: `admit` refuses, `step_up` returns `False`, and `unlock` returns `GuardVerdict(False, "error" | "unavailable")`. None of them raises into its caller except `asyncio.CancelledError`. `GuardLocked(reason)` is the exception `TauAgent.ask()` raises.

- **`LockedGuard(reason)`.** `status` is `unavailable` with that reason. `admit` refuses with it, `unlock` returns a verdict with it and `step_up` returns `False`. `lock` and `cancel` do nothing.
- **`HubGuard(config)`** implements `Guard` over `HubClient`.
  - **Strict mapping.** Only an answer that says `unlocked` (or `allowed: true` from `/guard/admit`), with a valid proof and an `enrollment` id equal to the local marker's, admits. Everything else refuses with `unavailable`: `off`, 404, 403 after one token re-read, 5xx, a timeout, bad JSON, a missing proof or an enrollment mismatch.
  - **`admit`** has its own 3 s bound (`asyncio.wait_for`).
  - **Threads.** All blocking HTTP runs in daemon threads, never in `asyncio.to_thread`, which is joined at shutdown.
  - **`unlock` and `step_up`** post `/guard/verify`, then long-poll `GET /guard/status?since=<seq>` until the attempt is done, calling `on_progress` on every change of `seq`. On `asyncio.CancelledError` they post `/guard/cancel`, then re-raise.
  - **Policy.** The request carries the client's own weakening-sensitive policy (`[component.guard]` `step_up`, `unlock_liveness`), and the hub applies the stricter of the two.
- **`resolve_guard(config) -> Guard | None`** is memoized per `(config.home, config.data_dir)`:
  - `None` when neither the marker nor `enabled = true` is present;
  - `LockedGuard` for a non-bool `enabled`, an unknown key in `[component.guard]` or any platform but darwin (`unsupported_platform`);
  - otherwise `HubGuard(config)`, even when `enabled = false`, as long as the marker exists.
- **`ENROLLED_MARKER = "guard/enrolled"`**, relative to `data_dir`, holds JSON `{"v": 1, "enrollment": "<id>", "model": "<sha256>", "created": "<iso>"}`. tau-guard writes it; tau-core only reads it.
- **Helpers.** `guard_status_line(status, language) -> str` feeds `/status`. `guard_doctor_check(config, hub_status) -> Check` feeds `tau doctor`: one hook line in `run_doctor`, which 107 may later move to a public hook. It covers the guard being off or active, the `LockedGuard` reason, a missing or `off` guard block in the hub's `/status` while active, and a pinned `[components.hub] services` without `guard`.
- **Messages.** `GUARD_MESSAGES`, registered with `register_messages` at import with a collision assert against `MESSAGES`, the way `tau_tui/strings.py` does it; `i18n.py` stays untouched. Keys, each in `en` and `tr`:
  - `guard.refused.<reason>` for every admission reason;
  - `guard.state.<state>`;
  - `guard.verdict.<reason>` for every verdict reason;
  - `guard.progress.<step>` for every progress step;
  - `guard.lock_trigger.<trigger>` for every lock trigger;
  - `guard.step_up.start|passed|failed`, `guard.locked_during_turn`, `guard.unlocked` (`{method}`, `{failures}`), `guard.start_hub` (TauBar → Run the hub, or `tau hub run`), `guard.not_enrolled_hint`;
  - `status.guard` and `doctor.guard.*`.
- **Fixed English texts the model reads:** the step-up refusal "The guard could not confirm the user's identity." and the locked-approval note "tau was locked before the user answered."

### Admission in `TauAgent`

- **New fields** after `role`: `channel: str = "terminal"`, `guard: Guard | None = None`, and `client_id: str`, which defaults to `secrets.token_hex(8)` and can be overridden.
- **`build_agent`** gains `guard: Guard | None | object = DISCOVER` and `client_id: str | None = None` as its last kwargs. `DISCOVER` calls `resolve_guard(config)`, and channels that own a guard pass it explicitly on every build.
- **Admission** happens in `stream()`, inside `async with self._stream_lock()` and before it delegates to `_stream_locked`. Leave `_stream_locked` untouched. A helper `_refuse(reason)`:
  - emits the agent event `guard {"action": "refused", "channel", "reason"}`;
  - yields `Notice(t("guard.refused.<reason>"))`, with an unknown reason shown as `error`;
  - yields `TurnEnd("locked")`.

  Nothing is appended to history. There is no model call and no repair turn. A guard whose `admit` raises also refuses, with `error`.
- **Stop reason.** `STOP_REASONS += ("locked",)`. Update the `TurnEnd` docstring bullet (a test asserts it), `test_stream_contract.py` and the stop-reason table in the tau-core README.
- **`TauAgent.ask()`** raises `GuardLocked(reason)` when the turn is refused.
- **Compaction.** `compaction.summarize` builds its summarizer with the Strands `Agent`, not with `build_agent`, so it would bypass admission. It asks the agent's guard to admit first, and raises `GuardLocked` when refused.
- **In-hub channels opt out.** `TelegramService._build` (`tau_core/channels/telegram.py`) and tau-net network turns (`tau_net/turns.py`, `channel="net"`) pass `guard=None`. A repo-rule test fails when `guard=None` appears in any `packages/*/src` file outside this allowlist. No CLI flag, environment variable or config key may select a channel.

### Lock check and step-up in `TierGate`

- `TierGate(..., guard: Guard | None = None, client_id: str = "")`. A repo-rule test asserts that every `TierGate(` call in `packages/*/src` passes `guard=` explicitly. `build_agent` passes the agent's guard and client id.
- In `check`, when `guard` is set:
  1. **Before a tier-1 or tier-2 call**, `await guard.admit(...)` runs. A refusal refuses the call with the locked note, without an approver prompt, and the `tool_call` event records approval `"locked"`.
  2. **For tier-2 only**, after `_ask` returned `APPROVED` and still inside the approval lock, `ok = await guard.step_up(request, client_id=..., on_progress=cb)` runs.
     - `cb` emits `guard {"action": "challenge", "step", "hint", "deadline", "request_id"}` on the bus.
     - Before and after, the gate emits `guard {"action": "step_up", "phase": "start" | "end", "ok"?, "request_id", "tool"}`.
     - Anything but `True` becomes `REJECTED` with the refusal note, and the approval event gains `"step_up": "passed" | "failed"`.
     - On `CancelledError`, the gate records `failed` and re-raises.
  3. **Exempt calls** reach neither check.
- The step-up can only turn `APPROVED` into `REJECTED`. No path produces `APPROVED` from it.

### Control API: protected routes, token, proof

- **Protected by default.** `ControlApi.add_route(method, path, handler, *, open: bool = False)`; `/health` and `/status` are registered `open=True`. The HTTP request handler enforces the protection before dispatch, so unit tests that call `api.handle(ControlRequest(...))` keep working. It refuses a protected request with 403 JSON when:
  - the token file is empty or missing;
  - `X-Tau-Nonce` is missing, or `X-Tau-Auth` does not equal `hex(HMAC-SHA256(token, "req" | nonce | method | path))` (`hmac.compare_digest`); the raw token is never sent or accepted in a header;
  - an `Origin` header is present;
  - a POST's parsed media type is not `application/json` (parameters allowed).
- **Token.** `start()` writes the token after it holds the hub lock: `hub_dir/control.token`, 32 random bytes, urlsafe. The file is created with `O_CREAT|O_EXCL` (or mkstemp plus rename) at mode 0600, and `hub_dir` is chmod 0700 explicitly. On stop, the hub deletes the file only if it still holds this hub's token.
- **Response proof.** A protected answer carries `X-Tau-Proof = hex(HMAC-SHA256(token, "resp" | nonce | method | path | status | body))`; the `req` and `resp` domains never overlap.
- **`HubClient(config)`**, in `tau_core/hub/client.py` and exported from `tau_core.hub`, offers `get(path, *, timeout, query=None)` and `post(path, body, *, timeout)`.
  - It is loopback only, ignores proxies (`ProxyHandler({})`) and refuses redirects.
  - It reads the token file on every request and retries once after a 403.
  - It signs every protected request (nonce and `X-Tau-Auth`) and verifies the proof.
  - It raises `HubUnavailable` (no hub, bad proof) or `HubError(status, payload)`.
- **`GET /spend` becomes protected.** Update its test and any other caller.
- **Log permissions.** If it is a one-line change, `hub/logs` becomes 0700 and new log files 0600; otherwise leave it to 111.

### Testing helper

Append `FakeGuard(state="locked", verdicts=(), step_ups=(), progress=(), admissions=None)` at the end of `tau_core/testing.py`.
- It records `calls`, and `admit` follows `state` (or a scripted sequence).
- `unlock` pops a verdict (default `GuardVerdict(False, "no_match")`) and replays the scripted `progress` through `on_progress`.
- `step_up` pops a boolean, and returns `False` once the script is exhausted.
- `set_state(...)` flips the state and bumps `seq` for `watch`.

It never approves anything.

## Acceptance criteria

- [x] `tau_core` exports `Guard`, `GuardStatus`, `GuardVerdict`, `GuardProgress`, `GuardTurn`, `Admission`, `GuardLocked`, `LockedGuard`, `HubGuard`, `resolve_guard` and the reason lists exactly as above; `tau_core.hub` exports `HubClient`, `HubUnavailable` and `HubError`
- [x] The guard never yields `APPROVED`: a parametrized test over approver decisions × step-up results (`True`, `False`, a non-bool truthy value, raising, `CancelledError`) × admissions shows the gate approves only when the approver said `APPROVED` and `step_up` returned exactly `True`; `step_up` is never called for tier 0/1, exempt calls or non-approved decisions
- [x] A refused turn appends nothing to the history or the session store, makes no model call (`FakeModel` records no call), yields a `Notice` and `TurnEnd("locked")` and emits one `guard` agent event; the next admitted turn needs no repair turn
- [x] An unknown admission reason is shown as `error` (no `KeyError`); a guard whose `admit` raises refuses with `error`
- [x] `STOP_REASONS` contains `locked`; the `TurnEnd` docstring, `test_stream_contract.py` and the README stop-reason table agree
- [x] `TauAgent.ask()` raises `GuardLocked`; `compaction.summarize` raises `GuardLocked` before any model call when the guard refuses
- [x] With a guard that refuses, a tier-1 or tier-2 call is refused without an approver prompt and its `tool_call` event says `locked`; a failed step-up records `step_up: failed` and returns the fixed refusal note to the model
- [x] Against a real `ControlApi` on port 0, a protected route answers 403 on a missing or empty token file, a missing nonce, a missing or wrong `X-Tau-Auth` (including a raw token), any `Origin` header and a `text/plain` POST; `application/json; charset=utf-8` is accepted; `/health` and `/status` answer without a token; `GET /spend` needs it
- [x] The token file is created only after the hub lock is held, with mode 0600, and `hub_dir` is 0700; a second hub that loses the lock race leaves the live token alone; stop removes the file only when it still holds its own token
- [x] A protected answer without a valid proof is `unavailable`: a fake listener on port 0 that answers `{"state": "unlocked"}` without a proof makes `HubGuard.admit` refuse
- [x] `HubGuard` refuses (`unavailable`) on `off`, 404, 403 twice, 5xx, a timeout, bad JSON, a missing proof and an enrollment mismatch (parametrized against a fake hub), and admits only `unlocked` with a proof and the matching enrollment
- [x] Cancelling a `HubGuard.unlock` task posts `/guard/cancel` and re-raises; `on_progress` is called once per `seq` change
- [x] `resolve_guard` returns `None` with neither marker nor `enabled = true`; `LockedGuard` for `enabled = "true"`, `enabled = 1`, an unknown key such as `enable = true` and a non-darwin platform; `HubGuard` with only the marker, including when `enabled = false`; the same object for the same `(home, data_dir)`
- [x] Repo-rule tests: `guard=None` appears in `packages/*/src` only in `tau_core/channels/telegram.py` and `tau_net/turns.py`; every `TierGate(` call in `packages/*/src` passes `guard=`
- [x] With the marker present, Telegram turns and network turns still run (they build with `guard=None`)
- [x] Every verdict reason, admission reason, progress step and lock trigger has `en` and `tr` messages (test); `GUARD_MESSAGES` does not collide with `MESSAGES`; `i18n.py` is unchanged
- [x] `FakeGuard` replays scripted progress, never approves, and `test_no_auto_approve` still passes
- [x] `tau doctor` shows the guard check, and `/status` shows the guard line only when a guard is active
- [x] With no guard configured the whole suite passes unchanged; `uv run pytest -q`, `ruff check` and `ruff format --check` are green

## Blocked by

None - can start immediately.

## Comments

- 2026-09-30: filed with ADR 0008.
- 2026-09-30: done on `feat/guard` (commits 2546b78, 1d753c3, da844cf, 785f557, 5602b80, 83b229e, 5787f69). `tau_core.guard` holds the protocol, `LockedGuard`, `HubGuard`, `resolve_guard`, `admit_turn` and the messages; `tau_core.hub.client.HubClient` calls protected routes; `ControlApi` writes `hub_dir/control.token` in `start()` before the port opens and signs protected answers. Notes for the next issues:
  - **Route contract details for 111.** `GET /guard/status` returns `attempt` as `{id, kind, step, seq, deadline, hint, done, ok, reason, method, retry_after}`; `HubGuard` follows the attempt by `id` (from the `202 {attempt, seq}` of `/guard/verify`), reports progress once per `attempt.seq`, and accepts a result only with `ok: true`, `reason: "match"`, `state: "unlocked"` and the local enrollment. A refused `/guard/verify` may answer 4xx with `{reason, retry_after}` (for example `cooldown`). An admit answer with `state: "off"` refuses. `GUARD_CONFIG_KEYS` lists the `[component.guard]` keys through 114; an issue that adds a knob adds it there, or the guard locks for good.
  - **The refused turn's `guard` event** is recorded in the session's event log like every agent event (no prompt text); no message, title or repair is written.
  - **`summarize`** raises `CompactionLocked`, a `CompactionError` and a `GuardLocked`, so the channels' existing `/compact` error paths report it.
  - **`HubUnavailable.reason`** (`no_hub`, `timeout`, `bad_proof`, `bad_response`) becomes `GuardStatus.reason`; `guard_status_line` turns `no_hub` into the start-the-hub hint. `HubGuard.watch` waits up to 2 s before returning an `unavailable` status, so a watcher never spins.
  - **Doctor** lines stay English like the rest of `tau doctor`; `guard_doctor_check(..., language=)` can localize them later.
  - Only the `hub/logs` directory mode (0700) changed here; 0600 log files are left to 111.
  - The suite's only failure is the pre-existing `test_no_personal_paths_in_tracked_files` (issue 130).
