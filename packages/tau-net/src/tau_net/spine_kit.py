"""The spine kit: ``tau net spine init`` and ``tau net spine deploy`` (tau-universe.md §4).

tau-net ships the spine Worker as a kit in ``tau_net/spine_kit/``, generated from
``cloud/spine`` by ``bun run kit``:

- ``worker.js``: the Worker, bundled by ``wrangler deploy --dry-run --outdir``;
- ``wrangler.template.jsonc``: its local-mode Wrangler config (``main = "worker.js"``, no
  build step), with an empty ``ADDRESS`` and a commented-out route for :func:`render_config`;
- ``package.template.json``: the project's ``package.json`` with Wrangler pinned;
- ``migrations/*.sql``: the D1 schema, only when the config has a D1 binding;
- ``VERSION`` and ``README.md``.

:func:`init_project` writes a Wrangler project from it; :func:`deploy_project` deploys that
project with ``bunx wrangler`` (``npx wrangler`` when bun is not on ``PATH``, see
:func:`package_tools`) and writes ``TAU_SPINE_TOKEN`` and ``TAU_SPINE_URL`` into the hub's
``.env``. Every external command goes through a :class:`Runner`, so tests never start bun,
npm or Wrangler. The token reaches Wrangler only on stdin: it is never part of a command
line, never printed and never logged. Error messages are plain English.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Protocol

from tau_net.config import SPINE_TOKEN_ENV, SPINE_URL_ENV
from tau_net.encoding import AddressError, host_of, parse_host

__all__ = [
    "GITIGNORE",
    "Completed",
    "DeployResult",
    "InitResult",
    "Kit",
    "NotLoggedIn",
    "PackageTools",
    "Runner",
    "SpineKitError",
    "SubprocessRunner",
    "deploy_project",
    "init_project",
    "is_workers_dev",
    "load_kit",
    "package_tools",
    "parse_jsonc",
    "render_config",
    "spine_host",
]

logger = logging.getLogger(__name__)

KIT_DIR = "spine_kit"
WORKER = "worker.js"
CONFIG = "wrangler.jsonc"
PACKAGE = "package.json"
TEMPLATE = "wrangler.template.jsonc"
PACKAGE_TEMPLATE = "package.template.json"
README = "README.md"
VERSION = "VERSION"
MIGRATIONS = "migrations"
REQUIRED = (WORKER, TEMPLATE, PACKAGE_TEMPLATE, README, VERSION)

GITIGNORE = "node_modules/\n.wrangler/\n.dev.vars\n"
ADDRESS_PLACEHOLDER = '"ADDRESS": ""'
ROUTE_PLACEHOLDER = re.compile(r'^(\s*)// "routes": \[.*\],\s*$', re.MULTILINE)
HUB_TOKEN_SECRET = "HUB_TOKEN"
TOKEN_BYTES = 32

_IPV4 = re.compile(r"\d{1,3}(\.\d{1,3}){3}")
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_WORKERS_DEV_URL = re.compile(
    r"https://([a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*"
    r"\.workers\.dev)\b",
    re.IGNORECASE,
)


class SpineKitError(Exception):
    """A spine project that cannot be written or deployed; the message is one English line."""


class NotLoggedIn(SpineKitError):
    """``wrangler whoami`` shows no Cloudflare login."""


# -- the kit -----------------------------------------------------------------------------------


def parse_jsonc(text: str) -> Any:
    """JSONC to Python: comments and trailing commas outside strings are dropped (the rule of
    ``cloud/spine/scripts/configure.mjs``). :class:`ValueError` for anything else."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i : j + 1])
            i = j + 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end == -1:
                raise ValueError("unterminated comment")
            i = end + 2
        else:
            out.append(c)
            i += 1
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out)))


@dataclass(frozen=True)
class Kit:
    """The kit's files, read into memory (about 100 KiB)."""

    version: str
    worker: bytes
    template: str
    package: str
    readme: str
    migrations: dict[str, bytes] = field(default_factory=dict)

    @property
    def has_d1(self) -> bool:
        return bool(parse_jsonc(self.template).get("d1_databases"))


