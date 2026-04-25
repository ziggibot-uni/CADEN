"""Writes into Libbie.

Every write goes through here. Nothing else is allowed to execute INSERTs
against the DB. That is how we keep the invariant that structured rows
(ratings, predictions, residuals, tasks) are mirrored into the events log.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from ..errors import DBError
from . import db as _db

# Module-level write lock. Every write_* function takes this before touching
# the DB. The spec calls for "a single async write queue served by one
# coroutine"; for v0 this lock satisfies the same invariant (no two writers
# hold a transaction at once) without the queue ceremony. Reads are not
# guarded — WAL mode handles those. RLock so write_rating etc. can call
# write_event while still holding it.
_WRITE_LOCK = threading.RLock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Event:
    id: int
    timestamp: str
    source: str
    raw_text: str
    meta: dict


# ---- events ------------------------------------------------------------------

def write_event(
    conn: sqlite3.Connection,
    source: str,
    raw_text: str,
    embedding: Sequence[float] | None,
    meta: dict | None = None,
    timestamp: str | None = None,
) -> int:
    """Insert an event (and its embedding, if given). Returns event id.

    An event without an embedding is unusual but legal — callers who hold
    pure-structural records may write without one. Events that represent
    Sean's text, CADEN's text, ratings, predictions, or residuals should
    always have an embedding so retrieval sees them.
    """
    with _WRITE_LOCK:
        try:
            cur = conn.execute(
                "INSERT INTO events (timestamp, source, raw_text, meta_json) VALUES (?, ?, ?, ?)",
                (
                    timestamp or _now_iso(),
                    source,
                    raw_text,
                    json.dumps(meta or {}, ensure_ascii=False, sort_keys=True),
                ),
            )
            event_id = int(cur.lastrowid)
            if embedding is not None:
                blob = _db.pack_vector(embedding)
                conn.execute(
                    "INSERT INTO event_embeddings (event_id, embedding) VALUES (?, ?)",
                    (event_id, blob),
                )
                conn.execute(
                    "INSERT INTO vec_events (rowid, embedding) VALUES (?, ?)",
                    (event_id, blob),
                )
            return event_id
        except sqlite3.Error as e:
            raise DBError(f"failed to write event (source={source!r}): {e}") from e


# ---- ratings -----------------------------------------------------------------

def write_rating(
    conn: sqlite3.Connection,
    event_id: int,
    mood: float | None,
    energy: float | None,
    productivity: float | None,
    c_mood: float | None,
    c_energy: float | None,
    c_productivity: float | None,
    rationale: str,
    embedding: Sequence[float] | None,
) -> int:
    """Write a rating row and mirror it into events as source='rating'."""
    with _WRITE_LOCK:
        try:
            cur = conn.execute(
                """
                INSERT INTO ratings
                  (event_id, mood, energy, productivity,
                   conf_mood, conf_energy, conf_productivity,
                   rationale, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, mood, energy, productivity,
                 c_mood, c_energy, c_productivity, rationale, _now_iso()),
            )
            rating_id = int(cur.lastrowid)
        except sqlite3.Error as e:
            raise DBError(f"failed to write rating for event {event_id}: {e}") from e

        mirror_text = (
            f"Rating of event #{event_id}: "
            f"mood={_fmt(mood)} energy={_fmt(energy)} productivity={_fmt(productivity)}.\n"
            f"Rationale: {rationale}"
        )
        write_event(
            conn,
            source="rating",
            raw_text=mirror_text,
            embedding=embedding,
            meta={
                "rating_id": rating_id,
                "event_id": event_id,
                "mood": mood,
                "energy": energy,
                "productivity": productivity,
                "confidence": {
                    "mood": c_mood, "energy": c_energy, "productivity": c_productivity,
                },
            },
        )
        return rating_id


def _fmt(v: float | None) -> str:
    return "unknown" if v is None else f"{v:.3f}"


# ---- tasks & task_events -----------------------------------------------------

def write_task(
    conn: sqlite3.Connection,
    description: str,
    deadline_iso: str,
    google_task_id: str | None,
    embedding: Sequence[float] | None,
) -> int:
    with _WRITE_LOCK:
        try:
            cur = conn.execute(
                """
                INSERT INTO tasks
                  (google_task_id, description, deadline_utc, status, created_at)
                VALUES (?, ?, ?, 'open', ?)
                """,
                (google_task_id, description, deadline_iso, _now_iso()),
            )
            task_id = int(cur.lastrowid)
        except sqlite3.Error as e:
            raise DBError(f"failed to write task: {e}") from e

        write_event(
            conn,
            source="task",
            raw_text=f"Task: {description} (deadline {deadline_iso})",
            embedding=embedding,
            meta={"task_id": task_id, "google_task_id": google_task_id, "deadline": deadline_iso},
        )
        return task_id


