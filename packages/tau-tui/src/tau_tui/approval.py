"""Tier-2 approvals inside the TUI.

:class:`TuiApprover` is the channel's ``Approver``: ``decide`` pushes an :class:`ApprovalScreen`
and waits on a future the dialog resolves. Nothing is approved without a key press or a click;
a dialog closed any other way, an app that is not running or a cancelled wait all reject.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from rich.text import Text
from tau_core import ApprovalRequest, Decision
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

logger = logging.getLogger(__name__)

APPROVE_DELAY = 0.5
"""Seconds before ``e``/``Onayla`` work, so keys typed for the chat cannot approve by accident."""


def format_arguments(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments, ensure_ascii=False, indent=2, sort_keys=True, default=str)


class ApprovalScreen(ModalScreen[Decision]):
    """Tool, arguments and effect of one tier-2 call; ``e`` approves, ``h`` or Esc rejects."""

    DEFAULT_CSS = """
    ApprovalScreen {
        align: center middle;
    }
    ApprovalScreen > #dialog {
        width: 76;
        max-width: 100%;
        height: auto;
        max-height: 100%;
        padding: 0 1;
        border: heavy $warning;
        background: $surface;
    }
    ApprovalScreen #title {
        text-style: bold;
        color: $warning;
    }
    ApprovalScreen #arguments {
        height: auto;
        max-height: 8;
        padding-left: 2;
    }
    ApprovalScreen #hint {
        margin-top: 1;
        color: $text-muted;
    }
    ApprovalScreen #buttons {
        height: auto;
        align-horizontal: center;
    }
    ApprovalScreen #buttons Button {
        margin: 0 2;
    }
    """

    BINDINGS = [
        Binding("e", "approve", "Onayla", show=False),
        Binding("h", "reject", "Reddet", show=False),
        Binding("escape", "reject", "Reddet", show=False),
    ]

    def __init__(self, request: ApprovalRequest, *, approve_delay: float = APPROVE_DELAY) -> None:
        super().__init__()
        self.request = request
        self.approve_delay = approve_delay
        self.armed = approve_delay <= 0
        self._decided = False

    def compose(self) -> ComposeResult:
        request = self.request
        with Vertical(id="dialog"):
            yield Static(Text(f"⚠ Onay gerekiyor (tier {int(request.tier)})"), id="title")
            yield Static(Text.assemble(("Araç: ", "bold"), request.tool), id="tool")
            yield Static(Text("Argümanlar:", style="bold"))
            with VerticalScroll(id="arguments"):
                yield Static(Text(format_arguments(request.arguments)), id="arguments-json")
            yield Static(Text.assemble(("Etki: ", "bold"), request.effect or "—"), id="effect")
            yield Static(Text("Onaylıyor musunuz? e: onayla · h veya Esc: reddet"), id="hint")
            with Horizontal(id="buttons"):
                yield Button("Onayla", variant="success", id="approve", disabled=not self.armed)
                yield Button("Reddet", variant="error", id="reject")

    def on_mount(self) -> None:
        self.query_one("#reject", Button).focus()  # Enter rejects
        if not self.armed:
            self.set_timer(self.approve_delay, self._arm)

    def _arm(self) -> None:
        self.armed = True
        self.query_one("#approve", Button).disabled = False

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


class TuiApprover:
    """Approver for the TUI channel. Attach it to the running app before the first turn."""

    name = "tui"

    def __init__(self, app: App[Any] | None = None, *, approve_delay: float = APPROVE_DELAY):
        self.app = app
        self.approve_delay = approve_delay
        self.pending: ApprovalRequest | None = None

    def attach(self, app: App[Any]) -> None:
        self.app = app

    async def decide(self, request: ApprovalRequest) -> Decision:
        app = self.app
        if app is None or not app.is_running:
            logger.warning("no running TUI to ask about %s; rejecting", request.tool)
            return Decision.REJECTED
        future: asyncio.Future[Decision] = asyncio.get_running_loop().create_future()

        def resolve(result: Decision | None) -> None:
            if not future.done():
                future.set_result(
                    Decision.APPROVED if result == Decision.APPROVED else Decision.REJECTED
                )

        screen = ApprovalScreen(request, approve_delay=self.approve_delay)
        self.pending = request
        try:
            app.push_screen(screen, callback=resolve)
            return await future
        except asyncio.CancelledError:
            # A timeout or shutdown: take the dialog down so it cannot approve later.
            if screen.is_attached and app.screen is screen:
                screen.action_reject()
            raise
        finally:
            self.pending = None
