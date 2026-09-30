"""Tier-2 approvals inside the TUI.

:class:`TuiApprover` is the channel's ``Approver``: ``decide`` pushes an :class:`ApprovalScreen`
and waits on a future the dialog resolves. Nothing is approved without a key press or a click;
a dialog closed any other way, an app that is not running or a cancelled wait all reject.
Around the dialog it posts :class:`ApprovalPending` / :class:`ApprovalDone` to the app so the
transcript, the composer and the header can show the attention state. While the owner guard
has the app locked nothing is asked (``REJECTED`` at once), and a lock rejects the pending
dialog (:meth:`TuiApprover.reject_pending`).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from rich.text import Text
from tau_core import ApprovalRequest, Decision, t
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from tau_tui.theme import glyph, mark_ascii

logger = logging.getLogger(__name__)

APPROVE_DELAY = 0.5
"""Seconds before ``y``/``e``/Approve work: keys typed for the chat cannot approve by accident."""


class ApprovalPending(Message):
    """Posted to the app just before the dialog opens."""

    def __init__(self, request: ApprovalRequest) -> None:
        super().__init__()
        self.request = request


class ApprovalDone(Message):
    """Posted to the app once the decision is known."""

    def __init__(self, request: ApprovalRequest, decision: Decision) -> None:
        super().__init__()
        self.request = request
        self.decision = decision


def format_arguments(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _indent(text: str, by: int = 2) -> str:
    pad = " " * by
    return "\n".join(pad + line for line in text.splitlines())


class ApprovalScreen(ModalScreen[Decision]):
    """Tool, effect and arguments of one tier-2 call; ``y``/``e`` approve, ``n``/``h``/Esc reject.

    The keys work in both languages whatever the UI setting."""

    DEFAULT_CSS = """
    ApprovalScreen { align: center middle; }
    ApprovalScreen > #dialog {
        width: 58; max-width: 100%; height: auto; max-height: 100%; padding: 0 1;
        border: round $accent; background: $panel;
    }
    ApprovalScreen #title { text-style: bold; color: $accent; margin-bottom: 1; }
    ApprovalScreen #arguments { height: auto; max-height: 8; }
    ApprovalScreen #hint { margin-top: 1; color: $text-muted; }
    ApprovalScreen #buttons { height: auto; align-horizontal: center; margin-top: 1; }
    ApprovalScreen #buttons Button { margin: 0 4; }
    ApprovalScreen.-phone #dialog { width: 100%; }
    ApprovalScreen.-phone #buttons { layout: vertical; }
    """

    BINDINGS = [
        Binding("y", "approve", show=False),
        Binding("e", "approve", show=False),
        Binding("n", "reject", show=False),
        Binding("h", "reject", show=False),
        Binding("escape", "reject", show=False),
    ]

    def __init__(self, request: ApprovalRequest, *, approve_delay: float = APPROVE_DELAY) -> None:
        super().__init__()
        self.request = request
        self.approve_delay = approve_delay
        self.armed = approve_delay <= 0
        self._decided = False

    @property
    def language(self) -> str:
        return str(getattr(self.app, "language", "en"))

    def _hint(self) -> Text:
        hint = t("approval.hint", self.language)
        if not self.armed:
            first, sep, rest = hint.partition(" · ")
            hint = f"{first} (arming…){sep}{rest}" if sep else f"{hint} (arming…)"
        return Text(hint)

    def compose(self) -> ComposeResult:
        request, lang = self.request, self.language
        tier = int(request.tier)
        with Vertical(id="dialog"):
            title = t("approval.title", lang, tier=tier)
            yield Static(
                Text(f"{glyph('attention')} {title} · {t(f'tier.{tier}', lang)}"),
                id="title",
                markup=False,
            )
            yield Static(
                Text.assemble(f"{t('approval.tool', lang)}: ", (request.tool, "bold")),
                id="tool",
                markup=False,
            )
            yield Static(
                Text(f"{t('approval.effect', lang)}: {request.effect or '—'}"),
                id="effect",
                markup=False,
            )
            yield Static(Text(f"{t('approval.arguments', lang)}:"), markup=False)
            with VerticalScroll(id="arguments", can_focus=False):
                yield Static(
                    Text(_indent(format_arguments(request.arguments))),
                    id="arguments-json",
                    markup=False,
                )
            yield Static(self._hint(), id="hint", markup=False)
            with Horizontal(id="buttons"):
                yield Button(
                    t("approval.approve", lang),
                    variant="success",
                    id="approve",
                    compact=True,
                    disabled=not self.armed,
                )
                yield Button(t("approval.reject", lang), variant="error", id="reject", compact=True)

    @property
    def scroll_target(self) -> VerticalScroll:
        """What the app's PageUp/PageDown scroll while this dialog is on top."""
        return self.query_one("#arguments", VerticalScroll)

    def on_mount(self) -> None:
        mark_ascii(self)
        self.query_one("#reject", Button).focus()  # Enter rejects; Tab toggles the buttons
        if not self.armed:
            self.set_timer(self.approve_delay, self._arm)

    def _arm(self) -> None:
        self.armed = True
        self.query_one("#approve", Button).disabled = False
        self.query_one("#hint", Static).update(self._hint())

    def _decide(self, decision: Decision) -> None:
        if self._decided or self.app.screen is not self:
            return
        self._decided = True
        self.dismiss(decision)

    def action_approve(self) -> None:
        if self.armed:
            self._decide(Decision.APPROVED)

    def action_reject(self) -> None:
        self._decide(Decision.REJECTED)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "approve":
            self.action_approve()
        else:
            self.action_reject()

    @property
    def text(self) -> str:
        parts = []
        for widget in self.query(Static):
            content = widget.content
            parts.append(getattr(content, "plain", str(content)))
        return "\n".join(parts)


