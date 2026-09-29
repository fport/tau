"""``tau components``, ``tau doctor`` and ``tau init``: see, check and set up an installation.

- :func:`inventory` lists every component tau can see: the built-in seeds, every entry point
  in every ``tau.*`` group and the in-process registrations, with distribution, version,
  whether ``[components]`` enables it and the load error when there is one.
- :func:`run_doctor` checks an installation without building a model client or starting
  anything: the config file, each role's provider and credentials, the session store, the
  persona files, ``.env`` against ``.env.example`` and whether a hub answers on the control API.
- :func:`init_home` writes a fresh ``tau.toml`` from the shipped template, the persona files and
  (optionally) ``TAU_PROFILE`` in ``.env``, picking the provider from the credentials present.

All output is English; the helpers are plain functions so tests need no terminal.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tomllib
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path

import click
from dotenv import dotenv_values
from strands.types.tools import AgentTool

from tau_core import registry
from tau_core.cli import help_option
from tau_core.config import (
    CONFIG_FILE,
    DEFAULT_HOME,
    DIST_PREFIX,
    KNOWN_TABLES,
    PROFILES,
    Config,
    ConfigError,
    RoleConfig,
)
from tau_core.i18n import DEFAULT_LANGUAGE, LANGUAGES
from tau_core.models import PLANNED_PROVIDERS, missing_credentials, provider_load_failure
from tau_core.persona import PersonaLoader
from tau_core.plugins import _as_tools
from tau_core.sessions import PLANNED_BACKENDS, open_session_store
from tau_core.tiers import tier_of

logger = logging.getLogger(__name__)

TEMPLATES = resources.files("tau_core") / "templates"
PROVIDER_PREFERENCE = ("bedrock", "anthropic", "fake")
"""``tau init`` picks the first provider whose credentials are present; ``fake`` needs none."""
INIT_ROLES = ("brain", "fast")
"""Roles whose provider and model id ``tau init`` rewrites; ``local`` keeps the template's."""
HEALTH_TIMEOUT = 1.0

