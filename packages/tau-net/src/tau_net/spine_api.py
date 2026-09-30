"""Deploy a spine project through the Cloudflare API: no Node.js, bun or Wrangler (ADR 0014 §4,
tau-universe.md §4).

``tau net spine deploy DIR`` takes this path unless ``--wrangler`` is given. It reads the
``wrangler.jsonc`` and ``worker.js`` that ``tau net spine init`` writes and sends Cloudflare
what ``wrangler deploy`` would, with a scoped API token (:data:`TOKEN_ENV`):

1. ``GET /user/tokens/verify``: the token works. Without a token, :func:`token_link` is the
   dashboard page that creates one with the permissions pre-filled (:func:`required_scopes`).
2. ``GET /accounts``, unless the account is known (``--account-id``, ``account_id`` in the
   project's config, or ``CLOUDFLARE_ACCOUNT_ID``).
3. ``GET /accounts/{id}/workers/subdomain`` for a ``workers.dev`` address.
4. ``GET /accounts/{id}/workers/scripts``: whether the Worker exists and its migration tag.
5. For each KV binding without an id: the id the deployed Worker already uses (``GET
   …/workers/scripts/{name}/settings``), else a namespace titled ``<name>-<binding>``
   (Wrangler's name for it, ``GET /accounts/{id}/storage/kv/namespaces``), else a new one
   (``POST`` there). The account id and the KV ids are recorded in ``wrangler.jsonc``, as
   Wrangler records what it provisions, so a re-deploy updates the same Worker in place.
6. ``PUT /accounts/{id}/workers/scripts/{name}``: ``worker.js`` as an ES module with the
   metadata of :func:`upload_metadata` (vars, KV, Durable Objects, rate limits, migrations,
   compatibility date and flags, observability).
7. ``PUT …/secrets``: ``HUB_TOKEN`` = ``TAU_SPINE_TOKEN`` of the hub's ``.env`` (generated
   when missing).
8. ``PUT …/schedules``: the cron triggers.
9. ``POST …/subdomain``: ``workers.dev`` on, or off when a custom domain serves the spine,
   whose ``PUT /accounts/{id}/workers/domains`` comes next.
10. ``GET https://<address>/hub/health`` with the new token, a few times, since a new address
    can take a while; a spine that does not answer yet is a note, not a failure.

Durable Object migrations follow Wrangler's rule: the tags come from ``wrangler.jsonc`` and the
deployed Worker's ``migration_tag`` decides which steps are sent, so this path and Wrangler can
take turns on the same Worker.

Neither token is ever part of a command line, a log line, an exception or the output: the API
token travels only in the ``Authorization`` header, the hub token only in the secret's body and
the health check's header, and every error text is masked.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tau_net.spine import SpineClient, SpineError, Transport, UrllibTransport
from tau_net.spine_kit import (
    CONFIG,
    HUB_TOKEN_SECRET,
    DeployResult,
    SpineKitError,
    dotenv_value,
    ensure_hub_token,
    is_workers_dev,
    parse_jsonc,
    project_address,
    render_config,
    save_url,
    spine_host,
)

__all__ = [
    "ACCOUNT_ENV",
    "API",
    "TOKEN_ENV",
    "Account",
    "CloudflareAPI",
    "CloudflareError",
    "NeedAccount",
    "NeedToken",
    "Scope",
    "deploy_api",
    "multipart",
    "plan_migrations",
    "required_scopes",
    "set_members",
    "token_link",
    "upload_metadata",
]

logger = logging.getLogger(__name__)

API = "https://api.cloudflare.com/client/v4"
TOKEN_ENV = "CLOUDFLARE_API_TOKEN"
ACCOUNT_ENV = "CLOUDFLARE_ACCOUNT_ID"
TOKEN_PAGE = "https://dash.cloudflare.com/profile/api-tokens"
TOKEN_NAME = "tau spine"
MODULE_TYPE = "application/javascript+module"
API_TIMEOUT = 60.0
HEALTH_ATTEMPTS = 6
HEALTH_DELAY = 5.0
HEALTH_TIMEOUT = 15.0
MAX_PAGES = 20

NOT_FOUND_CODES = frozenset({10007, 10090})
"""Cloudflare's "no such Worker" (and "no such environment") error codes."""
AUTH_CODES = frozenset({9106, 9109, 10000})
"""Authentication errors: the token lacks a permission (or is not accepted at all)."""

_ACCOUNT_ID = re.compile(r"[0-9a-f]{32}")

# Keys of wrangler.jsonc the API path understands; anything else needs --wrangler.
SUPPORTED_KEYS = frozenset(
    {
        "$schema",
        "name",
        "main",
        "no_bundle",
        "find_additional_modules",
        "compatibility_date",
        "compatibility_flags",
        "observability",
        "vars",
        "kv_namespaces",
        "durable_objects",
        "migrations",
        "ratelimits",
        "triggers",
        "routes",
        "workers_dev",
        "account_id",
        "dev",
    }
)


