"""Polling-based completion detection.

Webhook / push is unavailable for a local desktop app without a public URL,
so v0 polls Google Tasks periodically and compares statuses against the
local DB. Completions trigger the residual pipeline.

This module exposes a single function the UI can call on a timer; it does
not own its own thread.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta

from ..errors import GoogleSyncError, SchedulerError
from ..libbie.store import complete_task
from ..scheduler.residual import compute_and_store
from .tasks import TasksClient
from .calendar import CalendarClient


def poll_once(
    conn: sqlite3.Connection,
    tasks_client: TasksClient,
    calendar_client: CalendarClient | None = None,
) -> list[int]:
    """For each local open task whose Google Task is now complete, finalise it.

    Returns the list of local task ids finalised in this pass.
    """
    local_rows = conn.execute(
        "SELECT id, google_task_id FROM tasks WHERE status='open' AND google_task_id IS NOT NULL"
    ).fetchall()
    if not local_rows:
        return []

    finalised: list[int] = []
    for row in local_rows:
        g_id = row["google_task_id"]
        try:
            g = tasks_client.get(g_id)
        except GoogleSyncError:
            # re-raise; no silent fallback
            raise
        if g.status != "completed":
            continue
        when = g.completed_at or datetime.now(timezone.utc)
        when_iso = when.astimezone(timezone.utc).isoformat(timespec="seconds")

        complete_task(conn, int(row["id"]), when_iso)

        pred = conn.execute(
            "SELECT id, pred_duration_min FROM predictions WHERE task_id=? ORDER BY id DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        te = conn.execute(
            """
            SELECT google_event_id, planned_start FROM task_events WHERE task_id=?
            ORDER BY chunk_index ASC LIMIT 1
            """,
            (row["id"],),
        ).fetchone()
        if pred is None or te is None:
            # missing pairing is a bug, per spec — complain loudly
            raise SchedulerError(
                f"task {row['id']} completed but missing prediction/task_event pairing"
            )

        ps_dt = datetime.fromisoformat(te["planned_start"])
        if calendar_client is not None:
            # Edit google calendar per spec
            ge_id = te["google_event_id"]
            if not ge_id.startswith("local-only-"):
                if when < ps_dt:
                    # Early-completion case
                    dur_min = float(pred["pred_duration_min"])
                    shift_start = when - timedelta(minutes=dur_min)
                    calendar_client.reschedule(ge_id, shift_start, when)
                else:
                    # Normal case
                    calendar_client.set_end_time(ge_id, when)

        compute_and_store(
            conn,
            prediction_id=int(pred["id"]),
            planned_start_iso=te["planned_start"],
            actual_end_iso=when_iso,
        )
        finalised.append(int(row["id"]))
    return finalised
