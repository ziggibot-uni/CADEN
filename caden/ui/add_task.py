"""Add-task modal: explicit button, required description + deadline.

Per spec: tasks enter through a button, not via chat parsing. The form
enforces both fields; a bypass is a bug. Submitting:

  1. writes the Task row (+ mirrored event) in Libbie
  2. creates a Google Task (if Google sync is available)
  3. asks the scheduler for a plan
  4. creates a Google Calendar event per chunk (if Google sync is available)
  5. links task_events
  6. emits a prediction bundle

When Google sync is not configured, steps 2 and 4 degrade to storing the plan
locally only — but loudly, with a visible note. This is the single pragmatic
softening in v0: boot doesn't require Google to be live just to run chat.
The moment Google is configured, tasks flow end to end.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import dateparser
from textual.app import ComposeResult
from textual.containers import Grid, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from ..errors import CadenError, SchedulerError
from ..libbie.store import link_task_event, write_task
from ..scheduler.predict import emit_prediction
from ..scheduler.schedule import ExistingEvent, plan
from .services import Services


class AddTaskScreen(ModalScreen[bool]):
    DEFAULT_CSS = """
    AddTaskScreen {
        align: center middle;
    }
    AddTaskScreen > Vertical {
        width: 90;
        height: auto;
        max-height: 90%;
        border: thick $accent;
        background: $panel;
        padding: 1 2;
    }
    AddTaskScreen Label {
        margin-top: 1;
    }
    AddTaskScreen #buttons {
        margin-top: 1;
        height: auto;
    }
    AddTaskScreen #status {
        margin-top: 1;
        height: auto;
        max-height: 8;
        color: $text;
    }
    AddTaskScreen #live {
        margin-top: 1;
        height: 12;
        min-height: 12;
        border: round $surface;
        background: $boost;
        padding: 0 1;
        display: none;
    }
    AddTaskScreen #live.-active {
        display: block;
    }
    AddTaskScreen #live-thinking {
        color: $text-muted;
    }
    AddTaskScreen #live-content {
        color: $text;
    }
    """

    def __init__(self, services: Services) -> None:
        super().__init__()
        self.services = services
        # Running buffers of the scheduler's streaming output.
        self._thinking_buf: str = ""
        self._content_buf: str = ""
        self._status_lines: list[str] = []
        self._t0: float = 0.0

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Add a task", classes="title")
            yield Label("Description (required)")
            yield Input(placeholder="what is the task?", id="desc")
            yield Label("Deadline (e.g. 'tomorrow 5pm', 'apr 30 2:30pm', 'next monday at 9am')")
            yield Input(placeholder="in plain english…", id="deadline")
            yield Static("", id="status")
            with VerticalScroll(id="live"):
                yield Static("", id="live-thinking", markup=False)
                yield Static("", id="live-content", markup=False)
            with Grid(id="buttons"):
                yield Button("Add", variant="primary", id="ok")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)
            return
        if event.button.id == "ok":
            self.run_worker(self._submit(), exclusive=True, group="add-task")

    async def _submit(self) -> None:
        status = self.query_one("#status", Static)
        desc = self.query_one("#desc", Input).value.strip()
        dl_raw = self.query_one("#deadline", Input).value.strip()
        if not desc:
            status.update("description is required")
            return
        if not dl_raw:
            status.update("deadline is required")
            return
        deadline = dateparser.parse(
            dl_raw,
            settings={
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": True,
            },
        )
        if deadline is None:
            status.update(
                "could not understand that date/time — try 'tomorrow 5pm' or 'apr 30 2:30pm'"
            )
            return
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)

        self._t0 = time.monotonic()
        self._set_status("submit: starting")
        try:
            await asyncio.to_thread(self._execute, desc, deadline)
        except CadenError as e:
            self._set_status(f"FAILED: {e}")
            return
        self.dismiss(True)

    def _set_status(self, text: str) -> None:
        """Append a timestamped status line. Safe from any thread."""
        elapsed = (time.monotonic() - self._t0) if self._t0 else 0.0
        line = f"[{elapsed:5.1f}s] {text}"
        self._status_lines.append(line)
        # Keep only the last 6 lines to fit max-height: 8.
        if len(self._status_lines) > 6:
            self._status_lines = self._status_lines[-6:]
        body = "\n".join(self._status_lines)
        try:
            self.app.call_from_thread(self._update_status_widget, body)
        except RuntimeError:
            # We're already on the UI thread — call directly.
            self._update_status_widget(body)
        # Mirror to the launching terminal so a frozen UI is still diagnosable.
        print(line, flush=True)

    def _update_status_widget(self, body: str) -> None:
        self.query_one("#status", Static).update(body)

    # ---- live streaming surface ---------------------------------------------
    # The scheduler LLM call can take a while. Streaming both the reasoning
    # and the accumulating JSON into a visible panel makes it obvious the
    # model is actually working and lets Sean see what it's considering.

    def _show_live(self) -> None:
        self._thinking_buf = ""
        self._content_buf = ""
        live = self.query_one("#live", VerticalScroll)
        self.query_one("#live-thinking", Static).update("")
        self.query_one("#live-content", Static).update("")
        live.add_class("-active")

    def _hide_live(self) -> None:
        self.query_one("#live", VerticalScroll).remove_class("-active")

    def _push_thinking(self) -> None:
        box = self.query_one("#live", VerticalScroll)
        self.query_one("#live-thinking", Static).update(self._thinking_buf)
        box.scroll_end(animate=False)

    def _push_content(self) -> None:
        box = self.query_one("#live", VerticalScroll)
        self.query_one("#live-content", Static).update(self._content_buf)
        box.scroll_end(animate=False)

    def _on_sched_thinking(self, chunk: str) -> None:
        # Called from the worker thread while llm.chat_stream runs.
        if not self._thinking_buf and not self._content_buf:
            self.app.call_from_thread(
                self._set_status_direct, "[dim]first tokens arriving\u2026[/dim]"
            )
        self._thinking_buf += chunk
        self.app.call_from_thread(self._push_thinking)

    def _on_sched_content(self, chunk: str) -> None:
        if not self._thinking_buf and not self._content_buf:
            self.app.call_from_thread(
                self._set_status_direct, "[dim]first tokens arriving\u2026[/dim]"
            )
        self._content_buf += chunk
        self.app.call_from_thread(self._push_content)

    def _set_status_direct(self, text: str) -> None:
        # kept for backward compat; route through the timestamped log
        self._set_status(text)

    def _gather_existing(
        self, deadline: datetime, now: datetime
    ) -> list[ExistingEvent]:
        """Pull calendar events between now and deadline, tag CADEN-owned ones."""
        s = self.services
        if s.calendar is None:
            return []
        raw = s.calendar.list_window(now, deadline)  # type: ignore[attr-defined]
        # CADEN-owned ids come from task_events rows.
        caden_ids = {
            row["google_event_id"]
            for row in s.conn.execute(
                "SELECT google_event_id FROM task_events"
            ).fetchall()
        }
        out: list[ExistingEvent] = []
        for e in raw:
            out.append(
                ExistingEvent(
                    google_event_id=e.id,
                    summary=e.summary,
                    start=e.start,
                    end=e.end,
                    caden_owned=(e.id in caden_ids),
                )
            )
        return out

    def _apply_displacements(self, task_id_ignored: int, displacements) -> None:
        """Move CADEN-owned events in Google Calendar and update task_events rows.

        External events are never touched (the scheduler refused moves on
        non-CADEN ids before we got here). We update planned_start/end on
        the corresponding task_event row so residual math stays honest.
        """
        s = self.services
        if not displacements:
            return
        if s.calendar is None:
            raise SchedulerError(
                "scheduler proposed moves but calendar client is not configured"
            )
        for d in displacements:
            s.calendar.reschedule(  # type: ignore[attr-defined]
                d.google_event_id, d.new_start, d.new_end
            )
            s.conn.execute(
                """
                UPDATE task_events
                SET planned_start=?, planned_end=?
                WHERE google_event_id=?
                """,
                (
                    d.new_start.astimezone(timezone.utc).isoformat(timespec="seconds"),
                    d.new_end.astimezone(timezone.utc).isoformat(timespec="seconds"),
                    d.google_event_id,
                ),
            )

    def _execute(self, desc: str, deadline: datetime) -> None:
        s = self.services
        now = datetime.now(timezone.utc)

        # 1. gather calendar context so the LLM can place the task well
        self._set_status("reading calendar\u2026")
        existing = self._gather_existing(deadline, now)

        # 2. embed the description — both the scheduler and the prediction
        # step use it for retrieval, so compute once and reuse.
        self._set_status("embedding description\u2026")
        desc_emb = s.embedder.embed(desc)

        # 3. ask the LLM to pick a block (and any displacements needed)
        self._set_status(
            f"sending scheduler prompt to ollama "
            f"({len(existing)} existing event(s) in window)\u2026"
        )
        self.app.call_from_thread(self._show_live)
        try:
            sched = plan(
                desc,
                deadline,
                conn=s.conn,
                llm=s.llm,
                existing_events=existing,
                description_embedding=desc_emb,
                now=now,
                on_open=lambda: self._set_status("HTTP stream opened, waiting for first token\u2026"),
                on_thinking=self._on_sched_thinking,
                on_content=self._on_sched_content,
            )
        finally:
            self.app.call_from_thread(self._hide_live)
        self._set_status(
            f"plan received: {sched.total_minutes}min, "
            f"{len(sched.displacements)} displacement(s)"
        )

        # 4. Google Task (the deadline-side handle)
        g_task_id: str | None = None
        if s.tasks is not None:
            self._set_status("creating Google task\u2026")
            gt = s.tasks.create(title=desc, due=deadline, notes="created by CADEN")  # type: ignore[attr-defined]
            g_task_id = gt.id
        self._set_status("writing task to Libbie\u2026")
        task_id = write_task(
            s.conn,
            description=desc,
            deadline_iso=deadline.astimezone(timezone.utc).isoformat(timespec="seconds"),
            google_task_id=g_task_id,
            embedding=desc_emb,
        )

        # 5. if google calendar is not configured, degrade loudly
        if s.calendar is None:
            for c in sched.chunks:
                link_task_event(
                    s.conn,
                    task_id=task_id,
                    google_event_id=f"local-only-{task_id}-{c.index}",
                    chunk_index=c.index,
                    chunk_count=c.count,
                    planned_start_iso=c.start.isoformat(timespec="seconds"),
                    planned_end_iso=c.end.isoformat(timespec="seconds"),
                )
            self._set_status("emitting prediction (LLM call)\u2026")
            emit_prediction(
                s.conn,
                task_id=task_id,
                description=desc,
                description_embedding=desc_emb,
                planned_start_iso=sched.chunks[0].start.isoformat(timespec="seconds"),
                planned_end_iso=sched.chunks[-1].end.isoformat(timespec="seconds"),
                google_event_id=None,
                llm=s.llm,
                embedder=s.embedder,
            )
            raise SchedulerError(
                "task stored locally but Google sync is not configured; "
                "calendar event NOT created. configure google_credentials_path to enable."
            )

        # 6. apply displacements first so the new block lands in clean space
        if sched.displacements:
            self._set_status(
                f"moving {len(sched.displacements)} existing block(s)\u2026"
            )
            self._apply_displacements(task_id, sched.displacements)

        # 7. create the calendar event(s) for this task
        first_event_id: str | None = None
        n = len(sched.chunks)
        for c in sched.chunks:
            self._set_status(f"creating calendar event {c.index + 1}/{n}\u2026")
            title = desc if c.count == 1 else f"{desc} ({c.index + 1}/{c.count})"
            ce = s.calendar.create_event(  # type: ignore[attr-defined]
                summary=title,
                start=c.start,
                end=c.end,
                description=f"CADEN task #{task_id}\n\n{sched.rationale}",
            )
            if first_event_id is None:
                first_event_id = ce.id
            link_task_event(
                s.conn,
                task_id=task_id,
                google_event_id=ce.id,
                chunk_index=c.index,
                chunk_count=c.count,
                planned_start_iso=c.start.isoformat(timespec="seconds"),
                planned_end_iso=c.end.isoformat(timespec="seconds"),
            )

        # 8. prediction bundle
        self._set_status("emitting prediction (LLM call)\u2026")
        emit_prediction(
            s.conn,
            task_id=task_id,
            description=desc,
            description_embedding=desc_emb,
            planned_start_iso=sched.chunks[0].start.isoformat(timespec="seconds"),
            planned_end_iso=sched.chunks[-1].end.isoformat(timespec="seconds"),
            google_event_id=first_event_id,
            llm=s.llm,
            embedder=s.embedder,
        )
