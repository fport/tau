"""``TauApp``: header, chat pane, event pane and an input line.

Under 100 columns the panes stack (chat above events); wider terminals put them side by side.
Everything is one row high except the panes, so 80x24 over mosh on a phone stays usable.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from rich.text import Text
from tau_core import (
    Config,
    SessionStore,
    TauAgent,
    build_agent,
)
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.theme import Theme
from textual.widgets import Input, Static

from tau_tui.approval import APPROVE_DELAY, TuiApprover
from tau_tui.panes import SIGNAL, ChatPane, EventPane

logger = logging.getLogger(__name__)

WIDE_BREAKPOINT = 100
PLACEHOLDER = "Mesajınızı yazın · /araçlar · /çık"
COMMAND_HINT = "/araçlar, /çık"
BUSY_TEXT = "tau hâlâ yanıtlıyor; bitince tekrar gönderin."
QUIT_HINT = "Çıkmak için Ctrl+Q'ya basın veya /çık yazın."
NO_SESSION_TEXT = "Devam edilecek oturum yok; yeni bir oturum açıldı."
TIER_LABELS = {0: "okuma", 1: "dijital yazma, günlüğe yazılır", 2: "fiziksel, onay gerekir"}

# Brand palette (docs/brand/render.py): VOID background, SIGNAL/EMBER/FLARE accents, CORE text.
TAU_THEME = Theme(
    name="tau",
    primary=SIGNAL,
    secondary="#FF7A3D",
    accent="#FFB25C",
    warning="#FFB25C",
    error="#FF4D4D",
    success="#3DBE7A",
    foreground="#FFF4E0",
    background="#05071A",
    surface="#05071A",
    panel="#12061A",
    dark=True,
)


class SessionNotFound(Exception):
    """``--resume ID`` named a session the store does not have."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Oturum bulunamadı: {session_id}.")
        self.session_id = session_id


def resume_text(session_id: str, title: str | None = None) -> str:
    return f"Oturuma devam ediliyor: {session_id}" + (f" ({title})" if title else "")


def resolve_resume(store: SessionStore, resume: str | None) -> tuple[str | None, str | None]:
    """``--resume [ID]`` → ``(session_id, notice)``; ``""`` means the most recent session."""
    if resume is None:
        return None, None
    if resume == "":
        recent = store.list_sessions(limit=1)
        if not recent:
            return None, NO_SESSION_TEXT
        return recent[0].session_id, resume_text(recent[0].session_id, recent[0].title)
    if store.read_session(resume) is None:
        raise SessionNotFound(resume)
    return resume, resume_text(resume, store.read_meta(resume).get("title"))


def _turkish_lower(text: str) -> str:
    return text.replace("I", "ı").replace("İ", "i").lower()


def header_text(profile: str, session_id: str) -> Text:
    """Profile and session id only: never paths."""
    return Text.assemble(
        ("tau", f"bold {SIGNAL}"),
        "  profil: ",
        (profile, "bold"),
        "  oturum: ",
        (session_id, "bold"),
    )


