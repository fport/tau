"""Edit the bootstrap config (``tau.toml`` and ``.env``) from a channel.

``Config`` reads the two files once at start-up; this module is the small, testable editor
behind ``/settings`` in the terminal and the settings screen of the TUI. ``tau.toml`` is edited
through tomlkit so comments and layout survive; ``.env`` through python-dotenv's ``set_key`` /
``unset_key``. Both files are written atomically and ``.env`` is kept at mode ``0600``.

Credential *values* never leave this module: nothing here logs, prints or returns one (the
only value that passes through is the argument of :func:`set_credential`), and the UI shows
:func:`mask` output or a ``set`` / ``not set`` flag. Runtime *Settings* (the hot-reloaded file
under ``TAU_DATA_DIR``, issue 019) are a different thing and not touched here.
"""

from __future__ import annotations

import logging
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomlkit
from dotenv import dotenv_values, set_key, unset_key
from tomlkit import TOMLDocument
from tomlkit.items import Table

from tau_core.builder import env_names, env_with_dotenv, provider_probe
from tau_core.config import (
    CONFIG_FILE,
    CONTEXT_MODES,
    Config,
    ConfigError,
    RoleConfig,
    resolve_home,
)
from tau_core.i18n import DEFAULT_LANGUAGE, LANGUAGES, t
from tau_core.models import PLANNED_PROVIDERS, missing_credentials, required_env

__all__ = [
    "AGENT_KEYS",
    "KEEP",
    "CredentialStatus",
    "HomeFiles",
    "check_document",
    "clear_credential",
    "configured_providers",
    "credential_names_for",
    "credential_present",
    "credential_source",
    "credential_status",
    "default_home",
    "describe_home",
    "is_secret_name",
    "known_env_names",
    "known_providers",
    "load_document",
    "mask",
    "masked_credential",
    "report_lines",
    "roles_in",
    "save_document",
    "set_agent_option",
    "set_credential",
    "set_role",
    "set_ui_language",
    "status_text",
    "tilde_path",
    "validate",
]

logger = logging.getLogger(__name__)

AGENT_KEYS = ("context", "window_size", "max_turns", "max_total_tokens")
"""The ``[agent]`` keys :func:`set_agent_option` accepts."""
DOTENV_FILE = ".env"
DOTENV_EXAMPLE = ".env.example"
PRIVATE_MODE = 0o600
PRIVATE_DIR_MODE = 0o700
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "_FP")
"""A variable whose name carries one of these is a secret (``ANTHROPIC_API_KEY``,
``AWS_BEARER_TOKEN_BEDROCK``, ``AWS_SECRET_ACCESS_KEY``, ``TAU_HOST_FP``); the rest
(``AWS_REGION``, ``TAU_PROFILE``, ``TELEGRAM_ALLOWED_CHAT_IDS``) are plain settings."""


class _Keep:
    """Sentinel: leave the key as it is (``None`` means *remove it*)."""

    def __repr__(self) -> str:  # pragma: no cover - repr only
        return "KEEP"


KEEP: Any = _Keep()


# -- where things are --------------------------------------------------------------------------


def default_home(env: Mapping[str, str] | None = None) -> Path:
    """The home ``Config.load()`` would pick without an argument (see ``resolve_home``)."""
    return resolve_home(None, env)


@dataclass(frozen=True)
class HomeFiles:
    """The files of a configuration root and whether each exists (for the Files section)."""

    home: Path
    config: Path
    dotenv: Path
    dotenv_example: Path
    persona: Path
    user: Path

    def exists(self, name: str) -> bool:
        return getattr(self, name).is_file()

    def rows(self) -> list[tuple[str, Path, bool]]:
        """``(label, path, exists)`` in display order."""
        return [
            (label, getattr(self, name), self.exists(name))
            for name, label in (
                ("config", CONFIG_FILE),
                ("dotenv", DOTENV_FILE),
                ("dotenv_example", DOTENV_EXAMPLE),
                ("persona", "persona/persona.md"),
                ("user", "persona/user.md"),
            )
        ]


def describe_home(home: Path | str) -> HomeFiles:
    root = Path(home).expanduser().resolve()
    return HomeFiles(
        home=root,
        config=root / CONFIG_FILE,
        dotenv=root / DOTENV_FILE,
        dotenv_example=root / DOTENV_EXAMPLE,
        persona=root / "persona" / "persona.md",
        user=root / "persona" / "user.md",
    )


