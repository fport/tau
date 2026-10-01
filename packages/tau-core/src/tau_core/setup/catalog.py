"""The feature catalog of ``tau setup``: ``tau_core/templates/features.toml`` as dataclasses.

The catalog is data (ADR 0014 §1). This module parses and validates it strictly, because a
typo there would otherwise show up only when an owner picks that feature: an unknown key, a
platform or permission tau does not know, a ``requires`` that names no feature or forms a
cycle, a command that does not start with a plain word, a secret that would reach argv, and a
text key that is missing from the message table are all a :class:`CatalogError`.

``docs/reference/setup.md`` specifies the schema.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from tau_core.i18n import MESSAGES

__all__ = [
    "CATALOG_FILE",
    "PERMISSIONS",
    "PLATFORMS",
    "STEP_KINDS",
    "Catalog",
    "CatalogError",
    "Configured",
    "Feature",
    "Input",
    "Step",
    "load_catalog",
    "parse_catalog",
]

CATALOG_FILE = "features.toml"
PLATFORMS: tuple[str, ...] = ("darwin", "linux")
"""The platforms tau runs on, as ``sys.platform`` names them."""
PERMISSIONS: tuple[str, ...] = ("camera", "notifications", "microphone")
"""The macOS permissions a feature may need; the app asks for them (issue 171)."""
STEP_KINDS: tuple[str, ...] = ("command", "note")
SCHEMA = 1

_ID = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_INPUT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_WORD = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_FLAG = re.compile(r"^--[a-z][a-z0-9-]{0,31}$")
_ENV = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_PROGRAM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_PACKAGE = re.compile(r"^tau-[a-z][a-z0-9-]{0,31}$")
_FORBIDDEN_WORDS = frozenset({"sudo", "su", "doas"})


class CatalogError(ValueError):
    """``features.toml`` does not follow the schema; the message names the entry."""


@dataclass(frozen=True)
class Input:
    """A value a step needs: typed at a prompt in the wizard, or sent on stdin in JSON mode.

    A plain input goes into the step's argv, after ``flag`` or as a positional argument. A
    ``secret`` input never reaches argv: the engine writes it to ``<home>/.env`` (mode 0600)
    under ``env`` before the step runs, and the step reads it from there."""

    name: str
    label: str
    flag: str | None = None
    positional: bool = False
    secret: bool = False
    env: str | None = None
    required: bool = False
    default: str = ""
    path: bool = False
    """``~`` at the start is expanded to the home directory before the value reaches argv."""


@dataclass(frozen=True)
class Step:
    """One setup step of a feature: a tau subcommand (``kind = "command"``) or a text with a
    link (``kind = "note"``)."""

    id: str
    label: str
    kind: str = "command"
    command: tuple[str, ...] = ()
    """The arguments after ``tau``, e.g. ``("guard", "doctor")``."""
    interactive: bool = False
    """Needs the owner at a terminal (or its own UI): the wizard gives it the terminal, JSON
    mode reports ``needs_ui`` and ``--yes`` skips it."""
    optional: bool = False
    """Asked with the default "no"; ``--yes`` skips it; JSON mode runs it only when asked."""
    advisory: bool = False
    """A nonzero exit is reported, not counted as a failure (a check before the fix)."""
    local_only: bool = False
    """Refused over SSH (``SSH_CONNECTION`` or ``SSH_TTY``): it needs the owner at the Mac."""
    platforms: tuple[str, ...] = ()
    """Empty: every platform of the feature."""
    when_command: tuple[str, ...] = ()
    """Run only when ``tau <when_command> --help`` succeeds; otherwise ``unavailable`` is shown."""
    unavailable: str | None = None
    needs: tuple[str, ...] = ()
    """Programs that must be on ``PATH``; otherwise ``needs_text`` is shown and the step skipped."""
    needs_text: str | None = None
    text: str | None = None
    url: str | None = None
    inputs: tuple[Input, ...] = ()
    check: bool = False
    """The command is a check (:mod:`tau_core.setup.checks`): ``tau <command> --json`` prints
    one check object. The wizard shows it and waits while the owner does its action; JSON mode
    reports it as a ``check`` event and its action as ``needs_ui``."""

    def applies_to(self, platform: str, feature_platforms: tuple[str, ...]) -> bool:
        return platform in (self.platforms or feature_platforms)


@dataclass(frozen=True)
class Configured:
    """When a feature counts as set up: every file in ``files`` exists, at least one of
    ``any_files`` exists (when given), every variable in ``env`` is set in the environment or
    ``<home>/.env``, and ``tau <command>`` exits 0 (when given; asked last, as it costs a
    subprocess)."""

    files: tuple[str, ...] = ()
    any_files: tuple[str, ...] = ()
    env: tuple[str, ...] = ()
    command: tuple[str, ...] = ()


@dataclass(frozen=True)
class Feature:
    id: str
    label: str
    description: str
    platforms: tuple[str, ...]
    default_on: tuple[str, ...]
    """The platforms on which the feature is selected by default on a first run."""
    package: str | None = None
    lockstep: bool = False
    """Released with tau-core and pinned to its version (tau-tui, tau-guard)."""
    permissions: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    docs: str | None = None
    unavailable: str | None = None
    """Why the feature is not offered on the other platforms."""
    configured: Configured | None = None
    """``None``: installed means set up (or, without a package, never "done")."""
    keep_while_configured: str | None = None
    """``tau setup --remove`` refuses while the feature is set up, with this text."""
    advanced: bool = False
    steps: tuple[Step, ...] = ()

    def available_on(self, platform: str) -> bool:
        return platform in self.platforms

    def steps_for(self, platform: str) -> tuple[Step, ...]:
        return tuple(step for step in self.steps if step.applies_to(platform, self.platforms))


@dataclass(frozen=True)
class Catalog:
    schema: int
    docs: str
    features: tuple[Feature, ...] = field(default_factory=tuple)

    def ids(self) -> tuple[str, ...]:
        return tuple(feature.id for feature in self.features)

    def get(self, feature_id: str) -> Feature | None:
        return next((f for f in self.features if f.id == feature_id), None)

    def packages(self) -> tuple[str, ...]:
        return tuple(f.package for f in self.features if f.package)

    def with_requires(self, ids: Iterable[str]) -> list[str]:
        """``ids`` plus everything they require, in catalog order."""
        wanted = set(ids)
        todo = list(wanted)
        while todo:
            feature = self.get(todo.pop())
            for required in feature.requires if feature else ():
                if required not in wanted:
                    wanted.add(required)
                    todo.append(required)
        return [feature.id for feature in self.features if feature.id in wanted]

    def docs_url(self, feature: Feature, language: str) -> str | None:
        if not feature.docs:
            return None
        prefix = "tr/" if language == "tr" else ""
        return f"{self.docs}{prefix}{feature.docs}"


# -- parsing -------------------------------------------------------------------------------------

_FEATURE_KEYS = {
    "id",
    "package",
    "lockstep",
    "label",
    "description",
    "platforms",
    "default",
    "permissions",
    "requires",
    "docs",
    "unavailable",
    "configured",
    "keep_while_configured",
    "advanced",
    "step",
}
_STEP_KEYS = {
    "id",
    "kind",
    "label",
    "command",
    "interactive",
    "optional",
    "advisory",
    "local_only",
    "platforms",
    "when_command",
    "unavailable",
    "needs",
    "needs_text",
    "text",
    "url",
    "input",
    "check",
}
_INPUT_KEYS = {
    "name",
    "label",
    "flag",
    "positional",
    "secret",
    "env",
    "required",
    "default",
    "path",
}
_CONFIGURED_KEYS = {"files", "any_files", "env", "command"}


def _where(*parts: str) -> str:
    return "features.toml: " + " ".join(parts)


def _keys(table: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise CatalogError(f"{where}: unknown keys {', '.join(unknown)}")


def _str(table: Mapping[str, Any], key: str, where: str, *, required: bool = False) -> str | None:
    value = table.get(key)
    if value is None:
        if required:
            raise CatalogError(f"{where}: `{key}` is required")
        return None
    if not isinstance(value, str) or not value:
        raise CatalogError(f"{where}: `{key}` must be a non-empty string")
    return value


def _bool(table: Mapping[str, Any], key: str, where: str) -> bool:
    value = table.get(key, False)
    if not isinstance(value, bool):
        raise CatalogError(f"{where}: `{key}` must be true or false")
    return value


def _strings(table: Mapping[str, Any], key: str, where: str) -> tuple[str, ...]:
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise CatalogError(f"{where}: `{key}` must be a list of non-empty strings")
    return tuple(value)


def _message(key: str | None, where: str, messages: Mapping[str, Any]) -> str | None:
    if key is not None and key not in messages:
        raise CatalogError(f"{where}: no message `{key}` in the i18n table")
    return key


def _platforms(values: tuple[str, ...], where: str) -> tuple[str, ...]:
    unknown = [p for p in values if p not in PLATFORMS]
    if unknown:
        raise CatalogError(f"{where}: unknown platforms {', '.join(unknown)}")
    return values


def _parse_input(raw: Any, where: str, messages: Mapping[str, Any]) -> Input:
    if not isinstance(raw, dict):
        raise CatalogError(f"{where}: an input must be a table")
    _keys(raw, _INPUT_KEYS, where)
    name = _str(raw, "name", where, required=True)
    assert name is not None
    if not _INPUT_NAME.match(name):
        raise CatalogError(f"{where}: invalid input name {name!r}")
    where = f"{where} input {name}"
    label = _message(_str(raw, "label", where, required=True), where, messages)
    flag = _str(raw, "flag", where)
    env = _str(raw, "env", where)
    default = raw.get("default", "")
    if not isinstance(default, str):
        raise CatalogError(f"{where}: `default` must be a string")
    item = Input(
        name=name,
        label=label or "",
        flag=flag,
        positional=_bool(raw, "positional", where),
        secret=_bool(raw, "secret", where),
        env=env,
        required=_bool(raw, "required", where),
        default=default,
        path=_bool(raw, "path", where),
    )
    if item.secret:
        if item.flag or item.positional or item.default:
            raise CatalogError(f"{where}: a secret never reaches argv and has no default")
        if not item.env or not _ENV.match(item.env):
            raise CatalogError(f"{where}: a secret needs `env`, the .env name it is written to")
    else:
        if item.env:
            raise CatalogError(f"{where}: `env` is only for secrets")
        if bool(item.flag) == item.positional:
            raise CatalogError(f"{where}: give exactly one of `flag` and `positional = true`")
        if item.flag and not _FLAG.match(item.flag):
            raise CatalogError(f"{where}: invalid flag {item.flag!r}")
    return item


def _command(words: tuple[str, ...], where: str) -> tuple[str, ...]:
    if not words:
        return words
    for word in words:
        if not (_WORD.match(word) or _FLAG.match(word)) or word in _FORBIDDEN_WORDS:
            raise CatalogError(f"{where}: invalid command word {word!r}")
    if not _WORD.match(words[0]):
        raise CatalogError(f"{where}: a command starts with a tau subcommand")
    return words


def _parse_step(
    raw: Any, feature: str, platforms: tuple[str, ...], messages: Mapping[str, Any]
) -> Step:
    where = _where("feature", feature, "step")
    if not isinstance(raw, dict):
        raise CatalogError(f"{where}: a step must be a table")
    step_id = _str(raw, "id", where, required=True)
    assert step_id is not None
    if not _ID.match(step_id):
        raise CatalogError(f"{where}: invalid step id {step_id!r}")
    where = _where("feature", feature, "step", step_id)
    _keys(raw, _STEP_KEYS, where)
    kind = raw.get("kind", "command")
    if kind not in STEP_KINDS:
        raise CatalogError(f"{where}: `kind` must be one of {', '.join(STEP_KINDS)}")
    inputs_raw = raw.get("input", [])
    if not isinstance(inputs_raw, list):
        raise CatalogError(f"{where}: `input` must be an array of tables")
    inputs = tuple(_parse_input(item, where, messages) for item in inputs_raw)
    names = [item.name for item in inputs]
    if len(set(names)) != len(names):
        raise CatalogError(f"{where}: duplicate input names")
    step_platforms = _platforms(_strings(raw, "platforms", where), where)
    outside = [p for p in step_platforms if p not in platforms]
    if outside:
        raise CatalogError(f"{where}: platforms {', '.join(outside)} are not the feature's")
    needs = _strings(raw, "needs", where)
    if any(not _PROGRAM.match(program) for program in needs):
        raise CatalogError(f"{where}: invalid program name in `needs`")
    step = Step(
        id=step_id,
        label=_message(_str(raw, "label", where, required=True), where, messages) or "",
        kind=kind,
        command=_command(_strings(raw, "command", where), where),
        interactive=_bool(raw, "interactive", where),
        optional=_bool(raw, "optional", where),
        advisory=_bool(raw, "advisory", where),
        local_only=_bool(raw, "local_only", where),
        platforms=step_platforms,
        when_command=_command(_strings(raw, "when_command", where), where),
        unavailable=_message(_str(raw, "unavailable", where), where, messages),
        needs=needs,
        needs_text=_message(_str(raw, "needs_text", where), where, messages),
        text=_message(_str(raw, "text", where), where, messages),
        url=_str(raw, "url", where),
        inputs=inputs,
        check=_bool(raw, "check", where),
    )
    if step.url is not None and not step.url.startswith("https://"):
        raise CatalogError(f"{where}: `url` must be an https URL")
    if kind == "command":
        if not step.command:
            raise CatalogError(f"{where}: a command step needs `command`")
        if step.text or step.url:
            raise CatalogError(f"{where}: `text` and `url` belong to notes")
    else:
        if step.command or step.inputs or step.interactive or step.advisory or step.when_command:
            raise CatalogError(f"{where}: a note has only a text, a url and platforms")
        if not step.text:
            raise CatalogError(f"{where}: a note needs `text`")
    if step.when_command and not step.unavailable:
        raise CatalogError(f"{where}: `when_command` needs `unavailable`, the text shown instead")
    if step.needs and not step.needs_text:
        raise CatalogError(f"{where}: `needs` needs `needs_text`, the text shown instead")
    if step.check:
        if kind != "command":
            raise CatalogError(f"{where}: `check` is for command steps")
        if step.interactive or step.advisory or step.inputs:
            # The engine does the waiting of a check; it takes no inputs and never fails softly.
            raise CatalogError(f"{where}: a check is neither interactive nor advisory, no inputs")
    return step


def _parse_configured(raw: Any, where: str) -> Configured | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise CatalogError(f"{where}: `configured` must be a table")
    _keys(raw, _CONFIGURED_KEYS, f"{where} configured")
    configured = Configured(
        files=_strings(raw, "files", where),
        any_files=_strings(raw, "any_files", where),
        env=_strings(raw, "env", where),
        command=_command(_strings(raw, "command", where), f"{where} configured"),
    )
    if not (configured.files or configured.any_files or configured.env or configured.command):
        raise CatalogError(f"{where}: `configured` is empty")
    if any(not _ENV.match(name) for name in configured.env):
        raise CatalogError(f"{where}: invalid variable name in `configured.env`")
    return configured


def _parse_feature(raw: Any, messages: Mapping[str, Any]) -> Feature:
    if not isinstance(raw, dict):
        raise CatalogError(_where("a feature must be a table"))
    feature_id = _str(raw, "id", _where("feature"), required=True)
    assert feature_id is not None
    if not _ID.match(feature_id):
        raise CatalogError(_where(f"invalid feature id {feature_id!r}"))
    where = _where("feature", feature_id)
    _keys(raw, _FEATURE_KEYS, where)
    platforms = _platforms(_strings(raw, "platforms", where), where)
    if not platforms:
        raise CatalogError(f"{where}: `platforms` is empty")
    default = raw.get("default", False)
    if isinstance(default, bool):
        default_on = platforms if default else ()
    elif isinstance(default, list):
        default_on = _platforms(_strings(raw, "default", where), where)
    else:
        raise CatalogError(f"{where}: `default` must be true, false or a list of platforms")
    package = _str(raw, "package", where)
    if package is not None and (not _PACKAGE.match(package) or package == "tau-core"):
        raise CatalogError(f"{where}: invalid package {package!r}")
    permissions = _strings(raw, "permissions", where)
    unknown = [p for p in permissions if p not in PERMISSIONS]
    if unknown:
        raise CatalogError(f"{where}: unknown permissions {', '.join(unknown)}")
    steps_raw = raw.get("step", [])
    if not isinstance(steps_raw, list):
        raise CatalogError(f"{where}: `step` must be an array of tables")
    steps = tuple(_parse_step(item, feature_id, platforms, messages) for item in steps_raw)
    step_ids = [step.id for step in steps]
    if len(set(step_ids)) != len(step_ids):
        raise CatalogError(f"{where}: duplicate step ids")
    feature = Feature(
        id=feature_id,
        label=_message(_str(raw, "label", where, required=True), where, messages) or "",
        description=_message(_str(raw, "description", where, required=True), where, messages) or "",
        platforms=platforms,
        default_on=default_on,
        package=package,
        lockstep=_bool(raw, "lockstep", where),
        permissions=permissions,
        requires=_strings(raw, "requires", where),
        docs=_str(raw, "docs", where),
        unavailable=_message(_str(raw, "unavailable", where), where, messages),
        configured=_parse_configured(raw.get("configured"), where),
        keep_while_configured=_message(_str(raw, "keep_while_configured", where), where, messages),
        advanced=_bool(raw, "advanced", where),
        steps=steps,
    )
    if feature.lockstep and not feature.package:
        raise CatalogError(f"{where}: `lockstep` needs a package")
    if feature.docs and (feature.docs.startswith("/") or "://" in feature.docs):
        raise CatalogError(f"{where}: `docs` is a path relative to the catalog's `docs`")
    if set(PLATFORMS) - set(platforms) and not feature.unavailable:
        raise CatalogError(f"{where}: a feature missing a platform needs `unavailable`")
    return feature


def _check_requires(features: tuple[Feature, ...]) -> None:
    order = {feature.id: index for index, feature in enumerate(features)}
    by_id = {feature.id: feature for feature in features}
    for feature in features:
        for required in feature.requires:
            if required not in order or required == feature.id:
                raise CatalogError(_where("feature", feature.id, f"requires unknown {required!r}"))
            if order[required] > order[feature.id]:
                # Setup runs the features in catalog order, so what a feature needs comes first.
                raise CatalogError(_where("feature", feature.id, f"must come after {required!r}"))

    def visit(feature_id: str, path: tuple[str, ...]) -> None:
        if feature_id in path:
            raise CatalogError(_where("requires form a cycle:", " -> ".join((*path, feature_id))))
        for required in by_id[feature_id].requires:
            visit(required, (*path, feature_id))

    for feature in features:
        visit(feature.id, ())


def parse_catalog(text: str, *, messages: Mapping[str, Any] | None = None) -> Catalog:
    """The catalog in ``text`` (TOML), validated; ``messages`` defaults to the i18n table."""
    messages = MESSAGES if messages is None else messages
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CatalogError(f"features.toml: {exc}") from exc
    _keys(raw, {"schema", "docs", "feature"}, _where("top level"))
    if raw.get("schema") != SCHEMA:
        raise CatalogError(_where(f"`schema` must be {SCHEMA}"))
    docs = _str(raw, "docs", _where("top level"), required=True)
    assert docs is not None
    if not docs.startswith("https://") or not docs.endswith("/"):
        raise CatalogError(_where("`docs` must be an https URL ending in /"))
    features_raw = raw.get("feature", [])
    if not isinstance(features_raw, list) or not features_raw:
        raise CatalogError(_where("no [[feature]] entries"))
    features = tuple(_parse_feature(item, messages) for item in features_raw)
    ids = [feature.id for feature in features]
    if len(set(ids)) != len(ids):
        raise CatalogError(_where("duplicate feature ids"))
    packages = [feature.package for feature in features if feature.package]
    if len(set(packages)) != len(packages):
        raise CatalogError(_where("two features name the same package"))
    _check_requires(features)
    return Catalog(schema=SCHEMA, docs=docs, features=features)


def load_catalog() -> Catalog:
    """The catalog shipped with tau-core."""
    text = (resources.files("tau_core") / "templates" / CATALOG_FILE).read_text(encoding="utf-8")
    return parse_catalog(text)