class TuiApprover:
    """Approver for the TUI channel. Attach it to the running app before the first turn."""

    name = "tui"

    def __init__(self, app: App[Any] | None = None, *, approve_delay: float = APPROVE_DELAY):
        self.app = app
        self.approve_delay = approve_delay
        self.pending: ApprovalRequest | None = None
        self._screen: ApprovalScreen | None = None
        self._future: asyncio.Future[Decision] | None = None

    def reject_pending(self) -> None:
        """Reject the open dialog now (the owner guard locked): dismissed as ``REJECTED`` when
        it is on top, else its wait ends ``REJECTED`` and the dialog can no longer decide."""
        future, screen, app = self._future, self._screen, self.app
        if future is None or future.done():
            return
        if screen is not None and app is not None and screen.is_attached and app.screen is screen:
            screen.action_reject()
        else:
            future.set_result(Decision.REJECTED)

    def attach(self, app: App[Any]) -> None:
        self.app = app

    async def decide(self, request: ApprovalRequest) -> Decision:
        app = self.app
        if app is None or not app.is_running:
            logger.warning("no running TUI to ask about %s; rejecting", request.tool)
            return Decision.REJECTED
        if getattr(app, "locked", False) is True:
            logger.info("tau is locked; rejecting %s without asking", request.tool)
            return Decision.REJECTED
        future: asyncio.Future[Decision] = asyncio.get_running_loop().create_future()

        def resolve(result: Decision | None) -> None:
            if not future.done():
                future.set_result(
                    Decision.APPROVED if result == Decision.APPROVED else Decision.REJECTED
                )

        screen = ApprovalScreen(request, approve_delay=self.approve_delay)
        self.pending = request
        self._screen, self._future = screen, future
        decision = Decision.REJECTED
        try:
            app.post_message(ApprovalPending(request))
            app.push_screen(screen, callback=resolve)
            decision = await future
            return decision
        except asyncio.CancelledError:
            # A timeout or shutdown: take the dialog down so it cannot approve later.
            if screen.is_attached and app.screen is screen:
                screen.action_reject()
            raise
        finally:
            self.pending = None
            self._screen = self._future = None
            app.post_message(ApprovalDone(request, decision))
