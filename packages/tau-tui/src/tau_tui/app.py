"""``TauApp``: the wiring point of the tau TUI.

One row of chrome at the top, a bottom-anchored transcript, the events pane (a column at
≥100 cols, a strip at 60–99 cols with ≥30 rows, a swappable view below), a session sidebar at
≥140 cols, the composer and one row of hints. The agent is consumed only through the tau-core
public API: ``TauAgent.stream()`` turn events feed the current :class:`Turn`; the app-scoped
``EventBus`` feeds the events pane and enriches the tool cards.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, tzinfo
from typing import Any

from tau_core import (
    STOP_REASONS,
    AgentEvent,
    Config,
    EventBus,
    Notice,
    ReasoningDelta,
    SessionStore,
    TauAgent,
    TextDelta,
    Throttled,
    ToolFinished,
    ToolProgress,
    ToolUseStarted,
    TurnEnd,
    build_agent,
    command_hint,
    resolve_command,
    t,
)
from tau_core import __version__ as core_version
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widget import Widget

import tau_tui.strings  # noqa: F401  (registers the tui.* message keys)
from tau_tui.approval import APPROVE_DELAY, ApprovalDone, ApprovalPending, TuiApprover
from tau_tui.commands import HANDLERS, SWITCHING
from tau_tui.composer import CommandMenu, Composer, HintBar
from tau_tui.events import EventsPane
from tau_tui.header import HeaderBar
from tau_tui.history import build_history
from tau_tui.keys import app_bindings
from tau_tui.sessions import SessionPicker, SessionSidebar, recent_sessions
from tau_tui.theme import ASCII_CSS, TAU_ANSI_THEME, TAU_THEME, mark_ascii
from tau_tui.transcript import STREAM_MODES, Transcript, Turn, WelcomeFacts

logger = logging.getLogger(__name__)

EVENT_BUFFER = 500
AgentFactory = Callable[[str | None], TauAgent]


class SessionNotFound(Exception):
    """``--resume ID`` named a session the store does not have."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Session not found: {session_id}.")
        self.session_id = session_id


def resolve_resume(
    store: SessionStore, resume: str | None, *, language: str = "en"
) -> tuple[str | None, str | None]:
    """``--resume [ID]`` → ``(session_id, notice)``.

    ``None`` → nothing to resume; ``""`` → the most recent earlier session with messages (or a
    notice when there is none); an id → that session, or :class:`SessionNotFound`.
    """
    if resume is None:
        return None, None
    if resume == "":
        recent = recent_sessions(store, None)
        if not recent:
            return None, t("session.none_earlier", language)
        return recent[0].session_id, None
    if store.read_session(resume) is None:
        raise SessionNotFound(resume)
    return resume, None


def short(exc: BaseException) -> str:
    return " ".join(str(exc).split())[:160] or type(exc).__name__


class AgentEventReceived(Message):
    """An agent event arrived from the bus (posted, so any thread may emit)."""

    def __init__(self, event: AgentEvent) -> None:
        super().__init__()
        self.event = event


class TauScreen(Screen[None]):
    """The default screen: re-runs the app's chrome refresh once a resize applied the bands.

    ``Screen._on_resize`` sets the breakpoint classes; the public ``on_resize`` handler runs
    after it, so the hint bar and the composer cap see the new band.
    """

    def on_mount(self) -> None:
        mark_ascii(self)

    def on_resize(self, event: events.Resize) -> None:
        app = self.app
        if isinstance(app, TauApp):
            app.refresh_chrome()