# -- scopes and the token link -----------------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    """One permission of the API token: its key in a dashboard template URL and its label."""

    key: str
    type: str
    label: str


SCRIPTS = Scope("workers_scripts", "edit", "Account > Workers Scripts > Edit")
KV = Scope("workers_kv_storage", "edit", "Account > Workers KV Storage > Edit")
ACCOUNTS = Scope("account_settings", "read", "Account > Account Settings > Read")
ROUTES = Scope("workers_routes", "edit", "Zone > Workers Routes > Edit")


def required_scopes(config: Mapping[str, Any], *, custom_domain: bool) -> tuple[Scope, ...]:
    """The permissions a deploy of ``config`` needs: Workers Scripts (the upload, the Durable
    Objects, rate limits, secrets, crons and ``workers.dev``), Workers KV Storage when the config
    binds KV, Account Settings (read) to list the accounts, and Workers Routes on the zones for a
    custom domain."""
    scopes = [SCRIPTS]
    if config.get("kv_namespaces"):
        scopes.append(KV)
    scopes.append(ACCOUNTS)
    if custom_domain:
        scopes.append(ROUTES)
    return tuple(scopes)


def token_link(scopes: Sequence[Scope], *, name: str = TOKEN_NAME) -> str:
    """The dashboard page that creates a user API token with ``scopes`` pre-filled, for every
    account and zone of the user (Cloudflare's "API token template URLs")."""
    keys = json.dumps([{"key": s.key, "type": s.type} for s in scopes], separators=(",", ":"))
    query = urllib.parse.urlencode(
        {"permissionGroupKeys": keys, "accountId": "*", "zoneId": "all", "name": name},
        quote_via=urllib.parse.quote,
        safe="",
    )
    return f"{TOKEN_PAGE}?{query}"


# -- errors ------------------------------------------------------------------------------------


class CloudflareError(SpineKitError):
    """The Cloudflare API said no (``status`` ≥ 300 or ``success: false``) or did not answer
    (``status == 0``). The message is one English line with every secret masked."""

    def __init__(self, message: str, *, status: int = 0, codes: tuple[int, ...] = ()):
        super().__init__(message)
        self.status = status
        self.codes = codes


class NeedToken(SpineKitError):
    """No API token was given: :attr:`link` creates one with :attr:`scopes`."""

    def __init__(self, message: str, *, link: str, scopes: tuple[Scope, ...]):
        super().__init__(message)
        self.link = link
        self.scopes = scopes


@dataclass(frozen=True)
class Account:
    id: str
    name: str


class NeedAccount(SpineKitError):
    """The token reaches several accounts and none was chosen."""

    def __init__(self, message: str, *, accounts: tuple[Account, ...]):
        super().__init__(message)
        self.accounts = accounts


# -- the API client ----------------------------------------------------------------------------


