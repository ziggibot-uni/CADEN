"""Textual application root."""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header

from ..config import BOOTSTRAP_COMPLETION_POLL_SECONDS, log_bootstrap_use
from ..errors import CadenError
from ..google_sync.poll import poll_once
from .add_task import AddTaskScreen
from .dashboard import Dashboard
from .services import Services


class CadenApp(App):
    CSS = """
    Screen { background: $surface; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("a", "add_task", "Add task"),
        ("r", "refresh", "Refresh panels"),
    ]

    def __init__(self, services: Services) -> None:
        super().__init__()
        self.services = services

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Dashboard(self.services)
        yield Footer()

    def on_mount(self) -> None:
        # Completion polling runs only when Google Tasks is wired up.
        # Cadence is a bootstrap value (gate, not a rule).
        if self.services.tasks is not None:
            log_bootstrap_use(
                self.services.conn,
                "BOOTSTRAP_COMPLETION_POLL_SECONDS",
                BOOTSTRAP_COMPLETION_POLL_SECONDS,
            )
            self.set_interval(
                BOOTSTRAP_COMPLETION_POLL_SECONDS,
                self._poll_completions,
                name="completion-poll",
            )

    async def _poll_completions(self) -> None:
        try:
            finalised = await asyncio.to_thread(
                poll_once,
                self.services.conn,
                self.services.tasks,
                self.services.calendar,
            )
        except CadenError as e:
            # Loud failure: surface in the dashboard's status area. Do not
            # silently swallow; spec forbids it.
            self.bell()
            self.notify(f"completion poll failed: {e}", severity="error")
            return
        if finalised:
            self.notify(
                f"{len(finalised)} task(s) completed; residuals stored.",
                severity="information",
            )
            self.run_worker(self._dashboard().refresh_panels(), group="refresh-panels")

    async def action_add_task(self) -> None:
        def _on_close(submitted: bool | None) -> None:
            if submitted:
                self.run_worker(self._dashboard().refresh_panels(), group="refresh-panels")

        self.push_screen(AddTaskScreen(self.services), _on_close)

    def action_refresh(self) -> None:
        self.run_worker(self._dashboard().refresh_panels(), group="refresh-panels")

    def on_button_pressed(self, event) -> None:
        if event.button.id == "add-task":
            self.run_action("add_task")

    def _dashboard(self) -> Dashboard:
        return self.query_one(Dashboard)
