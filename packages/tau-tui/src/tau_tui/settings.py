"""The settings screen: edit ``tau.toml`` and ``.env`` without leaving the TUI.

``/settings`` (``/ayarlar``) or F10 opens :class:`SettingsScreen`, a keyboard-only modal in
the same family as the approval dialog and the session picker: a list of sections on the left
(Model roles · Credentials · Interface · Agent · Doctor · Files) and the section's form on the
right. Nothing touches a file until ``ctrl+s`` / F2; every write goes through
:mod:`tau_core.settings`, so comments in ``tau.toml`` survive and ``.env`` stays private.

A credential typed here lives only in a password ``Input`` until it is saved; it is never put
into a ``Static``, a notice, a log line or the ``text`` oracle. After the save the row shows
the masked form (``sk-…abcd``) that ``tau_core.settings.mask`` produces.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.text import Text
from tau_core import LANGUAGES, Config, ConfigError, t
from tau_core.builder import Check, run_doctor
from tau_core.config import CONTEXT_MODES, RoleConfig
from tau_core.models import PLANNED_PROVIDERS
from tau_core.settings import (
    KEEP,
    clear_credential,
    credential_names_for,
    credential_source,
    credential_status,
    describe_home,
    is_secret_name,
    known_env_names,
    known_providers,
    load_document,
    masked_credential,
    roles_in,
    save_document,
    set_agent_option,
    set_credential,
    set_role,
    set_ui_language,
    status_text,
    tilde_path,
    validate,
)
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, ContentSwitcher, Input, OptionList, Select, Static
from textual.widgets.option_list import Option

from tau_tui.theme import glyph, mark_ascii

logger = logging.getLogger(__name__)

SECTIONS: tuple[str, ...] = ("roles", "credentials", "interface", "agent", "doctor", "files")
"""Section ids, in the order the list shows them."""
SECTIONS_WIDTH = 18
"""The section list's width from 60 columns on; also the cap for the phone band."""
SECTIONS_WIDTH_PHONE = 12
"""The section list's width below 60 columns, widened to fit the longest label (cap 18)."""
SECTIONS_CHROME = 2
"""Columns the list spends beside its labels: ``padding-right: 1`` and the right border."""
PROFILE_VAR = "TAU_PROFILE"
DOCTOR_GLYPHS = {"ok": "ok", "warn": "attention", "fail": "fail", "info": "notice"}
"""Doctor status → :func:`tau_tui.theme.glyph` name."""


@dataclass(frozen=True)
class RoleDraft:
    """What the Model roles form holds for one role."""

    provider: str
    model_id: str
    max_tokens: int | None
    fallback: tuple[str, str] | None


@dataclass
class SettingsOutcome:
    """What a saved settings screen hands back to the app through :attr:`SettingsScreen.outcome`.

    ``config`` is the freshly validated ``Config`` (``None`` when the saved files no longer
    load; ``error`` then says why), ``language`` the UI language to apply, ``reload`` whether
    the agent must be rebuilt (a role, an agent option, a credential or the profile changed).
    """

    config: Config | None
    language: str
    reload: bool
    error: str | None = None
    changed: list[str] = field(default_factory=list)


def _int_or_none(raw: str, field_name: str, language: str) -> int | None:
    text = raw.strip().replace("_", "")
    if not text:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise ConfigError(t("tui.settings.number_expected", language, field=field_name)) from exc


class _Row(Horizontal):
    """One ``label  widget`` row of a form. The label column fits the longest label of either
    language (``token budget`` / ``token sınırı``: 12) so no label is ever clipped."""

    DEFAULT_CSS = """
    _Row { height: 1; }
    _Row > .label { width: 13; color: $text-muted; }
    _Row > Input { width: 1fr; }
    _Row > Select { width: 1fr; }
    _Row > Button { width: auto; margin-left: 1; }
    SettingsScreen.-phone _Row > .label { width: 12; }
    """

    def __init__(self, label: str, *widgets: Any, classes: str | None = None) -> None:
        super().__init__(classes=classes)
        self._label = label
        self._widgets = widgets

    def compose(self) -> ComposeResult:
        if self._label:
            yield Static(Text(self._label), classes="label", markup=False)
        yield from self._widgets


