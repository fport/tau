"""The JSON mode of ``tau setup``: the contract with the Mac app's wizard (issue 171).

``docs/reference/setup.md`` specifies it. In short:

- ``tau setup status --json`` prints one JSON object: the running version, the platform, the
  install mode, the configuration root and, per feature, its localized label and description,
  whether this platform has it, whether its package is installed and whether it is set up,
  and its steps with their inputs.
- ``tau setup install --features a,b --json`` and ``tau setup run <feature> --json`` print JSON
  lines, one event per line: ``progress``, ``log``, ``needs_ui``, then exactly one ``done`` or
  ``error`` as the last line.
- ``run`` reads its inputs as one JSON object on stdin (``{"steps": [...], "inputs": {...}}``),
  never from argv. A secret input goes to ``<home>/.env`` (mode 0600) before its step runs.
- A step that needs its own UI (``interactive`` in the catalog, e.g. ``tau guard setup``) is
  not run: ``needs_ui`` names its argv and the run stops there, so the app can run it itself.
- A check step (``check`` in the catalog, e.g. ``tau remote ssh``) runs quietly: a ``check``
  event carries its result, and while it fails with an action ``needs_ui`` carries that action
  (a command to show, never to run) and the run stops, with the check first in ``pending``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import click

from tau_core.builder import (
    KEY_NAMES,
    KEY_PROVIDERS,
    PROVIDER_PREFERENCE,
    _check_failure,
    default_home,
    env_with_dotenv,
    key_is_pasteable,
    write_env_key,
)
from tau_core.i18n import DEFAULT_LANGUAGE, LANGUAGES, t
from tau_core.setup.catalog import Catalog, Feature, Step
from tau_core.setup.engine import (
    Outcome,
    install_plan,
    parse_ids,
    preflight,
    render_user_md,
    run_check,
    step_argv,
    store_secrets,
    write_user_md,
)
from tau_core.setup.host import Host
from tau_core.setup.state import Snapshot, configured_language, feature_state, take_snapshot
from tau_core.setup.wizard import outcome_for_skip, platform_label

__all__ = [
    "CORE_STEPS",
    "PROTOCOL_VERSION",
    "STDIN_LIMIT",
    "install_json",
    "run_json",
    "status_payload",
]

PROTOCOL_VERSION = 1
STDIN_LIMIT = 64 * 1024
CORE_STEPS = ("init", "about", "doctor")
"""``tau setup run`` takes these besides the catalog's feature ids."""

Emit = Callable[..., None]


def emitter() -> Emit:
    """``emit("log", line=...)`` → one JSON line on stdout (``click.echo`` flushes it)."""

    def emit(event: str, /, **fields: Any) -> None:
        click.echo(json.dumps({"event": event, **fields}, ensure_ascii=False))

    return emit


def language_of(host: Host, snapshot: Snapshot) -> str:
    return configured_language(snapshot.home, host.environ) or DEFAULT_LANGUAGE


# -- status ----------------------------------------------------------------------------------------


def _step_json(step: Step, language: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": step.id,
        "kind": step.kind,
        "label": t(step.label, language),
        "interactive": step.interactive,
        "optional": step.optional,
        "local_only": step.local_only,
        "check": step.check,
    }
    if step.kind == "command":
        payload["command"] = list(step.command)
    if step.text:
        payload["text"] = t(step.text, language)
    if step.url:
        payload["url"] = step.url
    if step.needs:
        payload["needs"] = list(step.needs)
    if step.when_command:
        payload["when_command"] = list(step.when_command)
    payload["inputs"] = [
        {
            "name": item.name,
            "label": t(item.label, language),
            "secret": item.secret,
            "required": item.required,
            "default": item.default,
        }
        for item in step.inputs
    ]
    return payload