def multipart(parts: Sequence[tuple[str, str | None, str, bytes]]) -> tuple[bytes, str]:
    """``multipart/form-data`` from ``(name, filename, content type, data)`` parts:
    ``(body, content type header)``."""
    boundary = f"tau-{secrets.token_hex(16)}"
    chunks: list[bytes] = []
    for name, filename, content_type, data in parts:
        disposition = f'form-data; name="{name}"'
        if filename is not None:
            disposition += f'; filename="{filename}"'
        head = (
            f"--{boundary}\r\nContent-Disposition: {disposition}\r\n"
            f"Content-Type: {content_type}\r\n\r\n"
        )
        chunks += [head.encode("utf-8"), data, b"\r\n"]
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class CloudflareAPI:
    """``api.cloudflare.com/client/v4`` with a bearer token, over a :class:`Transport`."""

    def __init__(
        self,
        token: str,
        *,
        transport: Transport | None = None,
        base: str = API,
        hide: Sequence[str] = (),
        timeout: float = API_TIMEOUT,
    ):
        self._token = token
        self.transport: Transport = transport or UrllibTransport()
        self.base = base.rstrip("/")
        self._hide = [token, *hide]
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"CloudflareAPI(base={self.base!r}, token=<hidden>)"

    def hide(self, value: str) -> None:
        self._hide.append(value)

    def mask(self, text: str) -> str:
        for secret in self._hide:
            if secret:
                text = text.replace(secret, "***")
        return text

    def call(
        self,
        method: str,
        path: str,
        *,
        what: str,
        scope: Scope | None = None,
        json_body: Any = None,
        body: bytes | None = None,
        content_type: str | None = None,
        query: Mapping[str, Any] | None = None,
        missing_ok: bool = False,
        envelope: bool = False,
    ) -> Any:
        """One request; the ``result`` of a successful answer (the whole answer with
        ``envelope``). ``missing_ok`` turns "no such Worker" (404, codes 10007/10090) into
        ``None``. :class:`CloudflareError` names ``what`` failed and, for an authentication
        error, the permission ``scope`` the token lacks."""
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "User-Agent": "tau-net",
        }
        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif body is not None:
            data = body
        if content_type:
            headers["Content-Type"] = content_type
        try:
            status, _, answer = self.transport(method, url, headers, data, self.timeout)
        except OSError as exc:
            detail = self.mask(str(exc) or type(exc).__name__)
            raise CloudflareError(f"cannot reach the Cloudflare API to {what}: {detail}") from None
        logger.debug("cloudflare %s %s -> %s", method, path, status)
        try:
            payload = json.loads(answer.decode("utf-8")) if answer else None
        except ValueError:
            payload = None
        errors = _errors(payload)
        codes = tuple(code for code, _ in errors)
        ok = 200 <= status < 300 and isinstance(payload, dict) and payload.get("success", True)
        if ok and not errors:
            return payload if envelope else payload.get("result")
        if missing_ok and (status == 404 or NOT_FOUND_CODES & set(codes)):
            return None
        text = "; ".join(f"{code} {message}".strip() for code, message in errors)
        if not errors:
            text = "no JSON answer" if payload is None else "success false"
        why = self.mask(f"{status}, {text}")[:400]
        if status in (401, 403) or AUTH_CODES & set(codes):
            if scope is not None:
                raise CloudflareError(
                    f"Cloudflare refused to {what} ({why}): the API token needs the permission "
                    f'"{scope.label}"; add it to the token at {TOKEN_PAGE} (Edit) and deploy again',
                    status=status,
                    codes=codes,
                )
        raise CloudflareError(f"Cloudflare refused to {what} ({why})", status=status, codes=codes)

    def pages(
        self,
        path: str,
        *,
        what: str,
        scope: Scope | None,
        per_page: int,
        query: Mapping[str, Any] | None = None,
    ) -> list[Any]:
        """Every item of a paginated list (at most :data:`MAX_PAGES` pages)."""
        items: list[Any] = []
        for page in range(1, MAX_PAGES + 1):
            answer = self.call(
                "GET",
                path,
                what=what,
                scope=scope,
                query={**(query or {}), "page": page, "per_page": per_page},
                envelope=True,
            )
            result = answer.get("result") if isinstance(answer, dict) else None
            chunk = result if isinstance(result, list) else []
            items += chunk
            info = answer.get("result_info") if isinstance(answer, dict) else None
            total = info.get("total_pages") if isinstance(info, dict) else None
            if len(chunk) < per_page or (isinstance(total, int) and page >= total):
                break
        return items


def _errors(payload: Any) -> list[tuple[int, str]]:
    raw = payload.get("errors") if isinstance(payload, dict) else None
    out: list[tuple[int, str]] = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            code = item.get("code")
            out.append((code if isinstance(code, int) else 0, str(item.get("message") or "")))
    return out


# -- wrangler.jsonc, edited in place -----------------------------------------------------------


def _skip(text: str, i: int) -> int:
    """The index of the next character that is not white space or a comment."""
    n = len(text)
    while i < n:
        if text[i].isspace():
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end + 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end == -1:
                raise ValueError("unterminated comment")
            i = end + 2
        else:
            break
    return i


def _string_end(text: str, i: int) -> int:
    j = i + 1
    while j < len(text) and text[j] != '"':
        j += 2 if text[j] == "\\" else 1
    if j >= len(text):
        raise ValueError("unterminated string")
    return j + 1


def _value_end(text: str, i: int) -> int:
    if i >= len(text):
        raise ValueError("missing value")
    if text[i] == '"':
        return _string_end(text, i)
    if text[i] in "{[":
        depth, j = 0, i
        while j < len(text):
            c = text[j]
            if c == '"':
                j = _string_end(text, j)
                continue
            if text.startswith("//", j) or text.startswith("/*", j):
                j = _skip(text, j)
                continue
            if c in "{[":
                depth += 1
            elif c in "}]":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        raise ValueError("unterminated value")
    j = i
    while j < len(text) and text[j] not in ",}]" and not text[j].isspace():
        if text.startswith("//", j) or text.startswith("/*", j):
            break
        j += 1
    return j


