"""Repository rules that must never regress (CLAUDE.md non-negotiables)."""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGES = ROOT / "packages"


def _source_files() -> list[Path]:
    return [p for p in PACKAGES.glob("*/src/**/*") if p.is_file() and "__pycache__" not in p.parts]


def _code_files() -> list[Path]:
    """Source files minus package data: ``templates/`` holds ``tau init``'s tau.toml and the
    model-id table, which are data like the repository's own ``tau.toml``."""
    return [p for p in _source_files() if "templates" not in p.parts]


def test_repo_root_found() -> None:
    assert (ROOT / "pyproject.toml").is_file()
    assert (PACKAGES / "tau-core").is_dir()


def test_no_model_ids_in_code() -> None:
    offenders = []
    for path in _code_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "claude-" in text or "anthropic.claude" in text:
            offenders.append(path.relative_to(ROOT))
    assert offenders == [], f"model ids belong in tau.toml, not code: {offenders}"


def test_no_litellm_dependency() -> None:
    files = list(ROOT.glob("pyproject.toml")) + list(PACKAGES.glob("**/pyproject.toml"))
    files += [ROOT / "uv.lock"] if (ROOT / "uv.lock").is_file() else []
    offenders = [
        p.relative_to(ROOT) for p in files if "litellm" in p.read_text(encoding="utf-8").lower()
    ]
    assert offenders == [], f"litellm must never be a Python dependency: {offenders}"


def test_no_auto_approve() -> None:
    offenders = [
        p.relative_to(ROOT)
        for p in _source_files()
        if "AutoApprove" in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert offenders == [], f"tier-2 approval is never bypassed: {offenders}"


def _tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True, timeout=30
        ).stdout
    except (OSError, subprocess.SubprocessError):
        pytest.skip("not a git checkout")
    return [ROOT / name for name in out.decode().split("\0") if name]