def status_payload(host: Host, catalog: Catalog, snapshot: Snapshot) -> dict[str, Any]:
    language = language_of(host, snapshot)
    features = []
    for state in snapshot.features:
        feature = state.feature
        features.append(
            {
                "id": feature.id,
                "label": t(feature.label, language),
                "description": t(feature.description, language),
                "package": feature.package,
                "lockstep": feature.lockstep,
                "platforms": list(feature.platforms),
                "available": state.available,
                "unavailable_reason": (
                    t(feature.unavailable, language)
                    if feature.unavailable and not state.available
                    else None
                ),
                "default": snapshot.platform in feature.default_on,
                "advanced": feature.advanced,
                "permissions": [
                    {"id": p, "label": t(f"setup.permission.{p}", language)}
                    for p in feature.permissions
                ],
                "requires": list(feature.requires),
                "installed": state.installed,
                "version": state.version,
                "configured": state.configured,
                "state": state.state,
                "docs": catalog.docs_url(feature, language),
                "steps": [_step_json(step, language) for step in feature.steps_for(host.platform)],
            }
        )
    return {
        "protocol": PROTOCOL_VERSION,
        "version": snapshot.version,
        "platform": snapshot.platform,
        "platform_label": platform_label(snapshot.platform, language),
        "language": language,
        "ssh": snapshot.ssh,
        "install": {
            "mode": "uv-tool" if snapshot.uv_tool else "environment",
            "can_install": snapshot.uv_tool,
        },
        "home": str(snapshot.home),
        "config": snapshot.config,
        "about": snapshot.about,
        "core_steps": list(CORE_STEPS),
        "features": features,
    }


# -- install ---------------------------------------------------------------------------------------


def _unknown(emit: Emit, catalog: Catalog, feature: str, language: str) -> int:
    known = ", ".join((*catalog.ids(),))
    emit(
        "error",
        code="unknown_feature",
        message=t("setup.error.unknown_feature", language, feature=feature, known=known),
    )
    return 1


def _unavailable(emit: Emit, feature: Feature, snapshot: Snapshot, language: str) -> int:
    reason = t(feature.unavailable, language) if feature.unavailable else ""
    emit(
        "error",
        code="unavailable",
        feature=feature.id,
        message=t(
            "setup.error.unavailable",
            language,
            label=t(feature.label, language),
            platform=platform_label(snapshot.platform, language),
            reason=reason,
        ),
    )
    return 1


def install_json(host: Host, catalog: Catalog, features: Sequence[str], emit: Emit) -> int:
    snapshot = take_snapshot(host, catalog)
    language = language_of(host, snapshot)
    ids = parse_ids(features)
    for fid in ids:
        feature = catalog.get(fid)
        if feature is None:
            return _unknown(emit, catalog, fid, language)
        if not feature.available_on(snapshot.platform):
            return _unavailable(emit, feature, snapshot, language)
    ids = catalog.with_requires(ids)
    plan = install_plan(catalog, snapshot, host, add=ids)
    emit(
        "progress", phase="plan", features=ids, added=list(plan.added), packages=list(plan.packages)
    )
    if not plan.added:
        emit("done", ok=True, installed=[], changed=False)
        return 0
    packages = ", ".join(plan.added)
    if not snapshot.uv_tool:
        message = t("setup.install.not_uv_tool", language, packages=packages)
        emit("error", code="not_uv_tool", message=message)
        return 1
    if plan.uv is None:
        emit("error", code="uv_missing", message=t("setup.install.uv_missing", language))
        return 1
    emit("progress", phase="install", argv=list(plan.argv))
    try:
        code = host.run(plan.argv, on_line=lambda line: emit("log", line=line))
    except OSError as exc:
        message = t("setup.fail.start", language, error=exc.strerror or exc)
        emit("error", code="install_failed", message=message)
        return 1
    if code != 0:
        emit(
            "error",
            code="install_failed",
            exit=code,
            message=t("setup.install.failed", language, code=code),
        )
        return 1
    emit("done", ok=True, installed=list(plan.added), changed=True)
    return 0


# -- run -------------------------------------------------------------------------------------------


class BadInput(ValueError):
    pass


def read_request(host: Host) -> dict[str, Any]:
    """The stdin object: ``{"steps": [ids]?, "inputs": {name: string}?, "check": bool?}``."""
    raw = host.read_stdin(STDIN_LIMIT)
    if len(raw) > STDIN_LIMIT:
        raise BadInput("more than 64 KiB")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise BadInput(f"not JSON ({exc.msg})") from None
    if not isinstance(data, dict):
        raise BadInput("not a JSON object")
    unknown = sorted(set(data) - {"steps", "inputs", "check"})
    if unknown:
        raise BadInput(f"unknown keys: {', '.join(unknown)}")
    steps = data.get("steps")
    if steps is not None and (
        not isinstance(steps, list) or not all(isinstance(s, str) for s in steps)
    ):
        raise BadInput("`steps` must be a list of step ids")
    inputs = data.get("inputs", {})
    if not isinstance(inputs, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in inputs.items()
    ):
        raise BadInput("`inputs` must be an object of strings")
    if "check" in data and not isinstance(data["check"], bool):
        raise BadInput("`check` must be true or false")
    return data


