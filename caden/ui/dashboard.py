"""Dashboard: today | chat | next 7 days, with an add-task button.

When Google sync is configured, the side panels render real calendar events
and tasks. When it is not, they render a clear "(sync not configured)"
placeholder — which is spec-legal because boot didn't claim sync was live.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Iterable

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Static, Label

from .chat import ChatWidget
from .services import Services

from ..google_sync.poll import poll_once
from ..errors import CadenError
from ..libbie.store import write_event
from ..util.timefmt import format_display_time, resolve_display_tz


def day_window_utc(now: datetime, *, local_tz: tzinfo | None = None) -> tuple[datetime, datetime]:
    """Return the current dashboard day window using the 5 AM local boundary."""
    local_now = now.astimezone(local_tz)
    boundary = local_now.replace(hour=5, minute=0, second=0, microsecond=0)
    if local_now.hour < 5:
        start_local = boundary - timedelta(days=1)
        end_local = boundary
    else:
        start_local = boundary
        end_local = boundary + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


@dataclass(frozen=True)
class TimelineEntry:
    sort_at: datetime
    text: str
    google_event_id: str
    google_task_id: str | None
    summary: str
    event_obj: object | None = None


class TaskItem(Horizontal):
    DEFAULT_CSS = """
    TaskItem {
        height: auto;
        margin-bottom: 1;
        color: white;
        background: #111317;
    }
    TaskItem:hover {
        background: #1a2028;
    }
    TaskItem Label {
        width: 1fr;
        padding-right: 1;
        color: white;
    }
    TaskItem Button {
        min-width: 5;
        width: 5;
        height: 1;
        border: none;
        color: white;
        background: #1d3b2f;
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
        border: solid #2d557a;
        padding: 0 1;
        color: white;
        background: #101217;
    }
    SidePanel #title {
        height: 1;
        color: white;
        margin-bottom: 1;
    }
    SidePanel VerticalScroll {
        height: 1fr;
        color: white;
        background: #0f1115;
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

    async def set_entries(self, entries: list[TimelineEntry]) -> None:
        scroll = self.query_one("#scroll", VerticalScroll)
        await scroll.remove_children()
        if not entries:
            await scroll.mount(Static("(nothing scheduled)"))
            return

        for entry in entries:
            await scroll.mount(
                TaskItem(
                    entry.text,
                    entry.google_event_id,
                    entry.google_task_id,
                    entry.summary,
                    event_obj=entry.event_obj,
                )
            )


def _entry_text(kind: str, when: datetime, summary: str, *, tz_name: str | None = None) -> str:
    stamp = format_display_time(when, tz_name=tz_name, include_weekday=True)
    return f"{stamp}  [{kind}] {summary}"


def _fmt_pred_scalar(value: float | int | None) -> str:
    if value is None:
        return "?"
    return f"{float(value):.2f}"


def _prediction_bundle_text(pred_row) -> str:
    return (
        f"pred dur={int(pred_row['pred_duration_min'])}m "
        f"pre={_fmt_pred_scalar(pred_row['pred_pre_mood'])}/"
        f"{_fmt_pred_scalar(pred_row['pred_pre_energy'])}/"
        f"{_fmt_pred_scalar(pred_row['pred_pre_productivity'])} "
        f"post={_fmt_pred_scalar(pred_row['pred_post_mood'])}/"
        f"{_fmt_pred_scalar(pred_row['pred_post_energy'])}/"
        f"{_fmt_pred_scalar(pred_row['pred_post_productivity'])} "
        f"conf_dur={_fmt_pred_scalar(pred_row['conf_duration'])}"
    )


def _sparkline_for_prediction(pred_row) -> str:
    chars = "▁▂▃▄▅▆▇█"
    vals = [
        float(pred_row["pred_post_mood"] or 0.0),
        float(pred_row["pred_post_energy"] or 0.0),
        float(pred_row["pred_post_productivity"] or 0.0),
    ]
    out = []
    for v in vals:
        idx = int(round(((v + 1.0) / 2.0) * (len(chars) - 1)))
        idx = max(0, min(len(chars) - 1, idx))
        out.append(chars[idx])
    return "".join(out)


def _residual_bundle_text(residual_row) -> str:
    return (
        f"resid dur={int(residual_row['duration_residual_min'])}m "
        f"post={_fmt_pred_scalar(residual_row['post_state_residual_mood'])}/"
        f"{_fmt_pred_scalar(residual_row['post_state_residual_energy'])}/"
        f"{_fmt_pred_scalar(residual_row['post_state_residual_productivity'])}"
    )


def _timeline_entries(
    events,
    open_tasks,
    task_map: dict[str, str],
    *,
    prediction_bundle_by_event_id: dict[str, str] | None = None,
    residual_bundle_by_event_id: dict[str, str] | None = None,
    sparkline_by_event_id: dict[str, str] | None = None,
    tz_name: str | None = None,
) -> list[TimelineEntry]:
    entries: list[TimelineEntry] = []
    linked_task_ids = {task_id for task_id in task_map.values()}
    for event in events:
        linked_task_id = task_map.get(event.id)
        kind = "task" if linked_task_id else "event"
        summary = event.summary
        if residual_bundle_by_event_id is not None:
            residual_bundle = residual_bundle_by_event_id.get(event.id)
            if residual_bundle:
                summary = f"{summary} | {residual_bundle}"
        if linked_task_id and prediction_bundle_by_event_id is not None:
            bundle = prediction_bundle_by_event_id.get(event.id)
            if bundle:
                summary = f"{summary} | {bundle}"
        if sparkline_by_event_id is not None:
            spark = sparkline_by_event_id.get(event.id)
            if spark:
                summary = f"{summary} | trend:{spark}"
        entries.append(
            TimelineEntry(
                sort_at=event.start,
                text=_entry_text(kind, event.start, summary, tz_name=tz_name),
                google_event_id=event.id,
                google_task_id=linked_task_id,
                summary=event.summary,
                event_obj=event,
            )
        )

    for task in open_tasks:
        if task.id in linked_task_ids or task.due is None:
            continue
        entries.append(
            TimelineEntry(
                sort_at=task.due,
                    text=_entry_text("task", task.due, task.title, tz_name=tz_name),
                google_event_id=f"task-only:{task.id}",
                google_task_id=task.id,
                summary=task.title,
                event_obj=None,
            )
        )

    entries.sort(key=lambda entry: (entry.sort_at, entry.text))
    return entries


class Dashboard(Vertical):
    DEFAULT_CSS = """
    Dashboard {
        layout: vertical;
        height: 1fr;
        color: white;
        background: #0f1115;
    }
    Dashboard #row {
        height: 1fr;
        background: #0f1115;
    }
    Dashboard ChatWidget {
        width: 1fr;
        height: 100%;
        min-width: 40;
        border: solid #2d557a;
        background: #101317;
        color: white;
    }
    Dashboard #topbar {
        height: 3;
        padding: 1 1;
        background: #101317;
        border-bottom: solid #2d557a;
    }
    """

    def __init__(self, services: Services) -> None:
        super().__init__()
        self.services = services

    def compose(self) -> ComposeResult:
        with Horizontal(id="topbar"):
            yield Button("+ add task", id="add-task", variant="primary")
            yield Static("", id="residual-audit")
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
        display_tz = resolve_display_tz(self.services.config.display_tz)
        start_today, end_today = day_window_utc(now, local_tz=display_tz)
        end_week = start_today + timedelta(days=7)
        try:
            today = await asyncio.to_thread(self.services.calendar.list_window, start_today, end_today)
            week = await asyncio.to_thread(self.services.calendar.list_window, start_today, end_week)
            open_tasks = []
            if self.services.tasks is not None:
                open_tasks = await asyncio.to_thread(self.services.tasks.list_open)
        except Exception as e:
            await today_panel.set_body_text(f"error: {e}")
            await week_panel.set_body_text(f"error: {e}")
            return
        
        task_rows = self.services.conn.execute(
            "SELECT task_events.task_id, task_events.google_event_id, tasks.google_task_id FROM task_events "
            "JOIN tasks ON tasks.id = task_id "
            "WHERE tasks.status='open' AND google_task_id IS NOT NULL"
        ).fetchall()
        task_map = {r["google_event_id"]: r["google_task_id"] for r in task_rows}
        task_id_by_event = {r["google_event_id"]: int(r["task_id"]) for r in task_rows}

        latest_prediction_rows = self.services.conn.execute(
            """
            SELECT p.task_id,
                   p.pred_duration_min,
                   p.pred_pre_mood, p.pred_pre_energy, p.pred_pre_productivity,
                   p.pred_post_mood, p.pred_post_energy, p.pred_post_productivity,
                   p.conf_duration
            FROM predictions AS p
            JOIN (
              SELECT task_id, MAX(id) AS max_id
              FROM predictions
              GROUP BY task_id
            ) AS latest
              ON latest.max_id = p.id
            """
        ).fetchall()
        prediction_by_task_id = {
            int(row["task_id"]): row
            for row in latest_prediction_rows
        }
        prediction_bundle_by_event_id: dict[str, str] = {}
        sparkline_by_event_id: dict[str, str] = {}
        for google_event_id, task_id in task_id_by_event.items():
            pred = prediction_by_task_id.get(task_id)
            if pred is None:
                continue
            prediction_bundle_by_event_id[google_event_id] = _prediction_bundle_text(pred)
            sparkline_by_event_id[google_event_id] = _sparkline_for_prediction(pred)

        completed_residual_rows = self.services.conn.execute(
            """
            SELECT te.google_event_id,
                   r.duration_residual_min,
                   r.post_state_residual_mood,
                   r.post_state_residual_energy,
                   r.post_state_residual_productivity
            FROM predictions AS p
            JOIN (
              SELECT task_id, MAX(id) AS max_id
              FROM predictions
              GROUP BY task_id
            ) AS latest
              ON latest.max_id = p.id
            JOIN tasks AS t
              ON t.id = p.task_id
            JOIN task_events AS te
              ON te.task_id = t.id
            LEFT JOIN residuals AS r
              ON r.prediction_id = p.id
            WHERE t.status='complete'
              AND t.google_task_id IS NOT NULL
              AND t.completed_at_utc IS NOT NULL
              AND t.completed_at_utc >= ?
              AND t.completed_at_utc <= ?
            """,
            (start_today.isoformat(), end_today.isoformat()),
        ).fetchall()
        residual_bundle_by_event_id: dict[str, str] = {}
        for row in completed_residual_rows:
            if row["duration_residual_min"] is None:
                continue
            residual_bundle_by_event_id[str(row["google_event_id"])] = _residual_bundle_text(row)

        audit_widget = self.query_one("#residual-audit", Static)
        if completed_residual_rows:
            first = completed_residual_rows[0]
            if first["duration_residual_min"] is not None:
                audit_widget.update(
                    f"audit: resid {int(first['duration_residual_min'])}m"
                )
            else:
                audit_widget.update("audit: residual pending")
        else:
            audit_widget.update("")

        today_filtered = [
            e
            for e in today
            if e.end > now
            or e.id in task_map
            or e.id in residual_bundle_by_event_id
        ]
        week_filtered = [e for e in week if e.end > now or e.id in task_map]
        today_tasks = [task for task in open_tasks if task.due is not None and start_today <= task.due <= end_today]
        rolling_week_end = now + timedelta(days=7)
        # The panel is circadian-windowed, but due timestamps arrive as UTC
        # dates from Google Tasks and can land exactly on boundary edges around
        # local pre-5am runs. Include either window to avoid dropping valid
        # future tasks silently.
        week_tasks = [
            task
            for task in open_tasks
            if task.due is not None
            and (
                start_today <= task.due <= end_week
                or now <= task.due <= rolling_week_end
            )
        ]

        await today_panel.set_entries(
            _timeline_entries(
                today_filtered,
                today_tasks,
                task_map,
                prediction_bundle_by_event_id=prediction_bundle_by_event_id,
                residual_bundle_by_event_id=residual_bundle_by_event_id,
                sparkline_by_event_id=None,
                tz_name=self.services.config.display_tz,
            )
        )
        await week_panel.set_entries(
            _timeline_entries(
                week_filtered,
                week_tasks,
                task_map,
                prediction_bundle_by_event_id=prediction_bundle_by_event_id,
                residual_bundle_by_event_id=residual_bundle_by_event_id,
                sparkline_by_event_id=sparkline_by_event_id,
                tz_name=self.services.config.display_tz,
            )
        )

    def record_drag_override(self, *, google_event_id: str, new_start_iso: str, new_end_iso: str) -> int:
        text = (
            f"Dashboard drag override: {google_event_id} -> {new_start_iso} .. {new_end_iso}"
        )
        emb = self.services.embedder.embed(text)
        return write_event(
            self.services.conn,
            source="dashboard_drag_override",
            raw_text=text,
            embedding=emb,
            meta={
                "google_event_id": google_event_id,
                "new_start": new_start_iso,
                "new_end": new_end_iso,
                "trigger": "dashboard_drag_override",
            },
            timestamp=None,
        )

    def apply_inline_rating_correction(
        self,
        *,
        prediction_id: int,
        pre: tuple[float | None, float | None, float | None] | None = None,
        post: tuple[float | None, float | None, float | None] | None = None,
        reason: str = "dashboard_inline_correction",
    ) -> int:
        """Persist explicit dashboard-side rating corrections on a prediction row."""
        row = self.services.conn.execute(
            "SELECT id FROM predictions WHERE id=?",
            (prediction_id,),
        ).fetchone()
        if row is None:
            raise ValueError("unknown prediction_id")

        if pre is not None:
            self.services.conn.execute(
                "UPDATE predictions SET pred_pre_mood=?, pred_pre_energy=?, pred_pre_productivity=? WHERE id=?",
                (pre[0], pre[1], pre[2], prediction_id),
            )
        if post is not None:
            self.services.conn.execute(
                "UPDATE predictions SET pred_post_mood=?, pred_post_energy=?, pred_post_productivity=? WHERE id=?",
                (post[0], post[1], post[2], prediction_id),
            )
        self.services.conn.commit()

        text = f"Inline rating correction for prediction {prediction_id}"
        return write_event(
            self.services.conn,
            source="dashboard_rating_correction",
            raw_text=text,
            embedding=self.services.embedder.embed(text),
            meta={
                "trigger": "dashboard_inline_correction",
                "prediction_id": prediction_id,
                "reason": reason,
                "pre": list(pre) if pre is not None else None,
                "post": list(post) if post is not None else None,
            },
            timestamp=None,
        )

    def format_alternative_schedule_preview(self, options: Iterable[dict[str, object]]) -> list[str]:
        """Render candidate options with explicit Pareto marker for frontier entries."""
        lines: list[str] = []
        for idx, option in enumerate(options, start=1):
            tag = "[pareto]" if bool(option.get("pareto")) else "[alt]"
            label = str(option.get("label") or option.get("id") or f"option-{idx}")
            mood = float(option.get("mood") or 0.0)
            energy = float(option.get("energy") or 0.0)
            productivity = float(option.get("productivity") or 0.0)
            lines.append(
                f"{tag} {label} mood={mood:.2f} energy={energy:.2f} productivity={productivity:.2f}"
            )
        return lines

    def record_schema_growth_decision_from_dashboard(
        self,
        *,
        pending_event_id: int,
        decision: str,
        reason: str,
    ) -> int:
        """Persist dashboard accept/reject action for a pending schema proposal."""
        clean = decision.strip().lower()
        if clean not in {"accept", "reject"}:
            raise ValueError("decision must be accept or reject")

        text = f"Schema growth {clean} from dashboard (pending_event_id={pending_event_id})"
        return write_event(
            self.services.conn,
            source="dashboard_schema_decision",
            raw_text=text,
            embedding=self.services.embedder.embed(text),
            meta={
                "trigger": "dashboard_schema_decision",
                "pending_event_id": pending_event_id,
                "decision": clean,
                "reason": reason,
            },
            timestamp=None,
        )

    def phase_change_alert_text(self, *, direction: str, pvalue: float, sample_count: int) -> str:
        verdict = "phase shift detected" if pvalue < 0.05 else "phase stable"
        return (
            f"{verdict}: direction={direction}, p={pvalue:.4f}, n={sample_count}. "
            "Review recent residuals before schedule edits."
        )

    def optimization_readiness(self, *, min_residual_rows: int = 10) -> tuple[bool, str]:
        residual_count = int(
            self.services.conn.execute("SELECT COUNT(*) AS n FROM residuals").fetchone()["n"]
        )
        if residual_count < min_residual_rows:
            return False, f"need >= {min_residual_rows} residual rows (have {residual_count})"
        return True, "ready"

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
