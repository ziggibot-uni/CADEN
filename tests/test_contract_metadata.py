import sqlite3
import threading
from datetime import datetime, timezone

import pytest

from caden.errors import DBError
from caden.libbie import store as store_module
from caden.libbie.store import (
    append_event_metadata,
    complete_task,
    event_has_metadata_key,
    link_task_event,
    load_event,
    recent_events,
    update_task_event_plan,
    write_event,
    write_prediction,
    write_rating,
    write_residual,
    write_task,
)


def test_write_event_appends_event_metadata_rows(db_conn):
    event_id = write_event(
        db_conn,
        "sean_chat",
        "metadata test",
        [0.1] * 768,
        meta={"trigger": "chat_send", "linked_to": 123},
    )

    rows = db_conn.cursor().execute(
        "SELECT key, value FROM event_metadata WHERE event_id=? ORDER BY key, value",
        (event_id,),
    ).fetchall()
    pairs = {(row["key"], row["value"]) for row in rows}

    assert ("trigger", "chat_send") in pairs
    assert ("linked_to", "123") in pairs
    assert any(key == "captured_at" for key, _ in pairs)

    memory_row = db_conn.cursor().execute(
        "SELECT source, context, outcome, embedding_text FROM memories WHERE event_id=?",
        (event_id,),
    ).fetchone()
    assert memory_row is not None, "events written to Libbie must also yield a curated memory row"
    assert memory_row["source"] == "sean_chat"
    assert "metadata test" in memory_row["context"]
    assert "metadata test" in memory_row["embedding_text"]


def test_write_event_supports_documented_why_project_and_entry_type_metadata_keys(db_conn):
    event_id = write_event(
        db_conn,
        "sean_chat",
        "metadata conventions",
        [0.1] * 768,
        meta={
            "why": "Sean wanted the capture rationale preserved.",
            "project_id": None,
            "entry_type": "comment",
        },
    )

    pairs = {
        (row["key"], row["value"])
        for row in db_conn.cursor().execute(
            "SELECT key, value FROM event_metadata WHERE event_id=?",
            (event_id,),
        ).fetchall()
    }

    assert ("why", "Sean wanted the capture rationale preserved.") in pairs
    assert ("project_id", "null") in pairs
    assert ("entry_type", "comment") in pairs


def test_append_event_metadata_adds_why_later_without_mutating_event_row(db_conn):
    event_id = write_event(
        db_conn,
        "sean_chat",
        "Capture now; enrich why later.",
        [0.1] * 768,
        meta={"trigger": "chat_send"},
    )

    before_raw = db_conn.execute(
        "SELECT raw_text, meta_json FROM events WHERE id=?",
        (event_id,),
    ).fetchone()
    assert before_raw is not None
    assert event_has_metadata_key(db_conn, event_id, "why") is False

    append_event_metadata(db_conn, event_id, "why", "captured because it clarifies present state")

    after_raw = db_conn.execute(
        "SELECT raw_text, meta_json FROM events WHERE id=?",
        (event_id,),
    ).fetchone()
    assert after_raw is not None
    assert after_raw["raw_text"] == before_raw["raw_text"]
    assert after_raw["meta_json"] == before_raw["meta_json"]
    assert event_has_metadata_key(db_conn, event_id, "why") is True

    why_rows = db_conn.execute(
        "SELECT value FROM event_metadata WHERE event_id=? AND key='why'",
        (event_id,),
    ).fetchall()
    assert [row["value"] for row in why_rows] == [
        "captured because it clarifies present state"
    ]


def test_event_metadata_writes_are_append_only_at_the_sql_boundary(db_conn):
    statements: list[str] = []
    db_conn.set_trace_callback(statements.append)
    try:
        write_event(
            db_conn,
            "sean_chat",
            "append-only metadata test",
            [0.1] * 768,
            meta={"trigger": "chat_send", "linked_to": 456},
        )
    finally:
        db_conn.set_trace_callback(None)

    metadata_sql = [statement.upper() for statement in statements if "EVENT_METADATA" in statement.upper()]

    assert any("INSERT INTO EVENT_METADATA" in statement for statement in metadata_sql)
    assert all("UPDATE EVENT_METADATA" not in statement for statement in metadata_sql)
    assert all("DELETE FROM EVENT_METADATA" not in statement for statement in metadata_sql)


