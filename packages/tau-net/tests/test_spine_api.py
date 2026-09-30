"""``tau net spine deploy`` through the Cloudflare API (ADR 0014 §4, tau-universe.md §4).

:class:`FakeCloudflare` stands in for ``api.cloudflare.com`` and for the spines it deploys (a
:class:`~tau_net.testing.FakeSpine` per address, whose ``HUB_TOKEN`` is the secret the deploy
set). It records every request, so the tests assert the exact sequence and bodies. Nothing
here reaches the network.
"""

from __future__ import annotations

import email.parser
import email.policy
import itertools
import json
import logging
import re
import stat
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result
from tau_core.builder import env_with_dotenv
from tau_net.cli import net
from tau_net.spine import TransportError
from tau_net.spine_api import (
    HEALTH_ATTEMPTS,
    HEALTH_DELAY,
    multipart,
    plan_migrations,
    required_scopes,
    set_members,
    token_link,
    upload_metadata,
)
from tau_net.spine_kit import load_kit, parse_jsonc
from tau_net.testing import FakeSpine

API_TOKEN = "cf-example-api-token-0123456789abcdefghij"
WRONG_TOKEN = "cf-example-wrong-token-9876543210zyxwvu"
ACCOUNT = "0123456789abcdef0123456789abcdef"
OTHER = "fedcba9876543210fedcba9876543210"
SUBDOMAIN = "example-sub"
WORKERS_DEV = "tau-spine.example-sub.workers.dev"
ALL_SCOPES = frozenset(
    {"workers_scripts", "workers_kv_storage", "account_settings", "workers_routes"}
)
SCRIPT = f"/accounts/{ACCOUNT}/workers/scripts/tau-spine"


# -- the fake Cloudflare -----------------------------------------------------------------------


@dataclass
class Req:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body: bytes

    @property
    def line(self) -> str:
        return f"{self.method} {self.path}"

    def json(self) -> Any:
        return json.loads(self.body)


@dataclass
class Script:
    metadata: dict[str, Any] = field(default_factory=dict)
    parts: dict[str, tuple[str | None, str, bytes]] = field(default_factory=dict)
    migration_tag: str | None = None
    classes: set[str] = field(default_factory=set)
    bindings: list[dict[str, Any]] = field(default_factory=list)
    secrets: dict[str, str] = field(default_factory=dict)
    crons: list[str] = field(default_factory=list)
    workers_dev: bool = False


def _answer(status: int, payload: Any) -> tuple[int, dict[str, str], bytes]:
    return status, {"content-type": "application/json"}, json.dumps(payload).encode()


def _ok(result: Any, info: dict[str, Any] | None = None) -> tuple[int, dict[str, str], bytes]:
    payload = {"success": True, "errors": [], "messages": [], "result": result}
    if info is not None:
        payload["result_info"] = info
    return _answer(200, payload)


def _err(status: int, code: int, message: str) -> tuple[int, dict[str, str], bytes]:
    errors = [{"code": code, "message": message}]
    return _answer(status, {"success": False, "errors": errors, "messages": [], "result": None})