def _members(text: str) -> dict[str, tuple[int, int]]:
    """The top-level members of the JSONC object ``text``: key → (value start, value end)."""
    i = _skip(text, 0)
    if i >= len(text) or text[i] != "{":
        raise ValueError("not a JSON object")
    i += 1
    members: dict[str, tuple[int, int]] = {}
    while True:
        i = _skip(text, i)
        if i >= len(text):
            raise ValueError("unterminated object")
        if text[i] == "}":
            return members
        if text[i] == ",":
            i += 1
            continue
        if text[i] != '"':
            raise ValueError(f"unexpected {text[i]!r} at {i}")
        end = _string_end(text, i)
        key = json.loads(text[i:end])
        i = _skip(text, end)
        if i >= len(text) or text[i] != ":":
            raise ValueError(f"missing ':' after {key!r}")
        i = _skip(text, i + 1)
        value_end = _value_end(text, i)
        members[key] = (i, value_end)
        i = value_end


def _render(value: Any) -> str:
    """A value as ``cloud/spine/scripts/kit.mjs`` writes a top-level member's value."""
    return json.dumps(value, indent=2, ensure_ascii=False).replace("\n", "\n  ")


def set_members(text: str, updates: Mapping[str, Any], *, after: str = "name") -> str:
    """``text`` (a JSONC object) with the top-level members of ``updates`` replaced, or added
    after the member ``after``; comments and the rest of the text stay as they are."""
    for key, value in updates.items():
        members = _members(text)
        if key in members:
            start, end = members[key]
            text = text[:start] + _render(value) + text[end:]
            continue
        if after in members:
            at = members[after][1]
            text = text[:at] + f",\n  {json.dumps(key)}: {_render(value)}" + text[at:]
        else:
            at = _skip(text, 0) + 1
            text = text[:at] + f"\n  {json.dumps(key)}: {_render(value)}," + text[at:]
    parsed = parse_jsonc(text)  # still valid JSONC
    for key, value in updates.items():
        assert parsed[key] == value, key
    return text


# -- the upload --------------------------------------------------------------------------------


