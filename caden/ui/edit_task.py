"""Edit task modal: change title/summary."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from textual.app import ComposeResult
from textual.containers import Grid, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from .services import Services
from ..errors import CadenError
from .add_task import rewrite_times_local, _fmt_12h_with_date, _parse_local_deadline as _parse_local

class EditTaskScreen(ModalScreen[bool]):
    BINDINGS = [("escape", "cancel", "Cancel")]

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
            local_tz = datetime.now().astimezone().tzinfo or timezone.utc
            today_local = datetime.now(local_tz)
            start_val = _fmt_12h_with_date(
                self.event_obj.start.astimezone(local_tz), today_local
            )
            end_val = _fmt_12h_with_date(
                self.event_obj.end.astimezone(local_tz), today_local
            )
            raw_desc = self.event_obj.raw.get("description", "") or ""
            desc_val = rewrite_times_local(raw_desc, local_tz)
            
        with Vertical():
            yield Static("Edit Event", classes="title")
            yield Label("Title")
            yield Input(value=self.summary, id="title")
            yield Label("Start Time (e.g. 'today 5pm', '9:30 pm', 'apr 30 2:30pm')")
            yield Input(value=start_val, id="start")
            yield Label("End Time")
            yield Input(value=end_val, id="end")
            yield Label("Metadata / Description")
            yield Input(value=desc_val, id="desc")
            yield Static("", id="status")
            with Grid(id="buttons"):
                yield Button("Save", variant="primary", id="ok")
                yield Button("Complete Task", id="complete", variant="success")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
        elif event.button.id == "ok":
            self.run_worker(self._submit(), exclusive=True)
        elif event.button.id == "complete":
            self.run_worker(self._complete_task(), exclusive=True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    async def _complete_task(self) -> None:
        status = self.query_one("#status", Static)
        status.update("completing task...")
        try:
            await asyncio.to_thread(self._do_complete)
            self.dismiss(True)
        except Exception as e:
            status.update(f"error: {e}")

    def _do_complete(self) -> None:
        if self.g_task_id and self.services.tasks:
            self.services.tasks.mark_completed(self.g_task_id)
            from ..google_sync.poll import poll_once
            poll_once(self.services.conn, self.services.tasks, self.services.calendar)

    async def _submit(self) -> None:
        status = self.query_one("#status", Static)
        title = self.query_one("#title", Input).value.strip()
        start_str = self.query_one("#start", Input).value.strip()
        end_str = self.query_one("#end", Input).value.strip()
        desc_str = self.query_one("#desc", Input).value.strip()
        
        if not title or not start_str or not end_str:
            status.update("title, start, and end times are required")
            return
            
        start_dt = _parse_local(start_str)
        end_dt = _parse_local(end_str)

        if not start_dt or not end_dt:
            status.update("could not understand date/time format")
            return

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
        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
        clean_desc = rewrite_times_local(desc or "", local_tz)
        if self.services.calendar:
            try:
                event = self.services.calendar.service.events().get(
                    calendarId=self.services.calendar.calendar_id,
                    eventId=self.g_event_id
                ).execute()
                event['summary'] = title
                event['description'] = clean_desc
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
                task['notes'] = clean_desc
                self.services.tasks.service.tasks().update(
                    tasklist=self.services.tasks.task_list_id,
                    task=self.g_task_id,
                    body=task
                ).execute()
            except Exception as e:
                raise CadenError(f"Google Tasks update failed: {e}") from e
