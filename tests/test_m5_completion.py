import pytest
import sqlite3
import json
from datetime import datetime, timezone
from caden.libbie.db import connect
from caden.libbie.store import write_task, complete_task, link_task_event

@pytest.mark.asyncio
async def test_m5_completion(db_conn):
    # Create an initial task and event
    cur = db_conn.cursor()
    
    # 1. Insert a task
    task_id = write_task(
        db_conn,
        description="Complete me",
        deadline_iso=datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
        google_task_id="g_1",
        embedding=[0.1]*768
    )
    
    # 2. Insert a task_event
    start = datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 4, 25, 11, 0, tzinfo=timezone.utc)
    link_task_event(
        db_conn,
        task_id=task_id,
        google_event_id="e_1",
        planned_start_iso=start.isoformat(), chunk_index=0, chunk_count=1,
        planned_end_iso=end.isoformat(),
    )
    
    # 3. Add prediction so residual can be computed
    cur.execute("""
        INSERT INTO predictions (task_id, pred_duration_min, created_at)
        VALUES (?, ?, datetime("now"))
    """, (task_id, 60))
    db_conn.commit()

    # 4. Mark completion
    completed_time = datetime(2026, 4, 25, 10, 30, tzinfo=timezone.utc)
    from caden.scheduler.residual import compute_and_store
    compute_and_store(db_conn, prediction_id=1, planned_start_iso=start.isoformat(), actual_end_iso=completed_time.isoformat())

    complete_task(
        db_conn,
        task_id=task_id,
        completed_at_iso=completed_time.isoformat()
    )

    # 5. Assertions
    
    # Task should have a completed_at_utc
    task_row = cur.execute("SELECT completed_at_utc FROM tasks WHERE id=?", (task_id,)).fetchone()
    assert task_row["completed_at_utc"] is not None

    # Event should have end time early-terminated
    # In libbie/store.py, early termination sets end to max(start, completed_at_utc)
    event_row = cur.execute("SELECT actual_end FROM task_events WHERE task_id=?", (task_id,)).fetchone()
    assert event_row["actual_end"] == completed_time.isoformat()

    # Residuals row should exist
    prediction_id = cur.execute("SELECT id FROM predictions WHERE task_id=?", (task_id,)).fetchone()["id"]
    residual_row = cur.execute("SELECT duration_residual_min FROM residuals WHERE prediction_id=?", (prediction_id,)).fetchone()
    assert residual_row is not None
    # Original predicted 60, actually started 10:00 ended 10:30 (30 mins) => 30 - 60 = -30
    assert residual_row["duration_residual_min"] == -30
