"""Check steps: a ``tau`` command that reports a state and says what the owner must do.

A catalog step with ``check = true`` names a command that speaks this protocol: ``tau <command>
--json`` prints one JSON object and exits 0 when the check passes, 1 when it does not.

.. code-block:: json

    {"check": 1, "ok": false, "summary": "sshd is not set up",
     "checks": [{"id": "sshd", "label": "SSH server", "status": "fail", "detail": "off"}],
     "action": {"kind": "sudo", "text": "Run this in your own terminal ...",
                "command": "bash ~/.local/share/tau/remote/setup-all.sh", "sudo": true,
                "changes": ["..."], "script": "/.../setup-all.sh", "url": null},
     "values": {}}

- ``checks`` are the lines to show: ``ok``, ``fail``, ``warn`` or ``info``.
- ``action`` is what only the owner can do: install an app, log in, run a command in their own
  terminal. Its ``command`` is **shown, never run**: tau does not run it and neither does the
  app. ``sudo`` says it asks for the password. ``url`` is a page the owner may open.
- ``values`` are the facts the command found, for the app (e.g. the Termius host and user).

The terminal wizard renders the object, offers to open ``url``, and waits for "done" (check
again) or "skip". JSON mode passes it on as a ``check`` event and, while it fails with an
action, as ``needs_ui``: the app shows the action and runs the step again when the owner is done
(``docs/reference/setup.md``). The texts come localized from the command itself.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from tau_core.i18n import t

__all__ = [
    "ACTION_KINDS",
    "CHECK_PROTOCOL",
    "STATUSES",
    "Action",
    "CheckItem",
    "CheckResult",
    "parse_check",
    "render_action",
    "render_checks",
]

CHECK_PROTOCOL = 1
STATUSES: tuple[str, ...] = ("ok", "fail", "warn", "info")
ACTION_KINDS: tuple[str, ...] = ("install", "login", "sudo", "key", "other")
"""``install`` an app or program, ``login`` to a service, ``sudo`` a command that asks for the
password, ``key`` add the phone's key, ``other`` anything else."""
_MARKS = {"ok": "✓", "fail": "✗", "warn": "!", "info": "·"}
_TEXT_LIMIT = 2000
_LIST_LIMIT = 64


@dataclass(frozen=True)
class CheckItem:
    id: str
    label: str
    status: str
    detail: str = ""

    def as_json(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "status": self.status, "detail": self.detail}


@dataclass(frozen=True)
class Action:
    """What the owner does to make a check pass; nothing here is ever run by tau."""

    kind: str
    text: str
    command: str | None = None
    """To show (with a copy button in the app), never to run."""
    sudo: bool = False
    """``command`` asks for the owner's password (sudo)."""
    url: str | None = None
    changes: tuple[str, ...] = ()
    """What ``command`` changes on the machine, one line each."""
    script: str | None = None
    """The script behind ``command``, to read before running it."""

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "text": self.text,
            "command": self.command,
            "sudo": self.sudo,
            "url": self.url,
            "changes": list(self.changes),
            "script": self.script,
        }


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    summary: str
    checks: tuple[CheckItem, ...] = ()
    action: Action | None = None
    values: Mapping[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "check": CHECK_PROTOCOL,
            "ok": self.ok,
            "summary": self.summary,
            "checks": [item.as_json() for item in self.checks],
            "action": self.action.as_json() if self.action else None,
            "values": dict(self.values),
        }

    def dumps(self) -> str:
        return json.dumps(self.as_json(), ensure_ascii=False)


# -- parsing (the object comes from a subprocess: typed and bounded before it is shown) ----------


def _text(value: Any, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ValueError("expected a string")
    return value[:_TEXT_LIMIT]


def _parse_item(raw: Any) -> CheckItem:
    if not isinstance(raw, dict):
        raise ValueError("a check is an object")
    status = raw.get("status")
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    return CheckItem(
        id=_text(raw.get("id")) or "",
        label=_text(raw.get("label")) or "",
        status=status,
        detail=_text(raw.get("detail", "")) or "",
    )


def _parse_action(raw: Any) -> Action | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("`action` is an object or null")
    kind = raw.get("kind")
    if kind not in ACTION_KINDS:
        raise ValueError(f"unknown action kind {kind!r}")
    url = _text(raw.get("url"), optional=True)
    if url is not None and not url.startswith("https://"):
        raise ValueError("an action's url is https")
    changes = raw.get("changes", [])
    if not isinstance(changes, list):
        raise ValueError("`changes` is a list")
    sudo = raw.get("sudo", False)
    if not isinstance(sudo, bool):
        raise ValueError("`sudo` is true or false")
    return Action(
        kind=kind,
        text=_text(raw.get("text")) or "",
        command=_text(raw.get("command"), optional=True),
        sudo=sudo,
        url=url,
        changes=tuple(_text(line) or "" for line in changes[:_LIST_LIMIT]),
        script=_text(raw.get("script"), optional=True),
    )


def parse_check(text: str) -> CheckResult:
    """The check object a command printed; ``ValueError`` when it is not one."""
    data = json.loads(text)
    if not isinstance(data, dict) or data.get("check") != CHECK_PROTOCOL:
        raise ValueError("not a check object")
    ok = data.get("ok")
    if not isinstance(ok, bool):
        raise ValueError("`ok` is true or false")
    checks = data.get("checks", [])
    if not isinstance(checks, list):
        raise ValueError("`checks` is a list")
    values = data.get("values", {})
    if not isinstance(values, dict):
        raise ValueError("`values` is an object")
    return CheckResult(
        ok=ok,
        summary=_text(data.get("summary", "")) or "",
        checks=tuple(_parse_item(item) for item in checks[:_LIST_LIMIT]),
        action=_parse_action(data.get("action")),
        values=values,
    )


# -- rendering for a terminal ---------------------------------------------------------------------


def render_checks(items: Sequence[CheckItem]) -> list[str]:
    """``  ✓ label: detail`` per check."""
    lines = []
    for item in items:
        text = f"{item.label}: {item.detail}" if item.detail else item.label
        lines.append(f"  {_MARKS[item.status]} {text}")
    return lines


def render_action(action: Action, language: str, *, brief: bool = False) -> list[str]:
    """The action as the owner reads it: the text, the command to run themselves (indented so
    it copies cleanly), what it changes, the script to read first and the page. ``brief``
    (the same action shown again) keeps the text and the command."""
    lines = ["", f"  → {action.text}"]
    if action.command:
        lines += ["", f"      {action.command}"]
    if brief:
        return lines
    more: list[str] = []
    if action.changes:
        more.append("    " + t("setup.check.changes", language))
        more += [f"      • {change}" for change in action.changes]
    if action.script:
        more.append("    " + t("setup.check.script", language, path=action.script))
    if action.url:
        more.append(f"    {action.url}")
    return [*lines, "", *more] if more else lines
