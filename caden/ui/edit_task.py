"""Edit task modal: change title/summary."""

from __future__ import annotations

import asyncio
import dateparser
from datetime import timezone
from textual.app import ComposeResult
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from .services import Services
from ..errors import CadenError

class EditTaskScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    EditTaskScreen {
        align: center middle;
    }
    EditTaskScreen > Vertical {
        width: 70;
        height: auto;
        border: thick $accent;
        background: $panel;
        padding: 1 2;
    }
    EditTaskScreen Label { margin-top: 1; }
    EditTaskScreen #buttons { margin-top: 1; height: auto; }
    EditTaskScreen #status {
        margin-top: 1;
        color: $error;
    }
    """
    def __init__(self, services: Services, g_task_id: str | None, g_event_id: str, summary: str, event_obj=None) -> None:
        super().__init__()
        self.services = services
        self.g_task_id = g_task_id
        self.g_event_id = g_event_id
        self.summary = summary
        self.event_obj = event_obj

    def compose(self) -> ComposeResult:
        start_val = ""
        end_val = ""
        desc_val = ""
        if self.event_obj:
            start_val = self.event_obj.start.astimezone().strftime("%Y-%m-%d %H:%M")
            end_val = self.event_obj.end.astimezone().strftime("%Y-%m-%d %H:%M")
            desc_val = self.event_obj.raw.get("description", "")
            
        with Vertical():
            yield Static("Edit Event", classes="title")
            yield Label("Title")
            yield Input(value=self.summary, id="title")
            yield Label("Start Time (e.g. 'today 5pm' or '2026-04-24 17:00')")
            yield Input(value=start_val, id="start")
            yield Label("End Time")
            yield Input(value=end_val, id="end")
            yield Label("Metadata / Description")
            yield Input(value=desc_val, id="desc")
            yield Static("", id="status")
            with Grid(id="buttons"):
                yield Button("Save", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
        elif event.button.id == "ok":
            self.run_worker(self._submit(), exclusive=True)

    async def _submit(self) -> None:
        status = self.query_one("#status", Static)
        title = self.query_one("#title", Input).value.strip()
        start_str = self.query_one("#start", Input).value.strip()
        end_str = self.query_one("#end", Input).value.strip()
        desc_str = self.query_one("#desc", Input).value.strip()
        
        if not title or not start_str or not end_str:
            status.update("title, start, and end times are required")
            return
            
        start_dt = dateparser.parse(start_str, settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": True})
        end_dt = dateparser.parse(end_str, settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": True})
        
        if not start_dt or not end_dt:
            status.update("could not understand date/time format")
            return
            
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        if end_dt.tzinfo is None:
            end_dt = end_dt.replace(tzinfo=timezone.utc)
            
        if end_dt <= start_dt:
            status.update("end time must be after start time")
            return
        
        status.update("saving...")
        try:
            await asyncio.to_thread(self._save, title, start_dt, end_dt, desc_str)
            self.dismiss(True)
        except Exception as e:
            status.update(f"error: {e}")

    def _save(self, title: str, start_dt, end_dt, desc: str) -> None:
        if self.services.calendar:
            try:
                event = self.services.calendar.service.events().get(
                    calendarId=self.services.calendar.calendar_id,
                    eventId=self.g_event_id
                ).execute()
                event['summary'] = title
                event['description'] = desc
                event['start'] = {"dateTime": start_dt.astimezone(timezone.utc).isoformat()}
                event['end'] = {"dateTime": end_dt.astimezone(timezone.utc).isoformat()}
                self.services.calendar.service.events().update(
                    calendarId=self.services.calendar.calendar_id,
                    eventId=self.g_event_id,
                    body=event
                ).execute()
                
                # Update task_events locally to match
                self.services.conn.execute(
                    """
                    UPDATE task_events
                    SET planned_start=?, planned_end=?
                    WHERE google_event_id=?
                    """,
                    (
                        start_dt.astimezone(timezone.utc).isoformat(timespec="seconds"),
                        end_dt.astimezone(timezone.utc).isoformat(timespec="seconds"),
                        self.g_event_id,
                    ),
                )
                self.services.conn.commit()
            except Exception as e:
                raise CadenError(f"Calendar update failed: {e}")
        
        if self.g_task_id and self.services.tasks:
            try:
                task = self.services.tasks.service.tasks().get(
                    tasklist=self.services.tasks.task_list_id,
                    task=self.g_task_id
                ).execute()
                task['title'] = title
                task['notes'] = desc
                self.services.tasks.service.tasks().update(
                    tasklist=self.services.tasks.task_list_id,
                    task=self.g_task_id,
                    body=task
                ).execute()
            except Exception:
                pass
