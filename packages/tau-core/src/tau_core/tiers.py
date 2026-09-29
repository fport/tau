"""Tool permission tiers.

Every tool declares a tier: 0 read (runs freely), 1 digital write (runs and is logged),
2 physical action or self-written code (needs an approval). A tool without a tier cannot be
registered; :class:`ToolCatalog` is the only way tools reach ``build_agent``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from enum import IntEnum
from typing import Any

from strands import tool as strands_tool
from strands.types.tools import AgentTool

logger = logging.getLogger(__name__)


class Tier(IntEnum):
    READ = 0
    DIGITAL_WRITE = 1
    PHYSICAL = 2


class UntieredToolError(Exception):
    """A tool without a declared tier; the message names the tool."""

    def __init__(self, tool: str):
        self.tool = tool
        super().__init__(
            f"Tool '{tool}' declares no tier and cannot be registered. Use @tau_tool(tier=...)."
        )


def tau_tool(
    tier: Tier | int, *, effect: str | None = None, **tool_kwargs: Any
) -> Callable[[Callable[..., Any]], AgentTool]:
    """Strands ``@tool`` plus a tier and an optional effect text (shown in approvals).

    ``tool_kwargs`` go to ``strands.tool`` (``name``, ``description``, ``inputSchema``, ...).
    An invalid tier (not 0, 1 or 2, or a bool) raises ``ValueError`` at decoration time.
    """
    if isinstance(tier, bool):
        raise ValueError(f"tier must be a Tier (0, 1 or 2), not {tier!r}")
    declared = Tier(tier)

    def decorate(func: Callable[..., Any]) -> AgentTool:
        agent_tool = strands_tool(**tool_kwargs)(func) if tool_kwargs else strands_tool(func)
        # The spec is the durable home: a @tau_tool method accessed on an instance is a new
        # DecoratedFunctionTool that shares the spec but not instance attributes.
        spec = dict(agent_tool.tool_spec)
        annotations = dict(spec.get("annotations") or {})
        annotations[ANNOTATION_KEY] = {"tier": int(declared), "effect": effect}
        spec["annotations"] = annotations
        agent_tool.tool_spec = spec  # the validated setter
        agent_tool.tau_tier = declared  # type: ignore[attr-defined]
        agent_tool.tau_effect = effect  # type: ignore[attr-defined]
        return agent_tool

    return decorate


ANNOTATION_KEY = "tau"
"""``ToolSpec["annotations"]["tau"] = {"tier": int, "effect": str | None}``, set by ``tau_tool``.

The annotation is plain data in the spec and is authoritative only for tools registered
in-process (``tau.tools`` entry points, ``@tau_tool``), where tau code wrote it. A spec that
arrives from outside the process (an MCP ``ToolProvider``, issue 033/069) must not be trusted
to declare its own tier: the hub strips ``annotations["tau"]`` from such specs and assigns
tiers from its own manifest/config before a tool reaches the :class:`ToolCatalog`.
"""


def _annotation(tool: AgentTool) -> dict[str, Any] | None:
    spec = getattr(tool, "tool_spec", None)
    if not isinstance(spec, dict):
        return None
    annotations = spec.get("annotations")
    if not isinstance(annotations, dict):
        return None
    tau = annotations.get(ANNOTATION_KEY)
    return tau if isinstance(tau, dict) else None


def tier_of(tool: AgentTool) -> Tier:
    """The tool's declared tier; :class:`UntieredToolError` when it has none or an invalid one.

    The ``tau`` annotation of the tool spec is read first, the ``tau_tier`` attribute second.
    """
    tau = _annotation(tool)
    value = tau.get("tier") if tau is not None else None
    if value is None:
        value = getattr(tool, "tau_tier", None)
    name = getattr(tool, "tool_name", repr(tool))
    if value is None or isinstance(value, bool):
        raise UntieredToolError(name)
    try:
        return Tier(value)
    except ValueError as exc:
        raise UntieredToolError(name) from exc


def effect_of(tool: AgentTool) -> str:
    """What running the tool does, for approval prompts: the declared effect or the description."""
    tau = _annotation(tool)
    effect = tau.get("effect") if tau is not None else None
    if not effect:
        effect = getattr(tool, "tau_effect", None)
    if effect:
        return str(effect)
    spec = getattr(tool, "tool_spec", None) or {}
    return str(spec.get("description") or getattr(tool, "tool_name", ""))


class ToolCatalog:
    """Registered tools by name. Looked up live when a call happens, never cached elsewhere."""

    def __init__(self, tools: Iterable[AgentTool] = ()):
        self._tools: dict[str, AgentTool] = {}
        self.extend(tools)

    def add(self, tool: AgentTool) -> None:
        tier_of(tool)  # raises UntieredToolError
        name = tool.tool_name
        if name in self._tools and self._tools[name] is not tool:
            logger.warning("tool %s registered twice; the later one wins", name)
        self._tools[name] = tool

    def extend(self, tools: Iterable[AgentTool]) -> None:
        """Add all tools, or none of them when one is untiered."""
        tools = list(tools)
        for tool in tools:
            tier_of(tool)  # raises UntieredToolError before anything is registered
        for tool in tools:
            self.add(tool)

    def remove(self, name: str) -> None:
        self._tools.pop(name, None)

    def names(self) -> list[str]:
        return list(self._tools)

    def tools(self) -> list[AgentTool]:
        return list(self._tools.values())

    def get(self, name: str) -> AgentTool | None:
        return self._tools.get(name)

    def tier(self, name: str) -> Tier | None:
        tool = self._tools.get(name)
        return tier_of(tool) if tool is not None else None

    def __contains__(self, name: object) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)
