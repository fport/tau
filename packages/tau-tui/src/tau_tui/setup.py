"""First run inside the TUI: ``tau tui`` with no ``tau.toml`` anywhere opens :class:`SetupScreen`.

The screen asks for the home directory (default ``~/.tau``, editable), the provider for the
``brain`` and ``fast`` roles (detected from the environment and ``<home>/.env`` exactly like
``tau init``, with ``fake`` for a credential-free try) and the UI language, then **Create**
runs ``tau_core.builder.init_home`` — the same code as ``tau init`` — and the command continues
into the normal app on that home. A home that already holds a ``tau.toml`` is used as it is.

:func:`run_setup` runs the small :class:`SetupApp` and returns the :class:`SetupResult`, or
``None`` when the user left with Esc; ``tau_tui.cli`` then loads the config from the result.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from rich.text import Text
from tau_core import LANGUAGES, ConfigError, t
from tau_core.builder import PROVIDER_PREFERENCE, env_with_dotenv, init_home, pick_provider
from tau_core.config import CONFIG_FILE, DEFAULT_HOME, RoleConfig
from tau_core.i18n import DEFAULT_LANGUAGE
from tau_core.models import missing_credentials
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input, Select, Static

from tau_tui.theme import TAU_ANSI_THEME, TAU_THEME, glyph, mark_ascii

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SetupResult:
    """What the setup screen produced: the home to load and whether it was just created."""

    home: Path
    provider: str
    language: str
    created: bool


def provider_labels(
    env: Mapping[str, str], language: str = DEFAULT_LANGUAGE
) -> list[tuple[str, str]]:
    """``[(label, provider)]`` for the provider select: credentials found or not, per provider."""
    options: list[tuple[str, str]] = []
    for provider in PROVIDER_PREFERENCE:
        if provider == "fake":
            options.append((t("tui.setup.fake_note", language), provider))
            continue
        probe = RoleConfig(provider=provider, model_id="probe")
        key = (
            "tui.setup.no_credentials"
            if missing_credentials(probe, env)
            else "tui.setup.has_credentials"
        )
        options.append((t(key, language, provider=provider), provider))
    return options


class SetupScreen(ModalScreen[SetupResult | None]):
    """Home directory, provider and UI language; Enter, ``ctrl+s``, F2 or **Create** creates."""

    DEFAULT_CSS = """
    SetupScreen { align: center middle; }
    SetupScreen #dialog {
        width: 66; max-width: 100%; height: auto; max-height: 100%; padding: 0 1;
        border: round $accent; background: $panel;
    }
    SetupScreen.-phone #dialog { width: 100%; }
    SetupScreen #title { text-style: bold; color: $accent; margin-bottom: 1; }
    SetupScreen #intro { color: $text-muted; height: auto; margin-bottom: 1; }
    SetupScreen .row { height: 1; margin-bottom: 1; }
    SetupScreen .row > .label { width: 16; color: $text-muted; }
    SetupScreen .row > Input { width: 1fr; background: $surface; }
    SetupScreen .row > Select { width: 1fr; background: $surface; }
    SetupScreen .row > Select > SelectCurrent { background: $surface; }
    SetupScreen.-phone .row > .label { width: 12; }
    SetupScreen #buttons { height: auto; align-horizontal: center; }
    SetupScreen #status { height: auto; color: $error; margin-top: 1; }
    SetupScreen #hint { margin-top: 1; color: $text-muted; }
    """

    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("ctrl+s", "create", show=False, priority=True),
        Binding("f2", "create", show=False, priority=True),
    ]

    def __init__(
        self,
        *,
        default_home: str,
        env: Mapping[str, str] | None = None,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        super().__init__()
        self.default_home = default_home
        self.env: Mapping[str, str] = os.environ if env is None else env
        self.language = language if language in LANGUAGES else DEFAULT_LANGUAGE
        self._creating = False

    def _t(self, key: str, **kwargs: object) -> str:
        return t(key, self.language, **kwargs)

    def _home_path(self) -> Path:
        return Path(self.query_one("#home", Input).value.strip()).expanduser()

    def compose(self) -> ComposeResult:
        home = Path(self.default_home).expanduser()
        detected = pick_provider(env_with_dotenv(home, self.env))
        with Vertical(id="dialog"):
            yield Static(
                Text(f"{glyph('attention')} {self._t('tui.setup.title')}"), id="title", markup=False
            )
            yield Static(Text(self._t("tui.setup.intro")), id="intro", markup=False)
            with Horizontal(classes="row"):
                yield Static(Text(self._t("tui.setup.home")), classes="label", markup=False)
                yield Input(self.default_home, compact=True, id="home")
            with Horizontal(classes="row"):
                yield Static(Text(self._t("tui.setup.provider")), classes="label", markup=False)
                yield Select(
                    provider_labels(self.env, self.language),
                    value=detected,
                    allow_blank=False,
                    compact=True,
                    id="provider",
                )
            with Horizontal(classes="row"):
                yield Static(Text(self._t("tui.setup.language")), classes="label", markup=False)
                yield Select(
                    [(name, name) for name in LANGUAGES],
                    value=self.language,
                    allow_blank=False,
                    compact=True,
                    id="language",
                )
            with Horizontal(id="buttons"):
                yield Button(
                    self._t("tui.setup.create"), variant="success", id="create", compact=True
                )
            yield Static(Text(""), id="status", markup=False)
            yield Static(Text(self._t("tui.setup.hint")), id="hint", markup=False)

    def on_mount(self) -> None:
        mark_ascii(self)
        self.query_one("#home", Input).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        event.stop()
        if event.select.id == "language" and isinstance(event.value, str):
            self.relabel(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_create()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "create":
            self.action_create()

    def relabel(self, language: str) -> None:
        self.language = language
        self.query_one("#title", Static).update(
            Text(f"{glyph('attention')} {self._t('tui.setup.title')}")
        )
        self.query_one("#intro", Static).update(Text(self._t("tui.setup.intro")))
        for key, label in (("home", 0), ("provider", 1), ("language", 2)):
            self.query(".row .label")[label].update(Text(self._t(f"tui.setup.{key}")))
        self.query_one("#create", Button).label = self._t("tui.setup.create")
        self.query_one("#hint", Static).update(self._hint_text())
        provider = self.query_one("#provider", Select)
        current = provider.value
        provider.set_options(provider_labels(self.env, language))
        if isinstance(current, str):
            provider.value = current

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(Text(text))

    def _hint_text(self) -> Text:
        key = "tui.setup.hint_phone" if self.has_class("-phone") else "tui.setup.hint"
        return Text(self._t(key))

    def on_resize(self, event: events.Resize) -> None:
        if self.is_attached:
            self.query_one("#hint", Static).update(self._hint_text())

    def action_create(self) -> None:
        """``init_home`` on the typed home (or use it as it is when it already has a config)."""
        if self._creating:
            return
        raw = self.query_one("#home", Input).value.strip()
        if not raw:
            self.set_status(self._t("tui.setup.empty_home"))
            return
        home = self._home_path()
        provider = str(self.query_one("#provider", Select).value)
        language = str(self.query_one("#language", Select).value)
        self._creating = True
        try:
            if (home / CONFIG_FILE).is_file():
                self.dismiss(SetupResult(home.resolve(), provider, language, created=False))
                return
            result = init_home(home, provider=provider, language=language)
        except (FileExistsError, ConfigError, OSError) as exc:
            self._creating = False
            logger.warning("setup failed: %s", exc)
            self.set_status(self._t("tui.setup.failed", error=exc))
            return
        self.dismiss(SetupResult(result.home, provider, language, created=True))

    def action_close(self) -> None:
        if self.app.screen is self:
            self.dismiss(None)

    @property
    def text(self) -> str:
        parts = []
        for widget in self.query(Static):
            content = widget.content
            parts.append(getattr(content, "plain", str(content)))
        return "\n".join(parts)


class SetupApp(App[SetupResult | None]):
    """The tau theme and one modal: :class:`SetupScreen`. Exits with its result."""

    TITLE = "tau"
    ENABLE_COMMAND_PALETTE = False
    HORIZONTAL_BREAKPOINTS = [(0, "-phone"), (60, "-narrow"), (100, "-wide"), (140, "-ultra")]
    CSS = """
    Screen { background: $background; color: $foreground; }
    ModalScreen { background: $background 60%; }
    """

    def __init__(
        self,
        *,
        default_home: str | None = None,
        env: Mapping[str, str] | None = None,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        super().__init__()
        self.default_home = DEFAULT_HOME if default_home is None else default_home
        self.env = env
        self.language = language
        self.register_theme(TAU_THEME)
        self.register_theme(TAU_ANSI_THEME)
        self.theme = TAU_THEME.name

    def get_default_screen(self) -> Screen:
        return _Backdrop(id="_default")

    def on_mount(self) -> None:
        if self.ansi_color:
            self.theme = TAU_ANSI_THEME.name
        self.push_screen(
            SetupScreen(default_home=self.default_home, env=self.env, language=self.language),
            callback=self._done,
        )

    def _done(self, result: SetupResult | None) -> None:
        self.exit(result)


class _Backdrop(Screen[None]):
    def on_mount(self) -> None:
        mark_ascii(self)


def run_setup(
    *, default_home: str | None = None, env: Mapping[str, str] | None = None, language: str = "en"
) -> SetupResult | None:
    """Run the setup app in the terminal; ``None`` when the user quit without creating."""
    return SetupApp(default_home=default_home, env=env, language=language).run()


__all__ = ["SetupApp", "SetupResult", "SetupScreen", "provider_labels", "run_setup"]