_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback, never a proxy
_ENV_NAME = re.compile(r"^\s*#?\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def template_text(name: str) -> str:
    """The shipped template ``name`` (``tau.toml``, ``persona.md``, ``user.example.md``,
    ``dotenv.example`` — written as ``.env.example`` — and the ``models.toml`` id table)."""
    return (TEMPLATES / name).read_text(encoding="utf-8")


def env_with_dotenv(home: Path, env: Mapping[str, str]) -> dict[str, str]:
    """``env`` on top of the values in ``<home>/.env``: the rule of ``Config.load`` (a variable
    that is already set never loses to the file), without touching the process environment.
    ``tau init`` and ``tau doctor`` read credentials through this, so a key that is only in
    ``.env`` — where the hint tells the user to put it — counts."""
    dotenv_path = home / ".env"
    file_values = dotenv_values(dotenv_path) if dotenv_path.is_file() else {}
    return {k: v for k, v in file_values.items() if v is not None} | dict(env)


# -- tau components --------------------------------------------------------------------------


@dataclass(frozen=True)
class ComponentRow:
    """One line of ``tau components``."""

    group: str
    name: str
    distribution: str
    version: str
    source: str
    """``built-in``, ``entry point``, ``registered`` or ``planned``."""
    enabled: bool
    note: str = ""
    error: str | None = None


def _roles_using(config: Config | None, provider: str) -> list[str]:
    if config is None:
        return []
    return [
        name
        for name, role in config.roles.items()
        if provider in {role.provider, role.fallback.provider if role.fallback else None}
    ]


def _tool_rows(config: Config | None) -> list[ComponentRow]:
    rows: list[ComponentRow] = []
    for item in registry.load_group(registry.TOOLS_GROUP, expect=lambda obj: None):
        if item.error is not None:
            rows.append(
                ComponentRow(
                    item.group,
                    item.name,
                    item.distribution,
                    item.version,
                    "entry point",
                    False,
                    error=item.error,
                )
            )
            continue
        try:
            tools = _as_tools(item.obj)
        except TypeError as exc:
            rows.append(
                ComponentRow(
                    item.group,
                    item.name,
                    item.distribution,
                    item.version,
                    "entry point",
                    False,
                    error=str(exc),
                )
            )
            continue
        for tool in tools:
            if not isinstance(tool, AgentTool):
                rows.append(
                    ComponentRow(
                        item.group,
                        item.name,
                        item.distribution,
                        item.version,
                        "entry point",
                        False,
                        error=f"not a tool: {tool!r}",
                    )
                )
                continue
            tier = tier_of(tool)
            enabled = config is None or not config.components.tool_disabled(
                tool.tool_name, item.distribution
            )
            note = f"tier {int(tier)}" if tier is not None else "no tier: never registered"
            rows.append(
                ComponentRow(
                    item.group,
                    tool.tool_name,
                    item.distribution,
                    item.version,
                    "entry point",
                    enabled and tier is not None,
                    note=note,
                )
            )
    return rows


def _seeded_rows(group: str, config: Config | None) -> list[ComponentRow]:
    """Seed + entry points + registrations of a provider/session group."""
    rows: list[ComponentRow] = []
    seed_names = set()
    for item in registry.seeds(group):
        seed_names.add(item.name)
        rows.append(_lookup_row(item, "built-in", config))
    for item in registry.load_group(group):
        if item.error is not None:
            rows.append(
                ComponentRow(
                    item.group,
                    item.name,
                    item.distribution,
                    item.version,
                    "entry point",
                    False,
                    error=item.error,
                )
            )
        elif item.name in seed_names:
            rows.append(
                ComponentRow(
                    item.group,
                    item.name,
                    item.distribution,
                    item.version,
                    "entry point",
                    False,
                    error="ignored: would replace a built-in",
                )
            )
        else:
            rows.append(_lookup_row(item, "entry point", config))
    for item in registry.registered(group):
        rows.append(_lookup_row(item, "registered", config))
    if config is not None:
        planned = PLANNED_PROVIDERS if group == registry.PROVIDERS_GROUP else PLANNED_BACKENDS
        known = {row.name for row in rows}
        for name, issue in planned.items():
            uses = (
                _roles_using(config, name)
                if group == registry.PROVIDERS_GROUP
                else ["sessions"]
                if config.sessions.backend == name
                else []
            )
            if uses and name not in known:
                rows.append(
                    ComponentRow(
                        group,
                        name,
                        "-",
                        "-",
                        "planned",
                        False,
                        note=f"not available until issue {issue}; used by " + ", ".join(uses),
                    )
                )
    return rows


def _lookup_row(item: registry.Loaded, source: str, config: Config | None) -> ComponentRow:
    if item.group == registry.PROVIDERS_GROUP:
        uses = _roles_using(config, item.name)
        note = f"in use: {', '.join(uses)}" if uses else "available"
    else:
        in_use = config is not None and config.sessions.backend == item.name
        note = "in use" if in_use else "available"
    return ComponentRow(
        item.group, item.name, item.distribution, item.version, source, True, note=note
    )


def _switched_rows(group: str, enabled_names: tuple[str, ...]) -> list[ComponentRow]:
    rows: list[ComponentRow] = []
    for item in registry.load_group(group):
        if item.error is not None:
            rows.append(
                ComponentRow(
                    item.group,
                    item.name,
                    item.distribution,
                    item.version,
                    "entry point",
                    False,
                    error=item.error,
                )
            )
            continue
        enabled = not enabled_names or item.name in enabled_names
        rows.append(
            ComponentRow(
                item.group,
                item.name,
                item.distribution,
                item.version,
                "entry point",
                enabled,
                note="" if enabled else "not listed in [components]",
            )
        )
    return rows


def _command_rows() -> list[ComponentRow]:
    rows: list[ComponentRow] = []
    for item in registry.load_group(
        registry.COMMANDS_GROUP,
        expect=lambda obj: None if isinstance(obj, click.Command) else "not a click command",
    ):
        rows.append(
            ComponentRow(
                item.group,
                item.name,
                item.distribution,
                item.version,
                "entry point",
                item.error is None,
                note=f"tau {item.name}" if item.error is None else "",
                error=item.error,
            )
        )
    return rows


def inventory(config: Config | None) -> list[ComponentRow]:
    """Every component in every ``tau.*`` group, in :data:`registry.GROUPS` order.

    Without a ``config`` nothing is disabled and providers/backends show as ``available``.
    """
    components = config.components if config is not None else None
    rows: list[ComponentRow] = []
    rows += _tool_rows(config)
    rows += _command_rows()
    rows += _seeded_rows(registry.PROVIDERS_GROUP, config)
    rows += _seeded_rows(registry.SESSIONS_GROUP, config)
    rows += _switched_rows(registry.CONTEXT_GROUP, components.context if components else ())
    rows += _switched_rows(
        registry.HUB_SERVICES_GROUP, components.hub_services if components else ()
    )
    return rows


def format_inventory(rows: list[ComponentRow]) -> list[str]:
    """The text lines ``tau components`` prints: one heading per group, aligned columns."""
    lines: list[str] = []
    for group in registry.GROUPS:
        group_rows = [row for row in rows if row.group == group]
        lines.append(group)
        if not group_rows:
            lines.append("  (none)")
            continue
        name_w = max(len(row.name) for row in group_rows)
        dist_w = max(len(f"{row.distribution} {row.version}") for row in group_rows)
        for row in group_rows:
            state = "enabled" if row.enabled else ("error" if row.error else "disabled")
            tail = f"error: {row.error}" if row.error else row.note
            source = "" if row.source == "entry point" else f" ({row.source})"
            lines.append(
                f"  {row.name:<{name_w}}  {f'{row.distribution} {row.version}':<{dist_w}}"
                f"  {state:<8} {tail}{source}".rstrip()
            )
    return lines


def _load_config_or_none(home: Path | None) -> tuple[Config | None, str | None]:
    try:
        return Config.load(home), None
    except ConfigError as exc:
        return None, str(exc)


@click.command(
    name="components",
    help="List every component tau can see: tools, commands, providers, session backends, "
    "context sources and hub services, with their distribution, version, whether "
    "[components] enables them and any load error.",
    short_help="List installed components and their state.",
)
@help_option()
@click.option("--json", "as_json", is_flag=True, help="Print the listing as JSON.")
@click.pass_context
def components(ctx: click.Context, as_json: bool) -> None:
    obj = ctx.find_object(dict) or {}
    config, problem = _load_config_or_none(obj.get("home"))
    rows = inventory(config)
    if as_json:
        payload = {"config_error": problem, "components": [asdict(row) for row in rows]}
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if problem is not None:
        click.echo(f"note: {problem} Enabled/disabled reflects no configuration.", err=True)
    for line in format_inventory(rows):
        click.echo(line)


# -- tau doctor ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    """One ``tau doctor`` result: ``status`` is ``ok``, ``warn``, ``fail`` or ``info``."""

    name: str
    status: str
    detail: str


def _check_config(
    home: Path | None, env: Mapping[str, str] | None
) -> tuple[Config | None, list[Check]]:
    try:
        config = Config.load(home, env=env)
    except ConfigError as exc:
        return None, [Check("config", "fail", str(exc))]
    checks = [Check("config", "ok", f"{config.home / CONFIG_FILE} loaded")]
    try:
        raw = tomllib.loads((config.home / CONFIG_FILE).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):  # pragma: no cover - Config.load read it already
        raw = {}
    unknown = sorted(set(raw) - KNOWN_TABLES)
    if unknown:
        tables = ", ".join(f"[{name}]" for name in unknown)
        checks.append(Check("config", "warn", f"unknown top-level tables are ignored: {tables}"))
    return config, checks


def _check_role(name: str, role: RoleConfig, env: Mapping[str, str]) -> Check:
    provider = role.provider
    if registry.provider_factory(provider) is None:
        if provider in PLANNED_PROVIDERS:
            return Check(
                f"role {name}",
                "warn",
                f"provider '{provider}' is not available until issue {PLANNED_PROVIDERS[provider]}",
            )
        broken = registry.load_error(registry.PROVIDERS_GROUP, provider)
        if broken is not None:
            return Check(f"role {name}", "fail", provider_load_failure(provider, broken))
        return Check(f"role {name}", "fail", f"unknown provider '{provider}'")
    try:
        missing = missing_credentials(role, env)
    except ConfigError as exc:
        return Check(f"role {name}", "fail", str(exc))
    if not missing:
        needs = registry.provider_required_env(provider) or provider in ("bedrock", "anthropic")
        detail = "credentials present" if needs else "needs no credentials"
        return Check(f"role {name}", "ok", f"provider '{provider}', {detail}")
    fallback = role.fallback
    if fallback is not None and registry.provider_factory(fallback.provider) is not None:
        try:
            fallback_missing = missing_credentials(fallback, env)
        except ConfigError:
            fallback_missing = ["?"]
        if not fallback_missing:
            return Check(
                f"role {name}",
                "warn",
                f"provider '{provider}' is missing {', '.join(missing)}; the fallback "
                f"'{fallback.provider}' has credentials and will be used",
            )
    return Check(
        f"role {name}",
        "fail",
        f"provider '{provider}' is missing {', '.join(missing)} (names are in .env.example)",
    )


def _check_sessions(config: Config) -> Check:
    backend = config.sessions.backend
    try:
        store = open_session_store(config)
        store.list_sessions(limit=1)
    except ConfigError as exc:
        status = "warn" if backend in PLANNED_BACKENDS else "fail"
        return Check("sessions", status, str(exc))
    except Exception as exc:
        return Check("sessions", "fail", f"backend '{backend}' failed to open: {exc}")
    where = f" under {config.sessions_dir}" if backend == "file" else ""
    return Check("sessions", "ok", f"backend '{backend}' opens{where}")


def _check_persona(config: Config) -> list[Check]:
    loader = PersonaLoader(config.persona_dir)
    checks: list[Check] = []
    try:
        persona = loader.read()
    except ConfigError as exc:
        checks.append(Check("persona", "fail", str(exc)))
        return checks
    checks.append(Check("persona", "ok", f"{loader.persona_path} present and non-empty"))
    if persona.user:
        checks.append(Check("persona", "ok", f"{loader.user_path} present"))
    else:
        state = "is empty" if loader.user_path.is_file() else "is missing"
        checks.append(
            Check(
                "persona",
                "warn",
                f"{loader.user_path} {state}: tau addresses you formally and knows nothing "
                "about you (start from persona/user.example.md)",
            )
        )
    return checks


def env_names(text: str) -> set[str]:
    """Variable names in dotenv text, commented-out ``# NAME=`` lines included."""
    names: set[str] = set()
    for line in text.splitlines():
        match = _ENV_NAME.match(line)
        if match:
            names.add(match.group(1))
    return names


def _check_dotenv(config: Config) -> Check:
    dotenv = config.home / ".env"
    example = config.home / ".env.example"
    if not dotenv.is_file():
        return Check(".env", "info", f"no {dotenv}; credentials come from the environment")
    if not example.is_file():
        return Check(".env", "info", f"no {example} to compare {dotenv.name} against")
    try:
        unknown = sorted(
            env_names(dotenv.read_text(encoding="utf-8"))
            - env_names(example.read_text(encoding="utf-8"))
        )
    except OSError as exc:
        return Check(".env", "warn", f"could not read {dotenv} or {example}: {exc}")
    if unknown:
        return Check(
            ".env",
            "warn",
            f"names in {dotenv.name} that {example.name} does not list: {', '.join(unknown)}",
        )
    return Check(".env", "ok", f"every name in {dotenv.name} is listed in {example.name}")


def _check_hub(config: Config) -> Check:
    url = f"http://127.0.0.1:{config.hub.control_port}/health"
    try:
        with _OPENER.open(url, timeout=HEALTH_TIMEOUT) as response:
            status, body = response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return Check("hub", "warn", f"control API answered {exc.code} on {url}")
    except (OSError, ValueError):
        return Check("hub", "info", f"hub is not running (nothing answers on {url})")
    except Exception as exc:  # e.g. http.client.IncompleteRead: a check must never raise
        logger.warning("hub check failed on %s: %s: %s", url, type(exc).__name__, exc)
        return Check(
            "hub", "warn", f"control API check failed on {url}: {type(exc).__name__}: {exc}"
        )
    if status == 200 and isinstance(body, dict) and body.get("ok"):
        return Check(
            "hub",
            "ok",
            f"hub is running (pid {body.get('pid', '?')}, up {body.get('uptime_s', '?')} s)",
        )
    return Check("hub", "warn", f"control API answered {status} on {url}: {body!r}")


def _check_components(config: Config) -> list[Check]:
    """Load errors, then every ``[components]`` name that no installed component answers to
    (a typo there would otherwise only show as a warning when the agent or the hub starts)."""
    rows = inventory(config)
    broken = [
        f"{row.group}:{row.name} ({row.distribution}): {row.error}" for row in rows if row.error
    ]
    checks = [
        Check("components", "warn", "failed to load: " + "; ".join(broken))
        if broken
        else Check("components", "ok", "every component loads")
    ]
    unknown = unknown_component_names(config, rows)
    if unknown:
        listed = "; ".join(f"{where}: {', '.join(names)}" for where, names in unknown.items())
        checks.append(
            Check(
                "components",
                "warn",
                f"[components] names no installed component provides: {listed} "
                "(see `tau components`)",
            )
        )
    return checks


def unknown_component_names(config: Config, rows: list[ComponentRow]) -> dict[str, list[str]]:
    """``{"[components] context": [...], ...}`` for the names in ``[components]`` that match
    nothing in ``rows`` (``tools.disabled`` entries match a tool name or ``dist:<distribution>``
    of a listed tool)."""
    components = config.components
    tools = [row for row in rows if row.group == registry.TOOLS_GROUP]
    tool_names = {row.name for row in tools}
    tool_dists = {f"{DIST_PREFIX}{row.distribution}" for row in tools}
    found: dict[str, list[str]] = {}
    unknown_tools = [
        name for name in components.tools_disabled if name not in tool_names | tool_dists
    ]
    if unknown_tools:
        found["[components.tools] disabled"] = unknown_tools
    for where, wanted, group in (
        ("[components] context", components.context, registry.CONTEXT_GROUP),
        ("[components.hub] services", components.hub_services, registry.HUB_SERVICES_GROUP),
    ):
        names = {row.name for row in rows if row.group == group}
        missing = [name for name in wanted if name not in names]
        if missing:
            found[where] = missing
    return found


def run_doctor(home: Path | None = None, *, env: Mapping[str, str] | None = None) -> list[Check]:
    """Every check, in order; a ``fail`` in ``config`` stops the rest (they need it).

    With ``env=None`` the process environment is used and ``<home>/.env`` is loaded into it,
    exactly as ``tau chat`` does; an explicit mapping is merged with ``.env`` without touching
    the process (tests).
    """
    config, checks = _check_config(home, env)
    if config is None:
        return checks
    env = os.environ if env is None else env_with_dotenv(config.home, env)
    for name, role in config.roles.items():
        checks.append(_check_role(name, role, env))
    checks.append(_check_sessions(config))
    checks += _check_persona(config)
    checks.append(_check_dotenv(config))
    checks += _check_components(config)
    checks.append(_check_hub(config))
    return checks


def format_checks(checks: list[Check]) -> list[str]:
    lines = [f"{check.status:<4} {check.name}: {check.detail}" for check in checks]
    counts = {
        status: sum(1 for c in checks if c.status == status) for status in ("ok", "warn", "fail")
    }
    lines.append(
        f"{len(checks)} checks: {counts['ok']} ok, {counts['warn']} warnings, "
        f"{counts['fail']} failed"
    )
    return lines


@click.command(
    name="doctor",
    help="Check the installation: tau.toml, each role's provider and credentials (no model "
    "client is built), the session store, the persona files, .env against .env.example, "
    "component load errors, [components] names nothing provides and whether a hub answers on "
    "the control API. Exit 1 when a check fails.",
    short_help="Check the installation.",
)
@help_option()
@click.option("--json", "as_json", is_flag=True, help="Print the checks as JSON.")
@click.pass_context
def doctor(ctx: click.Context, as_json: bool) -> None:
    obj = ctx.find_object(dict) or {}
    checks = run_doctor(obj.get("home"))
    failed = any(check.status == "fail" for check in checks)
    if as_json:
        click.echo(
            json.dumps(
                {"ok": not failed, "checks": [asdict(c) for c in checks]},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for line in format_checks(checks):
            click.echo(line)
    if failed:
        ctx.exit(1)


# -- tau init --------------------------------------------------------------------------------


@dataclass(frozen=True)
class InitResult:
    home: Path
    provider: str
    language: str
    written: tuple[Path, ...]
    kept: tuple[Path, ...]


def pick_provider(env: Mapping[str, str]) -> str:
    """The first of :data:`PROVIDER_PREFERENCE` whose credentials are in ``env``."""
    for provider in PROVIDER_PREFERENCE:
        probe = RoleConfig(provider=provider, model_id="probe")
        if not missing_credentials(probe, env):
            return provider
    return PROVIDER_PREFERENCE[-1]  # pragma: no cover - fake needs nothing


def model_ids(provider: str) -> dict[str, str]:
    """``{role: model_id}`` for ``provider`` from the shipped ``models.toml`` (data, not code)."""
    table = tomllib.loads(template_text("models.toml"))
    ids = table.get(provider)
    if not isinstance(ids, dict):
        raise ConfigError(f"tau init has no model ids for provider '{provider}'.")
    return {role: str(model_id) for role, model_id in ids.items()}


_HEADER = re.compile(r"^\s*\[([^\]]+)\]")
_PROVIDER_LINE = re.compile(r'^(provider\s*=\s*)"[^"]*"(.*)$')
_MODEL_ID_LINE = re.compile(r'^(model_id\s*=\s*)"[^"]*"(.*)$')
_LANGUAGE_LINE = re.compile(r'^(language\s*=\s*)"[^"]*"(.*)$')


def render_config(template: str, *, provider: str, language: str) -> str:
    """The template with ``provider``/``model_id`` rewritten for :data:`INIT_ROLES`, the
    ``[models.roles.brain.fallback]`` table dropped when the provider is not ``bedrock`` (the
    fallback only makes sense for it), and ``[ui] language`` set. Comments survive."""
    ids = model_ids(provider)
    out: list[str] = []
    table: str | None = None
    skipping = False
    for line in template.splitlines():
        header = _HEADER.match(line)
        if header:
            table = header.group(1).strip()
            skipping = table == "models.roles.brain.fallback" and provider != "bedrock"
        if skipping:
            continue
        role = (
            table.removeprefix("models.roles.")
            if table and table.startswith("models.roles.")
            else None
        )
        if role in INIT_ROLES and (match := _PROVIDER_LINE.match(line)):
            line = f'{match.group(1)}"{provider}"{match.group(2)}'
        elif role in INIT_ROLES and (match := _MODEL_ID_LINE.match(line)):
            line = f'{match.group(1)}"{ids[role]}"{match.group(2)}'
        elif table == "ui" and (match := _LANGUAGE_LINE.match(line)):
            line = f'{match.group(1)}"{language}"{match.group(2)}'
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).rstrip("\n") + "\n"


def default_home(env: Mapping[str, str]) -> Path:
    return Path(env.get("TAU_HOME") or DEFAULT_HOME).expanduser().resolve()


def init_home(
    home: Path,
    *,
    provider: str,
    language: str,
    profile: str | None = None,
    force: bool = False,
) -> InitResult:
    """Write ``tau.toml``, the persona files, ``.env.example`` and, with ``profile``,
    ``TAU_PROFILE`` in ``.env``.

    ``tau.toml``, ``persona.md`` and ``user.example.md`` are never overwritten without ``force``;
    ``user.md`` (personal facts) and ``.env.example`` (the list of names ``tau doctor`` checks
    ``.env`` against, which the user extends) are never overwritten at all, and ``.env`` is only
    appended to. Raises ``FileExistsError`` for an existing ``tau.toml`` without ``force`` and
    ``ConfigError`` when the written file does not load.
    """
    home = Path(home).expanduser().resolve()
    config_path = home / CONFIG_FILE
    if config_path.exists() and not force:
        raise FileExistsError(f"{config_path} already exists. Use --force to overwrite it.")
    home.mkdir(parents=True, exist_ok=True)
    persona_dir = home / "persona"
    persona_dir.mkdir(exist_ok=True)
    written: list[Path] = []
    kept: list[Path] = []

    config_path.write_text(
        render_config(template_text(CONFIG_FILE), provider=provider, language=language),
        encoding="utf-8",
    )
    written.append(config_path)
    for name in ("persona.md", "user.example.md"):
        target = persona_dir / name
        if target.exists() and not force:
            kept.append(target)
            continue
        target.write_text(template_text(name), encoding="utf-8")
        written.append(target)
    for target, template in (
        (persona_dir / "user.md", "user.example.md"),
        (home / ".env.example", "dotenv.example"),
    ):
        if target.exists():
            kept.append(target)
        else:
            target.write_text(template_text(template), encoding="utf-8")
            written.append(target)
    if profile:
        dotenv = home / ".env"
        existing = dotenv.read_text(encoding="utf-8") if dotenv.is_file() else ""
        if "TAU_PROFILE" in env_names(existing):
            kept.append(dotenv)
        else:
            text = existing if not existing or existing.endswith("\n") else existing + "\n"
            dotenv.write_text(f"{text}TAU_PROFILE={profile}\n", encoding="utf-8")
            written.append(dotenv)
    Config.load(home, env={})  # the template must produce a loadable file; ConfigError otherwise
    return InitResult(home, provider, language, tuple(written), tuple(kept))


_NEXT_STEPS = {
    "bedrock": "AWS credentials were found in the environment or <home>/.env (AWS_REGION plus "
    "a profile, keys or a bearer token).",
    "anthropic": "ANTHROPIC_API_KEY was found in the environment or <home>/.env.",
    "fake": "No model credentials were found in the environment or <home>/.env, so both roles "
    "use the scripted 'fake' provider. Add AWS or Anthropic credentials to <home>/.env (names "
    "are in <home>/.env.example) and run `tau init --force`, or edit tau.toml.",
}


@click.command(
    name="init",
    help="Set up a configuration root: tau.toml from the shipped template (provider picked "
    "from the credentials present in the environment or <home>/.env: bedrock, then anthropic, "
    "else fake), persona/persona.md, persona/user.example.md, persona/user.md (from the "
    "example, unless it exists) and .env.example (the variable names). Existing files are kept "
    "unless --force is given; user.md and .env.example are never overwritten.",
    short_help="Create tau.toml and the persona files.",
)
@help_option()
@click.option(
    "--home",
    "home_option",
    type=click.Path(file_okay=False, path_type=Path),
    metavar="DIR",
    help="Configuration root to create (default: TAU_HOME, else ~/.tau).",
)
@click.option(
    "--provider",
    type=click.Choice(PROVIDER_PREFERENCE),
    metavar="NAME",
    help="Provider for the brain and fast roles (default: the first with credentials).",
)
@click.option(
    "--language",
    type=click.Choice(LANGUAGES),
    metavar="LANG",
    help=f"UI language, {' | '.join(LANGUAGES)} (asked when not given, unless --yes).",
)
@click.option(
    "--profile",
    type=click.Choice(PROFILES),
    metavar="NAME",
    help="Write TAU_PROFILE=NAME into <home>/.env (appended; an existing value is kept).",
)
@click.option("-y", "--yes", is_flag=True, help="Ask nothing; use defaults for what is not given.")
@click.option("--force", is_flag=True, help="Overwrite an existing tau.toml and persona.md.")
@click.pass_context
def init(
    ctx: click.Context,
    home_option: Path | None,
    provider: str | None,
    language: str | None,
    profile: str | None,
    yes: bool,
    force: bool,
) -> None:
    home = home_option.expanduser().resolve() if home_option else default_home(os.environ)
    if (home / CONFIG_FILE).exists() and not force:
        click.echo(f"{home / CONFIG_FILE} already exists. Use --force to overwrite it.", err=True)
        ctx.exit(1)
    if provider is None:
        provider = pick_provider(env_with_dotenv(home, os.environ))
        click.echo(f"Provider: {provider}. {_NEXT_STEPS[provider].replace('<home>', str(home))}")
    if language is None:
        language = (
            DEFAULT_LANGUAGE
            if yes
            else click.prompt(
                "UI language",
                type=click.Choice(LANGUAGES),
                default=DEFAULT_LANGUAGE,
                show_choices=True,
            )
        )
    try:
        result = init_home(home, provider=provider, language=language, profile=profile, force=force)
    except FileExistsError as exc:
        click.echo(str(exc), err=True)
        ctx.exit(1)
    except (ConfigError, OSError) as exc:
        click.echo(f"tau init failed: {exc}", err=True)
        ctx.exit(1)
    for path in result.written:
        click.echo(f"wrote {path}")
    for path in result.kept:
        click.echo(f"kept  {path}")
    click.echo(f"Configuration root: {result.home} (UI language: {result.language}).")
    click.echo("Next: edit persona/user.md, then run `tau doctor` and `tau chat`.")
