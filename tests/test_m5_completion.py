import pytest
import sqlite3
import json
from datetime import datetime, timedelta, timezone
import pandas as pd
from caden.libbie.db import connect
from caden.libbie.store import write_task, complete_task, link_task_event, write_event, write_rating
from caden.errors import SchedulerError
from caden.google_sync.poll import poll_once
from caden.google_sync.tasks import GTask

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
        planned_start_iso=start.isoformat(),
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

    mirrored = cur.execute(
        "SELECT id FROM events WHERE source='residual' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert mirrored is not None, "Residuals must be mirrored into events"


def test_m5_residual_state_fields_stay_null_without_nearby_ratings(db_conn):
    cur = db_conn.cursor()

    task_id = write_task(
        db_conn,
        description="No ratings nearby",
        deadline_iso=datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
        google_task_id="g_2",
        embedding=[0.1] * 768,
    )

    start = datetime(2026, 4, 25, 8, 0, tzinfo=timezone.utc)
    end = datetime(2026, 4, 25, 9, 0, tzinfo=timezone.utc)
    link_task_event(
        db_conn,
        task_id=task_id,
        google_event_id="e_2",
        planned_start_iso=start.isoformat(),
        planned_end_iso=end.isoformat(),
    )

    cur.execute(
        """
        INSERT INTO predictions (
            task_id,
            pred_duration_min,
            pred_pre_mood,
            pred_pre_energy,
            pred_pre_productivity,
            pred_post_mood,
            pred_post_energy,
            pred_post_productivity,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (task_id, 60, 0.2, 0.1, 0.0, 0.3, 0.2, 0.4),
    )
    db_conn.commit()

    from caden.scheduler.residual import compute_and_store

    residual_id = compute_and_store(
        db_conn,
        prediction_id=cur.execute(
            "SELECT id FROM predictions WHERE task_id=?", (task_id,)
        ).fetchone()["id"],
        planned_start_iso=start.isoformat(),
        actual_end_iso=end.isoformat(),
    )

    residual = cur.execute(
        """
        SELECT pre_state_residual_mood, pre_state_residual_energy, pre_state_residual_productivity,
               post_state_residual_mood, post_state_residual_energy, post_state_residual_productivity
        FROM residuals WHERE id=?
        """,
        (residual_id,),
    ).fetchone()

    assert residual is not None
    assert all(residual[key] is None for key in residual.keys()), "Cold-start residual state should stay unknown, not defaulted"


def test_m5_early_completion_shifts_event_and_skips_duration_residual(db_conn):
    cur = db_conn.cursor()

    task_id = write_task(
        db_conn,
        description="Finish before the planned window starts",
        deadline_iso=datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
        google_task_id="g_early",
        embedding=[0.1] * 768,
    )

    planned_start = datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc)
    planned_end = datetime(2026, 4, 25, 11, 0, tzinfo=timezone.utc)
    completed_at = planned_start - timedelta(minutes=15)

    link_task_event(
        db_conn,
        task_id=task_id,
        google_event_id="e_early",
        planned_start_iso=planned_start.isoformat(),
        planned_end_iso=planned_end.isoformat(),
    )
    cur.execute(
        """
        INSERT INTO predictions (task_id, pred_duration_min, created_at)
        VALUES (?, ?, datetime('now'))
        """,
        (task_id, 60),
    )
    db_conn.commit()

    class MockTasks:
        def get(self, task_id: str) -> GTask:
            return GTask(
                id=task_id,
                title="Finish before planned window",
                due=None,
                status="completed",
                completed_at=completed_at,
                raw={},
            )

    class MockCalendar:
        def __init__(self):
            self.rescheduled = []
            self.ended = []

        def reschedule(self, event_id, new_start, new_end):
            self.rescheduled.append((event_id, new_start, new_end))

        def set_end_time(self, event_id, when):
            self.ended.append((event_id, when))

    calendar = MockCalendar()
    finalised = poll_once(db_conn, MockTasks(), calendar)

    assert finalised == [task_id]
    assert calendar.ended == []
    assert calendar.rescheduled == [
        ("e_early", completed_at - timedelta(minutes=60), completed_at)
    ]

    residual = cur.execute(
        "SELECT duration_actual_min, duration_residual_min FROM residuals ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert residual is not None
    assert residual["duration_actual_min"] is None
    assert residual["duration_residual_min"] is None


def test_m5_completion_without_task_event_pairing_fails_loudly(db_conn):
    cur = db_conn.cursor()

    task_id = write_task(
        db_conn,
        description="Missing task-event pair",
        deadline_iso=datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
        google_task_id="g_missing_pair",
        embedding=[0.1] * 768,
    )
    cur.execute(
        """
        INSERT INTO predictions (task_id, pred_duration_min, created_at)
        VALUES (?, ?, datetime('now'))
        """,
        (task_id, 45),
    )
    db_conn.commit()

    class MockTasks:
        def get(self, task_id: str) -> GTask:
            return GTask(
                id=task_id,
                title="Broken pair",
                due=None,
                status="completed",
                completed_at=datetime(2026, 4, 25, 10, 30, tzinfo=timezone.utc),
                raw={},
            )

    with pytest.raises(SchedulerError, match="missing prediction/task_event pairing"):
        poll_once(db_conn, MockTasks())


def test_m5_normal_completion_truncates_google_event_and_fills_state_residuals(db_conn):
    cur = db_conn.cursor()

    task_id = write_task(
        db_conn,
        description="Normal completion with nearby ratings",
        deadline_iso=datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
        google_task_id="g_normal",
        embedding=[0.1] * 768,
    )

    planned_start = datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc)
    planned_end = datetime(2026, 4, 25, 11, 0, tzinfo=timezone.utc)
    completed_at = datetime(2026, 4, 25, 10, 30, tzinfo=timezone.utc)

    link_task_event(
        db_conn,
        task_id=task_id,
        google_event_id="e_normal",
        planned_start_iso=planned_start.isoformat(),
        planned_end_iso=planned_end.isoformat(),
    )
    cur.execute(
        """
        INSERT INTO predictions (
            task_id,
            pred_duration_min,
            pred_pre_mood,
            pred_pre_energy,
            pred_pre_productivity,
            pred_post_mood,
            pred_post_energy,
            pred_post_productivity,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (task_id, 60, 0.2, 0.1, 0.0, 0.1, 0.2, 0.3),
    )

    pre_event_id = write_event(
        db_conn,
        "sean_chat",
        "pre-boundary rating source",
        [0.1] * 768,
        timestamp=(planned_start + timedelta(minutes=5)).isoformat(),
    )
    write_rating(
        db_conn,
        event_id=pre_event_id,
        mood=0.5,
        energy=0.4,
        productivity=0.3,
        c_mood=0.8,
        c_energy=0.8,
        c_productivity=0.8,
        rationale="pre boundary",
        embedding=[0.1] * 768,
    )

    post_event_id = write_event(
        db_conn,
        "sean_chat",
        "post-boundary rating source",
        [0.1] * 768,
        timestamp=(completed_at - timedelta(minutes=2)).isoformat(),
    )
    write_rating(
        db_conn,
        event_id=post_event_id,
        mood=0.6,
        energy=0.5,
        productivity=0.4,
        c_mood=0.8,
        c_energy=0.8,
        c_productivity=0.8,
        rationale="post boundary",
        embedding=[0.1] * 768,
    )
    db_conn.commit()

    class MockTasks:
        def get(self, task_id: str) -> GTask:
            return GTask(
                id=task_id,
                title="Normal completion",
                due=None,
                status="completed",
                completed_at=completed_at,
                raw={},
            )

    class MockCalendar:
        def __init__(self):
            self.rescheduled = []
            self.ended = []

        def reschedule(self, event_id, new_start, new_end):
            self.rescheduled.append((event_id, new_start, new_end))

        def set_end_time(self, event_id, when):
            self.ended.append((event_id, when))

    calendar = MockCalendar()
    finalised = poll_once(db_conn, MockTasks(), calendar)

    assert finalised == [task_id]
    assert calendar.rescheduled == []
    assert calendar.ended == [("e_normal", completed_at)]

    task_event = cur.execute(
        "SELECT planned_start, actual_end FROM task_events WHERE task_id=?",
        (task_id,),
    ).fetchone()
    assert task_event["planned_start"] == planned_start.isoformat()
    assert task_event["actual_end"] == completed_at.isoformat(timespec="seconds")

    residual = cur.execute(
        """
        SELECT duration_actual_min, duration_residual_min,
               pre_state_residual_mood, pre_state_residual_energy, pre_state_residual_productivity,
               post_state_residual_mood, post_state_residual_energy, post_state_residual_productivity
        FROM residuals ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    assert residual is not None
    assert residual["duration_actual_min"] == 30
    assert residual["duration_residual_min"] == -30
    assert residual["pre_state_residual_mood"] == pytest.approx(0.3)
    assert residual["pre_state_residual_energy"] == pytest.approx(0.3)
    assert residual["pre_state_residual_productivity"] == pytest.approx(0.3)
    assert residual["post_state_residual_mood"] == pytest.approx(0.5)
    assert residual["post_state_residual_energy"] == pytest.approx(0.3)
    assert residual["post_state_residual_productivity"] == pytest.approx(0.1)


def test_m5_early_completion_still_fills_state_residuals_from_nearby_ratings(db_conn):
    cur = db_conn.cursor()

    task_id = write_task(
        db_conn,
        description="Early completion still gets state residuals",
        deadline_iso=datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
        google_task_id="g_early_state",
        embedding=[0.1] * 768,
    )

    planned_start = datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc)
    planned_end = datetime(2026, 4, 25, 11, 0, tzinfo=timezone.utc)
    completed_at = planned_start - timedelta(minutes=15)

    link_task_event(
        db_conn,
        task_id=task_id,
        google_event_id="e_early_state",
        planned_start_iso=planned_start.isoformat(),
        planned_end_iso=planned_end.isoformat(),
    )
    cur.execute(
        """
        INSERT INTO predictions (
            task_id,
            pred_duration_min,
            pred_pre_mood,
            pred_pre_energy,
            pred_pre_productivity,
            pred_post_mood,
            pred_post_energy,
            pred_post_productivity,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (task_id, 60, 0.0, 0.0, 0.0, 0.1, 0.1, 0.1),
    )

    pre_event_id = write_event(
        db_conn,
        "sean_chat",
        "planned start nearby rating source",
        [0.1] * 768,
        timestamp=(planned_start - timedelta(minutes=10)).isoformat(),
    )
    write_rating(
        db_conn,
        event_id=pre_event_id,
        mood=0.2,
        energy=0.3,
        productivity=0.4,
        c_mood=0.8,
        c_energy=0.8,
        c_productivity=0.8,
        rationale="pre boundary",
        embedding=[0.1] * 768,
    )

    post_event_id = write_event(
        db_conn,
        "sean_chat",
        "early completion nearby rating source",
        [0.1] * 768,
        timestamp=(completed_at + timedelta(minutes=1)).isoformat(),
    )
    write_rating(
        db_conn,
        event_id=post_event_id,
        mood=0.6,
        energy=0.5,
        productivity=0.4,
        c_mood=0.8,
        c_energy=0.8,
        c_productivity=0.8,
        rationale="post boundary",
        embedding=[0.1] * 768,
    )

    db_conn.commit()

    class MockTasks:
        def get(self, task_id: str) -> GTask:
            return GTask(
                id=task_id,
                title="Early completion",
                due=None,
                status="completed",
                completed_at=completed_at,
                raw={},
            )

    residual_id = poll_once(db_conn, MockTasks())

    assert residual_id == [task_id]
    residual = cur.execute(
        """
        SELECT duration_actual_min, duration_residual_min,
               pre_state_residual_mood, pre_state_residual_energy, pre_state_residual_productivity,
               post_state_residual_mood, post_state_residual_energy, post_state_residual_productivity
        FROM residuals ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    assert residual is not None
    assert residual["duration_actual_min"] is None
    assert residual["duration_residual_min"] is None
    assert residual["pre_state_residual_mood"] == pytest.approx(0.2)
    assert residual["pre_state_residual_energy"] == pytest.approx(0.3)
    assert residual["pre_state_residual_productivity"] == pytest.approx(0.4)
    assert residual["post_state_residual_mood"] == pytest.approx(0.5)
    assert residual["post_state_residual_energy"] == pytest.approx(0.4)
    assert residual["post_state_residual_productivity"] == pytest.approx(0.3)


def test_residual_aggregation_query_uses_pandas_and_groups_by_mechanism(db_conn, monkeypatch):
    from caden.scheduler import residual as residual_module

    captured = {"called": False}
    original_read_sql_query = residual_module.pd.read_sql_query

    def _spy_read_sql_query(sql, conn):
        captured["called"] = True
        return original_read_sql_query(sql, conn)

    monkeypatch.setattr(residual_module.pd, "read_sql_query", _spy_read_sql_query)

    task_one = write_task(
        db_conn,
        description="Aggregate residual one",
        deadline_iso=datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
        google_task_id="agg_task_1",
        embedding=[0.1] * 768,
    )
    task_two = write_task(
        db_conn,
        description="Aggregate residual two",
        deadline_iso=datetime(2026, 5, 1, tzinfo=timezone.utc).isoformat(),
        google_task_id="agg_task_2",
        embedding=[0.1] * 768,
    )
    prediction_one = db_conn.execute(
        "INSERT INTO predictions (task_id, pred_duration_min, created_at) VALUES (?, 60, datetime('now'))",
        (task_one,),
    ).lastrowid
    prediction_two = db_conn.execute(
        "INSERT INTO predictions (task_id, pred_duration_min, created_at) VALUES (?, 45, datetime('now'))",
        (task_two,),
    ).lastrowid
    db_conn.commit()

    residual_module.write_residual(
        db_conn,
        prediction_id=prediction_one,
        duration_actual_min=30,
        duration_residual_min=-30,
        pre_residuals=(0.2, None, -0.1),
        post_residuals=(0.4, 0.1, None),
        embedding=None,
    )
    residual_module.write_residual(
        db_conn,
        prediction_id=prediction_two,
        duration_actual_min=60,
        duration_residual_min=15,
        pre_residuals=(0.6, 0.3, None),
        post_residuals=(None, -0.2, 0.5),
        embedding=None,
    )

    summary = residual_module.aggregate_residuals_by_mechanism(db_conn)

    assert captured["called"] is True
    assert isinstance(summary, pd.DataFrame)
    rows = {
        row["mechanism"]: row
        for row in summary.to_dict(orient="records")
    }

    assert rows["duration"]["sample_count"] == 2
    assert rows["duration"]["mean_residual"] == pytest.approx(-7.5)
    assert rows["duration"]["mean_abs_residual"] == pytest.approx(22.5)
    assert rows["pre_mood"]["sample_count"] == 2
    assert rows["pre_mood"]["mean_residual"] == pytest.approx(0.4)
    assert rows["pre_energy"]["sample_count"] == 1
    assert rows["pre_energy"]["mean_abs_residual"] == pytest.approx(0.3)
    assert rows["post_productivity"]["sample_count"] == 1
    assert rows["post_productivity"]["mean_residual"] == pytest.approx(0.5)


def test_m5_poll_once_uses_local_open_state_and_finalises_in_arrival_order(db_conn):
    cur = db_conn.cursor()

    first_task_id = write_task(
        db_conn,
        description="First open task",
        deadline_iso=datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
        google_task_id="g_first",
        embedding=[0.1] * 768,
    )
    second_task_id = write_task(
        db_conn,
        description="Second open task",
        deadline_iso=datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
        google_task_id="g_second",
        embedding=[0.1] * 768,
    )
    already_complete_id = write_task(
        db_conn,
        description="Already complete locally",
        deadline_iso=datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
        google_task_id="g_done",
        embedding=[0.1] * 768,
    )
    complete_task(
        db_conn,
        task_id=already_complete_id,
        completed_at_iso=datetime(2026, 4, 25, 9, 0, tzinfo=timezone.utc).isoformat(),
    )

    for task_id, event_id in [
        (first_task_id, "e_first"),
        (second_task_id, "e_second"),
        (already_complete_id, "e_done"),
    ]:
        link_task_event(
            db_conn,
            task_id=task_id,
            google_event_id=event_id,
            planned_start_iso=datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc).isoformat(),
            planned_end_iso=datetime(2026, 4, 25, 11, 0, tzinfo=timezone.utc).isoformat(),
        )
        cur.execute(
            "INSERT INTO predictions (task_id, pred_duration_min, created_at) VALUES (?, ?, datetime('now'))",
            (task_id, 60),
        )
    db_conn.commit()

    calls: list[str] = []

    class MockTasks:
        def get(self, task_id: str) -> GTask:
            calls.append(task_id)
            return GTask(
                id=task_id,
                title=task_id,
                due=None,
                status="completed",
                completed_at=datetime(2026, 4, 25, 10, 30, tzinfo=timezone.utc),
                raw={},
            )

    finalised = poll_once(db_conn, MockTasks())

    assert finalised == [first_task_id, second_task_id]
    assert calls == ["g_first", "g_second"]