def _log(emit: Emit, **fields: str) -> Callable[[str], None]:
    return lambda line: emit("log", **fields, line=line)


def _run_captured(
    host: Host, argv: Sequence[str], emit: Emit, language: str, *, feature: str, step: str
) -> tuple[int | None, str]:
    try:
        return host.run(argv, on_line=_log(emit, feature=feature, step=step)), ""
    except OSError as exc:
        return None, t("setup.fail.start", language, error=exc.strerror or exc)


def run_json(host: Host, catalog: Catalog, target: str, emit: Emit) -> int:
    snapshot = take_snapshot(host, catalog)
    language = language_of(host, snapshot)
    try:
        request = read_request(host)
    except BadInput as exc:
        message = t("setup.error.bad_input", language, detail=exc)
        emit("error", code="bad_input", message=message)
        return 1
    if target == "init":
        return _run_init(host, snapshot, request, emit, language)
    if target == "about":
        return _run_about(snapshot, request, emit, language)
    if target == "doctor":
        return _run_doctor(host, emit, language)
    feature = catalog.get(target)
    if feature is None:
        return _unknown(emit, catalog, target, language)
    state = snapshot.get(target)
    assert state is not None
    if not state.available:
        return _unavailable(emit, feature, snapshot, language)
    if not state.installed:
        assert feature.package is not None
        message = t("setup.error.not_installed", language, package=feature.package, feature=target)
        emit("error", code="not_installed", feature=target, message=message)
        return 1
    return _run_feature(host, snapshot, feature, request, emit, language)


def _run_feature(
    host: Host,
    snapshot: Snapshot,
    feature: Feature,
    request: Mapping[str, Any],
    emit: Emit,
    language: str,
) -> int:
    steps = feature.steps_for(host.platform)
    known = [step.id for step in steps]
    asked = request.get("steps")
    chosen = list(asked) if asked is not None else [s.id for s in steps if not s.optional]
    for step_id in chosen:
        if step_id not in known:
            message = t("setup.error.unknown_step", language, feature=feature.id, step=step_id)
            emit("error", code="unknown_step", feature=feature.id, message=message)
            return 1
    values: dict[str, str] = dict(request.get("inputs", {}))
    names = {item.name for step in steps if step.id in chosen for item in step.inputs}
    stray = sorted(set(values) - names)
    if stray:
        detail = f"unknown inputs for these steps: {', '.join(stray)}"
        emit("error", code="bad_input", message=t("setup.error.bad_input", language, detail=detail))
        return 1
    results: list[Outcome] = []
    pending: list[str] = []
    selected = [step for step in steps if step.id in chosen]
    for index, step in enumerate(selected):
        label = t(step.label, language)
        skip = preflight(step, feature, host)
        if skip is not None:
            outcome = outcome_for_skip(feature, step, skip, language, host.platform)
            results.append(outcome)
            emit("progress", feature=feature.id, **outcome.as_json(), label=label)
            continue
        if step.kind == "note":
            outcome = Outcome(feature.id, step.id, label, "info")
            extra = {"text": t(step.text or "", language)}
            if step.url:
                extra["url"] = step.url
            results.append(outcome)
            emit("progress", feature=feature.id, step=step.id, status="info", label=label, **extra)
            continue
        if step.check:
            outcome = _check_step(host, feature, step, label, emit, language)
            if outcome is None:  # needs_ui: the owner acts, then the app runs it again
                results.append(Outcome(feature.id, step.id, label, "needs_ui"))
                pending = [s.id for s in selected[index:]]
                break
            results.append(outcome)
            emit("progress", feature=feature.id, **outcome.as_json(), label=label)
            continue
        args, missing = step_argv(step, values, host.environ)
        if missing is not None:
            detail = t("setup.skip.no_input", language, input=missing)
            outcome = Outcome(feature.id, step.id, label, "skipped", "no_input", detail)
            results.append(outcome)
            emit("progress", feature=feature.id, **outcome.as_json(), label=label)
            continue
        for name, written in store_secrets(step, values, snapshot.home):
            key = "setup.input.saved" if written else "setup.input.kept"
            emit(
                "log",
                feature=feature.id,
                step=step.id,
                line=t(key, language, name=name, path=snapshot.home / ".env"),
            )
        argv = [*host.tau(), *args]
        if step.interactive:
            emit(
                "needs_ui",
                feature=feature.id,
                step=step.id,
                label=label,
                command=args,
                argv=argv,
            )
            results.append(Outcome(feature.id, step.id, label, "needs_ui"))
            pending = [s.id for s in selected[index + 1 :]]
            break
        emit(
            "progress",
            feature=feature.id,
            step=step.id,
            status="running",
            label=label,
            command=args,
        )
        code, problem = _run_captured(host, argv, emit, language, feature=feature.id, step=step.id)
        if code == 0:
            outcome = Outcome(feature.id, step.id, label, "done", code=0)
        elif code is not None and step.advisory:
            detail = t("setup.advisory", language, code=code)
            outcome = Outcome(feature.id, step.id, label, "done", "advisory", detail, code)
        else:
            detail = problem or t("setup.fail.exit", language, code=code)
            reason = "start" if code is None else "exit"
            outcome = Outcome(feature.id, step.id, label, "failed", reason, detail, code)
        results.append(outcome)
        emit("progress", feature=feature.id, **outcome.as_json(), label=label)
    ok = not any(o.status == "failed" for o in results)
    env = env_with_dotenv(snapshot.home, host.environ)
    after = feature_state(feature, host, home=snapshot.home, data=snapshot.data, env=env)
    emit(
        "done",
        feature=feature.id,
        ok=ok,
        configured=after.configured,
        results=[o.as_json() for o in results],
        pending=pending,
    )
    return 0 if ok else 1