def _page(items: list[Any], query: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    page, per_page = int(query.get("page", 1)), int(query.get("per_page", 20))
    chunk = items[(page - 1) * per_page : page * per_page]
    pages = max(1, -(-len(items) // per_page))
    info = {"page": page, "per_page": per_page, "count": len(chunk), "total_pages": pages}
    return _ok(chunk, {**info, "total_count": len(items)})


class FakeCloudflare:
    """``api.cloudflare.com/client/v4`` in memory, a :class:`~tau_net.spine.Transport`."""

    def __init__(
        self,
        *,
        token: str = API_TOKEN,
        accounts: tuple[tuple[str, str], ...] = ((ACCOUNT, "Alice's account"),),
        subdomain: str | None = SUBDOMAIN,
        scopes: frozenset[str] = ALL_SCOPES,
    ):
        self.token = token
        self.accounts = accounts
        self.subdomain = subdomain
        self.scopes = scopes
        self.requests: list[Req] = []
        self.scripts: dict[tuple[str, str], Script] = {}
        self.namespaces: dict[str, dict[str, str]] = {}
        self.domains: dict[str, str] = {}
        self.spines: dict[str, FakeSpine] = {}
        self.serves: dict[str, tuple[str, str]] = {}
        self._ids = itertools.count(1)

    # -- the transport -------------------------------------------------------------------------

    def __call__(self, method, url, headers, body, timeout):  # noqa: ANN001
        parts = urllib.parse.urlsplit(url)
        if parts.netloc == "api.cloudflare.com":
            return self._api(method, parts, headers, body)
        spine = self.spines.get(parts.netloc)
        if spine is None:
            raise TransportError(f"no route to {parts.netloc}")
        return spine(method, url, headers, body, timeout)

    @property
    def lines(self) -> list[str]:
        return [request.line for request in self.requests]

    def request(self, line: str) -> Req:
        (match,) = [request for request in self.requests if request.line == line]
        return match

    def new_id(self) -> str:
        return f"{next(self._ids):032x}"

    def deployed(self, name: str = "tau-spine", account: str = ACCOUNT) -> Script:
        return self.scripts[(account, name)]

    def _spine(self, host: str, account: str, name: str) -> None:
        script = self.scripts[(account, name)]
        spine = self.spines.get(host) or FakeSpine(host)
        spine.hub_token = script.secrets.get("HUB_TOKEN", "")
        self.spines[host] = spine
        self.serves[host] = (account, name)

    def _sync(self, account: str, name: str) -> None:
        for host, served in self.serves.items():
            if served == (account, name):
                self.spines[host].hub_token = self.scripts[served].secrets.get("HUB_TOKEN", "")

    # -- the API -------------------------------------------------------------------------------

    def _api(self, method, parts, headers, body):  # noqa: ANN001, C901
        path = parts.path.removeprefix("/client/v4")
        query = dict(urllib.parse.parse_qsl(parts.query))
        lowered = {str(k).lower(): str(v) for k, v in headers.items()}
        request = Req(method, path, query, lowered, body or b"")
        self.requests.append(request)
        if lowered.get("authorization") != f"Bearer {self.token}":
            return _err(401, 1000, "Invalid API Token")
        if path == "/user/tokens/verify" and method == "GET":
            return _ok({"id": "0" * 32, "status": "active"})

        def need(scope: str) -> bool:
            return scope in self.scopes

        denied = _err(403, 10000, "Authentication error")
        if path == "/accounts" and method == "GET":
            if not need("account_settings"):
                return denied
            return _page([{"id": a, "name": n} for a, n in self.accounts], query)
        match = re.fullmatch(r"/accounts/([0-9a-f]{32})(/.*)", path)
        assert match, path
        account, rest = match.groups()
        assert account in {a for a, _ in self.accounts}, account
        kv = self.namespaces.setdefault(account, {})

        if rest == "/storage/kv/namespaces":
            if not need("workers_kv_storage"):
                return denied
            if method == "GET":
                return _page([{"id": i, "title": t} for i, t in kv.items()], query)
            title = request.json()["title"]
            if title in kv.values():
                return _err(400, 10014, "a namespace with this title already exists")
            kv[self.new_id()] = title
            return _ok({"id": list(kv)[-1], "title": title})
        if rest == "/workers/domains" and method == "PUT":
            if not need("workers_routes"):
                return denied
            data = request.json()
            assert (account, data["service"]) in self.scripts
            self.domains[data["hostname"]] = data["service"]
            self._spine(data["hostname"], account, data["service"])
            return _ok({"id": "d" * 32, **data})
        if not need("workers_scripts"):
            return denied
        if rest == "/workers/subdomain" and method == "GET":
            if self.subdomain is None:
                return _err(404, 10007, "This subdomain does not exist")
            return _ok({"subdomain": self.subdomain})
        if rest == "/workers/scripts" and method == "GET":
            listed = [
                {"id": name, "migration_tag": script.migration_tag}
                for (owner, name), script in self.scripts.items()
                if owner == account
            ]
            return _ok(listed)
        match = re.fullmatch(r"/workers/scripts/([a-z0-9-]+)(/[a-z]+)?", rest)
        assert match, rest
        name, sub = match.groups()
        script = self.scripts.get((account, name))
        if sub is None and method == "PUT":
            return self._upload(account, name, request)
        if script is None:
            return _err(404, 10007, "workers.api.error.script_not_found")
        if sub == "/settings" and method == "GET":
            return _ok({"bindings": script.bindings})
        if sub == "/secrets" and method == "PUT":
            data = request.json()
            assert data["type"] == "secret_text"
            script.secrets[data["name"]] = data["text"]
            self._sync(account, name)
            return _ok({"name": data["name"], "type": "secret_text"})
        if sub == "/schedules" and method == "PUT":
            script.crons = [item["cron"] for item in request.json()]
            return _ok({"schedules": request.json()})
        if sub == "/subdomain" and method == "POST":
            script.workers_dev = request.json()["enabled"]
            host = f"{name}.{self.subdomain}.workers.dev"
            if script.workers_dev:
                self._spine(host, account, name)
            else:
                self.spines.pop(host, None)
                self.serves.pop(host, None)
            return _ok({"enabled": script.workers_dev})
        raise AssertionError(f"unexpected {method} {path}")

    def _upload(self, account: str, name: str, request: Req):  # noqa: ANN202
        header = f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
        message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
            header + request.body
        )
        parts: dict[str, tuple[str | None, str, bytes]] = {}
        for part in message.iter_parts():
            key = part.get_param("name", header="content-disposition")
            parts[key] = (
                part.get_filename(),
                part.get_content_type(),
                part.get_payload(decode=True),
            )
        metadata = json.loads(parts["metadata"][2])
        filename, content_type, _ = parts[metadata["main_module"]]
        assert filename == metadata["main_module"]
        assert content_type == "application/javascript+module"
        old = self.scripts.get((account, name))
        tag = old.migration_tag if old else None
        classes = set(old.classes) if old else set()
        migrations = metadata.get("migrations")
        if migrations:
            if migrations.get("old_tag") != tag:
                return _err(400, 10079, "migration tag precondition failed")
            for step in migrations["steps"]:
                classes |= set(step.get("new_sqlite_classes", []))
            tag = migrations["new_tag"]
        bindings = []
        for binding in metadata["bindings"]:
            if binding["type"] == "kv_namespace":
                if binding["namespace_id"] not in self.namespaces.get(account, {}):
                    return _err(400, 10041, "KV namespace not found")
            if binding["type"] == "durable_object_namespace":
                if binding["class_name"] not in classes:
                    return _err(400, 10061, f"no migration for class {binding['class_name']}")
            bindings.append(binding)
        script = Script(metadata, parts, tag, classes, bindings)
        if old is not None:  # secrets, crons and the route survive an upload
            script.secrets, script.crons = old.secrets, old.crons
            script.workers_dev = old.workers_dev
        self.scripts[(account, name)] = script
        self._sync(account, name)
        return _ok({"id": name, "migration_tag": tag})

    def seed(self, *, tag: str = "v1", kv_title: str = "tau-spine-tau") -> str:
        """A Worker as ``wrangler deploy`` left it: its KV namespace, migration tag v1, the
        workers.dev address. Returns the namespace id."""
        namespace = self.new_id()
        self.namespaces.setdefault(ACCOUNT, {})[namespace] = kv_title
        bindings = [{"name": "TAU", "type": "kv_namespace", "namespace_id": namespace}]
        script = Script({}, {}, tag, {"Mailbox"}, bindings, {"HUB_TOKEN": "old"}, ["* * * * *"])
        self.scripts[(ACCOUNT, "tau-spine")] = script
        return namespace


# -- fixtures ----------------------------------------------------------------------------------


@dataclass
class Run:
    result: Result
    fake: FakeCloudflare
    opened: list[str]
    sleeps: list[float]

    @property
    def output(self) -> str:
        return self.result.output

    @property
    def lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.result.stdout.splitlines()]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "home"


@pytest.fixture
def cli(home: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Result]:
    monkeypatch.delenv("TAU_LANG", raising=False)

    def invoke(*args: str, input: str | None = None, **obj: object) -> Result:
        return CliRunner().invoke(net, list(args), input=input, obj={"home": home, **obj})

    return invoke


@pytest.fixture
def deploy(cli, home: Path) -> Callable[..., Run]:
    def run(
        target: Path,
        *args: str,
        fake: FakeCloudflare | None = None,
        input: str | None = None,
        environ: dict[str, str] | None = None,
        **obj: object,
    ) -> Run:
        fake = fake or FakeCloudflare()
        opened: list[str] = []
        sleeps: list[float] = []
        result = cli(
            "spine",
            "deploy",
            str(target),
            *args,
            input=input,
            spine_transport=fake,
            spine_environ=environ if environ is not None else {},
            spine_sleep=sleeps.append,
            spine_open=opened.append,
            **obj,
        )
        return Run(result, fake, opened, sleeps)

    return run


def _project(tmp_path: Path, cli, *args: str, name: str = "spine") -> Path:
    target = tmp_path / name
    result = cli("spine", "init", str(target), *args)
    assert result.exit_code == 0, result.output
    return target


def _dotenv(home: Path) -> dict[str, str]:
    return env_with_dotenv(home, {})


def _config(target: Path) -> dict[str, Any]:
    return parse_jsonc((target / "wrangler.jsonc").read_text(encoding="utf-8"))


KIT_LINK = (
    "https://dash.cloudflare.com/profile/api-tokens?permissionGroupKeys="
    "%5B%7B%22key%22%3A%22workers_scripts%22%2C%22type%22%3A%22edit%22%7D%2C"
    "%7B%22key%22%3A%22workers_kv_storage%22%2C%22type%22%3A%22edit%22%7D%2C"
    "%7B%22key%22%3A%22account_settings%22%2C%22type%22%3A%22read%22%7D%5D"
    "&accountId=%2A&zoneId=all&name=tau%20spine"
)


def _expected_metadata(namespace: str, *, address: str = "", migrations: bool = True) -> dict:
    template = parse_jsonc(load_kit().template)
    metadata: dict[str, Any] = {
        "main_module": "worker.js",
        "bindings": [
            {"name": "TAU_MODE", "type": "plain_text", "text": "local"},
            {"name": "ADDRESS", "type": "plain_text", "text": address},
            {"name": "ALLOW_INSECURE_PEERS", "type": "plain_text", "text": "0"},
            {"name": "TAU", "type": "kv_namespace", "namespace_id": namespace},
            {"name": "MAILBOX", "type": "durable_object_namespace", "class_name": "Mailbox"},
            {
                "name": "INBOX_IP_LIMIT",
                "type": "ratelimit",
                "namespace_id": "10501",
                "simple": {"limit": 60, "period": 60},
            },
            {
                "name": "INBOX_SENDER_LIMIT",
                "type": "ratelimit",
                "namespace_id": "10502",
                "simple": {"limit": 30, "period": 60},
            },
        ],
        "compatibility_date": template["compatibility_date"],
        "compatibility_flags": ["nodejs_compat"],
        "migrations": {"new_tag": "v1", "steps": [{"new_sqlite_classes": ["Mailbox"]}]},
        "observability": {"enabled": True, "head_sampling_rate": 1},
    }
    if not migrations:
        del metadata["migrations"]
    return metadata


# -- the token link ----------------------------------------------------------------------------


def test_the_token_link_is_cloudflares_template_url() -> None:
    """The documented format: permissionGroupKeys (URL-encoded JSON), accountId=*, zoneId=all."""
    config = parse_jsonc(load_kit().template)
    scopes = required_scopes(config, custom_domain=False)
    assert token_link(scopes) == KIT_LINK
    keys = urllib.parse.parse_qs(urllib.parse.urlsplit(KIT_LINK).query)["permissionGroupKeys"]
    assert json.loads(keys[0]) == [
        {"key": "workers_scripts", "type": "edit"},
        {"key": "workers_kv_storage", "type": "edit"},
        {"key": "account_settings", "type": "read"},
    ]
    custom = required_scopes(config, custom_domain=True)
    assert [s.key for s in custom][-1] == "workers_routes"
    assert "%7B%22key%22%3A%22workers_routes%22%2C%22type%22%3A%22edit%22%7D" in token_link(custom)
    assert [s.key for s in required_scopes({}, custom_domain=False)] == [
        "workers_scripts",
        "account_settings",
    ]


# -- a first deploy ----------------------------------------------------------------------------


def test_a_first_deploy_sends_exactly_the_documented_requests(
    tmp_path: Path, cli, deploy, home: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    target = _project(tmp_path, cli)
    run = deploy(target, input=f"{API_TOKEN}\n")
    assert run.result.exit_code == 0, run.output
    fake = run.fake

    assert fake.lines == [
        "GET /user/tokens/verify",
        "GET /accounts",
        f"GET /accounts/{ACCOUNT}/workers/subdomain",
        f"GET /accounts/{ACCOUNT}/workers/scripts",
        f"GET /accounts/{ACCOUNT}/storage/kv/namespaces",
        f"POST /accounts/{ACCOUNT}/storage/kv/namespaces",
        f"PUT {SCRIPT}",
        f"PUT {SCRIPT}/secrets",
        f"PUT {SCRIPT}/schedules",
        f"POST {SCRIPT}/subdomain",
    ]
    assert fake.request("GET /accounts").query == {"page": "1", "per_page": "50"}
    kv_list = fake.request(f"GET /accounts/{ACCOUNT}/storage/kv/namespaces")
    assert kv_list.query == {"page": "1", "per_page": "100"}
    assert fake.request(f"POST /accounts/{ACCOUNT}/storage/kv/namespaces").json() == {
        "title": "tau-spine-tau"
    }
    (namespace,) = fake.namespaces[ACCOUNT]

    upload = fake.request(f"PUT {SCRIPT}")
    assert upload.headers["content-type"].startswith("multipart/form-data; boundary=")
    script = fake.deployed()
    assert script.metadata == _expected_metadata(namespace)
    assert set(script.parts) == {"metadata", "worker.js"}
    assert script.parts["metadata"][:2] == (None, "application/json")
    assert script.parts["worker.js"] == (
        "worker.js",
        "application/javascript+module",
        load_kit().worker,
    )
    assert script.migration_tag == "v1"

    env = _dotenv(home)
    hub_token = env["TAU_SPINE_TOKEN"]
    assert len(hub_token) >= 40
    assert fake.request(f"PUT {SCRIPT}/secrets").json() == {
        "name": "HUB_TOKEN",
        "text": hub_token,
        "type": "secret_text",
    }
    assert fake.request(f"PUT {SCRIPT}/schedules").json() == [{"cron": "* * * * *"}]
    assert fake.request(f"POST {SCRIPT}/subdomain").json() == {"enabled": True}
    assert fake.spines[WORKERS_DEV].requests == [("GET", "/hub/health")]
    assert run.sleeps == []

    assert env["CLOUDFLARE_API_TOKEN"] == API_TOKEN
    assert env["TAU_SPINE_URL"] == f"https://{WORKERS_DEV}"
    assert stat.S_IMODE((home / ".env").stat().st_mode) == 0o600

    config = _config(target)
    assert config["account_id"] == ACCOUNT
    assert config["kv_namespaces"] == [{"binding": "TAU", "id": namespace}]
    text = (target / "wrangler.jsonc").read_text(encoding="utf-8")
    assert text.startswith("// tau spine") and "// ADDRESS: the tau's address" in text

    # The API token only in Authorization headers, the hub token only in the secret's body.
    for request in fake.requests:
        assert request.headers["authorization"] == f"Bearer {API_TOKEN}"
        assert API_TOKEN.encode() not in request.body
        if request.line != f"PUT {SCRIPT}/secrets":
            assert hub_token.encode() not in request.body
    for secret in (API_TOKEN, hub_token):
        assert secret not in run.output
        assert secret not in caplog.text

    assert run.opened == [KIT_LINK]
    output = run.output
    assert KIT_LINK in output
    for label in (
        "Account > Workers Scripts > Edit",
        "Account > Workers KV Storage > Edit",
        "Account > Account Settings > Read",
    ):
        assert f"  - {label}" in output
    assert "Zone > Workers Routes" not in output
    for line in (
        "Cloudflare accepted the API token.",
        "Saved CLOUDFLARE_API_TOKEN in",
        f"Cloudflare account: Alice's account ({ACCOUNT}).",
        f"Created the KV namespace tau-spine-tau ({namespace}) for TAU.",
        "Recorded the account and the KV namespace ids in",
        "Durable Object migrations: 1 step(s), up to v1.",
        "Uploaded the Worker tau-spine (",
        "Generated a new TAU_SPINE_TOKEN",
        "Set the Worker's HUB_TOKEN secret to TAU_SPINE_TOKEN.",
        "Cron triggers: * * * * *.",
        f"The workers.dev address is on: {WORKERS_DEV}.",
        f"Wrote TAU_SPINE_URL=https://{WORKERS_DEV}",
        f"The spine answers at https://{WORKERS_DEV} (version 0.1.0) and accepts TAU_SPINE_TOKEN.",
        f"The spine is deployed at https://{WORKERS_DEV}.",
        "tau net publish",
    ):
        assert line in output, line


def test_a_redeploy_updates_the_worker_in_place(tmp_path: Path, cli, deploy, home: Path) -> None:
    target = _project(tmp_path, cli)
    first = deploy(target, input=f"{API_TOKEN}\n")
    assert first.result.exit_code == 0, first.output
    fake = first.fake
    (namespace,) = fake.namespaces[ACCOUNT]
    hub_token = _dotenv(home)["TAU_SPINE_TOKEN"]
    fake.requests.clear()

    again = deploy(target, fake=fake)
    assert again.result.exit_code == 0, again.output
    assert fake.lines == [
        "GET /user/tokens/verify",
        f"GET /accounts/{ACCOUNT}/workers/subdomain",
        f"GET /accounts/{ACCOUNT}/workers/scripts",
        f"PUT {SCRIPT}",
        f"PUT {SCRIPT}/secrets",
        f"PUT {SCRIPT}/schedules",
        f"POST {SCRIPT}/subdomain",
    ]
    assert fake.deployed().metadata == _expected_metadata(namespace, migrations=False)
    assert fake.request(f"PUT {SCRIPT}/secrets").json()["text"] == hub_token
    assert _dotenv(home)["TAU_SPINE_TOKEN"] == hub_token
    assert len(fake.namespaces[ACCOUNT]) == 1
    assert "Using CLOUDFLARE_API_TOKEN from" in again.output
    assert f"Cloudflare account: {ACCOUNT}." in again.output
    assert "Durable Object migrations: already at v1." in again.output
    assert "Using the TAU_SPINE_TOKEN" in again.output
    assert "Recorded" not in again.output and again.opened == []


def test_a_new_project_keeps_the_storage_of_the_deployed_worker(
    tmp_path: Path, cli, deploy
) -> None:
    """The update path of the README: a new `tau net spine init` directory, same Worker."""
    fake = FakeCloudflare()
    first = deploy(_project(tmp_path, cli, name="old"), fake=fake, input=f"{API_TOKEN}\n")
    assert first.result.exit_code == 0, first.output
    (namespace,) = fake.namespaces[ACCOUNT]
    fake.requests.clear()

    target = _project(tmp_path, cli, name="new")
    run = deploy(target, fake=fake)
    assert run.result.exit_code == 0, run.output
    assert fake.lines == [
        "GET /user/tokens/verify",
        "GET /accounts",
        f"GET /accounts/{ACCOUNT}/workers/subdomain",
        f"GET /accounts/{ACCOUNT}/workers/scripts",
        f"GET {SCRIPT}/settings",
        f"PUT {SCRIPT}",
        f"PUT {SCRIPT}/secrets",
        f"PUT {SCRIPT}/schedules",
        f"POST {SCRIPT}/subdomain",
    ]
    assert fake.deployed().metadata == _expected_metadata(namespace, migrations=False)
    assert _config(target)["kv_namespaces"] == [{"binding": "TAU", "id": namespace}]
    assert f"KV namespace for TAU: {namespace}, the one the Worker already uses." in run.output


def test_the_api_takes_over_a_worker_that_wrangler_deployed(tmp_path: Path, cli, deploy) -> None:
    fake = FakeCloudflare()
    namespace = fake.seed()
    run = deploy(_project(tmp_path, cli), fake=fake, input=f"{API_TOKEN}\n")
    assert run.result.exit_code == 0, run.output
    script = fake.deployed()
    assert script.metadata == _expected_metadata(namespace, migrations=False)
    assert script.secrets["HUB_TOKEN"] != "old"
    assert f"POST /accounts/{ACCOUNT}/storage/kv/namespaces" not in fake.lines


def test_a_namespace_left_by_a_deleted_worker_is_reused(tmp_path: Path, cli, deploy) -> None:
    fake = FakeCloudflare()
    namespace = fake.seed()
    del fake.scripts[(ACCOUNT, "tau-spine")]
    run = deploy(_project(tmp_path, cli), fake=fake, input=f"{API_TOKEN}\n")
    assert run.result.exit_code == 0, run.output
    assert f"POST /accounts/{ACCOUNT}/storage/kv/namespaces" not in fake.lines
    assert fake.deployed().metadata == _expected_metadata(namespace)
    assert f"KV namespace for TAU: tau-spine-tau ({namespace}), already in" in run.output


def test_an_unknown_migration_tag_sends_every_step(tmp_path: Path, cli, deploy) -> None:
    fake = FakeCloudflare()
    fake.seed(tag="v0")
    run = deploy(_project(tmp_path, cli), fake=fake, input=f"{API_TOKEN}\n")
    assert run.result.exit_code == 0, run.output
    assert fake.deployed().metadata["migrations"] == {
        "old_tag": "v0",
        "new_tag": "v1",
        "steps": [{"new_sqlite_classes": ["Mailbox"]}],
    }
    assert "the deployed Worker has the migration tag v0" in run.output


# -- a custom domain ---------------------------------------------------------------------------


def test_a_custom_domain(tmp_path: Path, cli, deploy, home: Path) -> None:
    target = _project(tmp_path, cli, "--address", "tau.example.com")
    run = deploy(target, input=f"{API_TOKEN}\n")
    assert run.result.exit_code == 0, run.output
    fake = run.fake
    assert fake.lines == [
        "GET /user/tokens/verify",
        "GET /accounts",
        f"GET /accounts/{ACCOUNT}/workers/scripts",
        f"GET /accounts/{ACCOUNT}/storage/kv/namespaces",
        f"POST /accounts/{ACCOUNT}/storage/kv/namespaces",
        f"PUT {SCRIPT}",
        f"PUT {SCRIPT}/secrets",
        f"PUT {SCRIPT}/schedules",
        f"POST {SCRIPT}/subdomain",
        f"PUT /accounts/{ACCOUNT}/workers/domains",
    ]
    (namespace,) = fake.namespaces[ACCOUNT]
    expected = _expected_metadata(namespace, address="tau.example.com")
    assert fake.deployed().metadata == expected
    assert fake.request(f"POST {SCRIPT}/subdomain").json() == {"enabled": False}
    assert fake.request(f"PUT /accounts/{ACCOUNT}/workers/domains").json() == {
        "hostname": "tau.example.com",
        "service": "tau-spine",
    }
    assert _dotenv(home)["TAU_SPINE_URL"] == "https://tau.example.com"
    assert fake.spines["tau.example.com"].requests == [("GET", "/hub/health")]
    assert "  - Zone > Workers Routes > Edit" in run.output
    assert run.opened[0].endswith("&accountId=%2A&zoneId=all&name=tau%20spine")
    assert "workers_routes" in urllib.parse.unquote(run.opened[0])
    assert "Attached the custom domain tau.example.com." in run.output
    assert "The workers.dev address is off" in run.output


def test_an_address_flag_writes_the_route_into_the_project(tmp_path: Path, cli, deploy) -> None:
    target = _project(tmp_path, cli)
    run = deploy(target, "--address", "tau.example.com", input=f"{API_TOKEN}\n")
    assert run.result.exit_code == 0, run.output
    config = _config(target)
    assert config["vars"]["ADDRESS"] == "tau.example.com"
    assert config["routes"] == [{"pattern": "tau.example.com", "custom_domain": True}]
    initialised = _config(_project(tmp_path, cli, "--address", "tau.example.com", name="twin"))
    assert {k: v for k, v in config.items() if k not in ("account_id", "kv_namespaces")} == {
        k: v for k, v in initialised.items() if k != "kv_namespaces"
    }
    assert run.fake.domains == {"tau.example.com": "tau-spine"}
    assert "Wrote the address tau.example.com and its custom-domain route" in run.output


def test_an_address_that_contradicts_the_project(tmp_path: Path, cli, deploy) -> None:
    target = _project(tmp_path, cli, "--address", "tau.example.com")
    run = deploy(target, "--address", "other.example.org", input=f"{API_TOKEN}\n")
    assert run.result.exit_code == 1
    assert "has ADDRESS 'tau.example.com', not 'other.example.org'" in run.output
    assert run.fake.requests == []


def test_a_workers_dev_address_must_be_the_real_one(tmp_path: Path, cli, deploy) -> None:
    target = _project(tmp_path, cli)
    run = deploy(target, "--address", "tau-spine.someone-else.workers.dev", input=f"{API_TOKEN}\n")
    assert run.result.exit_code == 1
    assert f"the Worker's workers.dev address is {WORKERS_DEV}" in run.output
    assert all(request.method == "GET" for request in run.fake.requests)


# -- the token and the account -----------------------------------------------------------------


def test_a_token_from_the_environment_is_not_saved(tmp_path: Path, cli, deploy, home) -> None:
    run = deploy(_project(tmp_path, cli), environ={"CLOUDFLARE_API_TOKEN": API_TOKEN})
    assert run.result.exit_code == 0, run.output
    assert "Using CLOUDFLARE_API_TOKEN from the environment." in run.output
    assert "CLOUDFLARE_API_TOKEN" not in _dotenv(home)
    assert run.opened == []


def test_a_wrong_token_is_refused_and_not_saved(tmp_path: Path, cli, deploy, home) -> None:
    run = deploy(_project(tmp_path, cli), input=f"{WRONG_TOKEN}\n")
    assert run.result.exit_code == 1
    assert run.fake.lines == ["GET /user/tokens/verify"]
    assert "401, 1000 Invalid API Token" in run.output
    assert "is not a valid Cloudflare API token; create one at https://dash.cloudflare" in (
        run.output
    )
    assert WRONG_TOKEN not in run.output
    assert not (home / ".env").exists()


def test_an_empty_answer_at_the_prompt(tmp_path: Path, cli, deploy) -> None:
    run = deploy(_project(tmp_path, cli), input="\n")
    assert run.result.exit_code == 1
    assert "tau net: no Cloudflare API token: create one at https://dash." in run.output
    assert run.fake.requests == []


def test_several_accounts_are_offered(tmp_path: Path, cli, deploy) -> None:
    fake = FakeCloudflare(accounts=((ACCOUNT, "Alice"), (OTHER, "Work")))
    run = deploy(_project(tmp_path, cli), fake=fake, input=f"{API_TOKEN}\n2\n")
    assert run.result.exit_code == 0, run.output
    assert f"  1. Alice ({ACCOUNT})" in run.output and f"  2. Work ({OTHER})" in run.output
    assert (OTHER, "tau-spine") in fake.scripts and (ACCOUNT, "tau-spine") not in fake.scripts


def test_the_account_id_option(tmp_path: Path, cli, deploy) -> None:
    fake = FakeCloudflare(accounts=((ACCOUNT, "Alice"), (OTHER, "Work")))
    target = _project(tmp_path, cli)
    run = deploy(target, "--account-id", OTHER, fake=fake, input=f"{API_TOKEN}\n")
    assert run.result.exit_code == 0, run.output
    assert "GET /accounts" not in fake.lines
    assert _config(target)["account_id"] == OTHER
    bad = deploy(target, "--account-id", "nope", fake=fake)
    assert bad.result.exit_code == 1 and "not a Cloudflare account id: 'nope'" in bad.output


@pytest.mark.parametrize(
    ("missing", "address", "label", "failed"),
    [
        ("workers_kv_storage", None, "Account > Workers KV Storage > Edit", "list the KV"),
        ("workers_scripts", None, "Account > Workers Scripts > Edit", "read the account's"),
        ("account_settings", None, "Account > Account Settings > Read", "list the accounts"),
        ("workers_routes", "tau.example.com", "Zone > Workers Routes > Edit", "attach the custom"),
    ],
)
def test_a_missing_permission_is_named(
    tmp_path: Path, cli, deploy, missing: str, address: str | None, label: str, failed: str
) -> None:
    fake = FakeCloudflare(scopes=ALL_SCOPES - {missing})
    args = ("--address", address) if address else ()
    run = deploy(_project(tmp_path, cli, *args), fake=fake, input=f"{API_TOKEN}\n")
    assert run.result.exit_code == 1
    text = run.result.stderr
    assert text.startswith(f"tau net: Cloudflare refused to {failed}")
    assert "(403, 10000 Authentication error)" in text
    assert f'the API token needs the permission "{label}"' in text
    assert API_TOKEN not in run.output


def test_an_account_without_a_workers_dev_subdomain(tmp_path: Path, cli, deploy) -> None:
    fake = FakeCloudflare(subdomain=None)
    run = deploy(_project(tmp_path, cli), fake=fake, input=f"{API_TOKEN}\n")
    assert run.result.exit_code == 1
    assert "has no workers.dev subdomain yet: pick one at " in run.output
    assert f"https://dash.cloudflare.com/{ACCOUNT}/workers/onboarding" in run.output
    assert all(request.method == "GET" for request in fake.requests)


def test_a_spine_that_does_not_answer_yet_is_a_note(tmp_path: Path, cli, deploy, home) -> None:
    fake = FakeCloudflare()

    class Unreachable(FakeCloudflare):
        def __call__(self, method, url, headers, body, timeout):  # noqa: ANN001
            if "workers.dev" in url:
                raise TransportError("DNS not ready")
            return fake(method, url, headers, body, timeout)

    run = deploy(_project(tmp_path, cli), fake=Unreachable(), input=f"{API_TOKEN}\n")
    assert run.result.exit_code == 0, run.output
    assert run.sleeps == [HEALTH_DELAY] * (HEALTH_ATTEMPTS - 1)
    assert "does not answer at https://tau-spine.example-sub.workers.dev yet" in run.output
    assert "DNS not ready" in run.output
    assert _dotenv(home)["TAU_SPINE_URL"] == f"https://{WORKERS_DEV}"


def test_the_api_path_refuses_what_it_cannot_deploy(tmp_path: Path, cli, deploy) -> None:
    target = _project(tmp_path, cli)
    path = target / "wrangler.jsonc"
    config = _config(target)
    path.write_text(json.dumps({**config, "r2_buckets": [{"binding": "B"}]}), encoding="utf-8")
    run = deploy(target, input=f"{API_TOKEN}\n")
    assert run.result.exit_code == 1
    assert "has r2_buckets, which the Cloudflare API path does not deploy" in run.output
    assert "--wrangler" in run.output
    d1 = {**config, "d1_databases": [{"binding": "DB", "database_name": "x"}]}
    path.write_text(json.dumps(d1), encoding="utf-8")
    run = deploy(target, input=f"{API_TOKEN}\n")
    assert run.result.exit_code == 1 and "has a D1 database" in run.output
    assert run.fake.requests == []
    missing = deploy(tmp_path / "nothing", input=f"{API_TOKEN}\n")
    assert missing.result.exit_code == 1 and "is not a spine project" in missing.output


def test_the_wrangler_flags_do_not_mix(tmp_path: Path, cli) -> None:
    target = _project(tmp_path, cli)
    for extra in (("--json",), ("--account-id", ACCOUNT)):
        result = cli("spine", "deploy", str(target), "--wrangler", *extra)
        assert result.exit_code == 2
        assert "belong to the API path" in result.output


def test_the_api_path_speaks_turkish(tmp_path: Path, cli, deploy) -> None:
    run = deploy(_project(tmp_path, cli), input=f"{API_TOKEN}\n", lang="tr")
    assert run.result.exit_code == 0, run.output
    assert "Dağıtım şu izinlere sahip bir Cloudflare API token'ı istiyor:" in run.output
    assert "Cloudflare API token'ını kabul etti." in run.output
    assert "Spine https://tau-spine.example-sub.workers.dev adresinde yayında." in run.output


# -- --json for the app ------------------------------------------------------------------------


def test_json_asks_for_a_token_with_the_link(tmp_path: Path, cli, deploy) -> None:
    run = deploy(_project(tmp_path, cli), "--json", input="{}")
    assert run.result.exit_code == 1
    (line,) = run.lines
    assert line["type"] == "need_token"
    assert line["link"] == KIT_LINK
    assert line["scopes"] == [
        "Account > Workers Scripts > Edit",
        "Account > Workers KV Storage > Edit",
        "Account > Account Settings > Read",
    ]
    assert line["permissions"][0] == {"key": "workers_scripts", "type": "edit"}
    assert run.fake.requests == [] and run.opened == []


def test_json_deploys_with_the_token_on_stdin(tmp_path: Path, cli, deploy, home) -> None:
    fake = FakeCloudflare(accounts=((ACCOUNT, "Alice"), (OTHER, "Work")))
    target = _project(tmp_path, cli)
    first = deploy(target, "--json", fake=fake, input=json.dumps({"token": API_TOKEN}))
    assert first.result.exit_code == 1
    assert [line["type"] for line in first.lines] == ["progress"] * 2 + ["choose_account"]
    assert first.lines[-1]["accounts"] == [
        {"id": ACCOUNT, "name": "Alice"},
        {"id": OTHER, "name": "Work"},
    ]
    assert _dotenv(home)["CLOUDFLARE_API_TOKEN"] == API_TOKEN  # verified, so kept for the retry
    assert API_TOKEN not in first.result.stdout

    second = deploy(target, "--json", fake=fake, input=json.dumps({"account_id": OTHER}))
    assert second.result.exit_code == 0, second.output
    lines = second.lines
    assert all(line["type"] == "progress" for line in lines[:-1])
    assert {"key", "text", "fields"} <= set(lines[0])
    assert lines[-1] == {
        "type": "done",
        "url": f"https://{WORKERS_DEV}",
        "account_id": OTHER,
        "token_created": True,
        "healthy": True,
    }
    uploaded = [line for line in lines if line.get("key") == "net.spine.api.uploaded"]
    assert uploaded[0]["fields"]["name"] == "tau-spine"
    hub_token = _dotenv(home)["TAU_SPINE_TOKEN"]
    assert hub_token not in second.result.stdout and API_TOKEN not in second.result.stdout


@pytest.mark.parametrize("stdin", ["not json", "[]", '{"token": 1}', '{"password": "x"}'])
def test_json_refuses_bad_input(tmp_path: Path, cli, deploy, stdin: str) -> None:
    run = deploy(_project(tmp_path, cli), "--json", input=stdin)
    assert run.result.exit_code == 1
    (line,) = run.lines
    assert line["type"] == "error" and "stdin" in line["message"]


def test_json_reports_errors_as_a_line(tmp_path: Path, cli, deploy) -> None:
    run = deploy(_project(tmp_path, cli), "--json", input=json.dumps({"token": WRONG_TOKEN}))
    assert run.result.exit_code == 1
    assert run.lines[-1]["type"] == "error"
    assert "Invalid API Token" in run.lines[-1]["message"]
    assert WRONG_TOKEN not in run.result.stdout


# -- the pieces --------------------------------------------------------------------------------


def test_plan_migrations_follows_wranglers_rule() -> None:
    migrations = [
        {"tag": "v1", "new_sqlite_classes": ["Mailbox"]},
        {"tag": "v2", "new_sqlite_classes": ["TauBrain"]},
    ]
    both = [{"new_sqlite_classes": ["Mailbox"]}, {"new_sqlite_classes": ["TauBrain"]}]
    assert plan_migrations(migrations, None) == ({"new_tag": "v2", "steps": both}, False)
    assert plan_migrations(migrations, "v1") == (
        {"old_tag": "v1", "new_tag": "v2", "steps": both[1:]},
        False,
    )
    assert plan_migrations(migrations, "v2") == (None, False)
    assert plan_migrations(migrations, "v9") == (
        {"old_tag": "v9", "new_tag": "v2", "steps": both},
        True,
    )
    assert plan_migrations([], "v1") == (None, False)


def test_set_members_keeps_comments() -> None:
    text = '// head\n{\n  "name": "tau-spine", // the name\n  /* x */ "vars": {"A": "1"}\n}\n'
    out = set_members(text, {"account_id": ACCOUNT, "vars": {"A": "2"}})
    assert out.startswith('// head\n{\n  "name": "tau-spine",\n  "account_id": ')
    assert "// the name" in out and "/* x */" in out
    assert parse_jsonc(out) == {"name": "tau-spine", "account_id": ACCOUNT, "vars": {"A": "2"}}
    template = load_kit().template
    edited = set_members(template, {"kv_namespaces": [{"binding": "TAU", "id": "a" * 32}]})
    assert edited.count("//") == template.count("//")
    assert parse_jsonc(edited)["kv_namespaces"] == [{"binding": "TAU", "id": "a" * 32}]


def test_upload_metadata_sends_non_string_vars_as_json() -> None:
    config = {"vars": {"A": "x", "N": 3}, "compatibility_date": "2026-01-01"}
    metadata = upload_metadata(config, main="worker.js", kv_ids={}, migrations=None)
    assert metadata == {
        "main_module": "worker.js",
        "bindings": [
            {"name": "A", "type": "plain_text", "text": "x"},
            {"name": "N", "type": "json", "json": 3},
        ],
        "compatibility_date": "2026-01-01",
    }


def test_multipart_round_trips() -> None:
    body, content_type = multipart(
        [("metadata", None, "application/json", b'{"a":1}'), ("w.js", "w.js", "text/x", b"x\r\n")]
    )
    header = f"Content-Type: {content_type}\r\n\r\n".encode()
    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(header + body)
    parts = [
        (
            p.get_param("name", header="content-disposition"),
            p.get_filename(),
            p.get_content_type(),
            p.get_payload(decode=True),
        )
        for p in message.iter_parts()
    ]
    assert parts == [
        ("metadata", None, "application/json", b'{"a":1}'),
        ("w.js", "w.js", "text/x", b"x\r\n"),
    ]
