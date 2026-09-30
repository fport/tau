"""``tau guard window [--demo]`` (issue 126), registered on the ``tau guard`` group.

- Without options it says whether the guard window is on (``[component.guard] window``) and
  whether checks started from this session could show it (not macOS, ``SSH_CONNECTION``,
  ``TAU_GUARD_WINDOW=0``, no GUI session, no pyobjc AppKit), and that the hub's checks follow
  the hub's own ``tau.toml`` and session.
- ``--demo`` plays a scripted check in the window (``python -m tau_guard.overlay demo``: an
  unlock that passes, a step-up that fails, an enrollment behind Touch ID) on a dark synthetic
  picture; no camera, no worker, nothing unlocks. Esc closes it. The hidden ``--snapshot DIR``
  writes the demo's key moments as PNGs instead of opening the window.

AppKit and Quartz are only ever imported in that child process, never in the CLI. Tests pass
``guard_overlay`` (a callable ``(args, request) -> dict``) through the click context object.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import click
from tau_core import t
from tau_core.cli import help_option

from tau_guard.window import headless_reason, window_field

__all__ = ["register", "run_overlay"]

DEMO_WAIT = 120.0
PROBE_WAIT = 30.0
WHY = ("ssh", "platform", "disabled", "no_gui_session", "pyobjc_missing")


def run_overlay(args: list[str], request: dict[str, Any], *, timeout: float = DEMO_WAIT) -> dict:
    """Run ``python -m tau_guard.overlay <args>`` with ``request`` on stdin; its last stdout
    line (JSON), or ``{"ok": false, "reason": ...}``."""
    try:
        done = subprocess.run(
            [sys.executable, "-P", "-m", "tau_guard.overlay", *args],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "reason": type(exc).__name__}
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    try:
        answer = json.loads(lines[-1]) if lines else None
    except ValueError:
        answer = None
    if not isinstance(answer, dict):
        return {"ok": False, "reason": f"exit {done.returncode}"}
    return answer


def _why(reason: object, language: str) -> str:
    if isinstance(reason, str) and reason in WHY:
        return t(f"guard.cli.window.why.{reason}", language)
    return str(reason)


@click.command(
    name="window",
    help="Say whether the guard window can open here; --demo plays a scripted check in it "
    "(no camera).",
)
@help_option()
@click.option(
    "--demo",
    is_flag=True,
    help="Play a scripted unlock, a failed step-up and an enrollment in the guard window "
    "(synthetic picture, no camera; Esc closes it).",
)
@click.option(
    "--snapshot",
    type=click.Path(file_okay=False, path_type=Path),
    hidden=True,
    help="With --demo: write the demo's key moments as PNGs into this folder instead.",
)
@click.pass_context
def window_command(ctx: click.Context, demo: bool, snapshot: Path | None) -> None:
    from tau_guard.cli_face import _config as load_config
    from tau_guard.cli_face import _obj, _platform, _settings

    config = load_config(ctx)
    language = config.ui.language
    settings = _settings(ctx, config)
    runner = _obj(ctx).get("guard_overlay") or run_overlay
    if not demo:
        state = t("guard.cli.window.on" if settings.window else "guard.cli.window.off", language)
        click.echo(t("guard.cli.window.state", language, state=state))
        reason = headless_reason(platform=_platform(ctx))
        if reason is None:
            reason = runner(["probe"], {}, timeout=PROBE_WAIT).get("reason")
        if reason:
            click.echo(t("guard.cli.window.headless", language, why=_why(reason, language)))
        click.echo(t("guard.cli.window.hub", language))
        click.echo(t("guard.cli.window.demo_hint", language))
        return
    if _platform(ctx) != "darwin":
        click.echo(t("guard.cli.window.demo_failed", language, why=_why("platform", language)))
        ctx.exit(2)
    request: dict[str, Any] = {
        "texts": window_field(language, "unlock")["texts"],
        "language": language,
    }
    if snapshot is not None:
        request["snapshot"] = str(snapshot.resolve())
    else:
        click.echo(t("guard.cli.window.demo_start", language))
    answer = runner(["demo"], request)
    if answer.get("ok") is not True:
        why = _why(answer.get("reason"), language)
        click.echo(t("guard.cli.window.demo_failed", language, why=why), err=True)
        ctx.exit(1)
    if snapshot is not None:
        click.echo(t("guard.cli.window.demo_saved", language, path=snapshot))


def register(group: click.Group) -> None:
    group.add_command(window_command)