def _check_step(
    host: Host, feature: Feature, step: Step, label: str, emit: Emit, language: str
) -> Outcome | None:
    """Run a check step: its outcome, or ``None`` after ``needs_ui`` (it failed with an action
    the owner has to do). Nothing of the action is run here."""
    emit(
        "progress",
        feature=feature.id,
        step=step.id,
        status="checking",
        label=label,
        command=list(step.command),
    )
    result, code = run_check(host, step.command)
    if result is None:
        detail = t("setup.check.invalid", language, code=code)
        return Outcome(feature.id, step.id, label, "failed", "exit", detail, code)
    payload = result.as_json()
    del payload["check"]
    emit("check", feature=feature.id, step=step.id, **payload)
    if result.ok:
        return Outcome(feature.id, step.id, label, "done", code=0)
    if result.action is None:
        detail = result.summary or t("setup.fail.exit", language, code=code)
        return Outcome(feature.id, step.id, label, "failed", "check", detail, code)
    emit(
        "needs_ui",
        feature=feature.id,
        step=step.id,
        label=label,
        summary=result.summary,
        action=result.action.as_json(),
    )
    return None


# -- the core steps --------------------------------------------------------------------------------


def _done(emit: Emit, step: str, outcome: Outcome, **extra: Any) -> int:
    ok = outcome.status != "failed"
    emit("progress", feature="setup", **outcome.as_json(), label=outcome.label)
    emit(
        "done", feature="setup", step=step, ok=ok, results=[outcome.as_json()], pending=[], **extra
    )
    return 0 if ok else 1