class SettingsScreen(ModalScreen[bool]):
    """Sections on the left, the form on the right; ``ctrl+s`` / F2 saves, Esc closes.

    ``missing`` names credentials to highlight (the start-up path without credentials opens
    the Credentials section with them); ``env`` replaces the process environment for the
    credential status (tests); ``show_paths=False`` prints ``<home>/…`` instead of real paths
    (snapshots).
    """

    DEFAULT_CSS = """
    SettingsScreen { align: center middle; }
    SettingsScreen #dialog {
        width: 78; max-width: 100%; height: 1fr; margin-top: 1; padding: 0 1;
        border: round $accent; background: $panel;
    }
    SettingsScreen.-phone #dialog { width: 100%; }
    SettingsScreen #title { height: 1; text-style: bold; color: $accent; }
    SettingsScreen #body { height: 1fr; margin-top: 1; }
    SettingsScreen #sections {
        width: 18; height: 100%; background: $panel; border-right: solid $primary 35%;
        padding-right: 1; scrollbar-size-vertical: 1;
    }
    SettingsScreen.-phone #sections { width: 12; }
    SettingsScreen #sections > .option-list--option-highlighted {
        color: $block-cursor-foreground; background: $block-cursor-background;
    }
    SettingsScreen #pane { width: 1fr; height: 100%; padding-left: 1; }
    SettingsScreen .section { height: 100%; background: $panel; scrollbar-size-vertical: 1; }
    SettingsScreen .heading { height: 1; text-style: bold; color: $accent; margin-top: 1; }
    SettingsScreen .heading.-first { margin-top: 0; }
    SettingsScreen .note { color: $text-muted; height: auto; }
    SettingsScreen .status-line { color: $text-muted; height: auto; }
    SettingsScreen .cred-name { height: 1; margin-top: 1; }
    SettingsScreen .cred-name.-first { margin-top: 0; }
    SettingsScreen .cred-name.-missing { color: $accent; text-style: bold; }
    SettingsScreen .cred-state { color: $text-muted; height: auto; }
    SettingsScreen Input { background: $surface; }
    SettingsScreen Select { background: $surface; }
    SettingsScreen Select > SelectCurrent { background: $surface; }
    SettingsScreen Button { min-width: 7; }
    SettingsScreen #status {
        height: auto; min-height: 1; max-height: 3; margin-top: 1; color: $error;
    }
    SettingsScreen #hint { height: 1; color: $text-muted; }
    SettingsScreen .doctor-line { height: auto; }
    SettingsScreen .file-row { height: auto; }
    """

    BINDINGS = [
        Binding("escape", "close", show=False),
        Binding("ctrl+s", "save", show=False, priority=True),
        Binding("f2", "save", show=False, priority=True),
    ]

    def __init__(
        self,
        config: Config,
        *,
        language: str = "en",
        section: str = "roles",
        missing: list[str] | None = None,
        env: Mapping[str, str] | None = None,
        show_paths: bool = True,
    ) -> None:
        super().__init__()
        self.config = config
        self.home: Path = config.home
        self.language = language
        self.section = section if section in SECTIONS else SECTIONS[0]
        self.missing = list(missing or [])
        self.env = env
        self.show_paths = show_paths
        self.outcome: SettingsOutcome | None = None
        self._doc = load_document(self.home)
        self._roles: list[str] = roles_in(self._doc)
        self._initial: dict[str, Any] = {}
        self._cleared: set[str] = set()
        self._doctor_started = False

    # -- compose -------------------------------------------------------------------------------

    def _t(self, key: str, **kwargs: object) -> str:
        return t(key, self.language, **kwargs)

    def _provider_options(self, current: str | None) -> list[tuple[str, str]]:
        """The available providers only. A planned one (``ollama`` until issue 012) is never
        offered — saving it would stop the next start — but a role that already sits on one
        keeps it as its current value, labelled as planned, so the form can be left alone."""
        providers = dict(known_providers())
        options = [(name, name) for name, planned in providers.items() if not planned]
        if current and all(value != current for _, value in options):
            planned = providers.get(current, False)
            label = self._t("tui.settings.planned", provider=current) if planned else current
            options.append((label, current))
        return options

    def _planned_note(self) -> str:
        names = [name for name, planned in known_providers() if planned]
        if not names:
            return ""
        listed = ", ".join(f"{name} (issue {PLANNED_PROVIDERS.get(name, '?')})" for name in names)
        return self._t("tui.settings.planned_note", providers=listed)

    def _role_table(self, role: str) -> Any:
        return self._doc["models"]["roles"][role]

    def _compose_roles(self) -> ComposeResult:
        for n, role in enumerate(self._roles):
            table = self._role_table(role)
            provider = str(table.get("provider", ""))
            model_id = str(table.get("model_id", ""))
            max_tokens = table.get("max_tokens")
            fallback = table.get("fallback")
            fb_provider = str(fallback.get("provider", "")) if fallback is not None else None
            fb_model = str(fallback.get("model_id", "")) if fallback is not None else ""
            self._initial[f"role:{role}"] = RoleDraft(
                provider,
                model_id,
                int(max_tokens) if isinstance(max_tokens, int) else None,
                (fb_provider, fb_model) if fb_provider else None,
            )
            yield Static(
                Text(role), classes="heading" + (" -first" if n == 0 else ""), markup=False
            )
            yield _Row(
                self._t("tui.settings.provider"),
                Select(
                    self._provider_options(provider),
                    value=provider,
                    allow_blank=False,
                    compact=True,
                    id=f"provider-{role}",
                ),
            )
            yield _Row(
                self._t("tui.settings.model_id"),
                Input(model_id, compact=True, id=f"model-{role}"),
            )
            yield _Row(
                self._t("tui.settings.max_tokens"),
                Input(
                    str(max_tokens) if isinstance(max_tokens, int) else "",
                    compact=True,
                    type="integer",
                    id=f"tokens-{role}",
                ),
            )
            yield _Row(
                self._t("tui.settings.fallback"),
                Select(
                    self._provider_options(fb_provider),
                    value=fb_provider if fb_provider else Select.NULL,
                    prompt=self._t("tui.settings.no_fallback"),
                    allow_blank=True,
                    compact=True,
                    id=f"fbprovider-{role}",
                ),
            )
            yield _Row(
                self._t("tui.settings.fallback_model"),
                Input(fb_model, compact=True, id=f"fbmodel-{role}"),
            )
            yield Static(self._role_status_text(role), classes="status-line", id=f"status-{role}")
        note = self._planned_note()
        if note:
            yield Static(Text(note), classes="note -planned", id="planned-note", markup=False)

    def _role_status_text(self, role: str) -> Text:
        role_cfg = self.config.roles.get(role)
        if role_cfg is None:
            return Text("")
        status = credential_status(self.home, role_cfg, self.env)
        mark = {"ok": "ok", "none": "ok", "fallback": "attention", "missing": "fail"}.get(
            status.state, "fail"
        )
        return Text(f"{glyph(mark)} {status_text(status, self.language)}")

    def _needed_by(self) -> dict[str, list[str]]:
        needed: dict[str, list[str]] = {}
        for role, role_cfg in self.config.roles.items():
            for cfg in (role_cfg, role_cfg.fallback):
                if cfg is None:
                    continue
                for alternative in credential_names_for(cfg.provider):
                    for name in alternative:
                        roles = needed.setdefault(name, [])
                        if role not in roles:
                            roles.append(role)
        return needed

    def _credential_state(self, name: str) -> Text:
        if name in self._cleared:
            return Text(self._t("tui.settings.will_clear"))
        masked = masked_credential(self.home, name, self.env)
        if not masked:
            return Text(self._t("tui.settings.not_set"))
        state = self._t("tui.settings.set", masked=masked)
        if credential_source(self.home, name, self.env) == "environment":
            # ``Config.load`` never lets ``.env`` override a variable the shell already set.
            state += f" {self._t('tui.settings.from_environment')}"
        return Text(state)

    def _compose_credentials(self) -> ComposeResult:
        needed = self._needed_by()
        names = known_env_names(self.home)
        for name in self.missing:
            if name not in names:
                names.insert(0, name)
        for n, name in enumerate(names):
            missing = name in self.missing
            head = Text(name)
            if missing:
                head.append(f"  {glyph('attention')} {self._t('tui.settings.needed')}")
            elif name in needed:
                head.append(
                    f"  · {self._t('tui.settings.needed_by', roles=', '.join(needed[name]))}"
                )
            classes = "cred-name" + (" -first" if n == 0 else "") + (" -missing" if missing else "")
            yield Static(head, classes=classes, markup=False, id=f"credname-{name}")
            yield Static(self._credential_state(name), classes="cred-state", id=f"credstate-{name}")
            secret = is_secret_name(name)
            yield _Row(
                "",
                Input(
                    "",
                    password=secret,
                    compact=True,
                    placeholder=self._t(
                        "tui.settings.new_value" if secret else "tui.settings.new_value_plain"
                    ),
                    id=f"cred-{name}",
                ),
                Button(self._t("tui.settings.clear"), compact=True, id=f"clear-{name}"),
                classes="cred-row",
            )

    def _compose_interface(self) -> ComposeResult:
        ui = self._doc.get("ui")
        language = str(ui.get("language", "en")) if ui is not None else "en"
        self._initial["language"] = language
        self._initial["profile"] = self.config.profile
        yield _Row(
            self._t("tui.settings.language"),
            Select(
                [(name, name) for name in LANGUAGES],
                value=language if language in LANGUAGES else LANGUAGES[0],
                allow_blank=False,
                compact=True,
                id="language",
            ),
        )
        yield _Row(
            self._t("tui.settings.profile"),
            Input(self.config.profile, compact=True, id="profile"),
        )
        yield Static(Text(self._t("tui.settings.profile_note")), classes="note", markup=False)

    def _compose_agent(self) -> ComposeResult:
        agent = self.config.agent
        self._initial["agent"] = (
            agent.context,
            agent.window_size,
            agent.max_turns,
            agent.max_total_tokens,
        )
        yield _Row(
            self._t("tui.settings.context"),
            Select(
                [(mode, mode) for mode in CONTEXT_MODES],
                value=agent.context,
                allow_blank=False,
                compact=True,
                id="context",
            ),
        )
        yield _Row(
            self._t("tui.settings.window_size"),
            Input(str(agent.window_size), compact=True, type="integer", id="window_size"),
        )
        yield _Row(
            self._t("tui.settings.max_turns"),
            Input(str(agent.max_turns), compact=True, type="integer", id="max_turns"),
        )
        yield _Row(
            self._t("tui.settings.max_total_tokens"),
            Input(
                str(agent.max_total_tokens) if agent.max_total_tokens is not None else "",
                compact=True,
                type="integer",
                id="max_total_tokens",
            ),
        )
        yield Static(Text(self._t("tui.settings.agent_note")), classes="note", markup=False)

    def _compose_doctor(self) -> ComposeResult:
        yield Static(Text(self._t("tui.settings.doctor_running")), id="doctor-lines", markup=False)

    def _compose_files(self) -> ComposeResult:
        files = describe_home(self.home)
        for label, path, exists in files.rows():
            shown = tilde_path(path) if self.show_paths else f"<home>/{label}"
            state = t("settings.file_present" if exists else "settings.file_missing", self.language)
            mark = glyph("ok") if exists else glyph("fail")
            yield Static(
                Text(f"{mark} {label}: {shown} · {state}"), classes="file-row", markup=False
            )
        yield Static(Text(self._t("tui.settings.files_hint")), classes="note", markup=False)

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(
                Text(f"{glyph('attention')} {self._t('tui.settings.title')}"),
                id="title",
                markup=False,
            )
            with Horizontal(id="body"):
                yield OptionList(
                    *[
                        Option(self._t(f"tui.settings.section.{name}"), id=name)
                        for name in SECTIONS
                    ],
                    id="sections",
                    compact=True,
                )
                with ContentSwitcher(id="pane", initial=f"sec-{self.section}"):
                    with VerticalScroll(id="sec-roles", classes="section", can_focus=False):
                        yield from self._compose_roles()
                    with VerticalScroll(id="sec-credentials", classes="section", can_focus=False):
                        yield from self._compose_credentials()
                    with VerticalScroll(id="sec-interface", classes="section", can_focus=False):
                        yield from self._compose_interface()
                    with VerticalScroll(id="sec-agent", classes="section", can_focus=False):
                        yield from self._compose_agent()
                    with VerticalScroll(id="sec-doctor", classes="section", can_focus=False):
                        yield from self._compose_doctor()
                    with VerticalScroll(id="sec-files", classes="section", can_focus=False):
                        yield from self._compose_files()
            yield Static(Text(""), id="status", markup=False)
            yield Static(Text(self._t("tui.settings.hint")), id="hint", markup=False)

    # -- mount and navigation ---------------------------------------------------------------------

    @property
    def sections(self) -> OptionList:
        return self.query_one("#sections", OptionList)

    @property
    def pane(self) -> ContentSwitcher:
        return self.query_one("#pane", ContentSwitcher)

    @property
    def current(self) -> str:
        current = self.pane.current or f"sec-{SECTIONS[0]}"
        return current.removeprefix("sec-")

    @property
    def scroll_target(self) -> VerticalScroll:
        """What the app's PageUp/PageDown scroll while this screen is on top."""
        return self.query_one(f"#sec-{self.current}", VerticalScroll)

    def _sections_width(self) -> int:
        """Wide enough for the longest section label in the UI language (``Credentials``,
        ``Kimlikler``), never narrower than the band's default nor wider than 18."""
        longest = max(len(self._t(f"tui.settings.section.{name}")) for name in SECTIONS)
        base = SECTIONS_WIDTH_PHONE if self.has_class("-phone") else SECTIONS_WIDTH
        return min(max(longest + SECTIONS_CHROME, base), SECTIONS_WIDTH)

    def _fit_sections(self) -> None:
        self.sections.styles.width = self._sections_width()

    def on_mount(self) -> None:
        mark_ascii(self)
        self._fit_sections()
        listing = self.sections
        listing.highlighted = SECTIONS.index(self.section)
        if self.section == "doctor":
            self._start_doctor()
        if self.missing:
            for name in self.missing:
                try:
                    self.query_one(f"#cred-{name}", Input).focus()
                    return
                except Exception:
                    continue
        listing.focus()

    def show_section(self, name: str) -> None:
        """Switch the right pane to ``name`` (one of :data:`SECTIONS`)."""
        if name not in SECTIONS:
            return
        self.pane.current = f"sec-{name}"
        if name == "doctor":
            self._start_doctor()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        event.stop()
        if event.option_id:
            self.show_section(event.option_id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if event.option_id:
            self.show_section(event.option_id)
            self.focus_form()

    def focus_form(self) -> None:
        """Move the focus to the first field of the current section (Enter on a section)."""
        section = self.query_one(f"#sec-{self.current}", VerticalScroll)
        for widget in section.query("Input, Select, Button"):
            if widget.focusable:
                widget.focus()
                return

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = event.button.id or ""
        if not button_id.startswith("clear-"):
            return
        name = button_id.removeprefix("clear-")
        if name in self._cleared:
            self._cleared.discard(name)
            event.button.label = self._t("tui.settings.clear")
        else:
            self._cleared.add(name)
            event.button.label = self._t("tui.settings.keep")
            self.query_one(f"#cred-{name}", Input).value = ""
        self.query_one(f"#credstate-{name}", Static).update(self._credential_state(name))

    def _start_doctor(self) -> None:
        if self._doctor_started:
            return
        self._doctor_started = True
        self.run_worker(self._run_doctor(), group="doctor", exclusive=True, exit_on_error=False)

    async def _run_doctor(self) -> None:
        try:
            checks = await asyncio.to_thread(run_doctor, self.home, env=self.env)
        except Exception as exc:  # a check must never take the screen down
            logger.exception("doctor failed inside the settings screen")
            checks = [Check("doctor", "fail", f"{type(exc).__name__}: {exc}")]
        home = str(self.home)
        lines = []
        for check in checks:
            detail = check.detail if self.show_paths else check.detail.replace(home, "<home>")
            lines.append(
                f"{glyph(DOCTOR_GLYPHS.get(check.status, 'bullet'))} {check.name}: {detail}"
            )
        counts = {s: sum(1 for c in checks if c.status == s) for s in ("ok", "warn", "fail")}
        lines.append(
            self._t(
                "tui.settings.doctor_summary",
                n=len(checks),
                ok=counts["ok"],
                warn=counts["warn"],
                fail=counts["fail"],
            )
        )
        if self.is_attached:
            self.query_one("#doctor-lines", Static).update(Text("\n".join(lines)))

    def set_status(self, text: str) -> None:
        self.query_one("#status", Static).update(Text(text))

    def _hint_text(self) -> Text:
        key = "tui.settings.hint_phone" if self.has_class("-phone") else "tui.settings.hint"
        return Text(self._t(key))

    def on_resize(self, event: events.Resize) -> None:
        if self.is_attached:
            self._fit_sections()
            self.query_one("#hint", Static).update(self._hint_text())

    # -- save ---------------------------------------------------------------------------------

    def _read_roles(self) -> dict[str, RoleDraft]:
        drafts: dict[str, RoleDraft] = {}
        for role in self._roles:
            provider = self.query_one(f"#provider-{role}", Select).value
            model_id = self.query_one(f"#model-{role}", Input).value.strip()
            max_tokens = _int_or_none(
                self.query_one(f"#tokens-{role}", Input).value,
                f"{role} {self._t('tui.settings.max_tokens')}",
                self.language,
            )
            fb_provider = self.query_one(f"#fbprovider-{role}", Select).value
            fb_model = self.query_one(f"#fbmodel-{role}", Input).value.strip()
            fallback: tuple[str, str] | None = None
            if fb_provider is not Select.NULL and fb_provider:
                if not fb_model:
                    raise ConfigError(self._t("tui.settings.fallback_needs_model", role=role))
                fallback = (str(fb_provider), fb_model)
            drafts[role] = RoleDraft(str(provider), model_id, max_tokens, fallback)
        return drafts

    def _read_agent(self) -> tuple[str, int | None, int | None, int | None]:
        context = str(self.query_one("#context", Select).value)
        window = _int_or_none(
            self.query_one("#window_size", Input).value,
            self._t("tui.settings.window_size"),
            self.language,
        )
        turns = _int_or_none(
            self.query_one("#max_turns", Input).value,
            self._t("tui.settings.max_turns"),
            self.language,
        )
        budget = _int_or_none(
            self.query_one("#max_total_tokens", Input).value,
            self._t("tui.settings.max_total_tokens"),
            self.language,
        )
        return context, window, turns, budget

    def _credential_edits(self) -> tuple[dict[str, str], set[str]]:
        """``({name: new value}, {names to clear})`` from the Credentials form; a value is
        stripped of surrounding whitespace (a pasted key often carries a newline)."""
        new: dict[str, str] = {}
        for widget in self.query("#sec-credentials Input"):
            if not isinstance(widget, Input):
                continue
            name = (widget.id or "").removeprefix("cred-")
            value = widget.value.strip()
            if name and value and name not in self._cleared:
                new[name] = value
        return new, set(self._cleared)

    def action_save(self) -> None:
        """Write the changed values, validate the files, hand the outcome to the app."""
        language = self.language
        changed: list[str] = []
        try:
            roles = self._read_roles()
            context, window, turns, budget = self._read_agent()
            ui_language = str(self.query_one("#language", Select).value)
            profile = self.query_one("#profile", Input).value.strip()
            new_credentials, cleared = self._credential_edits()

            doc = load_document(self.home)
            for role, draft in roles.items():
                if draft != self._initial.get(f"role:{role}"):
                    set_role(
                        doc,
                        role,
                        draft.provider,
                        draft.model_id,
                        max_tokens=draft.max_tokens,
                        fallback=draft.fallback,
                    )
                    changed.append(f"role:{role}")
            if (context, window, turns, budget) != self._initial.get("agent"):
                set_agent_option(doc, "context", context)
                set_agent_option(doc, "window_size", window)
                set_agent_option(doc, "max_turns", turns)
                set_agent_option(doc, "max_total_tokens", budget)
                changed.append("agent")
            if ui_language != self._initial.get("language"):
                set_ui_language(doc, ui_language)
                changed.append("language")
            if any(item.startswith("role:") or item in ("agent", "language") for item in changed):
                save_document(self.home, doc)
            if profile != self._initial.get("profile"):
                if profile:
                    set_credential(self.home, PROFILE_VAR, profile, export=True)
                else:
                    clear_credential(self.home, PROFILE_VAR, export=True)
                changed.append("profile")
            for name, value in new_credentials.items():
                set_credential(self.home, name, value, export=True)
                changed.append(f"credential:{name}")
            for name in cleared:
                clear_credential(self.home, name, export=True)
                changed.append(f"credential:{name}")
        except (ConfigError, ValueError, OSError) as exc:
            self.set_status(t("settings.invalid", language, error=exc))
            return
        reload = any(item != "language" for item in changed)
        try:
            config = validate(self.home, env=self.env)
            error = None
        except ConfigError as exc:
            config, error = None, str(exc)
        self.outcome = SettingsOutcome(
            config=config, language=ui_language, reload=reload, error=error, changed=changed
        )
        self.dismiss(True)

    def action_close(self) -> None:
        if self.app.screen is self:
            self.dismiss(False)

    # -- oracles --------------------------------------------------------------------------------

    def relabel(self, language: str) -> None:
        self.language = language
        self._fit_sections()
        self.query_one("#hint", Static).update(self._hint_text())
        self.query_one("#title", Static).update(
            Text(f"{glyph('attention')} {self._t('tui.settings.title')}")
        )

    @property
    def text(self) -> str:
        """Every ``Static`` of the dialog that is on screen (never an ``Input`` value)."""
        parts = []
        for widget in self.query(Static):
            if not widget.display or any(not node.display for node in widget.ancestors):
                continue
            content = widget.content
            parts.append(getattr(content, "plain", str(content)))
        return "\n".join(parts)


def role_status_for(config: Config, role: str, env: Mapping[str, str] | None = None) -> str:
    """The one-line credential status of a role, as the Model roles section prints it."""
    role_cfg: RoleConfig | None = config.roles.get(role)
    if role_cfg is None:
        return ""
    return status_text(credential_status(config.home, role_cfg, env), config.ui.language)


__all__ = ["SECTIONS", "KEEP", "SettingsOutcome", "SettingsScreen", "role_status_for"]
