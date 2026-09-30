"""A sub-tau's agent: its prompt, its tools, its approver and its sessions.

Every sub-tau agent comes from ``tau_core.build_agent`` with an explicit tool list (the
allowlist, resolved in the tool catalog), an explicit persona, the model role of the
definition, the channel ``sub:<name>`` and the approver of whoever runs it. The tier gate is
tau-core's own: a tier-2 tool asks that approver on every call. The owner guard (ADR 0008) is
resolved from the configuration like any other agent's, unless the caller passes its own: a
delegation (``ask_sub``) runs under the guard of the turn that delegated.

**The prompt.** ``PersonaLoader`` reads a persona file and ``user.md`` and adds the ``## Now``
block; it strips HTML comments but knows nothing of front matter. So the persona the model
reads is rendered into a derived file, ``TAU_DATA_DIR/subs/<name>/persona.md`` (0600): the
fixed English :data:`HEADER`, a blank line, the persona text. It is rewritten only when the
definition changed, and the loader is given its absolute path as ``persona_file`` (pathlib
drops ``persona_dir`` for an absolute path), so ``user.md`` still comes from
``persona/user.md`` and the loader's hot reload, last-good fallback and cache point work
unchanged. The front matter never reaches the model.

**Sessions.** The last session of each sub-tau is remembered in
``TAU_DATA_DIR/subs/<name>/session``; :class:`SubConversation` resumes it unless asked for a
new one. A remembered id that belongs to another channel is ignored, so a sub-tau never
continues the main tau's history.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from strands.types.tools import AgentTool
from tau_core import (
    Approver,
    Config,
    EventBus,
    PersonaLoader,
    SessionStore,
    TauAgent,
    build_agent,
    open_session_store,
)
from tau_core.guard import DISCOVER, Guard

from tau_sub._files import private_dir, write_private
from tau_sub.definition import (
    FORBIDDEN_TOOLS,
    SUBS_DIR,
    ForbiddenToolError,
    SubRegistry,
    SubTau,
    UnknownToolError,
    tool_catalog,
    validate_name,
)

if TYPE_CHECKING:
    from strands.models.model import Model

__all__ = [
    "HEADER",
    "ModelFactory",
    "SubConversation",
    "allowed_tools",
    "build_sub_agent",
    "last_session",
    "persona_loader",
    "prompt_path",
    "prompt_persona",
    "remember_session",
    "state_dir",
    "write_prompt",
]

logger = logging.getLogger(__name__)

HEADER = (
    "You are /{name}, a specialist of your owner's tau: {about}. "
    "Stay within this task; say so when a request is outside it."
)
"""Fixed English: the first line of every sub-tau's system prompt."""

PROMPT_FILE = "persona.md"
SESSION_FILE = "session"
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")

ModelFactory = Callable[[str], "Model"]
"""``role → model``: replaces ``resolve_model`` (tests, embedding code)."""


def state_dir(config: Config, name: str) -> Path:
    """``TAU_DATA_DIR/subs/<name>``: the derived prompt and the remembered session."""
    return config.data_dir / SUBS_DIR / validate_name(name)


def prompt_path(config: Config, name: str) -> Path:
    return state_dir(config, name) / PROMPT_FILE


def _private_state_dir(config: Config, name: str) -> Path:
    private_dir(config.data_dir / SUBS_DIR)
    return private_dir(state_dir(config, name))


def prompt_persona(sub: SubTau) -> str:
    """The persona the model reads: :data:`HEADER`, then the definition's persona text."""
    about = sub.about.strip().rstrip(" .")
    return HEADER.format(name=sub.name, about=about) + "\n\n" + sub.persona.strip() + "\n"


def write_prompt(config: Config, sub: SubTau) -> Path:
    """Render :func:`prompt_persona` into the derived file, only when it changed (an
    unchanged file keeps its stamp, so the loader does not re-read it)."""
    path = prompt_path(config, sub.name)
    text = prompt_persona(sub)
    try:
        if path.read_text(encoding="utf-8") == text:
            return path
    except (OSError, UnicodeDecodeError):
        pass
    _private_state_dir(config, sub.name)
    write_private(path, text, overwrite=True)
    return path


def persona_loader(config: Config, sub: SubTau) -> PersonaLoader:
    """A ``PersonaLoader`` for ``sub``: the derived persona file plus ``persona/user.md``."""
    path = write_prompt(config, sub)
    # An absolute persona_file replaces persona_dir in the loader's path join (pathlib), while
    # user_file stays relative to persona_dir: the owner's persona/user.md.
    return PersonaLoader(config.persona_dir, persona_file=str(path))


def last_session(config: Config, name: str) -> str | None:
    """The session id remembered for ``name``, or ``None``."""
    try:
        text = (state_dir(config, name) / SESSION_FILE).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text if _SESSION_ID.fullmatch(text) else None


