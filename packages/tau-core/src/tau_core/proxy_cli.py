"""``tau proxy``: virtual keys and budgets of the proxy roles, and their spend (ADR 0009).

The LiteLLM proxy (``infra/litellm``) gives every ``proxy`` role its own virtual key. The key
carries the role's hard budget from ``tau.toml`` (``[models.roles.<role>.budget]``), so a cap
changes by editing ``tau.toml`` and running ``tau proxy keys``; no code changes.

- ``tau proxy keys`` creates the missing keys (written to ``<home>/.env`` as
  ``TAU_PROXY_KEY_<GROUP>``) and brings the existing ones in line with ``tau.toml``.
- ``tau proxy rotate ROLE`` replaces a role's key; the spend of the current period moves to
  the new key, so a rotation never resets a budget.
- ``tau proxy spend`` prints what every key has spent in its current period.

Managing keys needs ``LITELLM_MASTER_KEY`` (``infra/litellm/proxy.sh init`` generates it);
reading spend needs only the roles' own keys. Output is plain English, like ``tau doctor``.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import click

from tau_core.config import Config, ConfigError, RoleConfig
from tau_core.models import proxy_key_env, proxy_url
from tau_core.spend import RoleSpend, SpendTracker, proxy_roles

__all__ = [
    "KeyAction",
    "ProxyAdmin",
    "ProxyAdminError",
    "desired_key",
    "proxy",
    "rotate_key",
    "sync_keys",
]

logger = logging.getLogger(__name__)

MASTER_KEY_ENV = "LITELLM_MASTER_KEY"
ALIAS_PREFIX = "tau-"
ADMIN_TIMEOUT = 10.0


class ProxyAdminError(Exception):
    """An admin call to the proxy failed; ``status`` is the HTTP status (0: no answer)."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(f"proxy answered {status}: {message}" if status else message)


