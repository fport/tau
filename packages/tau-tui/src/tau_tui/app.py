"""``TauApp``: the wiring point of the tau TUI.

One row of chrome at the top, a bottom-anchored transcript, the events pane (a column at
≥100 cols, a strip at 60–99 cols with ≥30 rows, a swappable view below), a session sidebar at
≥140 cols, the composer and one row of hints. The agent is consumed only through the tau-core
public API: ``TauAgent.stream()`` turn events feed the current :class:`Turn`; the app-scoped
``EventBus`` feeds the events pane and enriches the tool cards.

With an owner guard (ADR 0008) ``build_app`` resolves the guard once and passes the same object
to every agent build. The app starts on the opaque lock screen (:class:`GuardScreen`) and builds
its first agent only after the first unlock, so the setup screens never open while locked. A
worker long-polls ``guard.watch()``; when the guard locks, the pending approval is rejected, the
running turn is cancelled the way Esc cancels it and the lock screen comes back. While locked
only ctrl+q and the :data:`~tau_core.guard.ALLOWED_WHILE_LOCKED` commands run.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, tzinfo
from typing import Any

from tau_core import (
    LANGUAGES,
    STOP_REASONS,
    AgentEvent,
    CompactionCancelled,
    CompactionError,
    Config,
    ConfigError,
    EventBus,
    Guard,
    GuardProgress,
    GuardStatus,
    MissingCredentials,
    Notice,
    ProviderNotSupported,
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
    compaction_title,
    describe_model,
    record_compaction,
    resolve_command,
    seed_messages,
    stored_role,
    summarize,
    t,
)
from tau_core import __version__ as core_version
from tau_core.commands import SLASH_COMMANDS, help_lines
from tau_core.guard import (
    ALLOWED_WHILE_LOCKED,
    DISCOVER,
    guard_status_line,
    process_client_id,
    resolve_guard,
)
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.worker import Worker

import tau_tui.strings  # noqa: F401  (registers the tui.* message keys)
from tau_tui.approval import APPROVE_DELAY, ApprovalDone, ApprovalPending, TuiApprover
from tau_tui.commands import AGENTLESS, HANDLERS, SWITCHING
from tau_tui.composer import CommandMenu, Composer, HintBar
from tau_tui.events import EventsPane
from tau_tui.guard import GuardScreen, progress_text, verdict_text
from tau_tui.header import HeaderBar
from tau_tui.history import build_history
from tau_tui.keys import app_bindings
from tau_tui.sessions import SessionPicker, SessionSidebar, recent_sessions
from tau_tui.settings import SECTIONS, SettingsOutcome, SettingsScreen
from tau_tui.theme import ASCII_CSS, TAU_ANSI_THEME, TAU_THEME, mark_ascii
from tau_tui.transcript import STREAM_MODES, BusyRow, Transcript, Turn, WelcomeFacts

logger = logging.getLogger(__name__)

EVENT_BUFFER = 500
DEFAULT_ROLE = "brain"
NO_SESSION = "—"
"""What the header shows for the session while there is no agent (no credentials yet)."""
AgentFactory = Callable[..., TauAgent]
"""``factory(session_id, *, role=None, seed_messages=None, config=None, guard=DISCOVER) ->
TauAgent``: every later agent (``/new``, ``/resume``, ``/compact``, ``/model``, a settings save)
on the app's bus, store and approver; ``config`` replaces the config every later build uses and
``guard`` is the app's owner guard."""
MODAL_BLOCKED_ACTIONS = frozenset(
    {
        "pick_session",
        "new_session",
        "show_tools",
        "toggle_events",
        "toggle_cards",
        "help",
        "settings",
    }
)
"""App actions that stay out of the way while the settings screen is on top (its own F2 saves;
the app's priority F2 would otherwise open the session picker over it)."""
LOCKED_ACTIONS = frozenset({"quit", "help_quit"})
"""App actions that still run while the owner guard is locked: ctrl+q and the ctrl+c hint.
The lock screen's own Enter and Esc are its bindings, not the app's."""
COUNTED_FAILURES = frozenset({"no_match", "spoof", "multiple_faces"})
"""Verdict reasons that count as a failed attempt (ADR 0008 decision 13)."""
WATCH_WAIT = 25.0
"""Seconds one ``guard.watch()`` long poll waits for a change."""


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
    GuardScreen { background: $background; }
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
    attempt_running: reactive[bool] = reactive(False, init=False)
    """A guard attempt runs (an unlock, a recheck or a step-up): the camera is on."""

    def __init__(
        self,
        agent: TauAgent | None,
        *,
        config: Config | None = None,
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
        role_pinned: bool = False,
        role: str = DEFAULT_ROLE,
        session_id: str | None = None,
        missing_credentials: MissingCredentials | None = None,
        unsupported_provider: ProviderNotSupported | None = None,
        show_paths: bool = True,
        version: str | None = None,
        guard: Guard | None = None,
    ) -> None:
        """``agent=None`` is the agentless start: ``missing_credentials`` says which variables
        the role lacks (the settings screen opens on the Credentials section with them marked)
        or ``unsupported_provider`` names a planned provider the stored config put on the role
        (the screen opens on Model roles). Either way the app opens on ``config``, the composer
        takes only ``/settings``, ``/help``, ``/lang`` and ``/quit``, and the first agent is
        built for ``session_id`` (``--resume``) on ``role`` once a save removes the blocker.

        ``guard`` is the owner guard every build gets. With a guard and no agent (and no
        blocker) the first agent is built after the first unlock."""
        super().__init__()
        if agent is None and config is None:
            raise ValueError("TauApp needs an agent or a config")
        self.agent = agent
        self._config: Config = config if config is not None else agent.config  # type: ignore[union-attr]
        self._default_role = role
        self._session_id = session_id
        self.missing_credentials = missing_credentials
        self.unsupported_provider = unsupported_provider
        self.show_paths = show_paths
        self.version = version or core_version
        """What the welcome card shows as the tau version (tests pin it so the snapshots do
        not change with every release)."""
        self.approver = approver
        if approver is not None:
            approver.attach(self)
        self.bus = bus or (agent.events if agent is not None else EventBus())
        self.agent_factory = agent_factory
        self.store = store
        self.role_pinned = role_pinned
        """``build_app(role=...)`` was explicit: a resumed session's stored role never wins."""
        self.notice = notice
        self.clock = clock or (lambda: datetime.now(UTC))
        self.tz = tz
        self.motion = motion
        self.show_durations = show_durations
        if stream_mode not in STREAM_MODES:
            raise ValueError(f"stream_mode must be one of {STREAM_MODES}, not {stream_mode!r}")
        self.stream_mode = stream_mode
        self.set_reactive(TauApp.language, language or self._config.ui.language)
        self.event_buffer: deque[AgentEvent] = deque(maxlen=EVENT_BUFFER)
        self.last_listing: list[str] = []
        self._unsubscribe: Callable[[], None] | None = None
        self._cancelling = False
        self._current_turn: Turn | None = None
        self._compaction_cancel: threading.Event | None = None
        """Set while ``/compact`` is summarizing; Esc sets it to cancel the summarizer."""
        self._compaction_row: BusyRow | None = None
        self.guard = guard
        """The owner guard (ADR 0008), the same object for every build. While it is ``None`` it
        is resolved again before every build and every submit (one stat), so a guard set up
        while the app runs locks it at once."""
        self.guard_status: GuardStatus | None = None
        """The guard's last known state (the watcher, a lock, an unlock)."""
        self.locked = guard is not None
        """The guard is not unlocked: only ctrl+q and the allowed commands run."""
        self.guard_screen: GuardScreen | None = None
        self._first_build_pending = (
            agent is None
            and guard is not None
            and missing_credentials is None
            and unsupported_provider is None
        )
        self._guard_failures = 0
        self._unlock_worker: Worker[None] | None = None
        self._watching = False
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
        """The config of the current agent, or the one the app opened on without an agent."""
        return self.agent.config if self.agent is not None else self._config

    @property
    def role(self) -> str:
        """The model role of the current agent (``/model`` switches it)."""
        return self.agent.role if self.agent is not None else self._default_role

    @property
    def session_id(self) -> str:
        return self.agent.session_id if self.agent is not None else NO_SESSION

    def _provider(self) -> str:
        """The provider actually serving the role, read off the model instance."""
        if self.agent is None:
            role_cfg = self.config.roles.get(self.role)
            return role_cfg.provider if role_cfg is not None else "?"
        return describe_model(self.agent).provider

    def _tool_counts(self) -> tuple[int, int]:
        if self.agent is None:
            return 0, 0
        catalog = self.agent.catalog
        tools = catalog.tools()
        approval = sum(1 for tool in tools if catalog.tier(tool.tool_name) == 2)
        return len(tools), approval

    @property
    def blocker_key(self) -> str:
        """The message key that says what the agentless start waits for: credentials, or
        (when only a planned provider is in the way) an available provider."""
        if self.missing_credentials is None and self.unsupported_provider is not None:
            return "settings.no_provider"
        return "settings.no_credentials"

    def _require_agent(self) -> TauAgent | None:
        """The agent, or ``None`` after telling the user what has to be set first."""
        if self.agent is None:
            self.notify(t(self.blocker_key, self.language), severity="warning")
        return self.agent

    def welcome_facts(self) -> WelcomeFacts:
        total, approval = self._tool_counts()
        return WelcomeFacts(
            version=self.version,
            profile=self.config.profile,
            session_id=self.session_id,
            role=self.role,
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
            session_id=self.session_id,
            role=self.role,
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
        if self.guard is not None:
            self._show_lock()  # the lock screen comes before anything else
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
        if self.agent is not None:
            await self._present_session(resumed=bool(self.agent.messages))
            await self._notice_fallback()
        elif not self._first_build_pending:
            await self._present_blocked()
        if self.notice and not self._first_build_pending:
            await transcript.add_notice(self.notice)
        if self.guard is not None:
            self.header.set_guard(True)
            self._start_watching()
        self.refresh_chrome()
        self.call_after_refresh(self.refresh_sessions)
        if self.agent is None and not self._first_build_pending:
            self.call_after_refresh(self.open_settings)

    async def _present_blocked(self) -> None:
        """The agentless start: the welcome card and what blocks the first agent."""
        transcript = self.transcript
        await transcript.show_welcome(self.welcome_facts())
        self.header.glyph.state = "attention"
        blocker = self.missing_credentials or self.unsupported_provider
        if blocker is not None:
            await transcript.add_notice(str(blocker))
        await transcript.add_notice(t(self.blocker_key, self.language))

    def on_unmount(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _relay(self, event: AgentEvent) -> None:
        self.post_message(AgentEventReceived(event))

    def _history_items(self) -> list:
        if self.agent is None:
            return []
        events_ = self.store.read_events(self.agent.session_id) if self.store else []
        return build_history(self.agent.messages, events_, tier_of=self._tier_of)

    def _tier_of(self, name: str) -> int | None:
        if self.agent is None:
            return None
        try:
            tier = self.agent.catalog.tier(name)
        except Exception:
            return None
        return int(tier) if tier is not None else None

    async def _notice_fallback(self) -> None:
        """One line when the role runs on its fallback provider (the start-up warning of
        ``tau chat`` goes to the log only while the TUI owns the terminal)."""
        if self.agent is None:
            return
        info = describe_model(self.agent)
        if info.fallback_of is None:
            return
        await self.transcript.add_notice(
            t(
                "settings.fallback_notice",
                self.language,
                role=self.agent.role,
                provider=info.provider,
                primary=info.fallback_of,
            )
        )

    async def _present_session(self, *, resumed: bool) -> None:
        if self.agent is None:
            return
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
        if self.attention:
            composer.state = "attention"
        elif self.busy:
            composer.state = "busy"
        elif self.agent is None:
            composer.set_disabled_key(self.blocker_key)
            composer.state = "disabled"
        else:
            composer.state = "idle"
        rows = 2 if self.chrome_screen.has_class("-short") else (3 if phone else 5)
        composer.set_max_rows(rows)

    def get_default_screen(self) -> Screen:
        return TauScreen(id="_default")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Keep the app's priority keys (F2 picker, ctrl+n, F1, …) out of the settings screen:
        its own F2 saves. The scroll actions stay, they know about modal targets. While the
        owner guard is locked only ctrl+q (and the ctrl+c hint) run."""
        if self.locked and action not in LOCKED_ACTIONS:
            return False
        if action in MODAL_BLOCKED_ACTIONS and isinstance(self.screen, SettingsScreen):
            return False
        return True

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

    def watch_attempt_running(self, running: bool) -> None:
        if self.is_running:
            self.header.set_guard(self.guard is not None, attempt=running)

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
        if self.guard_screen is not None:
            self.guard_screen.relabel(language)
        self.refresh_chrome()

    def action_help_quit(self) -> None:
        self.notify(t("tui.quit_hint", self.language))

    # -- input -------------------------------------------------------------------------------

    async def on_composer_submitted(self, message: Composer.Submitted) -> None:
        text = message.text.strip()
        if not text:
            return
        self.current_guard()
        if text.startswith("/"):
            self.composer.clear()
            self.menu.close()
            await self.run_command(text)
            self.refresh_chrome()
            return
        if self.locked:  # checked before the composer is cleared: the text stays
            self._show_lock(self.guard_status)
            return
        if self.busy:
            self.notify(t("tui.busy", self.language), severity="warning")
            return  # keep the typed text
        if self._require_agent() is None:
            return  # no credentials yet: keep the typed text, the toast says what to do
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
        if self.locked and name not in ALLOWED_WHILE_LOCKED:
            await self.answer(t("guard.cmd.refused", self.language, command=name))
            return
        if self.locked and name == "help":
            self._guard_say(self.locked_help_lines())
            return
        if name in SWITCHING and self.busy:
            self.notify(t("tui.busy_switch", self.language), severity="warning")
            return
        if name not in AGENTLESS and self._require_agent() is None:
            return
        await HANDLERS[name](self, argument)

    # -- turns -------------------------------------------------------------------------------

    @work(group="turn", exclusive=True, exit_on_error=False)
    async def run_turn(self, prompt: str) -> None:
        """One user turn: the stream drives the current :class:`Turn`."""
        lang = self.language
        agent = self.agent
        if agent is None:
            return
        turn = await self.transcript.begin_turn(prompt)
        self._current_turn = turn
        self.busy = True
        started = self.clock()
        elapsed = 0.0
        refused: list[str] = []  # admission refusals, read synchronously off the bus

        def on_event(event: AgentEvent) -> None:
            data = event.data
            if (
                event.kind == "guard"
                and data.get("action") == "refused"
                and "tool" not in data
                and event.session_id in (None, agent.session_id)
            ):
                refused.append(str(data.get("reason")))

        unsubscribe = self.bus.subscribe(on_event)
        refusal: str | None = None
        rechecked = False
        try:
            while True:
                locked = await self._stream_turn(turn, prompt, started)
                elapsed = (self.clock() - started).total_seconds()
                if not locked:
                    break
                reason = refused[-1] if refused else "error"
                if reason == "recheck" and not rechecked and self.guard is not None:
                    rechecked = True
                    if await self._recheck(turn):
                        await turn.set_busy("tui.busy.thinking")
                        continue  # the passive check passed: send the same prompt again
                refusal = reason
                await turn.end("locked", elapsed=elapsed)
                break
        except Exception as exc:
            logger.exception("TUI turn failed in session %s", agent.session_id)
            await turn.add_notice(t("tui.unexpected_error", lang, detail=short(exc)))
            await turn.end("error", elapsed=(self.clock() - started).total_seconds())
        finally:
            unsubscribe()
            if turn.running:
                await turn.end("error", elapsed=(self.clock() - started).total_seconds())
            self._current_turn = None
            self.busy = False
            self.transcript.trim()
            self.refresh_sessions()
        if refusal is not None:
            await self._after_refusal(prompt)

    async def _stream_turn(self, turn: Turn, prompt: str, started: datetime) -> bool:
        """Feed one ``stream(prompt)`` into ``turn``; ``True`` when the guard refused it
        (``TurnEnd("locked")``, the turn is left open for a recheck)."""
        assert self.agent is not None
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
                case TurnEnd(stop_reason="locked"):
                    return True
                case TurnEnd(stop_reason=stop_reason):
                    if stop_reason not in STOP_REASONS:
                        logger.warning("unknown stop reason %r", stop_reason)
                    await turn.end(stop_reason, elapsed=elapsed)
        return False

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
        if not self.query("#transcript"):
            return  # the app is closing (a lock rejected the dialog on the way out)
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
        if self.agent is None or event.session_id not in (None, self.agent.session_id):
            return
        if not self.query("#events"):
            return  # the app is closing: a turn cut short by a lock may still post events
        self.event_buffer.append(event)
        self.events_pane.add_event(event)
        await self.transcript.enrich(event)
        if event.kind == "guard":
            await self._on_guard_event(event.data)

    async def _on_guard_event(self, data: dict[str, Any]) -> None:
        """A tier-2 step-up in the busy line: its start, every challenge step (with a bell),
        its end; the camera glyph shows in the header meanwhile."""
        lang = self.language
        action = data.get("action")
        turn = self._current_turn
        running = turn is not None and turn.running
        if action == "step_up" and data.get("phase") == "start":
            self.attempt_running = True
            if running:
                await turn.set_busy("guard.step_up.start")  # type: ignore[union-attr]
            self.bell()
        elif action == "step_up" and data.get("phase") == "end":
            self.attempt_running = False
            if running:
                if data.get("ok") is not True:
                    await turn.add_notice(t("guard.step_up.failed", lang))  # type: ignore[union-attr]
                await turn.set_busy("tui.busy.running", tool=str(data.get("tool") or "?"))  # type: ignore[union-attr]
        elif action == "challenge":
            hint = data.get("hint")
            step = GuardProgress(
                step=str(data.get("step")),
                seq=0,
                deadline=None,
                hint=hint if isinstance(hint, str) else None,
            )
            if running:
                await turn.set_busy("tui.busy.step_up", step=progress_text(step, lang))  # type: ignore[union-attr]
            self.bell()

    # -- sessions ----------------------------------------------------------------------------

    def refresh_sessions(self) -> None:
        if not self.is_running:
            return
        current = self.agent.session_id if self.agent is not None else None
        try:
            self.sidebar.refresh_list(self.store, current, self.clock(), tz=self.tz)
        except Exception:
            logger.exception("could not refresh the session sidebar")

    def _try_build(
        self,
        session_id: str | None,
        *,
        role: str | None = None,
        seed: list | None = None,
        config: Config | None = None,
    ) -> tuple[TauAgent | None, str | None]:
        """``(agent, None)`` from the factory, or ``(None, why)``: ``MissingCredentials`` and
        ``ConfigError`` in full (they name the variables or the setting to fix), anything else
        as ``session.open_failed``. ``config`` makes this and every later build use it."""
        lang = self.language
        if self.agent_factory is None:
            return None, t("session.open_failed", lang, error="no factory")
        extra: dict[str, Any] = {} if config is None else {"config": config}
        guard = self.current_guard()
        try:
            agent = self.agent_factory(
                session_id,
                role=role or self.role,
                seed_messages=seed,
                guard=guard if guard is not None else DISCOVER,
                **extra,
            )
        except (MissingCredentials, ConfigError) as exc:
            logger.warning("could not build the agent: %s", exc)
            return None, str(exc)
        except Exception as exc:
            logger.exception("could not open session %s", session_id)
            return None, t("session.open_failed", lang, error=short(exc))
        return agent, None

    async def _build(
        self, session_id: str | None, *, role: str | None = None, seed: list | None = None
    ) -> TauAgent | None:
        """A new agent from the factory, or ``None`` after showing why it could not be built."""
        agent, error = self._try_build(session_id, role=role, seed=seed)
        if error is not None:
            await self.transcript.add_notice(error)
        return agent

    def _adopt(self, new: TauAgent) -> None:
        """Make ``new`` the app's agent and close the previous one (a rebuild on the same
        session takes over its pending repair notice first)."""
        old, self.agent = self.agent, new
        if old is not None:
            new.carry_over(old)
            old.close()
        self._config = new.config
        self.header.set_profile(new.config.profile)
        self.header.set_role(new.role, describe_model(new).provider)

    # -- settings ----------------------------------------------------------------------------

    def open_settings(self, section: str | None = None, missing: list[str] | None = None) -> None:
        """``/settings [section]`` / F10: the settings screen on ``section`` (default: Model
        roles; Credentials with the missing names highlighted while credentials block the
        start). Refused while a turn is busy; a second call while it is open does nothing. A
        save is applied by :meth:`apply_settings` after the screen closes. Never while the owner
        guard is locked."""
        if self.locked:
            self.notify(t("guard.refused.locked", self.language), severity="warning")
            return
        if self.busy:
            self.notify(t("tui.busy_settings", self.language), severity="warning")
            return
        if isinstance(self.screen, SettingsScreen):
            return
        if self.agent is None and self.missing_credentials is not None:
            section = section or "credentials"
            missing = missing or list(self.missing_credentials.variables)
        elif self.agent is None and self.unsupported_provider is not None:
            section = section or "roles"
        try:
            screen = SettingsScreen(
                self.config,
                language=self.language,
                section=section if section in SECTIONS else "roles",
                missing=missing,
                show_paths=self.show_paths,
            )
        except ConfigError as exc:  # tau.toml vanished or broke since the start
            logger.warning("settings screen could not open: %s", exc)
            self.notify(str(exc), severity="error")
            return

        def done(saved: bool | None) -> None:
            if saved and screen.outcome is not None:
                self.run_worker(
                    self.apply_settings(screen.outcome), group="settings", exclusive=True
                )

        self.push_screen(screen, callback=done)

    async def apply_settings(self, outcome: SettingsOutcome) -> None:
        """After a save: the UI language live, then (when a role, an agent option, a credential
        or the profile changed, or there was no agent yet) the agent rebuilt on the same
        session with the validated config. A failed rebuild keeps the current agent."""
        lang = outcome.language if outcome.language in LANGUAGES else self.language
        if outcome.language and outcome.language != self.language:
            self.language = outcome.language
        transcript = self.transcript
        if outcome.config is None:
            await transcript.add_notice(
                t("settings.saved_not_reloaded", lang, error=outcome.error or "?")
            )
            return
        first = self.agent is None
        if not (outcome.reload or first):
            await transcript.add_notice(t("settings.saved", lang))
            return
        session_id = self.agent.session_id if self.agent is not None else self._session_id
        new, error = self._try_build(session_id, role=self.role, config=outcome.config)
        if new is None:
            self._config = outcome.config
            await transcript.add_notice(t("settings.saved_not_reloaded", lang, error=error))
            return
        self._adopt(new)
        self.missing_credentials = None
        self.unsupported_provider = None
        if first:
            self.header.set_session(new.session_id)
            with self.batch_update():
                await transcript.reset()
                await self._present_session(resumed=bool(new.messages))
            self.refresh_sessions()
        elif transcript.query("#welcome"):
            await transcript.show_welcome(self.welcome_facts())
        self.header.glyph.state = self._idle_glyph_state()
        self.refresh_chrome()
        await transcript.add_notice(t("settings.saved_reloaded", lang))
        await self._notice_fallback()

    def action_settings(self) -> None:
        self.open_settings()

    async def switch_session(self, session_id: str | None, *, role: str | None = None) -> None:
        """``/new`` (``None``) or ``/resume`` (an id). A resumed session comes back on the role
        its metadata remembers from ``/model`` unless ``build_app(role=...)`` pinned one; ``role``
        overrides both."""
        lang = self.language
        if self.busy:
            self.notify(t("tui.busy_switch", lang), severity="warning")
            return
        if self._require_agent() is None:
            return
        if role is None and session_id is not None and not self.role_pinned:
            role = stored_role(self.store, session_id, self.config)
        new = await self._build(session_id, role=role)
        if new is None:
            return
        self._adopt(new)
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

    async def switch_model(self, role: str) -> None:
        """``/model <role>``: the same session on another role. The agent is rebuilt on the
        stored history; the role is written to the session's metadata so ``/resume`` and
        ``--resume`` come back on it. Refused while a turn is busy; a failed build (missing
        credentials, an unknown provider) leaves the current agent working."""
        lang = self.language
        if self.busy:
            self.notify(t("tui.busy_model", lang), severity="warning")
            return
        if self._require_agent() is None:
            return
        if role not in self.config.roles:
            await self.transcript.add_notice(
                t("model.unknown", lang, role=role, roles=", ".join(self.config.roles))
            )
            return
        session_id = self.agent.session_id
        if role != self.role:
            new = await self._build(session_id, role=role)
            if new is None:
                return
            self._adopt(new)
        if self.store is not None:
            try:
                self.store.write_meta(session_id, role=role)
            except Exception:
                logger.exception("could not store the role of session %s", session_id)
        if self.transcript.query("#welcome"):
            await self.transcript.show_welcome(self.welcome_facts())
        await self.transcript.add_notice(
            t("model.current", lang, role=role, provider=self._provider())
        )
        await self._notice_fallback()

    async def compact_session(self, focus: str | None = None) -> None:
        """``/compact [focus]``: summarize the session with its own model, open a new session
        seeded with the summary and continue there. The old session stays in the store; the two
        are linked in their metadata.

        The summary is written in a worker, never on the message pump, so the app stays
        responsive meanwhile: the chrome is busy (``✻ Summarizing…``), read-only commands run,
        turns and session switches are refused, and Esc cancels the summarizer through the
        SDK's cancel signal; the current session goes on untouched.
        """
        if self.busy:
            self.notify(t("tui.busy_switch", self.language), severity="warning")
            return
        if self._require_agent() is None:
            return
        self.busy = True  # before the worker starts, so no turn slips in between
        self.run_worker(
            self._run_compaction(focus), group="compact", exclusive=True, exit_on_error=False
        )

    async def _run_compaction(self, focus: str | None) -> None:
        lang = self.language
        old = self.agent
        if old is None:
            self.busy = False
            return
        n = len(old.messages)
        cancel = threading.Event()
        self._compaction_cancel = cancel
        row = BusyRow("tui.busy.summarizing", lang)
        self._compaction_row = row
        try:
            if n:
                await self.transcript.add_notice(t("compact.started", lang, n=n))
            await self.transcript.mount(row)
            try:
                summary = await summarize(old, focus=focus, cancel_signal=cancel)
            except CompactionCancelled:
                await self.transcript.add_notice(t("compact.cancelled", lang))
                return
            except CompactionError as exc:
                await self.transcript.add_notice(t("compact.failed", lang, error=exc))
                return
            title = compaction_title(old)
            seed = seed_messages(summary, old.session_id)
            new = await self._build(None, role=self.role, seed=seed)
            if new is None:
                return
            self._adopt(new)
            record_compaction(
                self.store,
                previous=old.session_id,
                new=new.session_id,
                title=title,
                role=new.role,
            )
            self.event_buffer.clear()
            self.last_listing = []
            with self.batch_update():
                await self.transcript.reset()  # takes the busy row with it
                self.events_pane.clear_all()
                self.events_pane.replay(
                    self.store.read_events(new.session_id) if self.store else []
                )
                await self.transcript.add_info([seed[0]["content"][0]["text"]])
                await self.transcript.add_notice(
                    t(
                        "compact.done",
                        lang,
                        n=n,
                        session=new.session_id,
                        previous=old.session_id,
                    )
                )
            self.header.set_session(new.session_id)
            self.refresh_sessions()
        except Exception as exc:
            logger.exception("compaction failed in session %s", old.session_id)
            await self.transcript.add_notice(t("tui.unexpected_error", lang, detail=short(exc)))
        finally:
            self._compaction_cancel = None
            self._compaction_row = None
            if row.is_mounted:
                await row.remove()
            self.busy = False

    async def clear_screen(self) -> None:
        """``/clear``: empty the transcript (turns, welcome card, info cards, the fold) and
        reset its bookkeeping. The session and the agent are untouched: ``/resume`` and
        ``--resume`` show the history again. Refused while a turn is still mounting widgets."""
        lang = self.language
        if self.busy:
            self.notify(t("tui.busy_clear", lang), severity="warning")
            return
        if self._require_agent() is None:
            return
        with self.batch_update():
            await self.transcript.reset()
            await self.transcript.add_notice(t("clear.done", lang, n=len(self.agent.messages)))
        self.header.glyph.state = self._idle_glyph_state()

    def on_session_sidebar_picked(self, message: SessionSidebar.Picked) -> None:
        message.stop()
        if message.session_id != self.session_id:
            self.run_worker(self.switch_session(message.session_id), group="switch")

    # -- actions -----------------------------------------------------------------------------

    async def action_escape(self) -> None:
        if self.menu.open:
            self.menu.close()
            self.refresh_chrome()
            return
        if self.busy:
            await self._cancel_busy()
            return
        if self.events_view_active():
            self.chrome_screen.remove_class("-events")
            self.refresh_chrome()
            return
        transcript = self.transcript
        if not transcript.is_vertical_scroll_end:
            transcript.scroll_end(animate=False)
            transcript.anchor()

    async def _cancel_busy(self) -> None:
        """Esc while busy: stop the running turn, or the summarizer of ``/compact``."""
        if not self.busy or self._cancelling:
            return
        self._cancelling = True
        if self._compaction_cancel is not None:
            # ``/compact`` is summarizing: stop the throwaway summarizer, not the agent.
            self._compaction_cancel.set()
            row = self._compaction_row
            if row is not None and row.is_mounted:
                row.set_verb("tui.busy.cancelling")
            return
        if self.agent is not None:
            self.agent.cancel()
        turn = self._current_turn
        if turn is not None and turn.running:
            await turn.set_busy("tui.busy.cancelling")

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
        if self._require_agent() is None:
            return
        sessions = recent_sessions(self.store, self.session_id)
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
        if self._require_agent() is None:
            return
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

    # -- the owner guard ---------------------------------------------------------------------

    def current_guard(self) -> Guard | None:
        """The app's guard; while there is none it is resolved again (a guard set up while the
        app runs is found here, and the app locks at once)."""
        if self.guard is None:
            self.guard = resolve_guard(self.config)
            if self.guard is not None:
                logger.info("an owner guard became active; locking")
                self.locked = True
                self._show_lock()
                if self.is_running:
                    self.header.set_guard(True)
                self._start_watching()
        return self.guard

    def locked_help_lines(self) -> list[str]:
        """``/help`` on the lock screen: only what works while locked."""
        lang = self.language
        lines = [
            line
            for command, line in zip(SLASH_COMMANDS, help_lines(lang), strict=True)
            if command.name in ALLOWED_WHILE_LOCKED
        ]
        return [t("chat.help_header", lang), *lines, "", t("tui.guard.hint", lang)]

    def _guard_say(self, lines: list[str]) -> bool:
        """Show ``lines`` on the lock screen when it is up; ``False`` when it is not."""
        if self.guard_screen is None:
            return False
        self.guard_screen.show(lines)
        return True

    async def answer(self, text: str) -> None:
        """A one-line answer: on the lock screen while it is up, else in the transcript."""
        if not self._guard_say([text]):
            await self.transcript.add_notice(text)

    def _show_lock(self, status: GuardStatus | None = None) -> None:
        if self.guard_screen is not None:
            if status is not None:
                self.guard_screen.set_status(status)
            return
        screen = GuardScreen(status)
        self.guard_screen = screen
        self.push_screen(screen, callback=self._lock_closed)

    def _lock_closed(self, unlocked: bool | None) -> None:
        if self.is_running:
            self.refresh_chrome()
            if self.screen is self.chrome_screen:  # a picker or settings screen may be back
                self.composer.prompt.focus()

    def _start_watching(self) -> None:
        if self.guard is None or self._watching or not self.is_running:
            return
        self._watching = True
        self._follow_guard()

    @work(group="guard-watch", exclusive=True, exit_on_error=False)
    async def _follow_guard(self) -> None:
        """Long-poll ``guard.watch()`` for the life of the app and apply every state."""
        guard = self.guard
        if guard is None:
            return
        since = -1
        while True:
            try:
                status = await guard.watch(since, wait=WATCH_WAIT)
            except asyncio.CancelledError:
                raise
            except Exception:  # the protocol says it never raises; fail closed if it does
                logger.exception("guard %s failed to answer watch", guard.name)
                status = GuardStatus(state="unavailable", reason="error")
                await asyncio.sleep(2.0)
            since = status.seq
            await self.apply_guard_status(status)

    async def apply_guard_status(self, status: GuardStatus) -> None:
        """Lock on anything but ``unlocked``; leave the lock when the guard reports
        ``unlocked`` and no attempt of this app is still running (it leaves by itself)."""
        self.guard_status = status
        if status.state != "unlocked":
            await self.enter_lock(status)
        elif self.locked and not self.attempt_running:
            await self.leave_lock(status.method)

    async def enter_lock(self, status: GuardStatus) -> None:
        """The guard locked: reject the pending approval, cancel the running turn (the Esc
        path, ``/compact`` included) and show the lock screen."""
        self.locked = True
        self.guard_status = status
        if self.guard_screen is not None:
            self.guard_screen.set_status(status)
            return
        if self.approver is not None:
            self.approver.reject_pending()
        if self.busy:
            turn = self._current_turn
            await self._cancel_busy()
            if turn is not None and turn.running:
                await turn.add_notice(t("guard.locked_during_turn", self.language))
        if self.is_running:
            self.menu.close()
        self._show_lock(status)
        self.refresh_chrome()

    async def leave_lock(self, method: str | None) -> None:
        """Unlocked: close the lock screen, build the first agent if it waited for this, and
        show the "Unlocked" notice with the failed attempts. No model call; a prompt kept in
        the composer stays there."""
        if not self.locked:
            return
        self.locked = False
        status = self.guard_status
        failures = max(self._guard_failures, status.failures if status is not None else 0)
        self._guard_failures = 0
        screen, self.guard_screen = self.guard_screen, None
        if screen is not None and screen.is_attached:
            if self.screen is not screen:
                screen.pop_until_active()
            screen.dismiss(True)
        if self._first_build_pending:
            self._first_build_pending = False
            await self._first_build()
        await self.transcript.add_notice(
            t("guard.unlocked", self.language, method=method or "—", failures=failures)
        )
        self.refresh_chrome()

    async def _first_build(self) -> None:
        """The first agent, built after the first unlock. Missing credentials or a planned
        provider open the agentless start (and its settings screen) now."""
        if self.agent_factory is None:
            return
        guard = self.current_guard()
        try:
            agent = self.agent_factory(
                self._session_id,
                role=self._default_role,
                guard=guard if guard is not None else DISCOVER,
            )
        except MissingCredentials as exc:
            logger.warning("opening without an agent: %s", exc)
            self.missing_credentials = exc
        except ProviderNotSupported as exc:
            logger.warning("opening without an agent: %s", exc)
            self.unsupported_provider = exc
        except Exception as exc:
            logger.exception("could not build the first agent")
            await self.transcript.add_notice(
                t("session.open_failed", self.language, error=short(exc))
            )
            return
        else:
            self._adopt(agent)
            self.header.set_session(agent.session_id)
            with self.batch_update():
                await self.transcript.reset()
                await self._present_session(resumed=bool(agent.messages))
            if self.notice:
                await self.transcript.add_notice(self.notice)
            await self._notice_fallback()
            self.header.glyph.state = self._idle_glyph_state()
            self.refresh_sessions()
            return
        await self._present_blocked()
        if self.notice:
            await self.transcript.add_notice(self.notice)
        self.refresh_chrome()
        self.open_settings()

    def start_unlock(self) -> None:
        """Enter on the lock screen (or ``/guard unlock``): one unlock attempt in a worker."""
        if self.guard is None or not self.locked or self.attempt_running:
            return
        self.attempt_running = True
        self._unlock_worker = self.run_worker(
            self._unlock(), group="guard-unlock", exclusive=True, exit_on_error=False
        )

    async def _unlock(self) -> None:
        guard = self.guard
        assert guard is not None
        lang = self.language
        screen = self.guard_screen
        if screen is not None:
            screen.begin_attempt()

        def on_progress(progress: GuardProgress) -> None:
            if self.guard_screen is not None:
                self.guard_screen.progress(progress)

        try:
            verdict = await guard.unlock(
                channel="tui",
                client_id=process_client_id(),
                kind="unlock",
                on_progress=on_progress,
            )
        except asyncio.CancelledError:
            if screen is not None:
                screen.end_attempt()
                screen.show([t("guard.verdict.cancelled", lang), t("guard.prompt.retry", lang)])
            raise
        finally:
            self.attempt_running = False
        if verdict.ok:
            await self.leave_lock(verdict.method)
            return
        if verdict.reason in COUNTED_FAILURES:
            self._guard_failures += 1
        if screen is not None:
            screen.end_attempt()
            screen.show([verdict_text(verdict, lang), t("guard.prompt.retry", lang)])
        status = await guard.status()
        await self.apply_guard_status(status)

    def cancel_unlock(self) -> None:
        """Esc on the lock screen: cancel the running attempt (the hub releases the camera)."""
        worker, guard = self._unlock_worker, self.guard
        if worker is None or worker.is_finished or guard is None:
            return
        worker.cancel()
        self.run_worker(
            guard.cancel(client_id=process_client_id()), group="guard-cancel", exit_on_error=False
        )

    async def _recheck(self, turn: Turn) -> bool:
        """The passive presence check after a ``recheck`` admission, in the busy line."""
        guard = self.guard
        assert guard is not None
        lang = self.language
        await turn.set_busy("guard.recheck")

        def on_progress(progress: GuardProgress) -> None:
            row = turn.busy_row
            if row is not None and row.is_mounted:
                row.set_verb("tui.busy.step_up", step=progress_text(progress, lang))

        self.attempt_running = True
        try:
            verdict = await guard.unlock(
                channel="tui",
                client_id=process_client_id(),
                kind="recheck",
                on_progress=on_progress,
            )
        finally:
            self.attempt_running = False
        if not verdict.ok:
            if verdict.reason in COUNTED_FAILURES:
                self._guard_failures += 1
            await turn.add_notice(verdict_text(verdict, lang))
        return verdict.ok

    async def _after_refusal(self, prompt: str) -> None:
        """A turn the guard refused: the prompt goes back into an empty composer and the
        guard's state decides whether the lock screen comes back."""
        composer = self.composer
        if not composer.text.strip():
            composer.prompt.load_text(prompt)
        guard = self.guard
        if guard is not None:
            await self.apply_guard_status(await guard.status())

    async def guard_command(self, argument: str) -> None:
        """``/guard [lock|unlock]``: the state, a lock, or an unlock attempt while locked."""
        lang = self.language
        guard = self.current_guard()
        if guard is None:
            await self.answer(t("guard.cmd.off", lang))
            return
        word = argument.strip().casefold()
        if not word:
            status = await guard.status()
            await self.answer(guard_status_line(status, lang))
            await self.apply_guard_status(status)
        elif word == "lock":
            self.action_lock()
        elif word == "unlock":
            if self.locked:
                self.start_unlock()
            else:
                await self.answer(t("guard.cmd.already_unlocked", lang))
        else:
            await self.answer(t("guard.cmd.usage", lang))

    def action_lock(self) -> None:
        """ctrl+l / F5 (and ``/guard lock``): lock the guard now, from anywhere."""
        if self.current_guard() is None:
            self.notify(t("guard.cmd.off", self.language))
            return
        self.run_worker(self._lock(), group="guard-lock", exclusive=True, exit_on_error=False)

    async def _lock(self) -> None:
        guard = self.guard
        assert guard is not None
        await guard.lock(channel="tui", client_id=process_client_id(), trigger="command")
        status = await guard.status()  # a lock the hub did not confirm must not look locked
        if status.state == "locked":
            await self.apply_guard_status(status)
        else:
            self.notify(t("guard.cmd.lock_failed", self.language), severity="error")


