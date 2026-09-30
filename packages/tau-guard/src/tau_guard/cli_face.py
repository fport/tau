"""``tau guard setup | enroll | verify | forget | doctor`` (issue 112), registered on the
``tau guard`` group by :mod:`tau_guard.cli`.

- **Where the work runs.** When a hub with an active guard runs, ``enroll`` and ``verify`` go
  through it (``POST /guard/enroll``, and ``HubGuard.unlock`` for ``verify``): the same worker
  and one camera permission, and the macOS prompt on the Mac's screen. Otherwise, and always for
  ``verify --explain``, ``forget`` and the doctor's self-test, the CLI runs a local worker
  (:func:`tau_guard.local.run_local`; the camera permission is then the terminal's). A local
  ``verify`` unlocks nothing. Local runs are written to ``guard/audit.jsonl`` too.
- **Refusals.** ``setup``, ``enroll`` and ``forget`` refuse on any platform but macOS and when
  ``SSH_CONNECTION`` is set (the prompt and the camera are at the Mac).
- **setup**: the platform, the model (download with its sha256 checked, or ``--model-file``),
  the enrollment, one verification, then ``[component.guard] enabled = true`` through
  ``tau_core.settings``, the restart hint and the remote-use note. On a first setup the hub's
  guard is not active yet (no marker, ``enabled`` not written), so the enrollment and the check
  run in a local worker under the terminal's camera permission even while a hub runs; setup
  then says that the app running the hub asks for its own camera permission on the first
  unlock.
- **forget**: behind LocalAuthentication in the worker, it removes the template, the marker and
  the Keychain key, and writes ``enabled = false`` when ``enabled = true`` was set, so the guard
  is off afterwards (ADR 0008 decision 4: forget is the off switch). When only the key could
  not be removed, the guard is still off (the marker is gone and ``enabled = false`` is
  written), and the command says so and exits 1.
- **verify --explain** prints each prompt as a highlighted line when it appears
  (``>>> TURN YOUR HEAD LEFT <<<``) and the numbers of every 3rd frame (``--explain=all``: every
  frame): the prompt on screen, head yaw, the turn from the frontal baseline and pitch in
  degrees, the landmarks' fit error, eye distance, detector score, brightness, sharpness and
  similarity. No frame is saved anywhere. A local check that fails its head-turn challenge
  names the liveness rule that failed.
  The guard window shows as well (the owner sees the picture the numbers belong to);
  ``--no-window`` turns it off.
- **The guard window** (issue 126): a check this command runs in a local worker shows the
  window when ``[component.guard] window`` is true (the default) and ``--no-window`` is not
  given; the worker falls back to the terminal lines without a GUI session. A check through the
  hub follows the hub's own setting (``--no-window`` then only prints a note). Esc in the
  window cancels the check (``cancelled``).
- **doctor** reports the platform, OpenCV's camera order, both models with their pinned sha256
  (and the enrolled and expected SFace sha after a model change), the enrollment,
  whether the template decrypts (and whether its head-turn calibration was measured in degrees
  or is the default of an enrollment from before issue 127), the Keychain key, the modes, the
  camera device, the camera permission of this terminal and the hub's last camera answer
  (naming the app each runs under), Touch ID (issue 114: available or why not, the lid, and
  whether the fingerprints are the ones pinned at enrollment; ``step_up = "none"`` and a Touch
  ID fallback on a Mac without Touch ID are warnings) and the failures of the last 24 h.
- **Touch ID** (issue 114) authorises re-enrollment and ``forget`` when the Mac has it (Touch
  ID only, with the pinned fingerprints); a first enrollment and a Mac without Touch ID take
  the device-owner prompt (Touch ID or the password). A refusal says why and what to do.

Interactive lines go through ``tau_core.i18n`` (``guard.cli.*``, ``guard.progress.*``,
``guard.verdict.*``); help texts and doctor check names stay English. Tests pass fakes through
the click context object: ``guard_client``, ``guard_worker`` (a runner like
:func:`~tau_guard.local.run_local`), ``guard_install``, ``platform`` and ``guard_app``.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

import click
from tau_core import Config, t
from tau_core.cli import help_option
from tau_core.guard import (
    PROGRESS_STEPS,
    VERDICT_REASONS,
    HubGuard,
    client_policy,
    process_client_id,
    read_enrollment,
)
from tau_core.hub import HubError, HubUnavailable
from tau_core.settings import load_document, save_document

from tau_guard.audit import AuditLog
from tau_guard.config import SettingsError, parse_settings
from tau_guard.engine import (
    SFACE_SHA256,
    YUNET_SHA256,
    ModelChecksumError,
    ModelError,
    install_sface,
    model_state,
    sface_path,
)
from tau_guard.liveness import FAILURES
from tau_guard.local import LocalWorkerError, run_local
from tau_guard.state import COUNTED_REASONS
from tau_guard.store import MARKER_FILE
from tau_guard.window import window_field

__all__ = ["register", "responsible_app"]

CLI_CHANNEL = "cli"
REQUEST_TIMEOUT = 5.0
LONG_POLL = 25.0
ENROLL_WAIT = 150.0
"""How long the CLI follows an enrollment (LocalAuthentication plus the capture)."""
VERIFY_WAIT = 60.0
SELFTEST_WAIT = 30.0
FORGET_WAIT = 90.0
DOCTOR_WINDOW = timedelta(hours=24)
CHECK_EVENTS = ("verify", "step_up", "recheck")
PROMPTS = ("look", "turn_left", "turn_right", "center")
"""The steps ``verify --explain`` highlights (and tags every frame line with)."""
EXPLAIN_EVERY = 3
"""``verify --explain`` prints every 3rd frame (``--explain=all``: every frame)."""


# -- plumbing ------------------------------------------------------------------------------------


def _obj(ctx: click.Context) -> dict[str, Any]:
    return ctx.find_object(dict) or {}


def _config(ctx: click.Context) -> Config:
    from tau_guard.cli import _config as load

    return load(ctx)


def _client(ctx: click.Context, config: Config) -> Any:
    from tau_guard.cli import _client as client

    return client(ctx, config)


def _platform(ctx: click.Context) -> str:
    return str(_obj(ctx).get("platform") or sys.platform)


def _guard_dir(config: Config) -> Path:
    return config.data_dir / "guard"


def _runner(ctx: click.Context, config: Config) -> Callable[..., dict[str, Any]]:
    runner = _obj(ctx).get("guard_worker")
    return runner or partial(run_local, _guard_dir(config))


def _settings(ctx: click.Context, config: Config) -> Any:
    try:
        return parse_settings(config.component("guard"))
    except SettingsError as exc:
        for problem in exc.problems:
            click.echo(f"[component.guard] {problem}", err=True)
        ctx.exit(2)


def _request(
    ctx: click.Context,
    config: Config,
    op: str,
    kind: str,
    *,
    window: str | None = None,
    **extra: Any,
) -> dict:
    """A worker request; ``window`` names the window's purpose (``enroll``, ``check``) when
    ``[component.guard] window`` allows it and the command did not say ``--no-window``."""
    settings = _settings(ctx, config)
    request = {
        "v": 1,
        "op": op,
        "kind": kind,
        "attempt": secrets.token_hex(8),
        "data_dir": str(config.data_dir),
        "policy": client_policy(config.component("guard")),
        "settings": settings.worker(),
        "challenge_fresh": False,
        **extra,
    }
    if window is not None and settings.window:
        request["window"] = window_field(config.ui.language, window)
    return request


def _hub_window_note(window: bool, language: str) -> None:
    """``--no-window`` with a check that runs in the hub: say who decides."""
    if not window:
        click.echo(t("guard.cli.window.through_hub", language))


def _refuse_elsewhere(ctx: click.Context, language: str) -> None:
    if _platform(ctx) != "darwin":
        click.echo(t("guard.cli.unsupported", language), err=True)
        ctx.exit(2)
    if os.environ.get("SSH_CONNECTION"):
        click.echo(t("guard.cli.ssh_refused", language), err=True)
        ctx.exit(2)


def _reason_text(reason: object, language: str, *, enroll: bool = False) -> str:
    key = reason if isinstance(reason, str) and reason in VERDICT_REASONS else "error"
    if enroll and key in ("timeout", "no_match"):
        return t(f"guard.cli.enroll.reason.{key}", language)
    return t(f"guard.verdict.{key}", language)


def _touch_id_hint(reason: object, language: str) -> None:
    """What to do after Touch ID refused an enrollment or ``forget``."""
    if reason in ("touch_id_failed", "touch_id_unavailable"):
        click.echo(t(f"guard.cli.touch_id.{reason}", language), err=True)


class _Printer:
    """Prints each new progress step (and its live hint) once; ``labels`` replaces a step's
    text (an enrollment's ``touch_id`` step is the device-owner prompt: Touch ID or the
    password). With ``highlight`` (``verify --explain``) a new prompt gets a line of its own
    (``>>> TURN YOUR HEAD LEFT <<<``), so it stands out among the frame lines; :attr:`step`
    is the prompt on screen."""

    def __init__(
        self, language: str, labels: dict[str, str] | None = None, *, highlight: bool = False
    ) -> None:
        self.language = language
        self.labels = labels or {}
        self.highlight = highlight
        self.last: tuple[str, str | None] | None = None
        self.step: str | None = None

    def __call__(self, step: str, hint: str | None) -> None:
        if step not in PROGRESS_STEPS or step in ("starting", "done"):
            return
        if (step, hint) == self.last:
            return
        new_step = self.last is None or self.last[0] != step
        self.last = (step, hint)
        self.step = step
        text = t(self.labels.get(step, f"guard.progress.{step}"), self.language)
        if self.highlight and new_step and step in PROMPTS:
            click.echo(t(f"guard.cli.verify.prompt.{step}", self.language))
            if hint not in VERDICT_REASONS:
                return
        if hint in VERDICT_REASONS:
            text = f"{text} {t(f'guard.verdict.{hint}', self.language)}"
        click.echo(f"  > {text}")

    def progress(self, progress: Any) -> None:
        self(progress.step, progress.hint)


def _hub_active(ctx: click.Context, config: Config, language: str) -> bool:
    """Whether a hub with an active guard runs (then enroll and verify go through it). No hub
    or a hub whose guard is off (404) → ``False``; any other bad answer ends the command."""
    try:
        _client(ctx, config).get("/guard/status", timeout=REQUEST_TIMEOUT)
    except HubUnavailable as exc:
        if exc.reason == "no_hub":
            return False
        click.echo(t("guard.cli.hub_error", language, error=exc.reason), err=True)
        ctx.exit(1)
    except HubError as exc:
        if exc.status == 404:
            return False
        click.echo(t("guard.cli.hub_error", language, error=exc.status), err=True)
        ctx.exit(1)
    return True


def _audit_local(config: Config, event: str, answer: dict[str, Any], started: float) -> None:
    """The audit records of a local run: ``camera_open``, ``touch_id`` and the event itself.
    A check's record names its method (a local check is the face check) and, for a
    ``spoof``, the liveness rule that failed, like the hub's records."""
    log = AuditLog(_guard_dir(config))
    camera_ms = answer.get("camera_ms")
    common = {"channel": CLI_CHANNEL, "client_id": process_client_id()}
    if isinstance(camera_ms, int) and not isinstance(camera_ms, bool):
        log.record("camera_open", ok=True, reason=event, duration_ms=camera_ms, **common)
    local_auth = answer.get("local_auth")
    if isinstance(local_auth, dict):  # validated by run_local
        log.record(
            "touch_id",
            trigger=event,
            ok=local_auth.get("outcome") == "ok",
            reason=local_auth.get("outcome"),
            duration_ms=local_auth.get("ms"),
            policy=local_auth.get("policy"),
            **common,
        )
    score = answer.get("score")
    method = answer.get("method") if isinstance(answer.get("method"), str) else "face"
    log.record(
        event,
        ok=answer.get("ok") is True,
        reason=answer.get("reason") if isinstance(answer.get("reason"), str) else None,
        score=score if isinstance(score, int | float) and not isinstance(score, bool) else None,
        liveness=answer.get("liveness") if isinstance(answer.get("liveness"), str) else None,
        duration_ms=int((time.monotonic() - started) * 1000),
        trigger="local",
        method=method if event in CHECK_EVENTS else None,
        **common,
    )


