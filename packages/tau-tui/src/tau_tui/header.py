"""The one-row header: the animated ``τ``, ``tau  profile · session`` and the context label.

With an owner guard active the context label starts with the lock glyph, and with the camera
glyph while a guard attempt (a step-up or a recheck) runs; without a guard nothing changes."""

from __future__ import annotations

from rich.text import Text
from tau_core import t
from textual import events
from textual.containers import HorizontalGroup
from textual.widgets import Static

from tau_tui.brand import TauGlyph
from tau_tui.theme import glyph


class HeaderBar(HorizontalGroup):
    DEFAULT_CSS = """
    HeaderBar { height: 1; padding: 0 1; background: $panel; color: $text-muted; }
    HeaderBar #glyph { width: 2; }
    HeaderBar #title { width: 1fr; text-wrap: nowrap; text-overflow: ellipsis; }
    HeaderBar #context { width: auto; dock: right; }
    """

    def __init__(
        self,
        *,
        profile: str,
        session_id: str,
        role: str,
        provider: str,
        tool_count: int,
        language: str = "en",
        motion: bool = True,
        id: str | None = "header",
    ) -> None:
        super().__init__(id=id)
        self.profile = profile
        self.session_id = session_id
        self.role = role
        self.provider = provider
        self.tool_count = tool_count
        self.language = language
        self.motion = motion
        self.events_view = False
        self.guard_active = False
        self.attempt = False

    def compose(self):
        yield TauGlyph(motion=self.motion, id="glyph")
        yield Static("", id="title", markup=False)
        yield Static("", id="context", markup=False)

    @property
    def glyph(self) -> TauGlyph:
        return self.query_one("#glyph", TauGlyph)

    def on_mount(self) -> None:
        self.refresh_text()

    def on_resize(self, event: events.Resize) -> None:
        self.refresh_text()

    def _band(self) -> str:
        try:
            screen = self.screen
        except Exception:
            return "narrow"
        for band in ("ultra", "wide", "phone"):
            if screen.has_class(f"-{band}"):
                return band
        return "narrow"

    def title_text(self) -> Text:
        if self._band() == "phone":
            return Text.assemble(("tau", "bold"), f" · {self.profile}")
        return Text.assemble(("tau", "bold"), f"  {self.profile} · {self.session_id}")

    def guard_marks(self) -> str:
        """``⚿ `` with a guard active, ``⚿ ◉ `` while an attempt runs, else nothing."""
        if not self.guard_active:
            return ""
        marks = [glyph("lock")] + ([glyph("camera")] if self.attempt else [])
        return " ".join(marks) + " "

    def context_text(self) -> Text:
        band = self._band()
        marks = self.guard_marks()
        if band in ("phone", "narrow") and self.events_view:
            return Text(marks + t("tui.header.events", self.language))
        if band == "phone":
            return Text(marks + self.language)
        if band == "narrow":
            return Text(f"{marks}{self.role} · {self.language}")
        if band == "wide":
            return Text(f"{marks}{self.role} · {self.tool_count} tools · {self.language}")
        return Text(
            f"{marks}{self.role} → {self.provider} · {self.tool_count} tools · {self.language}"
        )

    def refresh_text(self) -> None:
        if not self.is_mounted:
            return
        self.query_one("#title", Static).update(self.title_text())
        self.query_one("#context", Static).update(self.context_text())

    def set_session(self, session_id: str) -> None:
        self.session_id = session_id
        self.refresh_text()

    def set_profile(self, profile: str) -> None:
        """A settings save changed ``TAU_PROFILE`` (or ``--profile`` kept its override)."""
        self.profile = profile
        self.refresh_text()

    def set_events_view(self, active: bool) -> None:
        self.events_view = active
        self.refresh_text()

    def set_role(self, role: str, provider: str) -> None:
        """``/model``: the context label follows the role the agent now runs on."""
        self.role = role
        self.provider = provider
        self.refresh_text()

    def set_guard(self, active: bool, *, attempt: bool = False) -> None:
        """The owner guard's marks: active at all, and whether an attempt runs."""
        self.guard_active = active
        self.attempt = active and attempt
        self.refresh_text()

    def relabel(self, language: str) -> None:
        self.language = language
        self.refresh_text()

    @property
    def text(self) -> str:
        return f"{glyph('tau')} {self.title_text().plain}  {self.context_text().plain}"