def test_write_event_keeps_raw_events_append_only_at_the_sql_boundary(db_conn):
    statements: list[str] = []
    db_conn.set_trace_callback(statements.append)
    try:
        write_event(
            db_conn,
            "sean_chat",
            "immutable raw event",
            [0.1] * 768,
            meta={"trigger": "chat_send"},
        )
    finally:
        db_conn.set_trace_callback(None)

    event_sql = [statement.upper() for statement in statements if "EVENTS" in statement.upper()]

    assert any("INSERT INTO EVENTS" in statement for statement in event_sql)
    assert all("UPDATE EVENTS" not in statement for statement in event_sql)
    assert all("DELETE FROM EVENTS" not in statement for statement in event_sql)


def test_raw_events_can_be_replayed_with_provenance_and_memory_linkage(db_conn):
    event_id = write_event(
        db_conn,
        "sean_chat",
        "Replay this exact message later.",
        [0.1] * 768,
        meta={"trigger": "chat_send", "why": "audit trail"},
    )

    event = load_event(db_conn, event_id)
    memory_row = db_conn.execute(
        "SELECT event_id, source FROM memories WHERE event_id=?",
        (event_id,),
    ).fetchone()

    assert event is not None
    assert event.id == event_id
    assert event.source == "sean_chat"
    assert event.raw_text == "Replay this exact message later."
    assert event.meta["trigger"] == "chat_send"
    assert event.meta["why"] == "audit trail"
    assert memory_row is not None
    assert memory_row["event_id"] == event_id
    assert memory_row["source"] == "sean_chat"


def test_recent_events_retains_a_queryable_trace_of_sean_behavior_over_time(db_conn):
    first_id = write_event(
        db_conn,
        "sean_chat",
        "first behavior trace",
        [0.1] * 768,
        meta={"trigger": "chat_send"},
    )
    second_id = write_event(
        db_conn,
        "sean_chat",
        "second behavior trace",
        [0.1] * 768,
        meta={"trigger": "chat_send"},
    )

    events = recent_events(db_conn, limit=2, sources=("sean_chat",))

    assert [event.id for event in events] == [second_id, first_id]
    assert [event.raw_text for event in events] == [
        "second behavior trace",
        "first behavior trace",
    ]
    assert all(event.source == "sean_chat" for event in events)
    assert all(datetime.fromisoformat(event.timestamp).tzinfo is not None for event in events)


def test_memory_frame_contract_preserves_required_invariants(db_conn):
    event_id = write_event(
        db_conn,
        "sean_chat",
        "Sean does better with a short concrete next step.",
        [0.1] * 768,
        meta={"domain": "self_knowledge", "trigger": "chat_send"},
    )

    row = db_conn.cursor().execute(
        """
        SELECT event_id, memory_key, memory_type, source, domain,
               tags_json, context, outcome, hooks_json, embedding_text
        FROM memories
        WHERE event_id=?
        """,
        (event_id,),
    ).fetchone()

    assert row is not None
    assert row["event_id"] == event_id
    assert row["memory_key"] == f"event:{event_id}"
    assert row["source"] == "sean_chat"
    assert row["memory_type"] == "experience"
    assert row["domain"] == "self_knowledge"
    assert row["context"].strip()
    assert row["outcome"].strip()
    assert row["embedding_text"].strip()
    assert "short concrete next step" in row["embedding_text"]

    tags = set(__import__("json").loads(row["tags_json"]))
    hooks = __import__("json").loads(row["hooks_json"])

    assert "sean_chat" in tags
    assert "self_knowledge" in tags
    assert hooks, "memory frames must expose at least one retrieval hook"