def test_no_personal_paths_in_tracked_files() -> None:
    home_path = re.compile("/" + "Users/[A-Za-z0-9_.-]+|/" + "home/[a-z][a-z0-9_-]+/")
    offenders = []
    for path in _tracked_files():
        if path.name == "uv.lock" or not path.is_file() or path.suffix in {".png", ".jpg"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if home_path.search(text):
            offenders.append(path.relative_to(ROOT))
    assert offenders == [], f"absolute personal paths in tracked files: {offenders}"


# -- the owner guard (issue 110, ADR 0008) -----------------------------------------------------
#
# These rules catch an opt-out written by accident, not an adversary with a shell (ADR 0008
# puts that out of scope). They read the AST: a literal constant as ``guard=``, a name bound to
# one, a ``**`` splat or a value-use that hides the arguments, an assignment to ``.guard``,
# ``setattr(..., "guard", ...)``, a ``TauAgent(...)`` built by hand, and the aliases of all of it.

GUARD_NONE_ALLOWED = {
    Path("packages/tau-core/src/tau_core/channels/telegram.py"),
    Path("packages/tau-net/src/tau_net/turns.py"),
}
"""The identified in-hub channels, the only code that may opt out of the guard."""

GUARD_OWNERS = {
    Path("packages/tau-core/src/tau_core/agent.py"),
    Path("packages/tau-core/src/tau_core/guard.py"),
}
"""Where ``TauAgent`` is built and the guard is resolved; exempt from the attribute rules."""

GUARDED = frozenset({"build_agent", "TierGate", "TauAgent"})
"""Constructors whose ``guard`` must stay visible at the call."""
GUARD_CARRIERS = GUARDED | {"replace"}
"""Calls whose ``guard=`` is checked for names and expressions that may be a constant."""

_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _python_sources() -> list[tuple[Path, ast.Module]]:
    return [
        (path.relative_to(ROOT), ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for path in _source_files()
        if path.suffix == ".py"
    ]


def _calls(tree: ast.AST) -> list[ast.Call]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _aliases(tree: ast.AST) -> dict[str, str]:
    """Local name → guarded name, for ``from ... import TierGate as TG`` and the plain names."""
    names = {name: name for name in GUARD_CARRIERS}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in GUARD_CARRIERS and alias.asname:
                    names[alias.asname] = alias.name
    return names


def _target(node: ast.AST, aliases: dict[str, str]) -> str | None:
    """The guarded name ``node`` refers to (``TierGate``, ``approval.TierGate``, an alias)."""
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    if isinstance(node, ast.Attribute) and node.attr in GUARD_CARRIERS:
        return node.attr
    return None


def _maybe_constant(node: ast.AST | None) -> bool:
    """Can ``node`` evaluate to a literal constant (``None``, ``False``, ...)?"""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.IfExp):
        return _maybe_constant(node.body) or _maybe_constant(node.orelse)
    if isinstance(node, ast.BoolOp):
        return any(_maybe_constant(value) for value in node.values)
    if isinstance(node, ast.NamedExpr):
        return _maybe_constant(node.value)
    return False


def _scope_nodes(scope: ast.AST) -> list[ast.AST]:
    """The nodes of ``scope`` without descending into nested functions and classes."""
    found: list[ast.AST] = []
    todo = list(ast.iter_child_nodes(scope))
    while todo:
        node = todo.pop()
        found.append(node)
        if not isinstance(node, _SCOPES):
            todo.extend(ast.iter_child_nodes(node))
    return found


def _constant_names(scope: ast.AST, inherited: frozenset[str]) -> frozenset[str]:
    """Names bound in ``scope`` (assignment or parameter default) to what may be a constant."""
    names = set(inherited)
    if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
        args = scope.args
        positional = args.posonlyargs + args.args
        defaulted = positional[len(positional) - len(args.defaults) :]
        for arg, default in zip(defaulted, args.defaults, strict=True):
            if _maybe_constant(default):
                names.add(arg.arg)
        for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
            if default is not None and _maybe_constant(default):
                names.add(arg.arg)
    for node in _scope_nodes(scope):
        if isinstance(node, ast.Assign) and _maybe_constant(node.value):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif (
            isinstance(node, ast.AnnAssign | ast.NamedExpr)
            and isinstance(node.target, ast.Name)
            and _maybe_constant(node.value)
        ):
            names.add(node.target.id)
    return frozenset(names)


def _guard_opt_outs(tree: ast.Module) -> list[tuple[int, str]]:
    """``(line, what)`` for every way ``tree`` passes or sets a constant guard."""
    aliases = _aliases(tree)
    found: list[tuple[int, str]] = []

    def visit(scope: ast.AST, inherited: frozenset[str]) -> None:
        constants = _constant_names(scope, inherited)
        for node in _scope_nodes(scope):
            if isinstance(node, ast.Call):
                carrier = _target(node.func, aliases) in GUARD_CARRIERS
                for keyword in node.keywords:
                    if keyword.arg != "guard":
                        continue
                    value = keyword.value
                    if isinstance(value, ast.Constant):
                        found.append((node.lineno, f"guard={value.value!r}"))
                    elif carrier and (
                        _maybe_constant(value)
                        or (isinstance(value, ast.Name) and value.id in constants)
                    ):
                        found.append((node.lineno, f"guard={ast.unparse(value)}"))
            if isinstance(node, _SCOPES):
                visit(node, constants)

    visit(tree, frozenset())
    return found


def _guard_bypasses(tree: ast.Module, *, owner: bool) -> list[tuple[int, str]]:
    """``(line, what)`` for code that hides or replaces the guard of an agent or a gate."""
    aliases = _aliases(tree)
    found: list[tuple[int, str]] = []
    exempt_values: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _called_name(node) in ("isinstance", "issubclass"):
            exempt_values.update(id(arg) for arg in node.args)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = _target(node.func, aliases)
            if target in GUARDED and any(k.arg is None for k in node.keywords):
                found.append((node.lineno, f"**splat into {target}"))
            if target == "TauAgent" and not owner:
                found.append((node.lineno, "TauAgent(...) built outside build_agent"))
            values = [*node.args, *(k.value for k in node.keywords)]
            for value in values:
                used = _target(value, aliases)
                if used in GUARDED and id(value) not in exempt_values:
                    found.append((node.lineno, f"{used} passed as a value"))
            name = _called_name(node)
            if name in ("setattr", "__setattr__", "getattr") and len(node.args) >= 2:
                attribute = node.args[1]
                if isinstance(attribute, ast.Constant) and attribute.value in (
                    {"guard"} if name != "getattr" else GUARDED
                ):
                    found.append((node.lineno, f"{name}(..., {attribute.value!r})"))
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            value = node.value
            if _target(value, aliases) in GUARDED if value is not None else False:
                found.append((node.lineno, "a guarded constructor assigned to a name"))
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if owner or not (isinstance(target, ast.Attribute) and target.attr == "guard"):
                    continue
                on_self = isinstance(target.value, ast.Name) and target.value.id == "self"
                if not on_self or _maybe_constant(value):
                    found.append((node.lineno, f"{ast.unparse(target)} = ..."))
    return found


def test_only_identified_channels_opt_out_of_the_guard() -> None:
    found: dict[Path, list[tuple[int, str]]] = {}
    for path, tree in _python_sources():
        if opt_outs := _guard_opt_outs(tree):
            found[path] = opt_outs
    outside = {path: hits for path, hits in found.items() if path not in GUARD_NONE_ALLOWED}
    assert outside == {}, f"a constant guard outside the allowlist: {outside}"
    for path in GUARD_NONE_ALLOWED:
        assert [what for _, what in found.get(path, [])] == ["guard=None"], (
            f"{path} must opt out exactly once, with a literal guard=None"
        )


def test_nothing_hides_or_replaces_the_guard() -> None:
    offenders = [
        f"{path}:{line} {what}"
        for path, tree in _python_sources()
        for line, what in _guard_bypasses(tree, owner=path in GUARD_OWNERS)
    ]
    assert offenders == [], f"code that hides or replaces the guard: {offenders}"


def _tier_gates_without_guard(tree: ast.Module) -> list[int]:
    aliases = _aliases(tree)
    return [
        call.lineno
        for call in _calls(tree)
        if _target(call.func, aliases) == "TierGate"
        and not any(keyword.arg == "guard" for keyword in call.keywords)
    ]


def test_every_tier_gate_decides_about_the_guard() -> None:
    offenders = [
        f"{path}:{line}"
        for path, tree in _python_sources()
        for line in _tier_gates_without_guard(tree)
    ]
    assert offenders == [], f"TierGate( without guard=: {offenders}"


GUARD_RULE_CASES = {
    "literal None": "build_agent(config, guard=None)",
    "literal False": "build_agent(config, guard=False)",
    "literal in any call": "make_agent(config, guard=None)",
    "variable bound to None": "g = None\nbuild_agent(config, guard=g)",
    "parameter defaulting to None": "def f(g=None):\n    return build_agent(config, guard=g)",
    "closure over None": "g = None\ndef f():\n    return build_agent(config, guard=g)",
    "conditional None": "build_agent(config, guard=None if x else DISCOVER)",
    "or None": "TierGate(c, a, e, session_id=None, channel='x', guard=x or None)",
    "replace": "agent = dataclasses.replace(agent, guard=None if x else agent.guard)",
    "aliased build_agent": "from tau_core import build_agent as ba\ng = None\nba(guard=g)",
    "dict splat": "build_agent(config, **{'guard': None})",
    "kwargs splat": "build_agent(config, **options)",
    "attribute on an agent": "agent = build_agent(config)\nagent.guard = None",
    "attribute on a gate": "agent.gate.guard = other",
    "self attribute set to None": "class A:\n    def f(self):\n        self.guard = None",
    "setattr": "setattr(agent, 'guard', None)",
    "object.__setattr__": "object.__setattr__(agent, 'guard', None)",
    "TauAgent by hand": "TauAgent(agent=a, config=c, session_id=s, store=st, gate=g)",
    "aliased TierGate": "from tau_core.approval import TierGate as TG\n"
    "TG(c, a, e, session_id=None, channel='x')",
    "TierGate splat": "TierGate(c, a, e, **options)",
    "partial": "functools.partial(TierGate, cat, appr, ev)(session_id=None, channel='x')",
    "assigned to a name": "make = build_agent",
    "getattr": "factory = getattr(approval, 'TierGate')",
}


@pytest.mark.parametrize("source", GUARD_RULE_CASES.values(), ids=GUARD_RULE_CASES.keys())
def test_the_guard_rules_catch_each_way_to_opt_out(source: str) -> None:
    tree = ast.parse(source)
    assert (
        _guard_opt_outs(tree)
        or _guard_bypasses(tree, owner=False)
        or _tier_gates_without_guard(tree)
    )


def test_the_guard_rules_let_ordinary_code_through() -> None:
    source = """
from tau_core import TierGate, build_agent
from tau_core.guard import DISCOVER, resolve_guard

class Screen:
    def __init__(self, config, guard=None):
        self.guard = resolve_guard(config)
        self.status: GuardStatus | None = None

    def build(self, guard):
        gate: TierGate = TierGate(c, a, e, session_id=None, channel="tui", guard=self.guard)
        agent = build_agent(config, guard=self.guard if self.guard is not None else DISCOVER)
        return isinstance(gate, TierGate), agent

def report(agent):
    guard = agent.guard.status() if agent.guard is not None else None
    return status_lines(agent, guard=guard)
"""
    tree = ast.parse(source)
    assert _guard_opt_outs(tree) == []
    assert _guard_bypasses(tree, owner=False) == []
    assert _tier_gates_without_guard(tree) == []


def test_no_channel_flag_or_variable_selects_a_channel() -> None:
    offenders = [
        p.relative_to(ROOT)
        for p in _code_files()
        if p.suffix == ".py"
        and re.search(r"--channel\b|TAU_CHANNEL", p.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"a channel is chosen by code, never by a flag: {offenders}"