class TauApp(App[None]):
    """The tau TUI. The agent must be built with the same :class:`TuiApprover` and bus."""

    TITLE = "tau"
    AUTO_FOCUS = "#prompt"
    ENABLE_COMMAND_PALETTE = False
    HORIZONTAL_BREAKPOINTS = [(0, "-phone"), (60, "-narrow"), (100, "-wide"), (140, "-ultra")]
    VERTICAL_BREAKPOINTS = [(0, "-short"), (20, "-mid"), (30, "-tall")]
    BINDINGS = app_bindings()

    CSS = (
        """
    Screen { layout: vertical; background: $background; color: $foreground; }
    ModalScreen { background: $background 60%; }
    #body { height: 1fr; }
    #main { height: 1fr; }
    #stage { height: 1fr; }
    Screen.-narrow.-tall #stage { layout: vertical; }
    Screen.-phone.-events Transcript, Screen.-narrow.-events Transcript { display: none; }
    """
        + ASCII_CSS
    )

    language: reactive[str] = reactive("en", init=False)
    busy: reactive[bool] = reactive(False, init=False)
    attention: reactive[bool] = reactive(False, init=False)

    def __init__(
        self,
        agent: TauAgent,
        *,
        approver: TuiApprover | None = None,
        bus: EventBus | None = None,
        agent_factory: AgentFactory | None = None,
        store: SessionStore | None = None,
        notice: str | None = None,
        clock: Callable[[], datetime] | None = None,
        tz: tzinfo | None = None,
        motion: bool = True,
        show_durations: bool = True,
        stream_mode: str = "auto",
        language: str | None = None,
    ) -> None:
        super().__init__()
        self.agent = agent
        self.approver = approver
        if approver is not None:
            approver.attach(self)
        self.bus = bus or agent.events
        self.agent_factory = agent_factory
        self.store = store
        self.notice = notice
        self.clock = clock or (lambda: datetime.now(UTC))
        self.tz = tz
        self.motion = motion
        self.show_durations = show_durations
        if stream_mode not in STREAM_MODES:
            raise ValueError(f"stream_mode must be one of {STREAM_MODES}, not {stream_mode!r}")
        self.stream_mode = stream_mode
        self.set_reactive(TauApp.language, language or agent.config.ui.language)
        self.event_buffer: deque[AgentEvent] = deque(maxlen=EVENT_BUFFER)
        self.last_listing: list[str] = []
        self._unsubscribe: Callable[[], None] | None = None
        self._cancelling = False
        self._current_turn: Turn | None = None
        self.register_theme(TAU_THEME)
        self.register_theme(TAU_ANSI_THEME)
        self.theme = TAU_THEME.name

    def get_theme_variable_defaults(self) -> dict[str, str]:
        """The ``$tau-*`` state tokens resolve under any theme (also before ``on_mount``)."""
        defaults = dict(super().get_theme_variable_defaults())
        defaults.update({k: v for k, v in TAU_THEME.variables.items() if k.startswith("tau-")})
        return defaults

    # -- queries -----------------------------------------------------------------------------

    @property
    def transcript(self) -> Transcript:
        return self.query_one("#transcript", Transcript)

    @property
    def events_pane(self) -> EventsPane:
        return self.query_one("#events", EventsPane)

    @property
    def composer(self) -> Composer:
        return self.query_one("#composer", Composer)

    @property
    def menu(self) -> CommandMenu:
        return self.query_one("#menu", CommandMenu)

    @property
    def hint(self) -> HintBar:
        return self.query_one("#hint", HintBar)

    @property
    def header(self) -> HeaderBar:
        return self.query_one("#header", HeaderBar)

    @property
    def sidebar(self) -> SessionSidebar:
        return self.query_one("#sidebar", SessionSidebar)

    @property
    def config(self) -> Config:
        return self.agent.config

    def _provider(self) -> str:
        role = self.config.roles.get("brain")
        return role.provider if role is not None else "?"

    def _tool_counts(self) -> tuple[int, int]:
        catalog = self.agent.catalog
        tools = catalog.tools()
        approval = sum(1 for tool in tools if catalog.tier(tool.tool_name) == 2)
        return len(tools), approval

    def welcome_facts(self) -> WelcomeFacts:
        total, approval = self._tool_counts()
        return WelcomeFacts(
            version=core_version,
            profile=self.config.profile,
            session_id=self.agent.session_id,
            role="brain",
            provider=self._provider(),
            tools=total,
            approval_tools=approval,
        )

    def session_title(self, session_id: str) -> str:
        if self.store is None:
            return ""
        try:
            return str(self.store.read_meta(session_id).get("title") or "")
        except Exception:
            return ""

    # -- compose / mount ---------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        total, _ = self._tool_counts()
        yield HeaderBar(
            profile=self.config.profile,
            session_id=self.agent.session_id,
            role="brain",
            provider=self._provider(),
            tool_count=total,
            language=self.language,
            motion=self.motion,
        )
        with Horizontal(id="body"):
            yield SessionSidebar(self.language)
            with Vertical(id="main"):
                with Horizontal(id="stage"):
                    yield Transcript()
                    yield EventsPane(self.language)
                yield CommandMenu(self.language)
                yield Composer(self.language)
                yield HintBar(self.language)

    async def on_mount(self) -> None:
        if self.ansi_color:
            self.theme = TAU_ANSI_THEME.name
        transcript = self.transcript
        transcript.language = self.language
        transcript.show_durations = self.show_durations
        transcript.stream_mode = self.stream_mode
        transcript.clock = self.clock
        transcript.history_provider = self._history_items
        log = self.events_pane.log
        log.tz = self.tz
        log.show_durations = self.show_durations
        log.language = self.language
        self._unsubscribe = self.bus.subscribe(self._relay)
        await self._present_session(resumed=bool(self.agent.messages))
        if self.notice:
            await transcript.add_notice(self.notice)
        self.refresh_chrome()
        self.call_after_refresh(self.refresh_sessions)

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _relay(self, event: AgentEvent) -> None:
        self.post_message(AgentEventReceived(event))

    def _history_items(self) -> list:
        events_ = self.store.read_events(self.agent.session_id) if self.store else []
        return build_history(self.agent.messages, events_, tier_of=self._tier_of)

    def _tier_of(self, name: str) -> int | None:
        try:
            tier = self.agent.catalog.tier(name)
        except Exception:
            return None
        return int(tier) if tier is not None else None

    async def _present_session(self, *, resumed: bool) -> None:
        transcript = self.transcript
        events_ = self.store.read_events(self.agent.session_id) if (self.store and resumed) else []
        if self.agent.messages:
            await transcript.load_history(
                build_history(self.agent.messages, events_, tier_of=self._tier_of)
            )
            self.header.glyph.state = "idle"
        else:
            await transcript.show_welcome(self.welcome_facts())
            self.header.glyph.state = "welcome"
        self.events_pane.clear_all()
        self.events_pane.replay(events_)
        if resumed and self.agent.messages:
            session_id = self.agent.session_id
            await transcript.add_notice(
                t(
                    "session.resumed",
                    self.language,
                    title=self.session_title(session_id) or t("session.untitled", self.language),
                    session=session_id,
                    n=len(self.agent.messages),
                )
            )

    # -- chrome ------------------------------------------------------------------------------

    @property
    def chrome_screen(self) -> Screen:
        """The default screen: the one that holds the chrome and carries the breakpoint classes.

        ``self.screen`` is whatever is on top; while the approval dialog or the picker is up
        that modal has no breakpoint classes yet, so the bands are always read from here.
        """
        return self.screen_stack[0] if self.screen_stack else self.screen

    def _band(self) -> tuple[bool, bool]:
        """``(phone, wide)`` from the default screen's breakpoint classes."""
        screen = self.chrome_screen
        return screen.has_class("-phone"), screen.has_class("-wide") or screen.has_class("-ultra")

    def events_view_active(self) -> bool:
        screen = self.chrome_screen
        return screen.has_class("-events") and not (
            screen.has_class("-wide") or screen.has_class("-ultra")
        )

    def refresh_chrome(self) -> None:
        if not self.is_running:
            return
        try:
            hint, header, composer, menu = self.hint, self.header, self.composer, self.menu
        except Exception:
            return
        phone, wide = self._band()
        if self.attention:
            state = "attention"
        elif self.busy:
            state = "busy"
        elif menu.open:
            state = "menu"
        elif self.events_view_active():
            state = "events"
        else:
            state = "idle"
        hint.set_state(state, phone=phone, wide=wide)
        header.set_events_view(self.events_view_active())
        composer.state = "attention" if self.attention else ("busy" if self.busy else "idle")
        rows = 2 if self.chrome_screen.has_class("-short") else (3 if phone else 5)
        composer.set_max_rows(rows)

    def get_default_screen(self) -> Screen:
        return TauScreen(id="_default")

    def on_composer_changed(self, message: Composer.Changed) -> None:
        self.refresh_chrome()

    def watch_busy(self, busy: bool) -> None:
        if not busy:
            self._cancelling = False
        self.header.glyph.state = "busy" if busy else self._idle_glyph_state()
        self.refresh_chrome()

    def watch_attention(self, attention: bool) -> None:
        if attention:
            self.header.glyph.state = "attention"
        elif self.busy:
            self.header.glyph.state = "busy"
        else:
            self.header.glyph.state = self._idle_glyph_state()
        self.refresh_chrome()

    def _idle_glyph_state(self) -> str:
        return "welcome" if self.transcript.query("#welcome") else "idle"

    def watch_language(self, language: str) -> None:
        if not self.is_running:
            return
        self.transcript.relabel(language)
        self.composer.relabel(language)
        self.hint.relabel(language)
        self.events_pane.relabel(language)
        self.sidebar.relabel(language)
        self.header.relabel(language)
        self.menu.relabel(language)
        if isinstance(self.screen, SessionPicker):
            self.screen.relabel(language)
        self.refresh_chrome()

    def action_help_quit(self) -> None:
        self.notify(t("tui.quit_hint", self.language))

    # -- input -------------------------------------------------------------------------------

    async def on_composer_submitted(self, message: Composer.Submitted) -> None:
        text = message.text.strip()
        if not text:
            return
        if text.startswith("/"):
            self.composer.clear()
            self.menu.close()
            await self.run_command(text)
            self.refresh_chrome()
            return
        if self.busy:
            self.notify(t("tui.busy", self.language), severity="warning")
            return  # keep the typed text
        self.composer.clear()
        self.composer.push_history(text)
        self.run_turn(text)

    async def on_composer_help_requested(self, message: Composer.HelpRequested) -> None:
        await HANDLERS["help"](self, "")

    async def run_command(self, line: str) -> None:
        resolved = resolve_command(line)
        if resolved is None:
            name = line[1:].strip().partition(" ")[0]
            await self.transcript.add_notice(
                t(
                    "chat.unknown_command",
                    self.language,
                    name=name,
                    hint=command_hint(self.language),
                )
            )
            return
        name, argument = resolved
        if name in SWITCHING and self.busy:
            self.notify(t("tui.busy_switch", self.language), severity="warning")
            return
        await HANDLERS[name](self, argument)

    # -- turns -------------------------------------------------------------------------------

    @work(group="turn", exclusive=True, exit_on_error=False)
    async def run_turn(self, prompt: str) -> None:
        """One user turn: the stream drives the current :class:`Turn`."""
        lang = self.language
        turn = await self.transcript.begin_turn(prompt)
        self._current_turn = turn
        self.busy = True
        started = self.clock()
        elapsed = 0.0
        try:
            async for ev in self.agent.stream(prompt):
                elapsed = (self.clock() - started).total_seconds()
                match ev:
                    case TextDelta(text=text):
                        await turn.feed_text(text)
                    case ReasoningDelta(text=text):
                        await turn.feed_reasoning(text)
                    case ToolUseStarted():
                        await turn.add_tool(ev)
                        await turn.set_busy("tui.busy.running", tool=ev.tool)
                    case ToolProgress():
                        turn.tool_progress(ev.tool_use_id, ev.tool, ev.text)
                    case ToolFinished():
                        await turn.finish_tool(ev)
                        await turn.set_busy("tui.busy.thinking")
                    case Throttled(delay_seconds=delay):
                        await turn.set_busy("tui.busy.throttled", seconds=round(delay))
                    case Notice(text=text):
                        await turn.add_notice(text)
                    case TurnEnd(stop_reason=stop_reason):
                        if stop_reason not in STOP_REASONS:
                            logger.warning("unknown stop reason %r", stop_reason)
                        await turn.end(stop_reason, elapsed=elapsed)
        except Exception as exc:
            logger.exception("TUI turn failed in session %s", self.agent.session_id)
            await turn.add_notice(t("tui.unexpected_error", lang, detail=short(exc)))
            await turn.end("error", elapsed=(self.clock() - started).total_seconds())
        finally:
            if turn.running:
                await turn.end("error", elapsed=(self.clock() - started).total_seconds())
            self._current_turn = None
            self.busy = False
            self.transcript.trim()
            self.refresh_sessions()

    # -- approvals ---------------------------------------------------------------------------

    async def on_approval_pending(self, message: ApprovalPending) -> None:
        request = message.request
        card = self.transcript.match_pending(request.tool)
        if card is not None:
            card.set_arguments(request.arguments)
            card.set_pending()
        turn = self._current_turn
        if turn is not None and turn.running:
            await turn.set_busy("tui.busy.approval")
        self.attention = True
        self.bell()

    async def on_approval_done(self, message: ApprovalDone) -> None:
        card = self.transcript.match_pending(message.request.tool)
        if card is not None:
            if message.decision.value == "approved":
                card.approval = "approved"
            if card.status == "pending":
                card.status = "running"
        turn = self._current_turn
        if turn is not None and turn.running:
            await turn.set_busy("tui.busy.running", tool=message.request.tool)
        self.attention = False

    # -- events ------------------------------------------------------------------------------

    async def on_agent_event_received(self, message: AgentEventReceived) -> None:
        message.stop()
        event = message.event
        if event.session_id not in (None, self.agent.session_id):
            return
        self.event_buffer.append(event)
        self.events_pane.add_event(event)
        await self.transcript.enrich(event)

    # -- sessions ----------------------------------------------------------------------------

    def refresh_sessions(self) -> None:
        if not self.is_running:
            return
        try:
            self.sidebar.refresh_list(self.store, self.agent.session_id, self.clock(), tz=self.tz)
        except Exception:
            logger.exception("could not refresh the session sidebar")

    async def switch_session(self, session_id: str | None) -> None:
        lang = self.language
        if self.busy:
            self.notify(t("tui.busy_switch", lang), severity="warning")
            return
        if self.agent_factory is None:
            await self.transcript.add_notice(t("session.open_failed", lang, error="no factory"))
            return
        try:
            new = self.agent_factory(session_id)
        except Exception as exc:
            logger.exception("could not open session %s", session_id)
            await self.transcript.add_notice(t("session.open_failed", lang, error=short(exc)))
            return
        old, self.agent = self.agent, new
        old.close()
        self.event_buffer.clear()
        self.last_listing = []
        with self.batch_update():
            await self.transcript.reset()
            await self._present_session(resumed=session_id is not None)
        self.header.set_session(new.session_id)
        self.refresh_sessions()
        if session_id is None:
            await self.transcript.add_notice(t("session.new", lang, session=new.session_id))
        self.header.glyph.state = self._idle_glyph_state()

    def on_session_sidebar_picked(self, message: SessionSidebar.Picked) -> None:
        message.stop()
        if message.session_id != self.agent.session_id:
            self.run_worker(self.switch_session(message.session_id), group="switch")

    # -- actions -----------------------------------------------------------------------------

    async def action_escape(self) -> None:
        if self.menu.open:
            self.menu.close()
            self.refresh_chrome()
            return
        if self.busy:
            if not self._cancelling:
                self._cancelling = True
                self.agent.cancel()
                turn = self._current_turn
                if turn is not None and turn.running:
                    await turn.set_busy("tui.busy.cancelling")
            return
        if self.events_view_active():
            self.chrome_screen.remove_class("-events")
            self.refresh_chrome()
            return
        transcript = self.transcript
        if not transcript.is_vertical_scroll_end:
            transcript.scroll_end(animate=False)
            transcript.anchor()

    def action_toggle_events(self) -> None:
        screen = self.chrome_screen
        if screen.has_class("-wide") or screen.has_class("-ultra"):
            screen.toggle_class("-events-hidden")
        else:
            screen.toggle_class("-events")
        self.refresh_chrome()
        self.composer.prompt.focus()

    def action_pick_session(self) -> None:
        if self.busy:
            self.notify(t("tui.busy_switch", self.language), severity="warning")
            return
        sessions = recent_sessions(self.store, self.agent.session_id)
        self.last_listing = [s.session_id for s in sessions]

        def picked(result: str | None) -> None:
            if result is None:
                return
            self.run_worker(self.switch_session(result or None), group="switch")

        self.push_screen(
            SessionPicker(sessions, language=self.language, now=self.clock, tz=self.tz),
            callback=picked,
        )

    async def action_new_session(self) -> None:
        if self.busy:
            self.notify(t("tui.busy_switch", self.language), severity="warning")
            return
        await self.switch_session(None)

    async def action_show_tools(self) -> None:
        await HANDLERS["tools"](self, "")

    async def action_help(self) -> None:
        await HANDLERS["help"](self, "")

    def action_toggle_cards(self) -> None:
        self.transcript.toggle_last_turn()

    def _modal_scroll_target(self) -> Widget | None:
        """On a modal screen PageUp/PageDown scroll its ``scroll_target`` (arguments, list)."""
        if isinstance(self.screen, ModalScreen):
            target = getattr(self.screen, "scroll_target", None)
            return target if isinstance(target, Widget) else self.screen
        return None

    async def action_scroll_transcript_up(self) -> None:
        target = self._modal_scroll_target()
        if target is not None:
            target.scroll_page_up(animate=False)
            return
        transcript = self.transcript
        if transcript.scroll_y <= 0 and transcript.folded:
            await transcript.page_older()
            return
        transcript.scroll_page_up(animate=False)

    def action_scroll_transcript_down(self) -> None:
        target = self._modal_scroll_target()
        if target is not None:
            target.scroll_page_down(animate=False)
            return
        self.transcript.scroll_page_down(animate=False)

    def action_scroll_bottom(self) -> None:
        transcript = self.transcript
        transcript.scroll_end(animate=False)
        transcript.anchor()


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
    tz: tzinfo | None = None,
    motion: bool = True,
    show_durations: bool = True,
    stream_mode: str = "auto",
) -> TauApp:
    """Build the agent for the ``tui`` channel with a :class:`TuiApprover` and wrap it.

    One ``EventBus`` and one approver serve the app for its lifetime; ``agent_factory`` builds
    every later agent (``/new``, ``/resume``) on the same bus, store and approver. ``model``
    and ``tools`` are passed to ``build_agent`` (tests use ``FakeModel`` and test-local tools).
    """
    config = config or Config.load()
    if profile:
        config = config.with_overrides(profile=profile)
    bus = EventBus()
    approver = TuiApprover(approve_delay=approve_delay)
    tool_list = list(tools) if tools is not None else None

    def agent_factory(target: str | None) -> TauAgent:
        return build_agent(
            config=config,
            role=role,
            model=model,
            tools=tool_list,
            approver=approver,
            session_id=target,
            session_store=session_store,
            events=bus,
            channel="tui",
            clock=clock,
        )

    agent = agent_factory(session_id)
    return TauApp(
        agent,
        approver=approver,
        bus=bus,
        agent_factory=agent_factory,
        store=session_store,
        notice=notice,
        clock=clock,
        tz=tz,
        motion=motion,
        show_durations=show_durations,
        stream_mode=stream_mode,
    )
