"""Dashboard: today | chat | next 7 days, with an add-task button.

When Google sync is configured, the side panels render real calendar events
and tasks. When it is not, they render a clear "(sync not configured)"
placeholder — which is spec-legal because boot didn't claim sync was live.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Static, Label

from .chat import ChatWidget
from .services import Services

from ..google_sync.poll import poll_once
from ..errors import CadenError


class TaskItem(Horizontal):
    DEFAULT_CSS = """
    TaskItem {
        height: auto;
        margin-bottom: 1;
    }
    TaskItem:hover {
        background: $boost;
    }
    TaskItem Label {
        width: 1fr;
        padding-right: 1;
    }
    TaskItem Button {
        min-width: 5;
        width: 5;
        height: 1;
        border: none;
    }
    """

    class EditRequested(Message):
        def __init__(self, item: TaskItem) -> None:
            self.item = item
            super().__init__()

    def __init__(self, text: str, google_event_id: str, google_task_id: str | None, summary: str, event_obj=None) -> None:
        super().__init__()
        self._text = text
        self._g_event_id = google_event_id
        self._g_task_id = google_task_id
        self._summary = summary
        self.event_obj = event_obj

    def compose(self) -> ComposeResult:
        yield Label(self._text)
        if self._g_task_id:
            yield Button("✔", id=f"complete_{self._g_task_id}", variant="success")
            
    def on_click(self) -> None:
        self.post_message(self.EditRequested(self))


class SidePanel(Vertical):
    DEFAULT_CSS = """
    SidePanel {
        width: 35;
        border: solid $accent;
        padding: 0 1;
    }
    SidePanel #title {
        height: 1;
        color: $accent;
        margin-bottom: 1;
    }
    SidePanel VerticalScroll {
        height: 1fr;
    }
    """

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title

    def compose(self) -> ComposeResult:
        yield Static(self._title, id="title")
        yield VerticalScroll(id="scroll")

    async def set_body_text(self, text: str) -> None:
        scroll = self.query_one("#scroll", VerticalScroll)
        await scroll.remove_children()
        await scroll.mount(Static(text))

    async def set_events(self, events, task_map: dict[str, str]) -> None:
        scroll = self.query_one("#scroll", VerticalScroll)
        await scroll.remove_children()
        if not events:
            await scroll.mount(Static("(nothing scheduled)"))
            return

        for e in events:
            local = e.start.astimezone()
            stamp = local.strftime("%a %-I:%M %p").lower()
            text = f"{stamp}  {e.summary}"
            g_task_id = task_map.get(e.id)
            await scroll.mount(TaskItem(text, e.id, g_task_id, e.summary, event_obj=e))


class Dashboard(Vertical):
    DEFAULT_CSS = """
    Dashboard {
        layout: vertical;
        height: 100%;
    }
    Dashboard #row {
        height: 1fr;
    }
    Dashboard ChatWidget {
        width: 1fr;
    }
    Dashboard #topbar {
        height: 3;
        padding: 1 1;
    }
    """

    def __init__(self, services: Services) -> None:
        super().__init__()
        self.services = services

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Button("+ add task", id="add-task", variant="primary")
        with Horizontal(id="row"):
            yield SidePanel("Today")
            yield ChatWidget(self.services)
            yield SidePanel("Next 7 days")

    def on_mount(self) -> None:
        self.run_worker(self.refresh_panels(), group="refresh-panels")

    async def refresh_panels(self) -> None:
        today_panel, week_panel = self._panels()
        if self.services.calendar is None:
            await today_panel.set_body_text("(Google sync not configured)")
            await week_panel.set_body_text("(Google sync not configured)")
            return
        now = datetime.now(timezone.utc)
        local_now = now.astimezone()
        if local_now.hour < 5:
            start_local = local_now.replace(hour=5, minute=0, second=0, microsecond=0) - timedelta(days=1)
            end_local = local_now.replace(hour=5, minute=0, second=0, microsecond=0)
        else:
            start_local = local_now.replace(hour=5, minute=0, second=0, microsecond=0)
            end_local = local_now.replace(
                hour=5, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
        start_today = start_local.astimezone(timezone.utc)
        end_today = end_local.astimezone(timezone.utc)
        end_week = start_today + timedelta(days=7)
        try:
            today = await asyncio.to_thread(self.services.calendar.list_window, start_today, end_today)
            week = await asyncio.to_thread(self.services.calendar.list_window, start_today, end_week)
        except Exception as e:
            await today_panel.set_body_text(f"error: {e}")
            await week_panel.set_body_text(f"error: {e}")
            return
        
        task_rows = self.services.conn.execute(
            "SELECT google_event_id, google_task_id FROM task_events "
            "JOIN tasks ON tasks.id = task_id "
            "WHERE tasks.status='open' AND google_task_id IS NOT NULL"
        ).fetchall()
        task_map = {r["google_event_id"]: r["google_task_id"] for r in task_rows}

        today_filtered = [e for e in today if e.end > now or e.id in task_map]
        week_filtered = [e for e in week if e.end > now or e.id in task_map]

        await today_panel.set_events(today_filtered, task_map)
        await week_panel.set_events(week_filtered, task_map)

    def _panels(self) -> tuple[SidePanel, SidePanel]:
        panels = list(self.query(SidePanel))
        return panels[0], panels[1]

    @on(TaskItem.EditRequested)
    def on_task_edit(self, event: TaskItem.EditRequested) -> None:
        def check(changed: bool) -> None:
            if changed:
                self.run_worker(self.refresh_panels(), group="refresh-panels")
        
        from .edit_task import EditTaskScreen
        self.app.push_screen(EditTaskScreen(
            self.services,
            event.item._g_task_id,
            event.item._g_event_id,
            event.item._summary,
            event.item.event_obj
        ), check)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if not button_id:
            return
        if button_id.startswith("complete_"):
            event.stop()
            g_task_id = button_id.replace("complete_", "", 1)
            event.button.disabled = True
            event.button.label = "…"
            self.run_worker(self._complete_task(g_task_id), group="complete-task")

    async def _complete_task(self, g_task_id: str) -> None:
        try:
            if self.services.tasks is not None:
                await asyncio.to_thread(self.services.tasks.mark_completed, g_task_id)
                # poll_once acts on completed Google Tasks + local open tasks,
                # edits the calendar event, and stores residuals
                finalised = await asyncio.to_thread(
                    poll_once, 
                    self.services.conn, 
                    self.services.tasks, 
                    self.services.calendar
                )
                if finalised:
                    self.app.notify(
                        f"{len(finalised)} task(s) completed; residuals stored.",
                        severity="information",
                    )
        except CadenError as e:
            self.app.bell()
            self.app.notify(f"task completion failed: {e}", severity="error")
            return
        await self.refresh_panels()