def _run_local(
    ctx: click.Context,
    config: Config,
    op: str,
    request: dict[str, Any],
    *,
    timeout: float,
    printer: _Printer | None = None,
    on_explain: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    language = config.ui.language
    try:
        return _runner(ctx, config)(
            op,
            request,
            on_progress=printer.progress if printer is not None else None,
            on_explain=on_explain,
            timeout=timeout,
        )
    except LocalWorkerError as exc:
        log = _guard_dir(config) / "worker.log"
        click.echo(t("guard.cli.worker_failed", language, error=str(exc), log=log), err=True)
        ctx.exit(1)


def _set_enabled(config: Config, value: bool) -> Path:
    """``[component.guard] enabled = value`` in ``tau.toml``, keeping everything else."""
    doc = load_document(config.home)
    component = doc.get("component")
    if component is None:
        doc["component"] = {"guard": {"enabled": value}}
    elif "guard" not in component:
        component["guard"] = {"enabled": value}
    else:
        component["guard"]["enabled"] = value
    return save_document(config.home, doc)


# -- the model -----------------------------------------------------------------------------------


def _ensure_model(ctx: click.Context, config: Config, model_file: Path | None) -> None:
    language = config.ui.language
    installer = _obj(ctx).get("guard_install") or install_sface
    if model_file is None and model_state(sface_path(config.data_dir), SFACE_SHA256) == "ok":
        click.echo(t("guard.cli.model.present", language))
        return
    if model_file is None:
        click.echo(t("guard.cli.model.downloading", language))
    else:
        click.echo(t("guard.cli.model.copying", language, path=model_file))
    try:
        installer(config.data_dir, source=model_file)
    except ModelChecksumError as exc:
        text = t("guard.cli.model.checksum", language, expected=exc.expected, actual=exc.actual)
        click.echo(text, err=True)
        ctx.exit(1)
    except ModelError as exc:
        click.echo(t("guard.cli.model.failed", language, error=str(exc)), err=True)
        ctx.exit(1)
    click.echo(t("guard.cli.model.installed", language))


def _need_model(ctx: click.Context, config: Config) -> None:
    if model_state(sface_path(config.data_dir), SFACE_SHA256) != "ok":
        click.echo(t("guard.cli.no_model", config.ui.language), err=True)
        ctx.exit(1)


# -- enrollment ----------------------------------------------------------------------------------


def _hub_enroll(ctx: click.Context, config: Config, add: bool, printer: _Printer) -> dict:
    client = _client(ctx, config)
    body = {"client_id": process_client_id(), "add": add}
    try:
        started = client.post("/guard/enroll", body, timeout=REQUEST_TIMEOUT)
    except HubError as exc:
        payload = exc.payload if isinstance(exc.payload, dict) else {}
        reason = payload.get("reason") if exc.status != 403 else None
        return {"ok": False, "reason": reason if reason in VERDICT_REASONS else "unavailable"}
    except HubUnavailable:
        return {"ok": False, "reason": "unavailable"}
    attempt_id = started.get("attempt") if isinstance(started, dict) else None
    seq = started.get("seq") if isinstance(started, dict) else None
    if not isinstance(attempt_id, str) or not isinstance(seq, int):
        return {"ok": False, "reason": "error"}
    deadline = time.monotonic() + ENROLL_WAIT
    try:
        while time.monotonic() < deadline:
            query = {"since": str(seq), "wait": f"{LONG_POLL:g}", "attempt": attempt_id}
            try:
                payload = client.get(
                    "/guard/status", timeout=LONG_POLL + REQUEST_TIMEOUT, query=query
                )
            except (HubError, HubUnavailable):
                return {"ok": False, "reason": "unavailable"}
            record = payload.get("attempt") if isinstance(payload, dict) else None
            if not isinstance(record, dict) or record.get("id") != attempt_id:
                return {"ok": False, "reason": "unavailable"}
            new_seq = payload.get("seq")
            seq = new_seq if isinstance(new_seq, int) else seq
            printer(str(record.get("step")), record.get("hint"))
            if record.get("done") is True:
                ok = record.get("ok") is True and record.get("reason") == "match"
                return {"ok": ok, "reason": record.get("reason")}
    except KeyboardInterrupt:
        _cancel(client, attempt_id)
        raise
    _cancel(client, attempt_id)
    return {"ok": False, "reason": "timeout"}


def _cancel(client: Any, attempt_id: str) -> None:
    try:
        body = {"client_id": process_client_id(), "attempt": attempt_id}
        client.post("/guard/cancel", body, timeout=REQUEST_TIMEOUT)
    except Exception:
        pass


def _enroll(
    ctx: click.Context, config: Config, *, add: bool, window: bool = True
) -> tuple[bool, bool]:
    """``(enrolled, through the hub)``."""
    language = config.ui.language
    _need_model(ctx, config)
    had = read_enrollment(config) is not None
    click.echo(t("guard.cli.enroll.start", language))
    if add:
        click.echo(t("guard.cli.enroll.add", language))
    printer = _Printer(language, {"touch_id": "guard.cli.enroll.local_auth"})
    via_hub = _hub_active(ctx, config, language)
    if via_hub:
        click.echo(t("guard.cli.via_hub", language))
        _hub_window_note(window, language)
        answer = _hub_enroll(ctx, config, add, printer)
        first = not had
    else:
        click.echo(t("guard.cli.local", language))
        request = _request(
            ctx,
            config,
            "enroll",
            "enroll",
            window="enroll" if window else None,
            add=add,
            reason_text=t("guard.cli.la.enroll", language),
        )
        started = time.monotonic()
        answer = _run_local(ctx, config, "enroll", request, timeout=ENROLL_WAIT, printer=printer)
        _audit_local(config, "enroll", answer, started)
        first = answer.get("first") is True
    if answer.get("ok") is not True:
        reason = _reason_text(answer.get("reason"), language, enroll=True)
        click.echo(t("guard.cli.enroll.failed", language, reason=reason), err=True)
        _touch_id_hint(answer.get("reason"), language)
        return False, via_hub
    key = "done_add" if add else ("done_first" if first else "done_again")
    click.echo(t(f"guard.cli.enroll.{key}", language))
    return True, via_hub


# -- verification --------------------------------------------------------------------------------


def _explain_line(
    language: str, printer: _Printer, *, every: int = EXPLAIN_EVERY
) -> Callable[[dict[str, Any]], None]:
    """Prints every ``every``-th frame row (and every row with a hint or a new phase), tagged
    with the prompt on screen."""
    seen = {"rows": 0, "phase": None}

    def show(row: dict[str, Any]) -> None:
        def num(key: str, digits: int) -> str:
            value = row.get(key)
            return "-" if value is None else f"{value:.{digits}f}"

        def degrees(key: str) -> str:
            value = row.get(key)
            return "-" if value is None else f"{value:+.1f}°"

        hint = row.get("hint")
        index, seen["rows"] = seen["rows"], seen["rows"] + 1
        new_phase, seen["phase"] = row.get("phase") != seen["phase"], row.get("phase")
        if index % every and not new_phase and not isinstance(hint, str):
            return
        step = printer.step if printer.step in PROMPTS else "look"
        click.echo(
            t(
                "guard.cli.verify.explain_row",
                language,
                t=f"{row.get('t') or 0:6.2f}s",
                step=t(f"guard.cli.verify.tag.{step}", language),
                yaw=degrees("yaw"),
                turn=degrees("turn"),
                pitch=degrees("pitch"),
                fit=num("fit", 2),
                faces=row.get("faces") if row.get("faces") is not None else "-",
                score=num("score", 2),
                iod=num("iod", 0),
                brightness=num("brightness", 0),
                sharpness=num("sharpness", 0),
                similarity=num("similarity", 2),
                hint=f"  ({hint})" if isinstance(hint, str) else "",
            )
        )

    return show


def _rule_line(answer: dict[str, Any], language: str) -> None:
    """The liveness rule a failed local check broke, when the worker named one."""
    rule = answer.get("liveness")
    if answer.get("ok") is not True and answer.get("reason") == "spoof" and rule in FAILURES:
        text = t(f"guard.cli.verify.rule.{rule}", language)
        click.echo(t("guard.cli.verify.rule", language, rule=text, code=rule), err=True)


def _verify(
    ctx: click.Context, config: Config, *, explain: str | None, window: bool = True
) -> bool:
    """One check; ``explain`` is ``None``, ``"frames"`` (every 3rd frame) or ``"all"``."""
    language = config.ui.language
    printer = _Printer(language, highlight=explain is not None)
    if explain is None and _hub_active(ctx, config, language):
        click.echo(t("guard.cli.via_hub", language))
        _hub_window_note(window, language)
        guard = HubGuard(config, client=_client(ctx, config))
        verdict = asyncio.run(
            guard.unlock(
                channel=CLI_CHANNEL,
                client_id=process_client_id(),
                on_progress=lambda progress: printer(progress.step, progress.hint),
            )
        )
        if verdict.ok:
            click.echo(t("guard.cli.verify.passed", language))
            return True
        reason = _reason_text(verdict.reason, language)
        click.echo(t("guard.cli.verify.failed", language, reason=reason), err=True)
        return False
    click.echo(t("guard.cli.verify.local", language))
    request = _request(
        ctx,
        config,
        "verify",
        "unlock",
        window="check" if window else None,
        explain=explain is not None,
    )
    started = time.monotonic()
    every = 1 if explain == "all" else EXPLAIN_EVERY
    answer = _run_local(
        ctx,
        config,
        "verify",
        request,
        timeout=VERIFY_WAIT,
        printer=printer,
        on_explain=_explain_line(language, printer, every=every) if explain else None,
    )
    _audit_local(config, "verify", answer, started)
    if explain:
        click.echo(t("guard.cli.verify.nothing_saved", language))
    if answer.get("ok") is True:
        liveness = answer.get("liveness")
        score = answer.get("score")
        if liveness in ("challenge", "passive") and isinstance(score, int | float):
            label = t(f"guard.cli.verify.liveness.{liveness}", language)
            click.echo(
                t("guard.cli.verify.passed_detail", language, liveness=label, score=f"{score:.2f}")
            )
        else:
            click.echo(t("guard.cli.verify.passed", language))
        return True
    reason = _reason_text(answer.get("reason"), language)
    click.echo(t("guard.cli.verify.failed", language, reason=reason), err=True)
    _rule_line(answer, language)
    return False


# -- commands ------------------------------------------------------------------------------------

_no_window_option = click.option(
    "--no-window",
    is_flag=True,
    help="Keep the guard window off for checks this command runs itself (a check through the "
    "hub follows the hub's [component.guard] window).",
)


@click.command(
    name="setup",
    help="Set up the face guard at the Mac: the face model, your enrollment, one check, and "
    "[component.guard] enabled = true.",
)
@help_option()
@click.option(
    "--model-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Install SFace from this file instead of downloading it (checked against the pinned "
    "sha256).",
)
@_no_window_option
@click.pass_context
def setup_command(ctx: click.Context, model_file: Path | None, no_window: bool) -> None:
    config = _config(ctx)
    language = config.ui.language
    _refuse_elsewhere(ctx, language)
    _settings(ctx, config)
    click.echo(t("guard.cli.setup.start", language))
    _ensure_model(ctx, config, model_file)
    click.echo(t("guard.cli.setup.enroll", language))
    enrolled, via_hub = _enroll(ctx, config, add=False, window=not no_window)
    if not enrolled:
        ctx.exit(1)
    click.echo(t("guard.cli.setup.verify", language))
    if not _verify(ctx, config, explain=None, window=not no_window):
        click.echo(t("guard.cli.setup.verify_failed", language), err=True)
        ctx.exit(1)
    path = _set_enabled(config, True)
    click.echo(t("guard.cli.setup.enabled", language, path=path))
    click.echo(t("guard.cli.setup.restart", language))
    if not via_hub:  # the terminal's camera grant is not the hub's
        click.echo(t("guard.cli.setup.hub_camera", language))
    click.echo(t("guard.cli.setup.remote", language))
    click.echo(t("guard.cli.setup.done", language))


@click.command(name="enroll", help="Enroll your face again (behind Touch ID or your password).")
@help_option()
@click.option("--add", is_flag=True, help="Add samples under other light to the template.")
@_no_window_option
@click.pass_context
def enroll_command(ctx: click.Context, add: bool, no_window: bool) -> None:
    config = _config(ctx)
    _refuse_elsewhere(ctx, config.ui.language)
    if not _enroll(ctx, config, add=add, window=not no_window)[0]:
        ctx.exit(1)


@click.command(name="verify", help="Run one face check with the head-turn challenge.")
@help_option()
@click.option(
    "--explain",
    type=click.Choice(["frames", "all"]),
    is_flag=False,
    flag_value="frames",
    default=None,
    help="Run in a local worker and print each prompt and the numbers of every 3rd frame "
    "(--explain=all: every frame). No frame is saved.",
)
@_no_window_option
@click.pass_context
def verify_command(ctx: click.Context, explain: str | None, no_window: bool) -> None:
    config = _config(ctx)
    if _platform(ctx) != "darwin":
        click.echo(t("guard.cli.unsupported", config.ui.language), err=True)
        ctx.exit(2)
    if not _verify(ctx, config, explain=explain, window=not no_window):
        ctx.exit(1)


@click.command(
    name="forget",
    help="Remove your face template, the marker and the Keychain key (behind Touch ID or "
    "your password); the guard is off afterwards.",
)
@help_option()
@click.pass_context
def forget_command(ctx: click.Context) -> None:
    config = _config(ctx)
    language = config.ui.language
    _refuse_elsewhere(ctx, language)
    click.echo(t("guard.cli.forget.start", language))
    request = {
        "v": 1,
        "op": "forget",
        "data_dir": str(config.data_dir),
        "reason_text": t("guard.cli.la.forget", language),
    }
    started = time.monotonic()
    answer = _run_local(ctx, config, "forget", request, timeout=FORGET_WAIT)
    _audit_local(config, "forget", answer, started)
    removed = answer.get("removed") or []
    ok = answer.get("ok") is True
    if not ok and MARKER_FILE not in removed:
        reason = _reason_text(answer.get("reason"), language)
        click.echo(t("guard.cli.forget.failed", language, reason=reason), err=True)
        _touch_id_hint(answer.get("reason"), language)
        ctx.exit(1)
    # Behind LocalAuthentication the worker removed the marker: the guard is off, even when
    # the Keychain key could not go, so enabled = true must not keep it locked.
    if config.component("guard").get("enabled") is True:
        path = _set_enabled(config, False)
        click.echo(t("guard.cli.forget.disabled", language, path=path))
    if not ok:
        click.echo(t("guard.cli.forget.key_left", language), err=True)
        click.echo(t("guard.cli.forget.restart", language))
        ctx.exit(1)
    click.echo(t("guard.cli.forget.done" if removed else "guard.cli.forget.nothing", language))
    click.echo(t("guard.cli.forget.restart", language))


# -- doctor --------------------------------------------------------------------------------------


def responsible_app(pid: int, *, ps: Callable[[int], tuple[int, str] | None] | None = None) -> str:
    """The app a process runs under, for naming whose camera permission applies: the first
    ancestor whose executable lives in an ``.app`` bundle (``TauBar``, ``Terminal``,
    ``iTerm``), else ``launchd`` or ``unknown``."""
    lookup = ps or _ps
    seen: set[int] = set()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        entry = lookup(pid)
        if entry is None:
            return "unknown"
        parent, command = entry
        marker = command.find(".app/")
        if marker != -1:
            return os.path.basename(command[:marker])
        pid = parent
    return "launchd"


def _ps(pid: int) -> tuple[int, str] | None:
    try:
        out = subprocess.run(
            ["ps", "-o", "ppid=,comm=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    parent, _, command = out.partition(" ")
    return (int(parent), command.strip()) if parent.strip().isdigit() else None


def _failures(config: Config, now: datetime) -> int:
    entries = AuditLog(_guard_dir(config)).read(since=now - DOCTOR_WINDOW)
    return sum(
        1
        for entry in entries
        if entry.get("event") in CHECK_EVENTS
        and entry.get("ok") is False
        and entry.get("reason") in COUNTED_REASONS
    )


def _doctor_lines(ctx: click.Context, config: Config) -> list[tuple[str, str, str]]:
    language = config.ui.language
    lines: list[tuple[str, str, str]] = []

    def add(status: str, check: str, key: str, /, **kwargs: Any) -> None:
        lines.append((status, check, t(key, language, **kwargs)))

    platform = _platform(ctx)
    if platform != "darwin":
        add("fail", "platform", "guard.cli.doctor.platform_bad", platform=platform)
        return lines
    add("ok", "platform", "guard.cli.doctor.platform_ok")
    table = config.component("guard")
    try:
        settings = parse_settings(table)
    except SettingsError as exc:
        for problem in exc.problems:
            lines.append(("fail", "config", problem))
        settings = None
    request = {
        "v": 1,
        "op": "selftest",
        "deep": True,
        "data_dir": str(config.data_dir),
        "settings": {"camera": settings.camera if settings else "builtin"},
    }
    try:
        answer = _runner(ctx, config)("selftest", request, timeout=SELFTEST_WAIT)
    except LocalWorkerError as exc:
        add("fail", "worker", "guard.cli.doctor.selftest_failed", error=str(exc))
        answer = {}
    details = answer.get("details") if isinstance(answer.get("details"), dict) else {}
    checks = answer.get("checks") if isinstance(answer.get("checks"), dict) else {}
    for name, ok in sorted(checks.items()):
        if name != "platform" and ok is not True:
            lines.append(("fail", "import", f"{name}"))
    version = details.get("opencv") or "-"
    if details.get("opencv_verified") is True:
        add("ok", "opencv", "guard.cli.doctor.opencv_ok", version=version)
    else:
        from tau_guard.camera import VERIFIED_OPENCV

        verified = ", ".join(VERIFIED_OPENCV)
        key = "guard.cli.doctor.opencv_unverified"
        add("warn", "opencv", key, version=version, verified=verified)
    models = (("yunet", "YuNet 2023mar", YUNET_SHA256), ("sface", "SFace 2021dec", SFACE_SHA256))
    for name, label, pinned in models:
        state = details.get(name, "missing")
        status = "ok" if state == "ok" else "fail"
        key = {"ok": "model_ok", "mismatch": "model_mismatch"}.get(str(state), "model_missing")
        add(status, name, f"guard.cli.doctor.{key}", name=label, sha=_short(pinned))
    marker = _marker(config)
    if marker is None:
        add("warn", "enrollment", "guard.cli.doctor.not_enrolled")
    elif marker.get("model") != SFACE_SHA256:
        enrolled_with = marker.get("model")
        add(
            "fail",
            "enrollment",
            "guard.cli.doctor.model_changed",
            enrolled=_short(enrolled_with) if isinstance(enrolled_with, str) else "-",
            expected=_short(SFACE_SHA256),
        )
    else:
        add(
            "ok",
            "enrollment",
            "guard.cli.doctor.enrolled",
            enrollment=str(marker.get("enrollment")),
            created=str(marker.get("created")),
        )
    template = details.get("template")
    if template == "ok":
        add("ok", "template", "guard.cli.doctor.template_ok")
        calibration = details.get("calibration")
        if calibration in ("measured", "default"):
            add("ok", "calibration", f"guard.cli.doctor.calibration_{calibration}")
    elif template is not None:
        status = "warn" if template == "not_enrolled" else "fail"
        lines.append((status, "template", _reason_text(template, language)))
    keychain = details.get("keychain")
    if keychain in ("ok", "missing", "invalid", "unavailable"):
        status = {"ok": "ok", "missing": "warn"}.get(str(keychain), "fail")
        add(status, "keychain", f"guard.cli.doctor.keychain_{keychain}")
    if settings is not None:
        add(
            "ok",
            "modes",
            "guard.cli.doctor.modes",
            liveness=settings.unlock_liveness,
            step_up=settings.step_up,
            fallback=settings.unlock_fallback,
            unlock=f"{settings.unlock_threshold:.2f}",
            strict=f"{settings.step_up_threshold:.2f}",
        )
        if settings.unlock_liveness == "none":
            add("warn", "liveness", "guard.cli.doctor.liveness_none")
        if settings.step_up == "none":
            add("warn", "step_up", "guard.cli.doctor.step_up_none")
    camera = details.get("camera") if isinstance(details.get("camera"), dict) else {}
    if camera.get("device") and camera.get("builtin") is False:
        add(
            "warn",
            "camera",
            "guard.cli.doctor.camera_not_builtin",
            name=str(camera["device"]),
            camera=settings.camera if settings else "builtin",
        )
    elif camera.get("device"):
        add(
            "ok",
            "camera",
            "guard.cli.doctor.camera_ok",
            name=str(camera["device"]),
            others=camera.get("others", 0),
        )
    else:
        add(
            "fail",
            "camera",
            "guard.cli.doctor.camera_missing",
            camera=settings.camera if settings else "builtin",
        )
    app_name = _obj(ctx).get("guard_app") or responsible_app
    permission = camera.get("permission")
    status_key = f"guard.cli.doctor.tcc.{permission}" if permission in (0, 1, 2, 3) else None
    add(
        "ok" if permission == 3 else "warn",
        "camera permission",
        "guard.cli.doctor.permission",
        app=app_name(os.getpid()),
        status=t(status_key or "guard.cli.doctor.tcc.unknown", language),
    )
    lines.append(_hub_camera(ctx, config, app_name))
    lines.extend(_touch_id_lines(details.get("touch_id"), settings, language))
    count = _failures(config, datetime.now(UTC))
    add("ok" if count == 0 else "warn", "failures", "guard.cli.doctor.failures", count=count)
    return lines


TOUCH_ID_WHY = ("clamshell", "lockout", "disconnected", "not_available", "no_passcode", "error")
PIN_STATES = {
    "ok": "ok",
    "changed": "fail",
    "unreadable": "fail",
    "not_pinned": "warn",
    "unknown": "info",
}


def _touch_id_lines(touch: object, settings: Any, language: str) -> list[tuple[str, str, str]]:
    """The doctor's Touch ID lines: availability, the lid and the pinned fingerprints."""
    touch = touch if isinstance(touch, dict) else {}
    fallback = settings.unlock_fallback if settings is not None else "touch_id"
    step_up = settings.step_up if settings is not None else "face"
    state, detail, lid, pin = (touch.get(key) for key in ("biometry", "detail", "clamshell", "pin"))
    lines: list[tuple[str, str, str]] = []
    if state == "available":
        lines.append(("ok", "touch id", t("guard.cli.doctor.touch_id_ok", language)))
    elif state == "unavailable":
        why = t(f"guard.cli.doctor.why.{detail if detail in TOUCH_ID_WHY else 'error'}", language)
        text = t("guard.cli.doctor.touch_id_unavailable", language, why=why)
        lines.append(("warn", "touch id", text))
    elif state == "none":
        needs = fallback == "touch_id" or step_up in ("touch_id", "face_or_touch_id")
        key = "guard.cli.doctor.touch_id_none_needed" if needs else "guard.cli.doctor.touch_id_none"
        lines.append(("warn" if needs else "info", "touch id", t(key, language)))
    else:
        lines.append(("warn", "touch id", t("guard.cli.doctor.touch_id_unknown", language)))
    if lid is True:
        lines.append(("warn", "clamshell", t("guard.cli.doctor.clamshell_closed", language)))
    elif lid is False:
        lines.append(("ok", "clamshell", t("guard.cli.doctor.clamshell_open", language)))
    else:
        lines.append(("info", "clamshell", t("guard.cli.doctor.clamshell_unknown", language)))
    pin = pin if pin in PIN_STATES else "unknown"
    lines.append((PIN_STATES[pin], "touch id pin", t(f"guard.cli.doctor.pin_{pin}", language)))
    return lines


def _short(sha: str) -> str:
    """A sha256 for a doctor line: its first 12 hex digits."""
    return f"{sha[:12]}…" if len(sha) > 12 else sha


def _marker(config: Config) -> dict[str, Any] | None:
    from tau_guard.store import read_marker

    return read_marker(_guard_dir(config))


def _hub_camera(ctx: click.Context, config: Config, app_name: Callable[[int], str]) -> tuple:
    language = config.ui.language
    client = _client(ctx, config)
    try:
        status = client.get("/status", timeout=REQUEST_TIMEOUT)
        pid = status.get("pid") if isinstance(status, dict) else None
        guard = client.get("/guard/status", timeout=REQUEST_TIMEOUT)
    except (HubUnavailable, HubError):
        return ("info", "hub camera", t("guard.cli.doctor.hub_none", language))
    camera = guard.get("camera") if isinstance(guard, dict) else None
    app = app_name(pid) if isinstance(pid, int) and not isinstance(pid, bool) else "unknown"
    text = t(
        "guard.cli.doctor.hub_camera",
        language,
        app=app,
        camera=camera if isinstance(camera, str) else "-",
    )
    status = "warn" if camera in ("denied", "not_determined", "unavailable") else "ok"
    return (status, "hub camera", text)


@click.command(name="doctor", help="Check everything the face guard depends on.")
@help_option()
@click.pass_context
def doctor_command(ctx: click.Context) -> None:
    config = _config(ctx)
    lines = _doctor_lines(ctx, config)
    for status, name, detail in lines:
        click.echo(f"{status:<4} {name}: {detail}")
    if any(status == "fail" for status, _, _ in lines):
        ctx.exit(1)


def register(group: click.Group) -> None:
    for command in (setup_command, enroll_command, verify_command, forget_command, doctor_command):
        group.add_command(command)
