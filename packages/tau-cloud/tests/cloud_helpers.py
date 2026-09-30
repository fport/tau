"""Shared helpers for the command tests: a tau home with every file of the set (and a `.env`
that must never leave it) and a CliRunner call with the fakes in the context object.

Imported as ``cloud_helpers`` (``conftest.py`` puts this directory on ``sys.path``; the name
differs from the other packages' helpers so they never shadow each other)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from click.testing import CliRunner, Result
from tau_cloud.cli import cloud
from tau_core.testing import test_config
from tau_net.testing import DEFAULT_HUB_TOKEN, FakeSpine

SECRET = "sk-test-never-leaves-the-machine"
"""The value of a credential in every test home's ``.env``."""
USER_FACT = "PRIVATE-USER-FACT: the owner's door code is 4711."
TAU_TOML_EXTRA = """
# The network: comments must survive the cloud patch.
[component.net]
name = "Alice's tau"   # shown on the card
store = "file"
"""


def make_home(root: Path, *, net_note: bool = True, user: bool = True) -> Path:
    """A configuration root like ``tau init`` leaves it, plus ``persona/net.md`` and ``.env``."""
    config = test_config(root)
    home = config.home
    with (home / "tau.toml").open("a", encoding="utf-8") as handle:
        handle.write(TAU_TOML_EXTRA)
    persona = home / "persona"
    if user:
        (persona / "user.md").write_text(USER_FACT + "\n", encoding="utf-8")
    else:
        (persona / "user.md").unlink()
    if net_note:
        (persona / "net.md").write_text("- Public: likes short meetings.\n", encoding="utf-8")
    (home / ".env").write_text(f"ANTHROPIC_API_KEY={SECRET}\n", encoding="utf-8")
    return home


def spine_env(spine: FakeSpine, **extra: str) -> dict[str, str]:
    return {"TAU_SPINE_URL": spine.url, "TAU_SPINE_TOKEN": DEFAULT_HUB_TOKEN, **extra}


def invoke(
    spine: FakeSpine,
    home: Path,
    *args: str,
    env: Mapping[str, str] | None = None,
    interactive: bool | None = None,
    runner: Any = None,
    input: str | None = None,
) -> Result:
    obj: dict[str, Any] = {
        "home": home,
        "cloud_env": spine_env(spine) if env is None else dict(env),
        "cloud_transport": spine,
    }
    if interactive is not None:
        obj["cloud_interactive"] = interactive
    if runner is not None:
        obj["cloud_hub_runner"] = runner
    return CliRunner().invoke(cloud, list(args), obj=obj, input=input)