class ProxyAdmin:
    """The few key-management endpoints of the LiteLLM proxy, called with the master key."""

    def __init__(self, base_url: str, master_key: str, *, timeout: float = ADMIN_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self._master_key = master_key
        self._timeout = timeout

    def request(self, method: str, path: str, body: Any = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._master_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise ProxyAdminError(exc.code, _error_message(exc.read())) from exc
        except (OSError, ValueError) as exc:
            raise ProxyAdminError(0, f"the proxy at {self.base_url} did not answer: {exc}") from exc
        return json.loads(raw) if raw else None

    def key_info(self, key: str) -> dict | None:
        """The key's record, ``None`` when the proxy does not know the key."""
        try:
            payload = self.request("GET", "/key/info?" + urllib.parse.urlencode({"key": key}))
        except ProxyAdminError as exc:
            if exc.status in (400, 401, 404):
                return None
            raise
        info = payload.get("info") if isinstance(payload, dict) else None
        return info if isinstance(info, dict) else None

    def keys_by_alias(self, alias: str) -> list[dict]:
        query = urllib.parse.urlencode({"key_alias": alias, "return_full_object": "true"})
        payload = self.request("GET", f"/key/list?{query}")
        keys = payload.get("keys") if isinstance(payload, dict) else None
        return [key for key in keys or [] if isinstance(key, dict)]

    def generate(self, fields: Mapping[str, Any]) -> str:
        payload = self.request("POST", "/key/generate", dict(fields))
        key = payload.get("key") if isinstance(payload, dict) else None
        if not isinstance(key, str) or not key:
            raise ProxyAdminError(0, "the proxy returned no key")
        return key

    def update(self, key: str, fields: Mapping[str, Any]) -> None:
        self.request("POST", "/key/update", {"key": key, **fields})

    def delete(self, keys: list[str]) -> None:
        if keys:
            self.request("POST", "/key/delete", {"keys": keys})


def _error_message(raw: bytes) -> str:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return raw.decode("utf-8", "replace")[:300]
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)[:300]
    return str(payload.get("detail") if isinstance(payload, dict) else payload)[:300]


@dataclass(frozen=True)
class KeyAction:
    """What ``tau proxy keys``/``rotate`` did for one role."""

    role: str
    action: str  # created | updated | unchanged | rotated
    variable: str
    detail: str = ""


def desired_key(role: str, cfg: RoleConfig) -> dict[str, Any]:
    """The key fields ``tau.toml`` asks for: the role's model group only, its alias and, with
    a ``budget`` table, the cap and its period."""
    fields: dict[str, Any] = {
        "key_alias": f"{ALIAS_PREFIX}{role}",
        "models": [cfg.model_id],
        "metadata": {"tau_role": role, "managed_by": "tau proxy keys"},
    }
    if cfg.budget is not None:
        fields["max_budget"] = cfg.budget.usd
        fields["budget_duration"] = cfg.budget.period
    return fields


def _differences(info: Mapping[str, Any], fields: Mapping[str, Any]) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    for name in ("key_alias", "models", "max_budget", "budget_duration"):
        if name not in fields:
            continue
        current = info.get(name)
        wanted = fields[name]
        if name == "max_budget":
            same = current is not None and abs(float(current) - float(wanted)) < 1e-9
        else:
            same = current == wanted
        if not same:
            changed[name] = wanted
    return changed


def _budget_text(cfg: RoleConfig) -> str:
    if cfg.budget is None:
        return "no budget (the key has no cap; add [models.roles.<role>.budget])"
    text = f"${cfg.budget.usd:.2f} per {cfg.budget.period}"
    if cfg.budget.degrade_to:
        text += f", then {cfg.budget.degrade_to}"
    return text


def _selected(config: Config, roles: list[str] | None) -> dict[str, RoleConfig]:
    available = proxy_roles(config)
    if not available:
        raise ConfigError(
            'no role in tau.toml uses provider = "proxy"; nothing to do (see infra/litellm).'
        )
    if not roles:
        return available
    unknown = [name for name in roles if name not in available]
    if unknown:
        raise ConfigError(
            f"not a proxy role in tau.toml: {', '.join(unknown)} "
            f"(proxy roles: {', '.join(available)})."
        )
    return {name: available[name] for name in roles}


Writer = Callable[[str, str], None]
"""``(variable, value)`` → store it in ``<home>/.env`` (and the running process)."""


def sync_keys(
    config: Config,
    env: Mapping[str, str],
    admin: ProxyAdmin,
    write: Writer,
    *,
    roles: list[str] | None = None,
    replace: bool = False,
) -> list[KeyAction]:
    """Create the missing keys and align the existing ones with ``tau.toml``.

    A key in ``.env`` the proxy no longer knows is replaced. When the proxy already holds a
    key under the role's alias (``tau-<role>``) that ``.env`` does not have, it may belong to
    another tau home sharing the proxy, so it is only replaced with ``replace`` (its spend in
    the current period moves to the new key); otherwise :class:`ProxyAdminError` says so.
    """
    actions: list[KeyAction] = []
    done: set[str] = set()
    for role, cfg in _selected(config, roles).items():
        variable = proxy_key_env(cfg)
        if variable in done:
            continue
        done.add(variable)
        fields = desired_key(role, cfg)
        current = env.get(variable) or ""
        info = admin.key_info(current) if current else None
        if info is not None:
            changed = _differences(info, fields)
            if changed:
                admin.update(current, changed)
                detail = f"{', '.join(changed)} → {_budget_text(cfg)}"
                actions.append(KeyAction(role, "updated", variable, detail))
            else:
                actions.append(KeyAction(role, "unchanged", variable, _budget_text(cfg)))
            continue
        stale = admin.keys_by_alias(str(fields["key_alias"]))
        if stale and not replace:
            raise ProxyAdminError(
                0,
                f"the proxy already has a key named {fields['key_alias']} that {variable} in "
                ".env does not match. If it is this home's and .env lost it, run "
                "tau proxy keys --replace (its spend carries over); if another tau home uses "
                "it, give this one other model groups.",
            )
        carried = sum(float(key.get("spend") or 0.0) for key in stale)
        admin.delete([str(key["token"]) for key in stale if key.get("token")])
        new_key = admin.generate({**fields, "spend": carried} if carried else fields)
        write(variable, new_key)
        detail = _budget_text(cfg)
        if carried:
            detail += f"; ${carried:.2f} spent this period carried over"
        actions.append(KeyAction(role, "created", variable, detail))
    return actions


def rotate_key(
    config: Config,
    env: Mapping[str, str],
    admin: ProxyAdmin,
    write: Writer,
    role: str,
    *,
    clock: Callable[[], float] = time.time,
) -> KeyAction:
    """Replace the role's key: rename the old one out of the way, create the new one with the
    old one's spend, store it, then delete the old one (put back if creating fails)."""
    cfg = _selected(config, [role])[role]
    variable = proxy_key_env(cfg)
    old = env.get(variable) or ""
    info = admin.key_info(old) if old else None
    if info is None:
        raise ConfigError(f"{variable} is not a key the proxy knows; run tau proxy keys instead.")
    fields = desired_key(role, cfg)
    alias = str(fields["key_alias"])
    admin.update(old, {"key_alias": f"{alias}-rotated-{int(clock())}"})
    spend = float(info.get("spend") or 0.0)
    try:
        new_key = admin.generate({**fields, "spend": spend} if spend else fields)
    except ProxyAdminError:
        admin.update(old, {"key_alias": alias})
        raise
    write(variable, new_key)
    admin.delete([old])
    return KeyAction(role, "rotated", variable, f"${spend:.2f} spent this period kept")


def _spend_line(spend: RoleSpend) -> str:
    if spend.error is not None and not spend.known:
        return f"  {spend.role:<8} {spend.group:<8} unknown ({spend.error})"
    cap = f"${spend.max_budget:.2f}" if spend.max_budget is not None else "no cap"
    line = f"  {spend.role:<8} {spend.group:<8} ${spend.spend or 0.0:.2f} of {cap}"
    if spend.period:
        line += f" per {spend.period}"
    if spend.reset_at is not None:
        line += f", resets {spend.reset_at:%Y-%m-%d %H:%M} UTC"
    if spend.exhausted:
        line += " · SPENT" + (f", {spend.degrade_to} answers instead" if spend.degrade_to else "")
    if spend.drifted:
        line += " · differs from tau.toml, run tau proxy keys"
    return line


def _admin(config: Config, env: Mapping[str, str]) -> ProxyAdmin:
    master = env.get(MASTER_KEY_ENV)
    if not master:
        raise ConfigError(
            f"{MASTER_KEY_ENV} is not set; run infra/litellm/proxy.sh init and start the proxy."
        )
    first = next(iter(proxy_roles(config).values()), None)
    return ProxyAdmin(proxy_url(first, env), master)


def _writer(config: Config) -> Writer:
    from tau_core.settings import set_credential

    def write(variable: str, value: str) -> None:
        set_credential(config.home, variable, value, export=True)

    return write


def _load(ctx: click.Context) -> Config:
    obj = ctx.find_object(dict) or {}
    try:
        return Config.load(obj.get("home"))
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc


@click.group(
    name="proxy",
    help="Virtual keys, budgets and spend of the roles served through the LiteLLM proxy "
    '(provider = "proxy" in tau.toml; the proxy itself is infra/litellm).',
    short_help="Manage the model proxy's keys and budgets.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
def proxy() -> None:
    pass


@proxy.command(
    name="keys",
    help="Create the missing role keys (written to .env) and align every key's model group "
    "and budget with tau.toml. Needs LITELLM_MASTER_KEY. Safe to run again.",
)
@click.argument("roles", nargs=-1)
@click.option(
    "--replace",
    is_flag=True,
    help="Replace a key the proxy holds under a role's alias that .env does not have.",
)
@click.pass_context
def keys(ctx: click.Context, roles: tuple[str, ...], replace: bool) -> None:
    config = _load(ctx)
    try:
        actions = sync_keys(
            config,
            os.environ,
            _admin(config, os.environ),
            _writer(config),
            roles=list(roles) or None,
            replace=replace,
        )
    except (ConfigError, ProxyAdminError) as exc:
        raise click.ClickException(str(exc)) from exc
    for action in actions:
        click.echo(f"  {action.role:<8} {action.action:<9} {action.variable}  {action.detail}")


@proxy.command(
    name="rotate",
    help="Replace ROLE's key with a new one; the spend of the current period moves with it. "
    "Restart the hub afterwards so it reads the new key.",
)
@click.argument("role")
@click.pass_context
def rotate(ctx: click.Context, role: str) -> None:
    config = _load(ctx)
    try:
        action = rotate_key(config, os.environ, _admin(config, os.environ), _writer(config), role)
    except (ConfigError, ProxyAdminError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"  {action.role:<8} {action.action:<9} {action.variable}  {action.detail}")


@proxy.command(name="spend", help="Print what every proxy role's key spent in its period.")
@click.option("--json", "as_json", is_flag=True, help="Print the spend as JSON.")
@click.pass_context
def spend(ctx: click.Context, as_json: bool) -> None:
    config = _load(ctx)
    if not proxy_roles(config):
        raise click.ClickException('no role in tau.toml uses provider = "proxy".')
    spends = SpendTracker(config).refresh()
    if as_json:
        payload = {name: value.to_json() for name, value in spends.items()}
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for value in spends.values():
        click.echo(_spend_line(value))