def link_task_event(
    conn: sqlite3.Connection,
    task_id: int,
    google_event_id: str,
    chunk_index: int,
    chunk_count: int,
    planned_start_iso: str,
    planned_end_iso: str,
) -> int:
    with _WRITE_LOCK:
        try:
            cur = conn.execute(
                """
                INSERT INTO task_events
                  (task_id, google_event_id, chunk_index, chunk_count, planned_start, planned_end)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, google_event_id, chunk_index, chunk_count,
                 planned_start_iso, planned_end_iso),
            )
            return int(cur.lastrowid)
        except sqlite3.Error as e:
            raise DBError(f"failed to link task_event: {e}") from e


def complete_task(
    conn: sqlite3.Connection,
    task_id: int,
    completed_at_iso: str,
) -> None:
    with _WRITE_LOCK:
        try:
            conn.execute(
                "UPDATE tasks SET status='complete', completed_at_utc=? WHERE id=?",
                (completed_at_iso, task_id),
            )
            conn.execute(
                """
                UPDATE task_events SET actual_end=?
                WHERE task_id=? AND actual_end IS NULL
                """,
                (completed_at_iso, task_id),
            )
        except sqlite3.Error as e:
            raise DBError(f"failed to complete task {task_id}: {e}") from e


# ---- predictions -------------------------------------------------------------

def write_prediction(
    conn: sqlite3.Connection,
    task_id: int,
    google_event_id: str | None,
    predicted_duration_min: float,
    pre: tuple[float | None, float | None, float | None],
    post: tuple[float | None, float | None, float | None],
    confidences: dict[str, float | None],
    rationale: str,
    embedding: Sequence[float] | None,
) -> int:
    with _WRITE_LOCK:
        try:
            cur = conn.execute(
                """
                INSERT INTO predictions (
                  task_id, google_event_id, pred_duration_min,
                  pred_pre_mood, pred_pre_energy, pred_pre_productivity,
                  pred_post_mood, pred_post_energy, pred_post_productivity,
                  conf_duration,
                  conf_pre_mood, conf_pre_energy, conf_pre_productivity,
                  conf_post_mood, conf_post_energy, conf_post_productivity,
                  rationale,
                  created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id, google_event_id, int(round(predicted_duration_min)),
                    pre[0], pre[1], pre[2],
                    post[0], post[1], post[2],
                    confidences.get("duration"),
                    confidences.get("pre_mood"), confidences.get("pre_energy"), confidences.get("pre_productivity"),
                    confidences.get("post_mood"), confidences.get("post_energy"), confidences.get("post_productivity"),
                    rationale,
                    _now_iso(),
                ),
            )
            prediction_id = int(cur.lastrowid)
        except sqlite3.Error as e:
            raise DBError(f"failed to write prediction for task {task_id}: {e}") from e

        write_event(
            conn,
            source="prediction",
            raw_text=(
                f"Prediction for task #{task_id}: duration={predicted_duration_min:.0f}min. "
                f"Pre mood/energy/productivity={pre}. Post={post}. Rationale: {rationale}"
            ),
            embedding=embedding,
            meta={
                "prediction_id": prediction_id,
                "task_id": task_id,
                "google_event_id": google_event_id,
                "pre": pre,
                "post": post,
                "duration_min": predicted_duration_min,
                "confidence": confidences,
            },
        )
        return prediction_id


def write_residual(
    conn: sqlite3.Connection,
    prediction_id: int,
    duration_actual_min: float | None,
    duration_residual_min: float | None,
    pre_residuals: tuple[float | None, float | None, float | None],
    post_residuals: tuple[float | None, float | None, float | None],
    embedding: Sequence[float] | None,
) -> int:
    with _WRITE_LOCK:
        try:
            cur = conn.execute(
                """
                INSERT INTO residuals (
                  prediction_id,
                  duration_actual_min, duration_residual_min,
                  pre_state_residual_mood, pre_state_residual_energy, pre_state_residual_productivity,
                  post_state_residual_mood, post_state_residual_energy, post_state_residual_productivity,
                  created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prediction_id,
                    None if duration_actual_min is None else int(round(duration_actual_min)),
                    None if duration_residual_min is None else int(round(duration_residual_min)),
                    pre_residuals[0], pre_residuals[1], pre_residuals[2],
                    post_residuals[0], post_residuals[1], post_residuals[2],
                    _now_iso(),
                ),
            )
            residual_id = int(cur.lastrowid)
        except sqlite3.Error as e:
            raise DBError(f"failed to write residual for prediction {prediction_id}: {e}") from e

        write_event(
            conn,
            source="residual",
            raw_text=(
                f"Residuals for prediction #{prediction_id}: "
                f"duration_residual={duration_residual_min}min, "
                f"pre={pre_residuals}, post={post_residuals}"
            ),
            embedding=embedding,
            meta={
                "residual_id": residual_id,
                "prediction_id": prediction_id,
                "duration_actual_min": duration_actual_min,
                "duration_residual_min": duration_residual_min,
                "pre": pre_residuals,
                "post": post_residuals,
            },
        )
        return residual_id


# ---- reads convenience -------------------------------------------------------

def load_event(conn: sqlite3.Connection, event_id: int) -> Event | None:
    row = conn.execute(
        "SELECT id, timestamp, source, raw_text, meta_json FROM events WHERE id=?",
        (event_id,),
    ).fetchone()
    if row is None:
        return None
    return Event(
        id=row["id"],
        timestamp=row["timestamp"],
        source=row["source"],
        raw_text=row["raw_text"],
        meta=_safe_json(row["meta_json"]),
    )


def recent_events(
    conn: sqlite3.Connection,
    limit: int,
    sources: Sequence[str] | None = None,
) -> list[Event]:
    if sources:
        placeholders = ",".join("?" * len(sources))
        rows = conn.execute(
            f"""
            SELECT id, timestamp, source, raw_text, meta_json
            FROM events
            WHERE source IN ({placeholders})
            ORDER BY id DESC LIMIT ?
            """,
            (*sources, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, timestamp, source, raw_text, meta_json
            FROM events ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        Event(id=r["id"], timestamp=r["timestamp"], source=r["source"],
              raw_text=r["raw_text"], meta=_safe_json(r["meta_json"]))
        for r in rows
    ]


def _safe_json(s: Any) -> dict:
    if not s:
        return {}
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}