def kit_root() -> Traversable:
    return resources.files("tau_net").joinpath(KIT_DIR)


def load_kit(root: Traversable | Path | None = None) -> Kit:
    """The kit shipped in this package (or at ``root``); :class:`SpineKitError` when a file
    is missing, which means a broken install."""
    base: Traversable = kit_root() if root is None else root  # type: ignore[assignment]
    missing = [name for name in REQUIRED if not base.joinpath(name).is_file()]
    if missing:
        raise SpineKitError(
            f"the spine kit in tau-net is incomplete (missing {', '.join(missing)}); "
            "reinstall tau-net"
        )
    migrations: dict[str, bytes] = {}
    folder = base.joinpath(MIGRATIONS)
    if folder.is_dir():
        for item in sorted(folder.iterdir(), key=lambda entry: entry.name):
            if item.is_file() and item.name.endswith(".sql"):
                migrations[item.name] = item.read_bytes()
    kit = Kit(
        version=base.joinpath(VERSION).read_text(encoding="utf-8").strip(),
        worker=base.joinpath(WORKER).read_bytes(),
        template=base.joinpath(TEMPLATE).read_text(encoding="utf-8"),
        package=base.joinpath(PACKAGE_TEMPLATE).read_text(encoding="utf-8"),
        readme=base.joinpath(README).read_text(encoding="utf-8"),
        migrations=migrations,
    )
    if kit.has_d1 and not migrations:
        raise SpineKitError("the spine kit in tau-net has a D1 binding but no migrations")
    return kit


# -- addresses and the config ------------------------------------------------------------------


def spine_host(text: str) -> str:
    """A deployable address typed by a person: a DNS name with at least one dot, no port and
    no IP literal and no ``/@handle`` (``https://`` and a trailing ``/`` are forgiven): a spine's
    own address is always a plain host."""
    try:
        host = parse_host(text)
    except AddressError:
        raise SpineKitError(f"not a host name for a spine: {text!r}") from None
    if host_of(host) != host:
        raise SpineKitError(f"a deployed spine's address has no port: {host!r}")
    if "." not in host or _IPV4.fullmatch(host):
        raise SpineKitError(
            f"a spine's address is a domain name such as tau.example.com, not {host!r}"
        )
    return host


def is_workers_dev(host: str) -> bool:
    return host.endswith(".workers.dev")


def render_config(template: str, host: str | None) -> str:
    """The project's ``wrangler.jsonc``: the template as it is for no address or a
    ``*.workers.dev`` one; for any other host, ``vars.ADDRESS`` and a custom-domain route."""
    if host is None or is_workers_dev(host):
        text = template
    else:
        if template.count(ADDRESS_PLACEHOLDER) != 1 or not ROUTE_PLACEHOLDER.search(template):
            raise SpineKitError("the spine kit's Wrangler template has no address placeholders")
        route = json.dumps([{"pattern": host, "custom_domain": True}])
        text = template.replace(ADDRESS_PLACEHOLDER, f'"ADDRESS": {json.dumps(host)}')
        text = ROUTE_PLACEHOLDER.sub(lambda m: f'{m.group(1)}"routes": {route},', text, count=1)
    config = parse_jsonc(text)  # still valid JSONC
    if host is not None and not is_workers_dev(host):
        assert config["vars"]["ADDRESS"] == host and config["routes"][0]["pattern"] == host
    return text


# -- init --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class InitResult:
    path: Path
    version: str
    host: str | None
    files: tuple[str, ...]