def tilde_path(path: Path | str) -> str:
    """``~/.tau/tau.toml`` for a path under the user's home, else the path as it is: what the
    ``/settings`` report and the Files section print (the same rule as ``/session``)."""
    path = Path(path)
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


# -- tau.toml ------------------------------------------------------------------------------------


def load_document(home: Path | str) -> TOMLDocument:
    """``<home>/tau.toml`` as a tomlkit document (comments and layout kept)."""
    path = Path(home).expanduser().resolve() / CONFIG_FILE
    try:
        return tomlkit.parse(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {path}.") from exc
    except (OSError, ValueError) as exc:  # tomlkit's parse errors are ValueErrors
        raise ConfigError(f"Configuration file could not be read: {path}: {exc}") from exc


def _table(parent: Any, key: str, where: str) -> Table:
    """``parent[key]`` as a table, created when absent; a non-table value is a ``ConfigError``."""
    if key not in parent:
        parent[key] = tomlkit.table()
    value = parent[key]
    if not isinstance(value, Table):
        raise ConfigError(f"tau.toml: {where} must be a table.")
    return value


def roles_in(doc: TOMLDocument) -> list[str]:
    """The role names of ``[models.roles]`` in file order (``[]`` when there are none)."""
    models = doc.get("models")
    roles = models.get("roles") if isinstance(models, Table) else None
    return list(roles.keys()) if isinstance(roles, Table) else []


def _positive_int(raw: Any, where: str, key: str) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise ConfigError(f"tau.toml: {where} '{key}' must be an integer of 1 or more.")
    return raw


def _name(raw: Any, where: str, key: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ConfigError(f"tau.toml: {where} needs a '{key}'.")
    return raw.strip()


def _refuse_planned(provider: str, where: str) -> None:
    """A save never *introduces* a planned provider: the next start would stop with
    ``Provider '…' is not supported yet`` and a channel without an editor could not recover.
    A role that already names one (the shipped ``local`` role) is left as it is."""
    providers = dict(known_providers())
    if providers.get(provider):
        available = ", ".join(name for name, planned in providers.items() if not planned)
        raise ConfigError(
            f"tau.toml: {where} provider '{provider}' is not supported yet "
            f"(issue {PLANNED_PROVIDERS[provider]}); available: {available}."
        )


def _planned_uses(doc: TOMLDocument) -> set[tuple[str, str, str]]:
    """``{(role, "provider" | "fallback", name)}`` for every planned provider the document
    names, so :func:`check_document` can tell a new use from one that was already there."""
    uses: set[tuple[str, str, str]] = set()
    planned = {name for name, is_planned in known_providers() if is_planned}
    if not planned or not roles_in(doc):
        return uses
    for role, table in doc["models"]["roles"].items():
        if not isinstance(table, Table):
            continue
        for slot, cfg in (("provider", table), ("fallback", table.get("fallback"))):
            provider = cfg.get("provider") if isinstance(cfg, Table) else None
            if isinstance(provider, str) and provider in planned:
                uses.add((role, slot, provider))
    return uses


def set_role(
    doc: TOMLDocument,
    role: str,
    provider: str,
    model_id: str,
    *,
    max_tokens: int | None | Any = KEEP,
    fallback: tuple[str, str] | None | Any = KEEP,
) -> None:
    """Write ``[models.roles.<role>]``: ``provider`` and ``model_id`` always, ``max_tokens`` and
    ``fallback`` (``(provider, model_id)``) when given; ``None`` removes the key or the table,
    :data:`KEEP` (the default) leaves it as it is. Other keys (``region``, ``params``,
    ``cache``) are untouched. Validation mirrors ``Config``, and a planned provider (``ollama``
    until issue 012) is refused unless the role, or its fallback, already names it; nothing
    is written to disk."""
    where = f"[models.roles.{role}]"
    if not _ENV_NAME.match(role):
        raise ConfigError(f"tau.toml: invalid role name {role!r}.")
    models = _table(doc, "models", "[models]")
    roles = _table(models, "roles", "[models.roles]")
    table = _table(roles, role, where)
    provider = _name(provider, where, "provider")
    if provider != table.get("provider"):
        _refuse_planned(provider, where)
    table["provider"] = provider
    table["model_id"] = _name(model_id, where, "model_id")
    if max_tokens is None:
        table.pop("max_tokens", None)
    elif max_tokens is not KEEP:
        table["max_tokens"] = _positive_int(max_tokens, where, "max_tokens")
    if fallback is None:
        table.pop("fallback", None)
    elif fallback is not KEEP:
        fb_provider, fb_model = fallback
        sub_where = f"[models.roles.{role}.fallback]"
        existing = table.get("fallback")
        fb_provider = _name(fb_provider, sub_where, "provider")
        if not isinstance(existing, Table) or fb_provider != existing.get("provider"):
            _refuse_planned(fb_provider, sub_where)
        if isinstance(existing, Table):
            existing["provider"] = fb_provider
            existing["model_id"] = _name(fb_model, sub_where, "model_id")
        else:
            new = tomlkit.table()
            new["provider"] = fb_provider
            new["model_id"] = _name(fb_model, sub_where, "model_id")
            new.add(tomlkit.nl())
            table["fallback"] = new


def set_ui_language(doc: TOMLDocument, language: str) -> None:
    """``[ui] language``; must be one of :data:`tau_core.i18n.LANGUAGES`."""
    if language not in LANGUAGES:
        raise ConfigError(
            f"tau.toml: [ui] 'language' must be one of {', '.join(LANGUAGES)}, not {language!r}."
        )
    _table(doc, "ui", "[ui]")["language"] = language


def set_agent_option(doc: TOMLDocument, key: str, value: Any) -> None:
    """``[agent] <key>`` with ``Config``'s validation: ``context`` is ``sliding`` or
    ``summarize``; ``window_size`` and ``max_turns`` are integers of 1 or more;
    ``max_total_tokens`` is such an integer or ``None`` (the key is removed)."""
    if key not in AGENT_KEYS:
        raise ConfigError(f"tau.toml: [agent] has no option {key!r} (use {', '.join(AGENT_KEYS)}).")
    agent = _table(doc, "agent", "[agent]")
    if key == "context":
        if not isinstance(value, str) or value not in CONTEXT_MODES:
            raise ConfigError(
                f"tau.toml: [agent] 'context' must be one of {', '.join(CONTEXT_MODES)}, "
                f"not {value!r}."
            )
        agent[key] = value
        return
    if key == "max_total_tokens" and value is None:
        agent.pop(key, None)
        return
    agent[key] = _positive_int(value, "[agent]", key)


def _atomic_write(path: Path, text: str, *, mode: int | None) -> None:
    """Write ``text`` to a temp file next to ``path`` and rename it over; ``mode`` when given."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def check_document(doc: TOMLDocument, *, previous: TOMLDocument | None = None) -> Config:
    """Load the document through ``Config`` without touching the real files (a temp directory
    holds the rendered text, no ``.env``, an empty environment): a ``ConfigError`` here is
    the one the user would get at the next start.

    ``Config`` accepts a planned provider by name (``ollama`` until issue 012) although a
    role on it cannot start, so this check refuses one too — every use when ``previous`` is
    ``None``, only the uses ``previous`` (the document as it is on disk) did not already
    have otherwise, so the shipped ``local`` role never blocks an unrelated save."""
    with tempfile.TemporaryDirectory(prefix="tau-settings-") as tmp:
        Path(tmp, CONFIG_FILE).write_text(tomlkit.dumps(doc), encoding="utf-8")
        config = Config.load(tmp, env={})
    known = _planned_uses(previous) if previous is not None else set()
    for role, slot, provider in sorted(_planned_uses(doc) - known):
        suffix = "" if slot == "provider" else ".fallback"
        _refuse_planned(provider, f"[models.roles.{role}{suffix}]")
    return config


def save_document(home: Path | str, doc: TOMLDocument, *, check: bool = True) -> Path:
    """Write the document back to ``<home>/tau.toml`` atomically (temp file + rename), after
    :func:`check_document` against the file as it is unless ``check=False``: a document
    ``Config`` refuses, or one that newly names a planned provider, is never written. The
    file keeps its mode; a new one gets the process default."""
    if check:
        try:
            previous: TOMLDocument | None = load_document(home)
        except ConfigError:
            previous = None
        check_document(doc, previous=previous)
    path = Path(home).expanduser().resolve() / CONFIG_FILE
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    _atomic_write(path, tomlkit.dumps(doc), mode=mode)
    return path


def validate(home: Path | str, *, env: Mapping[str, str] | None = None) -> Config:
    """Load the saved files with ``Config.load`` and return the ``Config`` (``ConfigError``
    otherwise), so a channel can show the problem before it rebuilds anything. With
    ``env=None`` the process environment is used, exactly as a fresh start would."""
    return Config.load(home, env=env)


# -- .env ----------------------------------------------------------------------------------------


def _dotenv_path(home: Path | str) -> Path:
    return Path(home).expanduser().resolve() / DOTENV_FILE


def _check_name(name: str) -> str:
    if not _ENV_NAME.match(name):
        raise ValueError(f"invalid variable name: {name!r}")
    return name


def _make_private(path: Path) -> None:
    try:
        os.chmod(path, PRIVATE_MODE)
    except OSError:  # pragma: no cover - a filesystem without modes
        logger.warning("could not set the mode of %s", path)


def set_credential(home: Path | str, name: str, value: str, *, export: bool = False) -> Path:
    """Set ``NAME=value`` in ``<home>/.env`` (created private, mode ``0600``, when missing;
    kept private afterwards; a home directory this creates is mode ``0700``). Surrounding
    whitespace is stripped (a pasted key often carries a newline) and the value must not be
    empty after that. With ``export`` the running process sees the new value too
    (``os.environ``), so a rebuilt agent picks it up; the value is never logged."""
    _check_name(name)
    value = value.strip() if isinstance(value, str) else ""
    if not value:
        raise ValueError(f"{name}: the value must not be empty")
    path = _dotenv_path(home)
    if not path.exists():
        if not path.parent.is_dir():
            path.parent.mkdir(parents=True, mode=PRIVATE_DIR_MODE)
            try:
                os.chmod(path.parent, PRIVATE_DIR_MODE)  # the umask may have widened it
            except OSError:  # pragma: no cover - a filesystem without modes
                logger.warning("could not set the mode of %s", path.parent)
        path.touch(mode=PRIVATE_MODE)
        _make_private(path)
    set_key(path, name, value, quote_mode="auto")
    _make_private(path)
    if export:
        os.environ[name] = value
    logger.info("%s: %s set", path.name, name)
    return path


def clear_credential(home: Path | str, name: str, *, export: bool = False) -> bool:
    """Remove ``NAME`` from ``<home>/.env`` (and, with ``export``, from ``os.environ``).
    ``False`` when the file or the name is not there; never an error."""
    _check_name(name)
    path = _dotenv_path(home)
    removed = False
    if path.is_file() and name in dotenv_values(path):
        unset_key(path, name, quote_mode="auto")
        _make_private(path)
        removed = True
        logger.info("%s: %s cleared", path.name, name)
    if export:
        os.environ.pop(name, None)
    return removed


def credential_names_for(provider: str) -> list[list[str]]:
    """The credential alternatives of a provider (each inner list must be fully set), read
    from ``models.required_env``; ``[]`` for a provider that needs none, is planned or is
    unknown (nothing to ask for). For the proxy it is the brain role's key; the other roles'
    keys come from ``.env.example``."""
    try:
        return required_env(provider_probe(provider))
    except ConfigError:
        return []


@dataclass(frozen=True)
class CredentialStatus:
    """What :func:`credential_status` found for one role.

    ``state`` is ``ok`` (an alternative is fully set), ``none`` (the provider needs no
    credentials), ``fallback`` (the primary is missing something but the fallback has its
    credentials) or ``missing`` (nothing usable; ``missing`` names what the closest
    alternative lacks). ``unavailable`` marks a provider that cannot be resolved at all
    (planned, unknown or broken), with the reason in ``detail``.
    """

    state: str
    missing: list[str] = field(default_factory=list)
    satisfied: list[str] = field(default_factory=list)
    fallback_provider: str | None = None
    detail: str = ""


def _satisfied(alternatives: list[list[str]], env: Mapping[str, str]) -> list[str]:
    for alt in alternatives:
        if all(env.get(name) for name in alt):
            return list(alt)
    return []


def credential_status(
    home: Path | str, role_cfg: RoleConfig, env: Mapping[str, str] | None = None
) -> CredentialStatus:
    """Which alternative a role's provider is satisfied by, or what is missing, from ``env``
    on top of ``<home>/.env`` (the rule of ``Config.load``). Values are never returned."""
    merged = env_with_dotenv(Path(home).expanduser().resolve(), os.environ if env is None else env)
    try:
        alternatives = required_env(role_cfg)
    except ConfigError as exc:
        return CredentialStatus("unavailable", detail=str(exc))
    if not alternatives:
        return CredentialStatus("none")
    missing = missing_credentials(role_cfg, merged)
    if not missing:
        return CredentialStatus("ok", satisfied=_satisfied(alternatives, merged))
    fallback = role_cfg.fallback
    if fallback is not None:
        try:
            fallback_missing = missing_credentials(fallback, merged)
        except ConfigError:
            fallback_missing = ["?"]
        if not fallback_missing:
            return CredentialStatus(
                "fallback", missing=list(missing), fallback_provider=fallback.provider
            )
    return CredentialStatus("missing", missing=list(missing))


def known_providers() -> list[tuple[str, bool]]:
    """``[(name, planned), ...]``: every provider ``tau.toml`` may name, sorted, the built-in
    seed and every ``tau.providers`` component first, then the planned ones."""
    from tau_core import registry

    available = sorted(registry.provider_names())
    planned = sorted(name for name in PLANNED_PROVIDERS if name not in available)
    return [(name, False) for name in available] + [(name, True) for name in planned]


def configured_providers(home: Path | str) -> list[str]:
    """The providers ``<home>/tau.toml`` names, fallbacks included, in file order (``[]`` when
    the file is missing or unreadable)."""
    try:
        doc = load_document(home)
    except ConfigError:
        return []
    providers: list[str] = []
    roles = doc["models"]["roles"] if roles_in(doc) else {}
    for role in roles.values():
        if not isinstance(role, Table):
            continue
        for cfg in (role, role.get("fallback")):
            provider = cfg.get("provider") if isinstance(cfg, Table) else None
            if isinstance(provider, str) and provider not in providers:
                providers.append(provider)
    return providers


def known_env_names(home: Path | str, *, providers: list[str] | None = None) -> list[str]:
    """The variable names a Credentials editor should list, in this order: the credentials of
    ``providers`` (default: the providers named in ``<home>/tau.toml``, fallbacks included,
    then every other available provider, so a key for a provider the user is about to switch
    to has a row), then every name in ``<home>/.env.example`` (commented lines included) in
    file order, then names that are only in ``<home>/.env``. No value is read beyond the
    name."""
    root = Path(home).expanduser().resolve()
    if providers is None:
        providers = configured_providers(root)
        for name, planned in known_providers():
            if not planned and name not in providers:
                providers.append(name)
    names: list[str] = []

    def add(name: str) -> None:
        if name not in names:
            names.append(name)

    for provider in providers:
        for alternative in credential_names_for(provider):
            for name in alternative:
                add(name)
    example = root / DOTENV_EXAMPLE
    if example.is_file():
        try:
            for line in example.read_text(encoding="utf-8").splitlines():
                for name in sorted(env_names(line)):
                    add(name)
        except OSError:
            logger.warning("could not read %s", example)
    dotenv = root / DOTENV_FILE
    if dotenv.is_file():
        try:
            for name in dotenv_values(dotenv):
                add(name)
        except OSError:
            logger.warning("could not read %s", dotenv)
    return names


def credential_present(home: Path | str, name: str, env: Mapping[str, str] | None = None) -> bool:
    """Is ``name`` set (non-empty) in ``env`` or ``<home>/.env``? The value is not returned."""
    merged = env_with_dotenv(Path(home).expanduser().resolve(), os.environ if env is None else env)
    return bool(merged.get(name))


def masked_credential(
    home: Path | str, name: str, env: Mapping[str, str] | None = None
) -> str | None:
    """:func:`mask` of the value of ``name`` (``env`` over ``<home>/.env``), or ``None``."""
    merged = env_with_dotenv(Path(home).expanduser().resolve(), os.environ if env is None else env)
    value = merged.get(name)
    return mask(value) if value else None


def credential_source(
    home: Path | str, name: str, env: Mapping[str, str] | None = None
) -> str | None:
    """Where the value ``Config.load`` uses for ``name`` comes from: ``"environment"`` when
    ``env`` (default: the process environment) sets it and ``<home>/.env`` does not hold the
    same value — ``.env`` never overrides a variable that is already set, so an edit there
    would not take effect at the next start —, ``"dotenv"`` when the file supplies it (or
    both agree), ``None`` when it is set nowhere. No value is returned."""
    base = os.environ if env is None else env
    from_env = base.get(name)
    path = _dotenv_path(home)
    from_file = dotenv_values(path).get(name) if path.is_file() else None
    if from_env:
        return "dotenv" if from_file == from_env else "environment"
    return "dotenv" if from_file else None


def is_secret_name(name: str) -> bool:
    """Should an editor hide what is typed for ``name``? True for keys, tokens, secrets,
    passwords and fingerprints (see :data:`_SECRET_MARKERS`); ``AWS_REGION``, ``AWS_PROFILE``
    and the ``TAU_*`` settings are plain."""
    upper = name.upper()
    return any(marker in upper for marker in _SECRET_MARKERS)


def mask(value: str) -> str:
    """What the UI shows for a stored credential: ``sk-…abcd`` (the first three and the last
    four characters) from 20 characters on, ``ab…yz`` (two and two) for 12 to 19, only
    ``…`` and the last two below 12, so nothing recoverable is ever shown."""
    if not value:
        return ""
    if len(value) < 12:
        return f"…{value[-2:]}"
    if len(value) < 20:
        return f"{value[:2]}…{value[-2:]}"
    return f"{value[:3]}…{value[-4:]}"


# -- the /settings report ------------------------------------------------------------------------


def status_text(status: CredentialStatus, language: str = DEFAULT_LANGUAGE) -> str:
    """One phrase for a :class:`CredentialStatus` in the UI language."""
    if status.state == "ok":
        return t("settings.cred.ok", language)
    if status.state == "none":
        return t("settings.cred.none", language)
    if status.state == "fallback":
        return t(
            "settings.cred.fallback",
            language,
            names=", ".join(status.missing),
            provider=status.fallback_provider,
        )
    if status.state == "unavailable":
        return t("settings.cred.unavailable", language, detail=status.detail)
    return t("settings.cred.missing", language, names=", ".join(status.missing))


def report_lines(
    config: Config,
    *,
    language: str = DEFAULT_LANGUAGE,
    env: Mapping[str, str] | None = None,
    show_paths: bool = True,
) -> list[str]:
    """The ``/settings`` listing: roles with provider, model id and credential status, the UI
    language and profile, the context settings, the files and how to change things. No
    credential value appears; paths are printed ``~``-relative (:func:`tilde_path`) and
    ``show_paths=False`` writes ``<home>`` instead."""
    home = config.home
    files = describe_home(home)
    where = tilde_path(home) if show_paths else "<home>"
    lines = [t("settings.header", language, home=where), t("settings.roles_header", language)]
    width = max((len(name) for name in config.roles), default=0)
    for name, role in config.roles.items():
        status = status_text(credential_status(home, role, env), language)
        line = f"  {name:<{width}}  {role.provider} · {role.model_id}"
        if role.fallback is not None:
            line += f" · {t('model.fallback_note', language, provider=role.fallback.provider)}"
        lines.append(f"{line} · {status}")
    lines.append(
        t("settings.interface", language, language=config.ui.language, profile=config.profile)
    )
    agent = config.agent
    lines.append(
        t(
            "settings.agent",
            language,
            mode=agent.context,
            window=agent.window_size,
            turns=agent.max_turns,
            tokens=agent.max_total_tokens
            if agent.max_total_tokens is not None
            else t("settings.none", language),
        )
    )
    lines.append(t("settings.files_header", language))
    for label, path, exists in files.rows():
        state = t("settings.file_present" if exists else "settings.file_missing", language)
        shown = tilde_path(path) if show_paths else f"<home>/{label}"
        lines.append(f"  {label:<18}  {shown} · {state}")
    lines.append(t("settings.hint", language))
    return lines
