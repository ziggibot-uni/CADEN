"""Textual application root."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import Footer, Static, TabbedContent, TabPane

from ..config import COMPLETION_POLL_SECONDS
from ..errors import CadenError
from ..google_sync.poll import poll_once
from ..util.timefmt import format_display_time
from .add_task import AddTaskScreen
from .dashboard import Dashboard
from .project_manager import ProjectManagerPane
from .services import Services
from .sprocket import SprocketPane
from .thought_dump import ThoughtDumpPane


class CadenApp(App):
    CSS = """
    Screen {
        background: #0f1115;
        color: white;
    }
    TabbedContent {
        height: 1fr;
    }
    TabPane {
        height: 1fr;
    }
    #dashboard {
        height: 1fr;
    }
    #app-header {
        height: 1;
        background: #13202b;
        color: white;
    }
    #app-title {
        width: 1fr;
        padding: 0 1;
        content-align: center middle;
        color: white;
    }
    #app-clock {
        width: 14;
        padding: 0 1;
        content-align: right middle;
        color: white;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("a", "add_task", "Add task"),
        ("r", "refresh", "Refresh panels"),
        ("p", "focus_project_manager", "Project Manager"),
        ("t", "focus_thought_dump", "Thought Dump"),
        ("s", "focus_sprocket", "Sprocket"),
    ]

    def __init__(self, services: Services) -> None:
        super().__init__()
        self.services = services

    def compose(self) -> ComposeResult:
        with Horizontal(id="app-header"):
            yield Static("CADEN", id="app-title")
            yield Static("", id="app-clock")
        with TabbedContent(initial="dashboard"):
            with TabPane("Dashboard", id="dashboard"):
                yield Dashboard(self.services)
            with TabPane("Project Manager", id="project-manager"):
                yield ProjectManagerPane(self.services)
            with TabPane("Thought Dump", id="thought-dump"):
                yield ThoughtDumpPane(self.services)
            with TabPane("Sprocket", id="sprocket"):
                yield SprocketPane(self.services)
        yield Footer()

    def on_mount(self) -> None:
        self._update_clock()
        self.set_interval(1, self._update_clock, name="ui-clock")
        # Completion polling runs only when Google Tasks is wired up.
        # The cadence is an operational detail, not learned behavior.
        if self.services.tasks is not None:
            self.set_interval(
                COMPLETION_POLL_SECONDS,
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
            # Loud failure: surface in the dashboard's status area, pop the modal
            # and freeze the completion poll subsystem per the "no silent fallbacks" rule
            from ._error import ErrorBanner
            self.bell()
            self.workers.cancel_group("completion-poll") # Halts future runs
            self.push_screen(ErrorBanner(exception=e, context="completion-poll"))
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

    def _update_clock(self) -> None:
        try:
            self.query_one("#app-clock", Static).update(
                format_display_time(
                    datetime.now(timezone.utc),
                    tz_name=self.services.config.display_tz,
                )
            )
        except NoMatches:
            # Timer callbacks may race with app teardown in test harnesses.
            return

    def action_focus_project_manager(self) -> None:
        self.query_one(TabbedContent).active = "project-manager"

    def action_focus_sprocket(self) -> None:
        self.query_one(TabbedContent).active = "sprocket"

    def action_focus_thought_dump(self) -> None:
        self.query_one(TabbedContent).active = "thought-dump"

    async def register_sprocket_app_tab(self, *, app_name: str, tab_id: str) -> bool:
        """Register a new Sprocket-created app as a sibling tab.

        Returns True when a new tab is created, False when the tab already exists.
        """
        tabs = self.query_one(TabbedContent)
        pane_exists = False
        try:
            pane_exists = tabs.get_pane(tab_id) is not None
        except NoMatches:
            pane_exists = False
        if pane_exists:
            return False
        pane = TabPane(app_name, id=tab_id)
        await tabs.add_pane(pane)
        await pane.mount(Static(f"{app_name} (created by Sprocket)"))
        return True