def init_project(directory: Path | str, *, address: str | None = None) -> InitResult:
    """Write a Wrangler project for the spine into ``directory``, which must be new or empty."""
    host = spine_host(address) if address else None
    kit = load_kit()
    path = Path(directory).expanduser().resolve()
    if path.exists():
        if not path.is_dir():
            raise SpineKitError(f"{path} exists and is not a directory")
        if any(path.iterdir()):
            raise SpineKitError(f"{path} is not empty; choose a new or empty directory")
    files: dict[str, bytes] = {
        CONFIG: render_config(kit.template, host).encode("utf-8"),
        WORKER: kit.worker,
        PACKAGE: kit.package.encode("utf-8"),
        ".gitignore": GITIGNORE.encode("utf-8"),
        README: kit.readme.encode("utf-8"),
    }
    for name, data in kit.migrations.items():
        files[f"{MIGRATIONS}/{name}"] = data
    try:
        for name, data in files.items():
            target = path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    except OSError as exc:
        raise SpineKitError(f"cannot write {path}: {exc.strerror or exc}") from None
    return InitResult(path=path, version=kit.version, host=host, files=tuple(sorted(files)))


# -- running commands --------------------------------------------------------------------------


@dataclass(frozen=True)
class Completed:
    returncode: int
    output: str
    """stdout and stderr together."""


class Runner(Protocol):
    """How :func:`deploy_project` finds and starts programs; tests pass a fake."""

    def which(self, name: str) -> str | None: ...

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        stdin: str | None = None,
        echo: Callable[[str], None] | None = None,
    ) -> Completed:
        """Run ``argv`` in ``cwd``; ``stdin`` is written to the program's standard input (no
        input at all when ``None``); every output line goes to ``echo`` as it arrives."""
        ...