def test_memory_embedding_text_is_built_from_meaning_bearing_frame_content(db_conn):
    event_id = write_event(
        db_conn,
        "residual",
        "Short raw text",
        [0.1] * 768,
        meta={
            "domain": "planning",
            "rationale": "Longer semantic rationale for future retrieval.",
            "outcome": "Sean finished faster after scoping smaller.",
        },
    )

    row = db_conn.cursor().execute(
        "SELECT context, outcome, embedding_text FROM memories WHERE event_id=?",
        (event_id,),
    ).fetchone()

    assert row is not None
    assert row["context"] == "Short raw text"
    assert row["outcome"] == "Longer semantic rationale for future retrieval."
    assert "planning" in row["embedding_text"]
    assert "residual" in row["embedding_text"]
    assert "Longer semantic rationale for future retrieval." in row["embedding_text"]
    assert row["embedding_text"] != row["context"]


def test_task_event_rows_are_mirrored_into_events(db_conn):
    task_id = write_task(
        db_conn,
        description="Mirror me",
        deadline_iso=datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
        google_task_id="g_1",
        embedding=[0.1] * 768,
    )
    task_event_id = link_task_event(
        db_conn,
        task_id=task_id,
        google_event_id="e_1",
        planned_start_iso=datetime(2026, 4, 25, 10, 0, tzinfo=timezone.utc).isoformat(),
        planned_end_iso=datetime(2026, 4, 25, 11, 0, tzinfo=timezone.utc).isoformat(),
    )

    cur = db_conn.cursor()
    event_row = cur.execute(
        "SELECT id FROM events WHERE source='task_event' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    assert event_row is not None, "task_event rows must be mirrored into events"

    metadata_rows = cur.execute(
        "SELECT key, value FROM event_metadata WHERE event_id=?",
        (event_row["id"],),
    ).fetchall()
    pairs = {(row["key"], row["value"]) for row in metadata_rows}

    assert ("structured_id", str(task_event_id)) in pairs


def test_task_rows_are_mirrored_into_events(db_conn):
    task_id = write_task(
        db_conn,
        description="Task mirror check",
        deadline_iso=datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
        google_task_id="g_task_mirror",
        embedding=[0.1] * 768,
    )

    event_row = db_conn.cursor().execute(
        "SELECT id FROM events WHERE source='task' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert event_row is not None

    pairs = {
        (row["key"], row["value"])
        for row in db_conn.cursor().execute(
            "SELECT key, value FROM event_metadata WHERE event_id=?",
            (event_row["id"],),
        ).fetchall()
    }
    assert ("structured_id", str(task_id)) in pairs
    assert ("task_id", str(task_id)) in pairs


def test_tasks_table_stores_identity_deadline_status_and_completion_time(db_conn):
    deadline = datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat()
    completed_at = datetime(2026, 4, 29, 15, 45, tzinfo=timezone.utc).isoformat()

    task_id = write_task(
        db_conn,
        description="Task table contract",
        deadline_iso=deadline,
        google_task_id="g_task_contract",
        embedding=[0.1] * 768,
    )

    before = db_conn.cursor().execute(
        "SELECT google_task_id, description, deadline_utc, status, completed_at_utc FROM tasks WHERE id=?",
        (task_id,),
    ).fetchone()

    assert before is not None
    assert before["google_task_id"] == "g_task_contract"
    assert before["description"] == "Task table contract"
    assert before["deadline_utc"] == deadline
    assert before["status"] == "open"
    assert before["completed_at_utc"] is None

    complete_task(db_conn, task_id, completed_at)

    after = db_conn.cursor().execute(
        "SELECT google_task_id, description, deadline_utc, status, completed_at_utc FROM tasks WHERE id=?",
        (task_id,),
    ).fetchone()

    assert after is not None
    assert after["google_task_id"] == "g_task_contract"
    assert after["description"] == "Task table contract"
    assert after["deadline_utc"] == deadline
    assert after["status"] == "complete"
    assert after["completed_at_utc"] == completed_at


def test_stored_timestamps_use_iso8601_with_explicit_utc_offset(db_conn):
    deadline = datetime(2026, 4, 30, 18, 0, tzinfo=timezone.utc).isoformat()
    planned_start = datetime(2026, 4, 29, 14, 0, tzinfo=timezone.utc).isoformat()
    planned_end = datetime(2026, 4, 29, 15, 0, tzinfo=timezone.utc).isoformat()
    completed_at = datetime(2026, 4, 29, 14, 45, tzinfo=timezone.utc).isoformat()

    event_id = write_event(
        db_conn,
        "sean_chat",
        "Timestamp contract event",
        [0.1] * 768,
        timestamp=planned_start,
    )
    write_rating(
        db_conn,
        event_id=event_id,
        mood=0.2,
        energy=0.1,
        productivity=0.3,
        c_mood=0.8,
        c_energy=0.8,
        c_productivity=0.8,
        rationale="timestamp contract rating",
        embedding=[0.1] * 768,
    )

    task_id = write_task(
        db_conn,
        description="Timestamp contract task",
        deadline_iso=deadline,
        google_task_id="g_timestamp_contract",
        embedding=[0.1] * 768,
    )
    link_task_event(
        db_conn,
        task_id=task_id,
        google_event_id="evt_timestamp_contract",
        planned_start_iso=planned_start,
        planned_end_iso=planned_end,
    )
    complete_task(db_conn, task_id, completed_at)

    prediction_id = write_prediction(
        db_conn,
        task_id=task_id,
        google_event_id="evt_timestamp_contract",
        predicted_duration_min=60,
        pre=(0.1, 0.0, -0.1),
        post=(0.2, 0.1, 0.3),
        confidences={
            "duration": 0.8,
            "pre_mood": 0.7,
            "pre_energy": 0.7,
            "pre_productivity": 0.7,
            "post_mood": 0.6,
            "post_energy": 0.6,
            "post_productivity": 0.6,
        },
        rationale="timestamp contract prediction",
        embedding=[0.1] * 768,
    )
    residual_id = write_residual(
        db_conn,
        prediction_id=prediction_id,
        duration_actual_min=45,
        duration_residual_min=-15,
        pre_residuals=(0.1, 0.2, 0.3),
        post_residuals=(0.2, 0.1, 0.0),
        embedding=None,
    )

    timestamp_values = [
        db_conn.execute("SELECT timestamp FROM events WHERE id=?", (event_id,)).fetchone()["timestamp"],
        db_conn.execute("SELECT created_at FROM ratings ORDER BY id DESC LIMIT 1").fetchone()["created_at"],
        db_conn.execute(
            "SELECT deadline_utc, created_at, completed_at_utc FROM tasks WHERE id=?",
            (task_id,),
        ).fetchone()["deadline_utc"],
        db_conn.execute(
            "SELECT deadline_utc, created_at, completed_at_utc FROM tasks WHERE id=?",
            (task_id,),
        ).fetchone()["created_at"],
        db_conn.execute(
            "SELECT deadline_utc, created_at, completed_at_utc FROM tasks WHERE id=?",
            (task_id,),
        ).fetchone()["completed_at_utc"],
        db_conn.execute(
            "SELECT planned_start, planned_end, actual_end FROM task_events WHERE task_id=?",
            (task_id,),
        ).fetchone()["planned_start"],
        db_conn.execute(
            "SELECT planned_start, planned_end, actual_end FROM task_events WHERE task_id=?",
            (task_id,),
        ).fetchone()["planned_end"],
        db_conn.execute(
            "SELECT planned_start, planned_end, actual_end FROM task_events WHERE task_id=?",
            (task_id,),
        ).fetchone()["actual_end"],
        db_conn.execute("SELECT created_at FROM predictions WHERE id=?", (prediction_id,)).fetchone()["created_at"],
        db_conn.execute("SELECT created_at FROM residuals WHERE id=?", (residual_id,)).fetchone()["created_at"],
        db_conn.execute(
            "SELECT created_at FROM event_metadata WHERE event_id=? ORDER BY id LIMIT 1",
            (event_id,),
        ).fetchone()["created_at"],
    ]

    for value in timestamp_values:
        parsed = datetime.fromisoformat(value)
        assert parsed.tzinfo is not None


def test_all_runtime_db_writes_serialize_through_one_queue(db_conn):
    task_id = write_task(
        db_conn,
        description="Queue discipline task",
        deadline_iso=datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
        google_task_id="g_queue_discipline",
        embedding=[0.1] * 768,
    )
    link_task_event(
        db_conn,
        task_id=task_id,
        google_event_id="evt_queue_discipline",
        planned_start_iso=datetime(2026, 4, 29, 10, 0, tzinfo=timezone.utc).isoformat(),
        planned_end_iso=datetime(2026, 4, 29, 11, 0, tzinfo=timezone.utc).isoformat(),
    )

    gate_first = threading.Event()
    release_first = threading.Event()
    observed = {"active": 0, "max_active": 0}
    started = {"count": 0}
    state_lock = threading.Lock()

    def _observe(phase: str):
        if phase == "start":
            with state_lock:
                observed["active"] += 1
                observed["max_active"] = max(observed["max_active"], observed["active"])
                started["count"] += 1
                is_first = started["count"] == 1
            if is_first:
                gate_first.set()
                release_first.wait(timeout=2)
        else:
            with state_lock:
                observed["active"] -= 1

    store_module._WRITE_OBSERVER = _observe
    try:
        first = threading.Thread(
            target=update_task_event_plan,
            args=(
                db_conn,
                "evt_queue_discipline",
                datetime(2026, 4, 29, 12, 0, tzinfo=timezone.utc).isoformat(timespec="seconds"),
                datetime(2026, 4, 29, 13, 0, tzinfo=timezone.utc).isoformat(timespec="seconds"),
            ),
        )
        second = threading.Thread(
            target=update_task_event_plan,
            args=(
                db_conn,
                "evt_queue_discipline",
                datetime(2026, 4, 29, 14, 0, tzinfo=timezone.utc).isoformat(timespec="seconds"),
                datetime(2026, 4, 29, 15, 0, tzinfo=timezone.utc).isoformat(timespec="seconds"),
            ),
        )

        first.start()
        assert gate_first.wait(timeout=2)
        second.start()
        release_first.set()
        first.join(timeout=2)
        second.join(timeout=2)
    finally:
        store_module._WRITE_OBSERVER = None

    assert observed["max_active"] == 1
    row = db_conn.execute(
        "SELECT planned_start, planned_end FROM task_events WHERE google_event_id=?",
        ("evt_queue_discipline",),
    ).fetchone()
    assert row is not None
    assert row["planned_start"] == datetime(2026, 4, 29, 14, 0, tzinfo=timezone.utc).isoformat(timespec="seconds")
    assert row["planned_end"] == datetime(2026, 4, 29, 15, 0, tzinfo=timezone.utc).isoformat(timespec="seconds")


def test_write_prediction_persists_rationale_and_confidence_fields(db_conn):
    task_id = write_task(
        db_conn,
        description="Predict me",
        deadline_iso=datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
        google_task_id="g_pred",
        embedding=[0.1] * 768,
    )

    prediction_id = write_prediction(
        db_conn,
        task_id=task_id,
        google_event_id="evt_pred",
        predicted_duration_min=45,
        pre=(0.2, 0.4, 0.6),
        post=(0.3, 0.5, 0.7),
        confidences={
            "duration": 0.8,
            "pre_mood": 0.6,
            "pre_energy": 0.7,
            "pre_productivity": 0.5,
            "post_mood": 0.4,
            "post_energy": 0.3,
            "post_productivity": 0.2,
        },
        rationale="Short focused tasks usually finish on time.",
        embedding=[0.1] * 768,
    )

    row = db_conn.cursor().execute(
        """
        SELECT pred_duration_min,
               pred_pre_mood, pred_pre_energy, pred_pre_productivity,
               pred_post_mood, pred_post_energy, pred_post_productivity,
               rationale,
               conf_duration, conf_pre_mood, conf_pre_energy, conf_pre_productivity,
               conf_post_mood, conf_post_energy, conf_post_productivity
        FROM predictions
        WHERE id=?
        """,
        (prediction_id,),
    ).fetchone()

    assert row is not None
    assert row["pred_duration_min"] == 45
    assert row["pred_pre_mood"] == 0.2
    assert row["pred_pre_energy"] == 0.4
    assert row["pred_pre_productivity"] == 0.6
    assert row["pred_post_mood"] == 0.3
    assert row["pred_post_energy"] == 0.5
    assert row["pred_post_productivity"] == 0.7
    assert row["rationale"] == "Short focused tasks usually finish on time."
    assert row["conf_duration"] == 0.8
    assert row["conf_pre_mood"] == 0.6
    assert row["conf_pre_energy"] == 0.7
    assert row["conf_pre_productivity"] == 0.5
    assert row["conf_post_mood"] == 0.4
    assert row["conf_post_energy"] == 0.3
    assert row["conf_post_productivity"] == 0.2

    mirrored = db_conn.cursor().execute(
        "SELECT id FROM events WHERE source='prediction' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert mirrored is not None

    memory_row = db_conn.cursor().execute(
        "SELECT source, context, outcome, embedding_text FROM memories WHERE event_id=?",
        (mirrored["id"],),
    ).fetchone()
    assert memory_row is not None
    assert memory_row["source"] == "prediction"
    assert "Prediction for task" in memory_row["context"]
    assert "Short focused tasks usually finish on time." in memory_row["outcome"]
    assert "duration=45min" in memory_row["embedding_text"]


def test_write_rating_rows_are_mirrored_into_events(db_conn):
    event_id = write_event(
        db_conn,
        "sean_chat",
        "rating source event",
        [0.1] * 768,
        meta={},
    )

    rating_id = write_rating(
        db_conn,
        event_id=event_id,
        mood=0.1,
        energy=0.2,
        productivity=0.3,
        c_mood=0.4,
        c_energy=0.5,
        c_productivity=0.6,
        rationale="Useful rating rationale.",
        embedding=[0.1] * 768,
    )

    mirrored = db_conn.cursor().execute(
        "SELECT id FROM events WHERE source='rating' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert mirrored is not None

    pairs = {
        (row["key"], row["value"])
        for row in db_conn.cursor().execute(
            "SELECT key, value FROM event_metadata WHERE event_id=?",
            (mirrored["id"],),
        ).fetchall()
    }
    assert ("structured_id", str(rating_id)) in pairs
    assert ("rating_id", str(rating_id)) in pairs


def test_write_rating_appends_new_rows_without_overwriting_historical_ratings(db_conn):
    source_event_id = write_event(
        db_conn,
        "sean_chat",
        "same event, two later ratings",
        [0.1] * 768,
        meta={},
    )

    first_rating_id = write_rating(
        db_conn,
        event_id=source_event_id,
        mood=0.1,
        energy=0.2,
        productivity=0.3,
        c_mood=0.4,
        c_energy=0.5,
        c_productivity=0.6,
        rationale="first snapshot",
        embedding=[0.1] * 768,
    )
    second_rating_id = write_rating(
        db_conn,
        event_id=source_event_id,
        mood=0.7,
        energy=0.8,
        productivity=0.9,
        c_mood=0.3,
        c_energy=0.2,
        c_productivity=0.1,
        rationale="second snapshot",
        embedding=[0.1] * 768,
    )

    rows = db_conn.cursor().execute(
        "SELECT id, mood, rationale FROM ratings WHERE event_id=? ORDER BY id",
        (source_event_id,),
    ).fetchall()

    assert [row["id"] for row in rows] == [first_rating_id, second_rating_id]
    assert rows[0]["mood"] == 0.1
    assert rows[0]["rationale"] == "first snapshot"
    assert rows[1]["mood"] == 0.7
    assert rows[1]["rationale"] == "second snapshot"


def test_write_rating_never_updates_or_deletes_existing_rating_rows(db_conn):
    source_event_id = write_event(
        db_conn,
        "sean_chat",
        "rating immutability trace",
        [0.1] * 768,
        meta={},
    )
    statements: list[str] = []
    db_conn.set_trace_callback(statements.append)
    try:
        write_rating(
            db_conn,
            event_id=source_event_id,
            mood=0.1,
            energy=0.2,
            productivity=0.3,
            c_mood=0.4,
            c_energy=0.5,
            c_productivity=0.6,
            rationale="immutable rating",
            embedding=[0.1] * 768,
        )
    finally:
        db_conn.set_trace_callback(None)

    rating_sql = [statement.upper() for statement in statements if "RATINGS" in statement.upper()]

    assert any("INSERT INTO RATINGS" in statement for statement in rating_sql)
    assert all("UPDATE RATINGS" not in statement for statement in rating_sql)
    assert all("DELETE FROM RATINGS" not in statement for statement in rating_sql)


def test_write_residual_creates_curated_memory_from_structured_row(db_conn):
    task_id = write_task(
        db_conn,
        description="Residual memory trace",
        deadline_iso=datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
        google_task_id="g_residual_memory",
        embedding=[0.1] * 768,
    )
    prediction_id = write_prediction(
        db_conn,
        task_id=task_id,
        google_event_id="evt_pred_memory",
        predicted_duration_min=45,
        pre=(0.1, 0.2, 0.3),
        post=(0.4, 0.5, 0.6),
        confidences={
            "duration": 0.9,
            "pre_mood": 0.8,
            "pre_energy": 0.8,
            "pre_productivity": 0.8,
            "post_mood": 0.7,
            "post_energy": 0.7,
            "post_productivity": 0.7,
        },
        rationale="Prediction rationale",
        embedding=[0.1] * 768,
    )

    residual_id = write_residual(
        db_conn,
        prediction_id=prediction_id,
        duration_actual_min=30,
        duration_residual_min=-15,
        pre_residuals=(0.2, 0.3, 0.4),
        post_residuals=(0.5, 0.6, 0.7),
        embedding=None,
    )

    mirrored = db_conn.cursor().execute(
        "SELECT id FROM events WHERE source='residual' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert mirrored is not None

    memory_row = db_conn.cursor().execute(
        "SELECT memory_key, source, context, outcome, hooks_json, embedding_text FROM memories WHERE event_id=?",
        (mirrored["id"],),
    ).fetchone()
    assert memory_row is not None
    assert memory_row["memory_key"] == f"event:{mirrored['id']}"
    assert memory_row["source"] == "residual"
    assert "Residuals for prediction" in memory_row["context"]
    assert "duration_residual=-15min" in memory_row["outcome"]
    assert "residual" in memory_row["embedding_text"]
    assert "prediction" in memory_row["embedding_text"]


def test_write_prediction_and_rating_reject_invalid_unknown_sentinels_and_confidence_bounds(db_conn):
    task_id = write_task(
        db_conn,
        description="Reject bad values",
        deadline_iso=datetime(2026, 4, 30, tzinfo=timezone.utc).isoformat(),
        google_task_id="g_bad",
        embedding=[0.1] * 768,
    )
    event_id = write_event(
        db_conn,
        "sean_chat",
        "event for ratings",
        [0.1] * 768,
        meta={},
    )

    with pytest.raises(DBError, match="outside the allowed \[0.0, 1.0\] range"):
        write_prediction(
            db_conn,
            task_id=task_id,
            google_event_id=None,
            predicted_duration_min=30,
            pre=(0.1, 0.2, 0.3),
            post=(0.4, 0.5, 0.6),
            confidences={"duration": 1.2},
            rationale="bad confidence",
            embedding=None,
        )

    with pytest.raises(DBError, match="forbidden sentinel value"):
        write_rating(
            db_conn,
            event_id=event_id,
            mood=-1,
            energy=0.5,
            productivity=0.5,
            c_mood=0.4,
            c_energy=0.4,
            c_productivity=0.4,
            rationale="bad sentinel",
            embedding=None,
        )


def test_write_event_wraps_sqlite_failures_with_chained_dberror(db_conn):
    db_conn.close()

    with pytest.raises(DBError, match="failed to write event") as exc_info:
        write_event(
            db_conn,
            "sean_chat",
            "cannot write to a closed connection",
            [0.1] * 768,
            meta={},
        )

    assert isinstance(exc_info.value.__cause__, sqlite3.Error)