class TauApp(App[None]):
    """The tau TUI. The agent must be built with the same :class:`TuiApprover`."""

    TITLE = "tau"
    ENABLE_COMMAND_PALETTE = False
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (WIDE_BREAKPOINT, "-wide")]

    CSS = """
    Screen {
        layout: vertical;
    }
    #header {
        height: 1;
        padding: 0 1;
        background: $panel;
    }
    #panes {
        height: 1fr;
        layout: vertical;
    }
    #chat {
        height: 1fr;
        border-title-color: $text-muted;
    }
    #events {
        height: 8;
        max-height: 40%;
        border-top: solid $primary 50%;
        border-title-color: $text-muted;
    }
    #prompt {
        height: 1;
        background: $boost;
    }
    Screen.-wide #panes {
        layout: horizontal;
    }
    Screen.-wide #chat {
        border-top: solid $primary 50%;
    }
    Screen.-wide #events {
        width: 42%;
        height: 1fr;
        max-height: 100%;
        border-left: solid $primary 50%;
    }
    """

    def __init__(
        self,
        agent: TauAgent,
        *,
        approver: TuiApprover | None = None,
        notice: str | None = None,
    ) -> None:
        super().__init__()
        self.agent = agent
        self.approver = approver
        if approver is not None:
            approver.attach(self)
        self.notice = notice
        self.busy = False

    @property
    def chat(self) -> ChatPane:
        return self.query_one("#chat", ChatPane)

    @property
    def event_pane(self) -> EventPane:
        return self.query_one("#events", EventPane)

    @property
    def prompt_input(self) -> Input:
        return self.query_one("#prompt", Input)

    def compose(self) -> ComposeResult:
        yield Static(header_text(self.agent.config.profile, self.agent.session_id), id="header")
        with Container(id="panes"):
            yield ChatPane(id="chat")
            yield EventPane(self.agent.events, id="events")
        yield Input(placeholder=PLACEHOLDER, id="prompt", compact=True)

    def on_mount(self) -> None:
        self.register_theme(TAU_THEME)
        self.theme = TAU_THEME.name
        self.chat.border_title = "Sohbet"
        self.chat.show_history(self.agent.messages)
        if self.notice:
            self.chat.add_notice(self.notice)
        self.prompt_input.focus()

    def action_help_quit(self) -> None:
        self.notify(QUIT_HINT)

    # -- input -------------------------------------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        if text.startswith("/"):
            event.input.clear()
            self.run_command(text)
            return
        if self.busy:
            self.notify(BUSY_TEXT, severity="warning")
            return  # keep the typed text
        event.input.clear()
        self.chat.add_user(text)
        self.busy = True
        self.run_turn(text)

    def run_command(self, line: str) -> None:
        name, _, _arg = line[1:].strip().partition(" ")
        key = _turkish_lower(name)
        if key in ("çık", "cik"):
            self.exit()
        elif key in ("araçlar", "araclar"):
            self.chat.add_info(self._tool_lines())
        else:
            self.chat.add_notice(f"Bilinmeyen komut: /{name}. Komutlar: {COMMAND_HINT}")

    def _tool_lines(self) -> list[str]:
        catalog = self.agent.catalog
        tools = catalog.tools()
        if not tools:
            return ["Kayıtlı araç yok."]
        lines = [f"Araçlar ({len(tools)}):"]
        for tool in tools:
            tier = catalog.tier(tool.tool_name)
            label = TIER_LABELS.get(int(tier), "?") if tier is not None else "?"
            description = (tool.tool_spec.get("description") or "").strip().splitlines()
            first = f" — {description[0]}" if description else ""
            number = "?" if tier is None else int(tier)
            lines.append(f"{tool.tool_name}  tier {number} · {label}{first}")
        return lines

    # -- turns -------------------------------------------------------------------------------

    @work(group="turn", exit_on_error=False)
    async def run_turn(self, prompt: str) -> None:
        """One user turn; turn events go to the chat pane only."""
        chat = self.chat
        try:
            async for event in self.agent.stream(prompt):
                chat.show_turn_event(event)
        except Exception as exc:
            logger.exception("TUI turn failed in session %s", self.agent.session_id)
            detail = " ".join(str(exc).split())[:160] or type(exc).__name__
            chat.add_notice(f"Beklenmeyen hata: {detail}. Ayrıntı günlükte.")
        finally:
            chat.end_reply()
            self.busy = False


def build_app(
    config: Config | None = None,
    *,
    profile: str | None = None,
    role: str = "brain",
    session_id: str | None = None,
    session_store: SessionStore | None = None,
    model: Any = None,
    tools: Iterable[Any] | None = None,
    clock: Callable[[], datetime] | None = None,
    notice: str | None = None,
    approve_delay: float = APPROVE_DELAY,
) -> TauApp:
    """Build the agent for the ``tui`` channel with a :class:`TuiApprover` and wrap it.

    ``model`` and ``tools`` are passed to ``build_agent`` (tests use ``FakeModel`` and tools
    defined in the test); by default the role's model and the ``tau.tools`` entry points are used.
    """
    approver = TuiApprover(approve_delay=approve_delay)
    agent = build_agent(
        profile,
        config=config,
        role=role,
        model=model,
        tools=tools,
        approver=approver,
        session_id=session_id,
        session_store=session_store,
        channel="tui",
        clock=clock,
    )
    return TauApp(agent, approver=approver, notice=notice)