def plan_migrations(
    migrations: Sequence[Mapping[str, Any]], deployed_tag: str | None
) -> tuple[dict[str, Any] | None, bool]:
    """Wrangler's rule (``getMigrationsToUpload``): ``(migrations to send, tag unknown)``.

    - no tag deployed: every step, ``new_tag`` the last tag;
    - the deployed tag is the last one: nothing;
    - an earlier tag: ``old_tag`` it, the steps after it;
    - a tag the config does not list: ``old_tag`` it and every step (``True`` second)."""
    if not migrations:
        return None, False
    last = str(migrations[-1]["tag"])

    def steps(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [{k: v for k, v in item.items() if k != "tag"} for item in items]

    if not deployed_tag:
        return {"new_tag": last, "steps": steps(migrations)}, False
    tags = [str(item["tag"]) for item in migrations]
    if deployed_tag not in tags:
        return {"old_tag": deployed_tag, "new_tag": last, "steps": steps(migrations)}, True
    index = tags.index(deployed_tag)
    if index == len(tags) - 1:
        return None, False
    return {
        "old_tag": deployed_tag,
        "new_tag": last,
        "steps": steps(migrations[index + 1 :]),
    }, False


def upload_metadata(
    config: Mapping[str, Any],
    *,
    main: str,
    kv_ids: Mapping[str, str],
    migrations: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """The ``metadata`` part of the script upload, as ``wrangler deploy`` builds it from the
    same config (``createWorkerUploadForm``): the vars as ``plain_text`` (``json`` for a value
    that is not a string), the KV namespaces with their ids, the Durable Object namespaces, the
    rate limits, then the compatibility date and flags, the migrations and observability."""
    bindings: list[dict[str, Any]] = []
    vars_ = config.get("vars") or {}
    for name, value in vars_.items():
        if isinstance(value, str):
            bindings.append({"name": name, "type": "plain_text", "text": value})
    for name, value in vars_.items():
        if not isinstance(value, str):
            bindings.append({"name": name, "type": "json", "json": value})
    for kv in config.get("kv_namespaces") or []:
        binding = kv["binding"]
        bindings.append({"name": binding, "type": "kv_namespace", "namespace_id": kv_ids[binding]})
    for do in (config.get("durable_objects") or {}).get("bindings") or []:
        entry = {"name": do["name"], "type": "durable_object_namespace"}
        entry["class_name"] = do["class_name"]
        for key in ("script_name", "environment"):
            if do.get(key):
                entry[key] = do[key]
        bindings.append(entry)
    for limit in config.get("ratelimits") or []:
        bindings.append(
            {
                "name": limit["name"],
                "type": "ratelimit",
                "namespace_id": limit["namespace_id"],
                "simple": limit["simple"],
            }
        )
    metadata: dict[str, Any] = {"main_module": main, "bindings": bindings}
    if config.get("compatibility_date"):
        metadata["compatibility_date"] = config["compatibility_date"]
    if config.get("compatibility_flags"):
        metadata["compatibility_flags"] = list(config["compatibility_flags"])
    if migrations:
        metadata["migrations"] = dict(migrations)
    if config.get("observability"):
        metadata["observability"] = config["observability"]
    return metadata


def _check_config(path: Path, config: Mapping[str, Any]) -> str:
    """The module to upload; :class:`SpineKitError` for a config the API path cannot deploy."""
    config_path = path / CONFIG
    wrangler = "; deploy it with `tau net spine deploy --wrangler`"
    extra = sorted(set(config) - SUPPORTED_KEYS)
    if extra:
        raise SpineKitError(
            f"{config_path} has {', '.join(extra)}, which the Cloudflare API path does not "
            f"deploy{wrangler}"
        )
    main = config.get("main")
    if not isinstance(main, str) or "/" in main or not main.endswith((".js", ".mjs")):
        raise SpineKitError(f"{config_path} has no bundled main module (.js){wrangler}")
    if config.get("no_bundle") is not True:
        raise SpineKitError(
            f"{config_path} does not say no_bundle: the API path uploads {main} as it is{wrangler}"
        )
    if not (path / main).is_file():
        raise SpineKitError(f"{path} has no {main}; run `tau net spine init` into a new directory")
    if not isinstance(config.get("name"), str) or not config["name"]:
        raise SpineKitError(f"{config_path} has no Worker name")
    for route in config.get("routes") or []:
        if not (isinstance(route, dict) and route.get("custom_domain") and route.get("pattern")):
            raise SpineKitError(f"{config_path} has a route that is not a custom domain{wrangler}")
    for kv in config.get("kv_namespaces") or []:
        if not isinstance(kv, dict) or not kv.get("binding"):
            raise SpineKitError(f"{config_path} has a KV namespace without a binding")
    for item in config.get("migrations") or []:
        if not isinstance(item, dict) or not item.get("tag"):
            raise SpineKitError(f"{config_path} has a Durable Object migration without a tag")
    return main


# -- the deploy --------------------------------------------------------------------------------


def _say_nothing(key: str, /, **fields: Any) -> None:
    pass


def deploy_api(
    directory: Path | str,
    *,
    home: Path,
    address: str | None = None,
    account_id: str | None = None,
    token: str | None = None,
    transport: Transport | None = None,
    ask_token: Callable[[str, tuple[Scope, ...]], str | None] = lambda link, scopes: None,
    choose_account: Callable[[tuple[Account, ...]], str | None] = lambda accounts: None,
    say: Callable[..., None] = _say_nothing,
    environ: Mapping[str, str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    health_attempts: int = HEALTH_ATTEMPTS,
) -> DeployResult:
    """Deploy the spine project in ``directory`` through the Cloudflare API (see the module
    doc) and point the hub at it.

    The API token is ``token``, else ``CLOUDFLARE_API_TOKEN`` from the environment, else from
    ``<home>/.env``, else what ``ask_token(link, scopes)`` returns (a hidden prompt, or the
    JSON input of ``--json``); a token that did not come from the environment or ``.env`` is
    written to ``<home>/.env`` (mode ``0600``, only that line) once Cloudflare accepted it.
    ``None`` from ``ask_token`` raises :class:`NeedToken`. The account is ``account_id``, else
    ``account_id`` in the project's config, else ``CLOUDFLARE_ACCOUNT_ID``, else the only
    account the token reaches, else what ``choose_account`` returns (:class:`NeedAccount` for
    ``None``). The first failure raises :class:`SpineKitError`; nothing after it runs.
    """
    environ = os.environ if environ is None else environ
    path = Path(directory).expanduser().resolve()
    home = Path(home).expanduser().resolve()
    dotenv = home / ".env"
    config_path = path / CONFIG

    try:
        text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise SpineKitError(
            f"{path} is not a spine project (no {CONFIG}); run `tau net spine init {path}` first"
        ) from None
    except OSError as exc:
        raise SpineKitError(f"cannot read {config_path}: {exc.strerror or exc}") from None
    try:
        config = parse_jsonc(text)
    except ValueError as exc:
        raise SpineKitError(f"cannot read {config_path} (the Wrangler config): {exc}") from None
    if not isinstance(config, dict):
        raise SpineKitError(f"{config_path} is not a JSON object")
    if config.get("d1_databases"):
        raise SpineKitError(
            f"{config_path} has a D1 database, whose migrations only Wrangler applies; "
            "deploy it with `tau net spine deploy --wrangler`"
        )
    main = _check_config(path, config)
    name = str(config["name"])

    # The address: --address, vars.ADDRESS, or a custom-domain route; else workers.dev.
    host, known = project_address(path, config, address)
    routes = [str(r["pattern"]).lower() for r in config.get("routes") or []]
    custom = known if known and not is_workers_dev(known) else None
    if routes and custom is None and host is None:
        custom = spine_host(routes[0])  # the route names the address
    elif routes and custom not in routes:
        raise SpineKitError(
            f"{config_path} routes the spine to {routes[0]}, not to {custom or host}; "
            "fix the one that is wrong and deploy again"
        )
    workers_dev = config.get("workers_dev")
    workers_dev = (custom is None) if not isinstance(workers_dev, bool) else workers_dev
    if custom is None and not workers_dev:
        raise SpineKitError(
            f"{config_path} turns workers.dev off and names no custom domain; "
            "the spine would have no address"
        )
    scopes = required_scopes(config, custom_domain=custom is not None)
    link = token_link(scopes)

    # 1. The API token.
    token = (token or "").strip()
    source = "given"
    if not token:
        token = (environ.get(TOKEN_ENV) or "").strip()
        source = "env"
    if not token:
        token = dotenv_value(home, TOKEN_ENV)
        source = "dotenv"
    if not token:
        token = (ask_token(link, scopes) or "").strip()
        source = "asked"
    if not token:
        raise NeedToken(
            f"no Cloudflare API token: create one at {link} and paste it, or put "
            f"{TOKEN_ENV} into {dotenv}",
            link=link,
            scopes=scopes,
        )
    api = CloudflareAPI(token, transport=transport)
    where = {
        "env": f"{TOKEN_ENV} in the environment",
        "dotenv": f"{TOKEN_ENV} in {dotenv}",
    }.get(source, "the token given")
    answer = _verify(api, link, where)
    if answer.get("status") not in (None, "active"):
        raise CloudflareError(
            f"the Cloudflare API token is {answer.get('status')}, not active; create a new one "
            f"at {link}"
        )
    say("net.spine.api.token_ok")
    if source == "env":
        say("net.spine.api.token_env")
    elif source == "dotenv":
        say("net.spine.api.token_dotenv", path=dotenv)
    elif source in ("asked", "given"):
        from tau_core.settings import set_credential

        try:
            set_credential(home, TOKEN_ENV, token)
        except (OSError, ValueError) as exc:
            raise SpineKitError(f"cannot write {dotenv}: {exc}") from None
        say("net.spine.api.token_saved", path=dotenv)

    # 2. The account.
    account = _account(api, config, account_id, environ, choose_account, say)
    base = f"/accounts/{account}"
    script = f"{base}/workers/scripts/{name}"

    # 3. The workers.dev subdomain (a read, before anything is written).
    url_host = custom
    if custom is None:
        sub = api.call(
            "GET",
            f"{base}/workers/subdomain",
            what="read the account's workers.dev subdomain",
            scope=SCRIPTS,
            missing_ok=True,
        )
        subdomain = sub.get("subdomain") if isinstance(sub, dict) else None
        if not subdomain:
            raise SpineKitError(
                "the Cloudflare account has no workers.dev subdomain yet: pick one at "
                f"https://dash.cloudflare.com/{account}/workers/onboarding and deploy again, or "
                "deploy with --address HOST for a domain of yours"
            )
        url_host = f"{name}.{subdomain}.workers.dev".lower()
        if host and host != url_host:
            raise SpineKitError(
                f"the Worker's workers.dev address is {url_host}, not {host}; "
                "deploy without --address or with the right one"
            )
    assert url_host is not None

    # 4. The deployed Worker, if any.
    scripts = api.call("GET", f"{base}/workers/scripts", what="list the Workers", scope=SCRIPTS)
    deployed = next((s for s in scripts or [] if isinstance(s, dict) and s.get("id") == name), None)
    deployed_tag = str(deployed.get("migration_tag") or "") if deployed else ""

    # 5. KV namespaces, and the ids recorded in wrangler.jsonc.
    kv_ids = _kv_ids(api, config, base, script, name, deployed is not None, say)
    updates: dict[str, Any] = {}
    if config.get("account_id") != account:
        updates["account_id"] = account
    kv_config = [{**kv, "id": kv_ids[kv["binding"]]} for kv in config.get("kv_namespaces") or []]
    if kv_config and kv_config != config.get("kv_namespaces"):
        updates["kv_namespaces"] = kv_config
    new_text = text
    if custom is not None:
        new_text = _with_address(new_text, config, custom)
        if new_text != text:
            say("net.spine.api.address_saved", address=custom, path=config_path)
    if updates:
        new_text = set_members(new_text, updates)
    if new_text != text:
        try:
            config_path.write_text(new_text, encoding="utf-8")
        except OSError as exc:
            raise SpineKitError(f"cannot write {config_path}: {exc.strerror or exc}") from None
        if updates:
            say("net.spine.api.recorded", path=config_path)
        config = parse_jsonc(new_text)

    # 6. The upload.
    migrations, unknown = plan_migrations(config.get("migrations") or [], deployed_tag or None)
    if unknown:
        say("net.spine.api.migrations_unknown", tag=deployed_tag, path=config_path)
    if migrations:
        say(
            "net.spine.api.migrations",
            count=len(migrations["steps"]),
            tag=migrations["new_tag"],
        )
    elif deployed_tag:
        say("net.spine.api.migrations_current", tag=deployed_tag)
    metadata = upload_metadata(config, main=main, kv_ids=kv_ids, migrations=migrations)
    module = (path / main).read_bytes()
    body, content_type = multipart(
        [
            ("metadata", None, "application/json", json.dumps(metadata).encode("utf-8")),
            (main, main, MODULE_TYPE, module),
        ]
    )
    api.call(
        "PUT",
        script,
        what=f"upload the Worker {name}",
        scope=SCRIPTS,
        body=body,
        content_type=content_type,
    )
    say("net.spine.api.uploaded", name=name, size=f"{len(module) / 1024:.1f}")

    # 7. HUB_TOKEN.
    hub_token, created = ensure_hub_token(home, say=say, environ=environ)
    api.hide(hub_token)
    api.call(
        "PUT",
        f"{script}/secrets",
        what=f"set the Worker's {HUB_TOKEN_SECRET} secret",
        scope=SCRIPTS,
        json_body={"name": HUB_TOKEN_SECRET, "text": hub_token, "type": "secret_text"},
    )
    say("net.spine.deploy.secret_set")

    # 8. Cron triggers.
    triggers = config.get("triggers")
    crons = triggers.get("crons") if isinstance(triggers, dict) else None
    if isinstance(crons, list):
        api.call(
            "PUT",
            f"{script}/schedules",
            what="set the cron triggers",
            scope=SCRIPTS,
            json_body=[{"cron": str(cron)} for cron in crons],
        )
        say("net.spine.api.crons", crons=", ".join(map(str, crons)) or "-")

    # 9. workers.dev and the custom domain.
    api.call(
        "POST",
        f"{script}/subdomain",
        what="switch the workers.dev address " + ("on" if workers_dev else "off"),
        scope=SCRIPTS,
        json_body={"enabled": workers_dev},
    )
    if workers_dev and custom is None:
        say("net.spine.api.workers_dev", host=url_host)
    elif not workers_dev:
        say("net.spine.api.workers_dev_off")
    domains = [str(r["pattern"]).lower() for r in config.get("routes") or []]
    for pattern in domains:
        api.call(
            "PUT",
            f"{base}/workers/domains",
            what=f"attach the custom domain {pattern}",
            scope=ROUTES,
            json_body={"hostname": pattern, "service": name},
        )
        say("net.spine.api.domain", host=pattern)

    # 10. The URL, then the health check.
    url = f"https://{url_host}"
    save_url(home, url, say=say)
    healthy = _check_health(url, hub_token, transport, say, sleep, health_attempts, api.mask)
    logger.info("spine deployed through the Cloudflare API from %s to %s", path, url)
    return DeployResult(
        url=url,
        dotenv=dotenv,
        token_created=created,
        migrated=(),
        account_id=account,
        healthy=healthy,
    )


def _verify(api: CloudflareAPI, link: str, where: str) -> dict[str, Any]:
    try:
        answer = api.call("GET", "/user/tokens/verify", what="verify the API token")
    except CloudflareError as exc:
        if exc.status in (400, 401, 403) or AUTH_CODES & set(exc.codes) or 1000 in exc.codes:
            raise CloudflareError(
                f"{exc}: {where} is not a valid Cloudflare API token; create one at {link}",
                status=exc.status,
                codes=exc.codes,
            ) from None
        raise
    return answer if isinstance(answer, dict) else {}


def _account(
    api: CloudflareAPI,
    config: Mapping[str, Any],
    given: str | None,
    environ: Mapping[str, str],
    choose: Callable[[tuple[Account, ...]], str | None],
    say: Callable[..., None],
) -> str:
    for candidate in (given, config.get("account_id"), environ.get(ACCOUNT_ENV)):
        value = str(candidate or "").strip().lower()
        if value:
            if not _ACCOUNT_ID.fullmatch(value):
                raise SpineKitError(f"not a Cloudflare account id: {value!r} (32 hex digits)")
            say("net.spine.api.account_id", id=value)
            return value
    items = api.pages("/accounts", what="list the accounts", scope=ACCOUNTS, per_page=50)
    accounts = tuple(
        Account(str(item["id"]).lower(), str(item.get("name") or ""))
        for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    )
    if not accounts:
        raise SpineKitError(
            "the Cloudflare API token reaches no account; create it with "
            '"Account Resources: All accounts" (or yours) and deploy again'
        )
    if len(accounts) == 1:
        chosen = accounts[0]
    else:
        wanted = (choose(accounts) or "").strip().lower()
        match = [a for a in accounts if a.id == wanted]
        if not match:
            listing = ", ".join(f"{a.name} ({a.id})" for a in accounts)
            raise NeedAccount(
                f"the API token reaches {len(accounts)} accounts ({listing}); "
                "choose one with --account-id",
                accounts=accounts,
            )
        chosen = match[0]
    say("net.spine.api.account", name=chosen.name or "-", id=chosen.id)
    return chosen.id


def _kv_ids(
    api: CloudflareAPI,
    config: Mapping[str, Any],
    base: str,
    script: str,
    name: str,
    exists: bool,
    say: Callable[..., None],
) -> dict[str, str]:
    """The namespace id of every KV binding: from the config, from the deployed Worker, by
    Wrangler's title ``<name>-<binding>``, or new."""
    ids: dict[str, str] = {}
    missing = []
    for kv in config.get("kv_namespaces") or []:
        if kv.get("id"):
            ids[kv["binding"]] = str(kv["id"])
        else:
            missing.append(str(kv["binding"]))
    if not missing:
        return ids
    if exists:
        settings = api.call(
            "GET",
            f"{script}/settings",
            what=f"read the settings of the Worker {name}",
            scope=SCRIPTS,
            missing_ok=True,
        )
        bindings = settings.get("bindings") if isinstance(settings, dict) else None
        for binding in bindings or []:
            if (
                isinstance(binding, dict)
                and binding.get("type") == "kv_namespace"
                and binding.get("name") in missing
                and binding.get("namespace_id")
            ):
                ids[binding["name"]] = str(binding["namespace_id"])
                missing.remove(binding["name"])
                say("net.spine.api.kv_kept", binding=binding["name"], id=binding["namespace_id"])
    if not missing:
        return ids
    namespaces = api.pages(
        f"{base}/storage/kv/namespaces",
        what="list the KV namespaces",
        scope=KV,
        per_page=100,
    )
    by_title = {
        str(ns.get("title")): str(ns.get("id"))
        for ns in namespaces
        if isinstance(ns, dict) and ns.get("id")
    }
    for binding in missing:
        title = f"{name}-{binding.lower().replace('_', '-')}"
        if title in by_title:
            ids[binding] = by_title[title]
            say("net.spine.api.kv_found", binding=binding, title=title, id=ids[binding])
            continue
        created = api.call(
            "POST",
            f"{base}/storage/kv/namespaces",
            what=f"create the KV namespace {title}",
            scope=KV,
            json_body={"title": title},
        )
        if not isinstance(created, dict) or not created.get("id"):
            raise CloudflareError(f"Cloudflare created the KV namespace {title} without an id")
        ids[binding] = str(created["id"])
        say("net.spine.api.kv_created", binding=binding, title=title, id=ids[binding])
    return ids


def _with_address(text: str, config: Mapping[str, Any], host: str) -> str:
    """``text`` with ``vars.ADDRESS`` = ``host`` and its custom-domain route, as ``tau net spine
    init --address`` writes them (the same text when both are there already)."""
    vars_ = dict(config.get("vars") or {})
    routes = list(config.get("routes") or [])
    has_route = any(
        isinstance(r, dict) and str(r.get("pattern", "")).lower() == host for r in routes
    )
    if vars_.get("ADDRESS") == host and has_route:
        return text
    if not vars_.get("ADDRESS") and not routes:
        try:
            return render_config(text, host)
        except SpineKitError:
            pass  # an edited config: set the two members instead
    updates: dict[str, Any] = {}
    if vars_.get("ADDRESS") != host:
        vars_["ADDRESS"] = host
        updates["vars"] = vars_
    if not has_route:
        updates["routes"] = [*routes, {"pattern": host, "custom_domain": True}]
    return set_members(text, updates, after="vars")


def _check_health(
    url: str,
    hub_token: str,
    transport: Transport | None,
    say: Callable[..., None],
    sleep: Callable[[float], None],
    attempts: int,
    mask: Callable[[str], str],
) -> bool | None:
    if attempts <= 0:
        return None
    client = SpineClient(url, hub_token, transport=transport, timeout=HEALTH_TIMEOUT)
    error = ""
    for attempt in range(attempts):
        if attempt:
            sleep(HEALTH_DELAY)
        try:
            health = client.health()
        except SpineError as exc:
            error = mask(str(exc))
            continue
        if health.get("ok") is True:
            say("net.spine.api.health_ok", url=url, version=health.get("version") or "?")
            return True
        error = "health is not ok"
    say("net.spine.api.health_later", url=url, error=error[:200])
    return False