def remember_session(config: Config, name: str, session_id: str) -> None:
    directory = _private_state_dir(config, name)
    write_private(directory / SESSION_FILE, f"{session_id}\n", overwrite=True)


def allowed_tools(sub: SubTau, catalog: Mapping[str, AgentTool]) -> list[AgentTool]:
    """The tools of ``sub``'s allowlist, in its order. Never ``ask_sub`` or ``create_sub``."""
    tools: list[AgentTool] = []
    for name in sub.tools:
        if name in FORBIDDEN_TOOLS:
            raise ForbiddenToolError(sub.name, name)
        tool = catalog.get(name)
        if tool is None:
            raise UnknownToolError(sub.name, name)
        tools.append(tool)
    return tools


def build_sub_agent(
    config: Config,
    sub: SubTau,
    *,
    approver: Approver,
    session_id: str | None = None,
    session_store: SessionStore | None = None,
    model: Model | None = None,
    tools: Iterable[AgentTool] | None = None,
    events: EventBus | None = None,
    guard: Guard | None | object = DISCOVER,
) -> TauAgent:
    """The agent of ``sub``: its role, its allowlist only, its prompt, channel ``sub:<name>``.

    ``approver`` decides every tier-2 call; pass the approver of the channel the sub-tau runs
    on (never one that approves on its own). ``tools`` replaces the discovered catalog the
    allowlist is resolved in. ``guard`` is ``build_agent``'s: the default resolves the owner
    guard from the configuration; a delegation passes the guard of the turn that delegated.
    """
    return build_agent(
        config=config,
        role=sub.role,
        model=model,
        tools=allowed_tools(sub, tool_catalog(config, tools)),
        approver=approver,
        session_id=session_id,
        session_store=session_store,
        events=events,
        persona=persona_loader(config, sub),
        channel=sub.channel,
        guard=guard,
    )


class SubConversation:
    """A sub-tau conversation on its remembered session (``tau sub chat`` and ``tau sub ask``).

    ``new=True`` starts a fresh session. The session id is remembered as soon as the agent
    is built. :meth:`refresh` re-reads the definition before a turn: a new persona or about
    line only rewrites the derived prompt (the loader picks it up on the next model call); a
    new role or allowlist rebuilds the agent on the same session.
    """

    def __init__(
        self,
        config: Config,
        name: str,
        *,
        approver: Approver,
        new: bool = False,
        session_store: SessionStore | None = None,
        model_factory: ModelFactory | None = None,
        tools: Iterable[AgentTool] | None = None,
    ):
        self.config = config
        self.approver = approver
        self.model_factory = model_factory
        self._tools = list(tools) if tools is not None else None
        self.registry = SubRegistry(config, tools=self._tools)
        self.sub = self.registry.get(name)
        self.store = session_store if session_store is not None else open_session_store(config)
        self.agent = self._build(None if new else self._remembered())

    def _remembered(self) -> str | None:
        session_id = last_session(self.config, self.sub.name)
        if session_id is None:
            return None
        try:
            channel = self.store.read_meta(session_id).get("channel")
        except Exception:
            logger.info(
                "sub: remembered session %s of /%s is not readable", session_id, self.sub.name
            )
            return None
        if channel and channel != self.sub.channel:
            logger.warning(
                "sub: remembered session %s is on channel %s, not %s; starting a new one",
                session_id,
                channel,
                self.sub.channel,
            )
            return None
        return session_id

    def _build(self, session_id: str | None) -> TauAgent:
        model = self.model_factory(self.sub.role) if self.model_factory is not None else None
        agent = build_sub_agent(
            self.config,
            self.sub,
            approver=self.approver,
            session_id=session_id,
            session_store=self.store,
            model=model,
            tools=self._tools,
        )
        remember_session(self.config, self.sub.name, agent.session_id)
        return agent

    @property
    def session_id(self) -> str:
        return self.agent.session_id

    def new_session(self) -> str:
        """Continue on a fresh session; the old one stays in the store."""
        agent = self._build(None)
        self.agent.close()
        self.agent = agent
        return agent.session_id

    def refresh(self) -> str | None:
        """Re-read the definition: ``None`` when nothing the agent uses changed, ``"prompt"``
        when only the prompt was rewritten, ``"rebuilt"`` when the agent was rebuilt. Raises
        ``SubTauError`` (the current agent stays) when the definition is gone or invalid."""
        sub = self.registry.get(self.sub.name)
        if sub == self.sub:
            return None
        rebuild = (sub.role, sub.tools) != (self.sub.role, self.sub.tools)
        previous, self.sub = self.sub, sub
        if not rebuild:
            if prompt_persona(sub) == prompt_persona(previous):
                return None  # e.g. only `public` changed
            write_prompt(self.config, sub)
            return "prompt"
        try:
            agent = self._build(self.agent.session_id)
        except Exception:
            self.sub = previous
            raise
        agent.carry_over(self.agent)
        self.agent.close()
        self.agent = agent
        return "rebuilt"

    def close(self) -> None:
        self.agent.close()
