# Write a plugin

A plugin is a separate Python distribution that provides components to tau through entry points. It depends on `tau-core`'s public API, needs no change to tau, and plugs in with `pip install` (or `uv add`). This page builds one package, `tau-example`, that provides one component in **every** group. It is the same shape as the three test fixtures under [`packages/tau-core/tests/fixtures/`](https://github.com/fport/tau/tree/main/packages/tau-core/tests/fixtures), which are the reference implementations and are tested in tau-core's suite.

The contracts and the fail-closed rules are in [Components and plugins](../reference/components.md).

## The package

```text
tau-example/
├── pyproject.toml
├── README.md
└── src/tau_example/
    ├── __init__.py       tools, provider, session backend, context source, hub service
    └── cli.py            the `tau example` command
```

### `pyproject.toml`

```toml
[project]
name = "tau-example"
version = "0.1.0"
description = "Example tau plugin: one component in every entry-point group."
requires-python = ">=3.12"
dependencies = ["tau-core>=0.2", "click>=8.1"]

[project.entry-points."tau.tools"]
example = "tau_example:TOOLS"

[project.entry-points."tau.commands"]
example = "tau_example.cli:example"

[project.entry-points."tau.providers"]
example = "tau_example:make_model"

[project.entry-points."tau.sessions"]
example = "tau_example:make_store"

[project.entry-points."tau.context"]
example = "tau_example:make_context_source"

[project.entry-points."tau.hub_services"]
example = "tau_example:make_service"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/tau_example"]
```

The entry-point **name** (`example`) is what `tau components`, `tau.toml` and `[components]` refer to. It must not collide with a built-in seed (`bedrock`, `anthropic`, `fake`, `memory`, `file`); a colliding entry point is logged and ignored.

## Tools: `tau.tools`

A tool is a Strands tool with a **tier**. Use `@tau_tool`; a plain `@tool` has no tier and is skipped with a warning.

```python
# src/tau_example/__init__.py
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tau_core import (
    Config,
    ContextSource,
    MemorySessionStore,
    SessionStore,
    Tier,
    tau_tool,
)
from tau_core.config import RoleConfig
from tau_core.hub import ControlApi, ControlRequest, Hub
from tau_core.testing import FakeModel


@tau_tool(tier=Tier.READ)
def example_echo(text: str) -> str:
    """Returns the given text unchanged.

    Args:
        text: The text to return.
    """
    return text


@tau_tool(tier=Tier.PHYSICAL, effect="Example: pretends to toggle a relay; nothing moves.")
def example_relay(state: str) -> str:
    """Pretends to switch an example relay on or off (tier 2, asks for approval).

    Args:
        state: "on" or "off".
    """
    return f"relay {state} (simulated)"


TOOLS = [example_echo, example_relay]
```

The entry point value can be one tool, a list, or a zero-argument factory returning either. Descriptions and effects are English; the model reads them and the approval prompt shows the effect verbatim. Tier 2 means every call asks; there is no way for a plugin to skip that.

## A command: `tau.commands`

```python
# src/tau_example/cli.py
import click


@click.command(name="example", help="Say hello from the example plugin.")
@click.pass_context
def example(ctx: click.Context) -> None:
    obj = ctx.find_object(dict) or {}
    click.echo(f"hello from tau-example (profile {obj.get('profile') or 'home'})")
```

Any `click.Command` works; it is mounted as `tau example`. The parent's `--home`, `--profile`, `--lang` and `--verbose` arrive in `ctx.find_object(dict)` as `home`, `profile`, `lang` and `verbose`.

## A provider: `tau.providers`

A provider is a factory `(RoleConfig, env) -> strands Model`. Declare the credentials it needs as `required_env`: a list of alternatives, each a list of variable names that must all be set. `tau doctor` and `MissingCredentials` use it; a role on this provider fails before start-up when none of the alternatives is satisfied.

```python
def make_model(role_cfg: RoleConfig, env: Mapping[str, str]) -> FakeModel:
    """A scripted model; a real plugin returns a Strands Model for its API."""
    return FakeModel(default=f"example model for {role_cfg.model_id}")


make_model.required_env = [["EXAMPLE_API_KEY"]]  # type: ignore[attr-defined]
```

Use it from `tau.toml`:

```toml
[models.roles.brain]
provider = "example"
model_id = "example-large"
```

`Config.load` validates the name without importing your module; the factory is loaded only when a role on it is resolved. A factory that raises on import shows up in `tau components` and `tau doctor` as `Model provider 'example' from tau-example failed to load: …`.

## A session backend: `tau.sessions`