class SubprocessRunner:
    """The real :class:`Runner`: ``shutil.which`` and ``subprocess``, output captured line by
    line. Standard output is a pipe, so Wrangler runs non-interactively."""

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        stdin: str | None = None,
        echo: Callable[[str], None] | None = None,
    ) -> Completed:
        program = shutil.which(argv[0]) or argv[0]
        try:
            process = subprocess.Popen(
                [program, *argv[1:]],
                cwd=cwd,
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise SpineKitError(f"cannot run {argv[0]}: {exc.strerror or exc}") from None
        if stdin is not None and process.stdin is not None:
            try:
                process.stdin.write(stdin)
                process.stdin.close()
            except BrokenPipeError:  # pragma: no cover - the program exited early
                pass
        lines: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            lines.append(line)
            if echo is not None:
                echo(line.rstrip("\r\n"))
        return Completed(process.wait(), "".join(lines))


# -- deploy ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PackageTools:
    """The package manager :func:`deploy_project` drives, as argv prefixes."""

    install: tuple[str, ...]
    """Installs the project's ``package.json``, which pins Wrangler."""
    run: tuple[str, ...]
    """Runs the project's Wrangler after the install."""
    fetch: tuple[str, ...]
    """Runs a pinned ``wrangler@<version>`` before the install, without asking."""


BUN = PackageTools(install=("bun", "install"), run=("bunx",), fetch=("bunx",))
NPM = PackageTools(
    install=("npm", "install", "--no-audit", "--no-fund"), run=("npx",), fetch=("npx", "--yes")
)


def package_tools(runner: Runner) -> PackageTools:
    """bun (``bun install``, ``bunx wrangler``) when ``bun`` and ``bunx`` are on ``PATH``, else
    npm (``npm install``, ``npx wrangler``).

    Wrangler runs on Node.js either way: ``bunx`` starts it with the ``node`` its shebang
    names, and runs it on bun itself only when there is no ``node``, which Wrangler does not
    support. So bun needs ``node`` on ``PATH`` too. :class:`SpineKitError` names the missing
    program."""
    if runner.which("bun") is not None and runner.which("bunx") is not None:
        if runner.which("node") is None:
            raise SpineKitError(
                "node was not found on PATH; Wrangler runs on Node.js, also with bun: install "
                "Node.js 22 or newer (https://nodejs.org), then run this command again"
            )
        return BUN
    for program in ("npx", "npm"):
        if runner.which(program) is None:
            raise SpineKitError(
                f"{program} was not found on PATH; install Node.js 22 or newer "
                "(https://nodejs.org), then run this command again"
            )
    return NPM


@dataclass(frozen=True)
class DeployResult:
    url: str
    dotenv: Path
    token_created: bool
    migrated: tuple[str, ...]
    """The D1 bindings whose migrations were applied."""


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _last_line(output: str, hide: Sequence[str]) -> str:
    lines = [line.strip() for line in _plain(output).splitlines() if line.strip()]
    last = lines[-1] if lines else "no output"
    for secret in hide:
        if secret:
            last = last.replace(secret, "***")
    return last[:300]


def workers_dev_url(output: str, name: str | None = None) -> str | None:
    """The first ``https://….workers.dev`` URL in ``output``, preferring ``<name>.…``."""
    hosts = [match.group(1).lower() for match in _WORKERS_DEV_URL.finditer(_plain(output))]
    if not hosts:
        return None
    preferred = [host for host in hosts if name and host.startswith(f"{name.lower()}.")]
    return f"https://{(preferred or hosts)[0]}"


def _read_json(path: Path, what: str) -> dict[str, Any]:
    try:
        value = parse_jsonc(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SpineKitError(
            f"{path.parent} is not a spine project (no {path.name}); "
            f"run `tau net spine init {path.parent}` first"
        ) from None
    except (OSError, ValueError) as exc:
        raise SpineKitError(f"cannot read {path} ({what}): {exc}") from None
    if not isinstance(value, dict):
        raise SpineKitError(f"{path} is not a JSON object")
    return value


def _dotenv_value(home: Path, name: str) -> str:
    from tau_core.builder import env_with_dotenv

    return (env_with_dotenv(home, {}).get(name) or "").strip()


def deploy_project(
    directory: Path | str,
    *,
    home: Path,
    address: str | None = None,
    runner: Runner | None = None,
    say: Callable[..., None] = lambda key, **kwargs: None,
    echo: Callable[[str], None] = lambda line: None,
    environ: Mapping[str, str] | None = None,
) -> DeployResult:
    """Deploy the spine project in ``directory`` (§4) and point the hub at it.

    1. The package tools (:func:`package_tools`): bun and ``bunx`` when bun is on ``PATH``,
       else npm and ``npx``; below, ``bunx`` stands for either. ``wrangler whoami`` shows a
       login, else :class:`NotLoggedIn`.
    2. ``bun install`` (``npm install``), ``bunx wrangler deploy``, and ``bunx wrangler d1
       migrations apply <binding> --remote`` for each D1 binding of the project's
       ``wrangler.jsonc``.
    3. ``TAU_SPINE_TOKEN`` in ``<home>/.env`` (generated when missing) becomes the Worker's
       ``HUB_TOKEN`` through ``bunx wrangler secret put`` on stdin.
    4. ``TAU_SPINE_URL`` in ``<home>/.env``: ``https://<address>`` when the address is known
       (``address``, else ``vars.ADDRESS`` of the project), else the ``workers.dev`` URL the
       deploy printed.

    ``say(key, **fields)`` reports progress with message keys, ``echo(line)`` gets the output
    of the commands (the token replaced by ``***`` should it ever appear). The first failure
    raises :class:`SpineKitError`; nothing after it runs.
    """
    from tau_core.settings import set_credential

    runner = runner or SubprocessRunner()
    environ = os.environ if environ is None else environ
    path = Path(directory).expanduser().resolve()
    home = Path(home).expanduser().resolve()
    dotenv = home / ".env"

    config = _read_json(path / CONFIG, "the Wrangler config")
    if not (path / WORKER).is_file():
        raise SpineKitError(
            f"{path} has no {WORKER}; run `tau net spine init` into a new directory"
        )
    package = _read_json(path / PACKAGE, "package.json")
    name = config.get("name") if isinstance(config.get("name"), str) else None
    vars_ = config.get("vars") if isinstance(config.get("vars"), dict) else {}
    configured = str(vars_.get("ADDRESS") or "").strip().lower()
    host = spine_host(address) if address else None
    if host and configured and host != configured:
        raise SpineKitError(
            f"{path / CONFIG} has ADDRESS {configured!r}, not {host!r}; "
            "fix the one that is wrong and deploy again"
        )
    known = host or (spine_host(configured) if configured else None)
    d1 = [
        str(db["binding"])
        for db in config.get("d1_databases") or []
        if isinstance(db, dict) and db.get("binding")
    ]
    dev_deps = package.get("devDependencies") if isinstance(package, dict) else None
    pin = dev_deps.get("wrangler") if isinstance(dev_deps, dict) else None
    wrangler = f"wrangler@{pin}" if isinstance(pin, str) and pin else "wrangler"

    existing = _dotenv_value(home, SPINE_TOKEN_ENV)
    hidden: list[str] = [existing] if existing else []

    def redacted(line: str) -> None:
        for secret in hidden:
            if secret:
                line = line.replace(secret, "***")
        echo(line)

    def run(argv: list[str], *, stdin: str | None = None, show: bool = True) -> Completed:
        say("net.spine.deploy.run", command=" ".join(argv))
        result = runner.run(argv, cwd=path, stdin=stdin, echo=redacted if show else None)
        if result.returncode != 0:
            raise SpineKitError(
                f"`{' '.join(argv)}` failed (exit {result.returncode}): "
                f"{_last_line(result.output, hidden)}"
            )
        return result

    # 1. Tools and login.
    tools = package_tools(runner)
    login = " ".join([*tools.run, "wrangler", "login"])
    whoami = [*tools.fetch, wrangler, "whoami", "--json"]
    say("net.spine.deploy.run", command=" ".join(whoami))
    status = runner.run(whoami, cwd=path)  # not echoed: it lists the account's e-mail and ids
    compact = re.sub(r"\s+", "", _plain(status.output))
    if '"loggedIn":false' in compact or "notauthenticated" in compact.lower():
        raise NotLoggedIn(
            f"Wrangler is not logged in to Cloudflare; run `{login}`, "
            f"then `tau net spine deploy {path}` again"
        )
    if status.returncode != 0:
        raise SpineKitError(
            f"`{' '.join(whoami)}` failed (exit {status.returncode}): "
            f"{_last_line(status.output, hidden)}"
        )
    if '"loggedIn":true' not in compact:
        raise NotLoggedIn(
            f"`wrangler whoami` shows no Cloudflare login; run `{login}`, "
            f"then `tau net spine deploy {path}` again"
        )
    say("net.spine.deploy.logged_in")

    # 2. Install, deploy, migrate.
    run([*tools.install])
    deployed = run([*tools.run, "wrangler", "deploy"])
    printed_url = workers_dev_url(deployed.output, name)
    migrated: list[str] = []
    for binding in d1:
        run([*tools.run, "wrangler", "d1", "migrations", "apply", binding, "--remote"])
        migrated.append(binding)

    # 3. The hub token, on stdin only.
    token = existing
    created = False
    if not token:
        token = secrets.token_urlsafe(TOKEN_BYTES)
        hidden.append(token)
        try:
            set_credential(home, SPINE_TOKEN_ENV, token)
        except (OSError, ValueError) as exc:
            raise SpineKitError(f"cannot write {dotenv}: {exc}") from None
        created = True
        say("net.spine.deploy.token_created", path=dotenv)
    else:
        say("net.spine.deploy.token_kept", path=dotenv)
    from_env = (environ.get(SPINE_TOKEN_ENV) or "").strip()
    if from_env and from_env != token:
        say("net.spine.deploy.token_env")
    run([*tools.run, "wrangler", "secret", "put", HUB_TOKEN_SECRET], stdin=f"{token}\n")
    say("net.spine.deploy.secret_set")

    # 4. The URL.
    url = f"https://{known}" if known else printed_url
    if url is None:
        raise SpineKitError(
            "the deploy printed no workers.dev URL; set TAU_SPINE_URL in "
            f"{dotenv} to https://<your spine's address> yourself"
        )
    try:
        set_credential(home, SPINE_URL_ENV, url)
    except (OSError, ValueError) as exc:
        raise SpineKitError(f"cannot write {dotenv}: {exc}") from None
    say("net.spine.deploy.url_saved", url=url, path=dotenv)
    logger.info("spine deployed from %s to %s", path, url)
    return DeployResult(url=url, dotenv=dotenv, token_created=created, migrated=tuple(migrated))