def _run_init(
    host: Host, snapshot: Snapshot, request: Mapping[str, Any], emit: Emit, language: str
) -> int:
    """``tau init`` without prompts: the key (checked with one small request unless
    ``"check": false``) goes to ``<home>/.env`` first, then ``tau init --yes`` picks it up."""
    label = t("setup.core.init", language)
    if snapshot.config:
        detail = t("setup.skip.configured", language)
        return _done(emit, "init", Outcome("setup", "init", label, "skipped", "configured", detail))
    inputs: Mapping[str, str] = request.get("inputs", {})
    stray = sorted(set(inputs) - {"language", "provider", "key"})
    chosen_language = (inputs.get("language") or "").strip() or language
    provider = (inputs.get("provider") or "").strip()
    key = (inputs.get("key") or "").strip()
    if stray or chosen_language not in LANGUAGES:
        detail = f"unknown inputs: {', '.join(stray)}" if stray else "`language` is en or tr"
        emit("error", code="bad_input", message=t("setup.error.bad_input", language, detail=detail))
        return 1
    if provider and provider not in PROVIDER_PREFERENCE or key and provider not in KEY_PROVIDERS:
        message = t(
            "setup.error.bad_provider",
            language,
            provider=provider or "-",
            known=", ".join(KEY_PROVIDERS),
        )
        emit("error", code="bad_provider", message=message)
        return 1
    home = default_home(host.environ)
    if key:
        if not key_is_pasteable(key):
            emit("error", code="key_invalid", message=t("init.key.invalid", language))
            return 1
        if request.get("check", True):
            emit("progress", feature="setup", step="init", status="checking", label=label)
            result = host.key_check(provider, key)
            if not result.ok:
                emit(
                    "error",
                    code="key_refused",
                    check=result.code,
                    status=result.status or None,
                    message=_check_failure(result, provider, language),
                )
                return 1
        name = KEY_NAMES[provider]
        try:
            home.mkdir(parents=True, exist_ok=True)
            written = write_env_key(home, name, key)
        except (OSError, ValueError) as exc:
            reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else "invalid value"
            emit("error", code="key_not_written", message=f"{name}: {reason}")
            return 1
        message = "init.key.written" if written else "init.key.kept"
        emit(
            "log",
            feature="setup",
            step="init",
            line=t(message, language, name=name, path=home / ".env"),
        )
    args = ["init", "--yes", "--language", chosen_language]
    if provider:
        args += ["--provider", provider]
    emit("progress", feature="setup", step="init", status="running", label=label, command=args)
    code, problem = _run_captured(
        host, [*host.tau(), *args], emit, language, feature="setup", step="init"
    )
    if code == 0:
        return _done(emit, "init", Outcome("setup", "init", label, "done", code=0))
    detail = problem or t("setup.fail.exit", language, code=code)
    return _done(emit, "init", Outcome("setup", "init", label, "failed", "exit", detail, code))


def _run_about(snapshot: Snapshot, request: Mapping[str, Any], emit: Emit, language: str) -> int:
    label = t("setup.core.about", language)
    path = snapshot.home / "persona" / "user.md"
    if snapshot.about:
        detail = t("setup.about.kept", language, path=path)
        return _done(
            emit, "about", Outcome("setup", "about", label, "skipped", "configured", detail)
        )
    inputs: Mapping[str, str] = request.get("inputs", {})
    stray = sorted(set(inputs) - {"name", "address", "languages"})
    if stray:
        detail = f"unknown inputs: {', '.join(stray)}"
        emit("error", code="bad_input", message=t("setup.error.bad_input", language, detail=detail))
        return 1
    name = (inputs.get("name") or "").strip()
    if not name:
        detail = t("setup.skip.no_input", language, input="name")
        return _done(emit, "about", Outcome("setup", "about", label, "skipped", "no_input", detail))
    text = render_user_md(
        name=name, address=inputs.get("address", ""), languages=inputs.get("languages", "")
    )
    try:
        written = write_user_md(snapshot.home, text)
    except OSError as exc:
        detail = t("setup.fail.start", language, error=exc.strerror or exc)
        return _done(emit, "about", Outcome("setup", "about", label, "failed", "start", detail))
    detail = t("setup.about.written", language, path=written)
    return _done(emit, "about", Outcome("setup", "about", label, "done", detail=detail))


def _run_doctor(host: Host, emit: Emit, language: str) -> int:
    """``tau doctor --json``; the ``done`` event carries its checks."""
    label = t("setup.core.doctor", language)
    emit(
        "progress",
        feature="setup",
        step="doctor",
        status="running",
        label=label,
        command=["doctor", "--json"],
    )
    code, out = host.capture([*host.tau(), "doctor", "--json"])
    try:
        report = json.loads(out)
    except ValueError:
        report = None
    checks = report.get("checks") if isinstance(report, dict) else None
    if not isinstance(checks, list):
        for line in out.splitlines():
            emit("log", feature="setup", step="doctor", line=line)
        checks = []
    if code == 0:
        outcome = Outcome("setup", "doctor", label, "done", code=0)
    else:
        detail = t("setup.fail.exit", language, code=code)
        outcome = Outcome("setup", "doctor", label, "failed", "exit", detail, code)
    return _done(emit, "doctor", outcome, checks=checks)