def build_app(
    config: Config | None = None,
    *,
    profile: str | None = None,
    role: str | None = None,
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
    show_paths: bool = True,
    version: str | None = None,
    guard: Any = DISCOVER,
) -> TauApp:
    """Build the agent for the ``tui`` channel with a :class:`TuiApprover` and wrap it.

    One ``EventBus`` and one approver serve the app for its lifetime; ``agent_factory`` builds
    every later agent (``/new``, ``/resume``, ``/compact``, ``/model``, a settings save) on the
    same bus, store and approver, on the config a settings save last handed it (``config=``).
    ``model`` and ``tools`` are passed to ``build_agent`` (tests use ``FakeModel`` and
    test-local tools). ``role=None`` means ``brain``, or the role a resumed ``session_id``
    remembers from ``/model``; an explicit ``role`` pins it for the app's lifetime.

    When the first agent cannot be built for lack of credentials, or because the stored config
    puts the role on a planned provider (``PLANNED_PROVIDERS``), the app still opens,
    without an agent, on the settings screen's Credentials or Model roles section (see
    :class:`TauApp`), so the user can always recover in the UI; every other failure
    propagates. ``profile`` (``tau tui --profile``) overrides ``TAU_PROFILE`` for the app's
    lifetime, rebuilds after a settings save included. ``show_paths=False`` keeps real paths
    out of the settings screen and ``version`` pins what the welcome card shows (snapshots).

    ``guard`` defaults to the configuration's owner guard (``resolve_guard``, once for the
    app's lifetime; tests pass a ``FakeGuard``). With a guard the first agent is not built
    here: the app opens on the lock screen and builds it after the first unlock.
    """
    config = config or Config.load()
    if profile:
        config = config.with_overrides(profile=profile)
    guard = resolve_guard(config) if guard is DISCOVER else guard
    if guard is not None and not isinstance(guard, Guard):
        raise ConfigError(f"guard must implement tau_core.Guard, not {type(guard).__name__}")
    bus = EventBus()
    approver = TuiApprover(approve_delay=approve_delay)
    tool_list = list(tools) if tools is not None else None
    role_pinned = role is not None
    default_role = role or stored_role(session_store, session_id, config) or DEFAULT_ROLE
    current: dict[str, Config] = {"config": config}

    def agent_factory(
        target: str | None,
        *,
        role: str | None = None,
        seed_messages: list | None = None,
        config: Config | None = None,
        guard: Any = DISCOVER,
    ) -> TauAgent:
        if config is not None:
            current["config"] = config.with_overrides(profile=profile) if profile else config
        return build_agent(
            config=current["config"],
            role=role or default_role,
            model=model,
            tools=tool_list,
            approver=approver,
            session_id=target,
            session_store=session_store,
            events=bus,
            channel="tui",
            clock=clock,
            seed_messages=seed_messages,
            guard=guard,
        )

    missing: MissingCredentials | None = None
    unsupported: ProviderNotSupported | None = None
    agent: TauAgent | None = None
    try:
        if guard is None:  # with a guard the first agent waits for the first unlock
            agent = agent_factory(session_id)
    except MissingCredentials as exc:
        logger.warning("opening without an agent: %s", exc)
        agent, missing = None, exc
    except ProviderNotSupported as exc:
        logger.warning("opening without an agent: %s", exc)
        agent, unsupported = None, exc
    return TauApp(
        agent,
        config=current["config"],
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
        role_pinned=role_pinned,
        role=default_role,
        session_id=session_id,
        missing_credentials=missing,
        unsupported_provider=unsupported,
        show_paths=show_paths,
        version=version,
        guard=guard,
    )