A backend is a factory `(Config) -> SessionStore`. `SessionStore` is Strands' `SessionRepository` (nine methods) plus five tau extras: `list_sessions`, `append_event`, `read_events`, `write_meta`, `read_meta` and `event_sink`. The easiest start is to subclass `MemorySessionStore` or `FileSessionStore`.

```python
class ExampleSessionStore(MemorySessionStore):
    """An in-memory store with a marker attribute."""

    example = True


def make_store(config: Config) -> SessionStore:
    return ExampleSessionStore()
```

```toml
[sessions]
backend = "example"
```

Keep the store's discipline: never delete, never overwrite a message, write atomically, refuse ids that are not plain names.

## A context source: `tau.context`

A context source feeds the `## Now` block of the system prompt. The factory returns a zero-argument callable that returns partial overrides (`nodes`, `budget`). It runs **before every model call**, so it must return a cached value quickly and never do a network round trip. `None` means unknown; a source that raises is skipped and logged once.

```python
def make_context_source(config: Config) -> ContextSource:
    """Reports the nodes listed in [component.example] nodes; none configured = unknown."""
    nodes = config.component("example").get("nodes")
    return lambda: {"nodes": nodes}
```

```toml
[component.example]
nodes = ["mac", "arm"]
```

The prompt then reads `Live nodes: mac, arm`. `[components] context = ["example"]` enables only this source; an empty list enables every discovered one.

## A hub service: `tau.hub_services`

A hub service has a `name`, `async start(hub)` and `async stop()`. `tau hub run` starts the control API first, then every enabled service in order, and stops them in reverse. Inside `start` a service may add keys to `GET /status` and routes to the control API. Routes are additive only; `add_route` raises for a path that exists.

```python
class ExampleService:
    """Adds a /status key and a GET /example route once the hub has started it."""

    name = "example"

    def __init__(self, config: Config):
        self.config = config

    async def start(self, hub: Hub) -> None:
        hub.add_status_source(lambda: {"example": {"profile": self.config.profile}})
        api = hub.find_service(ControlApi.name)
        if isinstance(api, ControlApi):
            api.add_route("GET", "/example", self._example)

    async def stop(self) -> None:
        pass

    def _example(self, request: ControlRequest) -> tuple[int, Any]:
        return 200, {"example": True, "component": self.config.component("example")}


def make_service(config: Config) -> ExampleService:
    return ExampleService(config)
```

Handlers run in the server thread; reach the event loop with `asyncio.run_coroutine_threadsafe(coro, hub.loop)`. A service that fails to build or start is logged and skipped; the hub runs on. `[components.hub] services = ["example"]` enables only this one.

## Messages in the UI language

If your component prints anything a person reads, add the keys to the shared table so the terminal and the TUI show it in the configured language:

```python
from tau_core.i18n import register_messages, t

register_messages({"example.hello": {"en": "Hello from the example.", "tr": "Örnekten merhaba."}})
print(t("example.hello", "tr"))
```

Every key needs an English template; other languages fall back to it.

## Install and check

```sh
uv add ./tau-example                # in a project; or: pip install ./tau-example
tau components                      # every group now has an `example` row
tau doctor                          # load errors, [components] names, credentials
tau example                         # the command
tau chat                            # /tools shows example_echo (tier 0) and example_relay (tier 2)
```

In the tau repository itself, a plugin under development is added as a workspace member in the root `pyproject.toml` (`[tool.uv.workspace] members` plus `[tool.uv.sources]`) and to the `dev` dependency group, which is how the three fixtures are installed.

## Test it

Tests run offline with `tau_core.testing`:

```python
from tau_core import Decision, build_agent
from tau_core.testing import FakeModel, ScriptedApprover, ToolCall, test_config


async def test_relay_needs_approval(tmp_path):
    config = test_config(tmp_path)
    model = FakeModel([ToolCall("example_relay", {"state": "on"}), "Done."])
    approver = ScriptedApprover([Decision.REJECTED])
    agent = build_agent(config=config, model=model, approver=approver, tools=TOOLS)
    reply = await agent.ask("switch it on")
    assert "relay on" not in reply
```

`test_config` builds a throwaway `TAU_HOME` and `TAU_DATA_DIR` under `tmp_path`, so the test never touches your real files. Never script an approval where the behaviour under test is the refusal; and never make an approver that approves on its own.

## Publish it

Give the distribution a name that starts with `tau-`, keep the import name flat (`tau_example`), put the README and a version in `pyproject.toml`, and `uv build` then `uv publish`. tau discovers it on the next start of any command.
