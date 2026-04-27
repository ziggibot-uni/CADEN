"""Writes into Libbie.

Every write goes through here. Nothing else is allowed to execute INSERTs
against the DB. That is how we keep the invariant that structured rows
(ratings, predictions, residuals, tasks) are mirrored into the events log.
"""

from __future__ import annotations

from collections import deque
import json
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Sequence, TypeVar

from ..errors import DBError
from ..learning.schema import MemoryFrame
from . import db as _db

@dataclass
class _WriteQueueState:
    condition: threading.Condition = field(default_factory=threading.Condition)
    waiters: deque[object] = field(default_factory=deque)
    owner_ident: int | None = None
    depth: int = 0


_WRITE_QUEUES: dict[int, _WriteQueueState] = {}
_WRITE_QUEUES_LOCK = threading.Lock()
_TOKEN_RE = re.compile(r"[a-z0-9_]{3,}", re.IGNORECASE)
_STOPWORDS = {
    "the", "and", "for", "that", "with", "this", "from", "have", "what",
    "when", "your", "just", "into", "then", "they", "them", "been", "were",
    "will", "would", "could", "should", "about", "there", "their", "while",
}

_FORBIDDEN_UNKNOWN_SENTINELS = {-1.0, 999.0}
_R = TypeVar("_R")
_WRITE_OBSERVER: Callable[[str], None] | None = None


def _write_queue_state(conn: sqlite3.Connection) -> _WriteQueueState:
    key = id(conn)
    with _WRITE_QUEUES_LOCK:
        state = _WRITE_QUEUES.get(key)
        if state is None:
            state = _WriteQueueState()
            _WRITE_QUEUES[key] = state
        return state


def close_write_queue(conn: sqlite3.Connection) -> None:
    with _WRITE_QUEUES_LOCK:
        _WRITE_QUEUES.pop(id(conn), None)


def _run_write(conn: sqlite3.Connection, func: Callable[[], _R]) -> _R:
    state = _write_queue_state(conn)
    current_ident = threading.get_ident()

    with state.condition:
        if state.owner_ident == current_ident:
            state.depth += 1
            reentrant = True
            token = None
        else:
            token = object()
            state.waiters.append(token)
            while state.owner_ident is not None or state.waiters[0] is not token:
                state.condition.wait()
            state.owner_ident = current_ident
            state.depth = 1
            reentrant = False

    try:
        if _WRITE_OBSERVER is not None:
            _WRITE_OBSERVER("start")
        return func()
    finally:
        if _WRITE_OBSERVER is not None:
            _WRITE_OBSERVER("end")
        with state.condition:
            state.depth -= 1
            if state.depth == 0:
                state.owner_ident = None
                if not reentrant and token is not None and state.waiters and state.waiters[0] is token:
                    state.waiters.popleft()
                state.condition.notify_all()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _meta_value_text(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _append_event_metadata(
    conn: sqlite3.Connection,
    event_id: int,
    meta: dict[str, Any],
    *,
    created_at: str,
) -> None:
    rows = [(event_id, "captured_at", created_at, created_at)]
    for key, value in meta.items():
        if key == "captured_at":
            continue
        rows.append((event_id, key, _meta_value_text(value), created_at))
    conn.executemany(
        "INSERT INTO event_metadata (event_id, key, value, created_at) VALUES (?, ?, ?, ?)",
        rows,
    )


@dataclass(frozen=True)
class Event:
    id: int
    timestamp: str
    source: str
    raw_text: str
    meta: dict


def _tokenize(text: str, *, limit: int = 8) -> tuple[str, ...]:
    seen: list[str] = []
    for match in _TOKEN_RE.findall(text.lower()):
        if match in _STOPWORDS or match in seen:
            continue
        seen.append(match)
        if len(seen) >= limit:
            break
    return tuple(seen)


def _memory_type_for_source(source: str) -> str:
    if source in {"rating", "prediction"}:
        return "rule"
    if source == "residual":
        return "pattern"
    return "experience"


def _summary_text(text: str, *, limit: int = 240) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _validate_optional_score(name: str, value: float | None) -> None:
    if value is None:
        return
    numeric = float(value)
    if numeric in _FORBIDDEN_UNKNOWN_SENTINELS:
        raise DBError(f"{name} uses forbidden sentinel value {numeric}; use NULL for unknown")


def _validate_optional_confidence(name: str, value: float | None) -> None:
    if value is None:
        return
    numeric = float(value)
    if numeric in _FORBIDDEN_UNKNOWN_SENTINELS:
        raise DBError(f"{name} uses forbidden sentinel value {numeric}; use NULL for unknown")
    if not 0.0 <= numeric <= 1.0:
        raise DBError(f"{name}={numeric} is outside the allowed [0.0, 1.0] range")


def _memory_frame_for_event(
    event_id: int,
    source: str,
    raw_text: str,
    meta: dict[str, Any],
) -> MemoryFrame:
    # This is intentionally deterministic transitional scaffolding: the
    # boundary from raw provenance to MemoryFrame is part of the contract,
    # but the exact token/hook phrasing here is not frozen architecture.
    tags = list(_tokenize(raw_text, limit=8))
    tags.insert(0, source)
    domain = str(meta.get("domain") or source).strip().replace(" ", "_")
    if domain not in tags:
        tags.append(domain)
    for key in meta.keys():
        key_text = str(key).strip()
        if key_text and key_text not in tags:
            tags.append(key_text)
    hooks = [f"when dealing with {source.replace('_', ' ')}"]
    for token in tags[1:4]:
        hooks.append(f"when {token.replace('_', ' ')} matters")
    outcome = str(meta.get("rationale") or meta.get("outcome") or raw_text).strip()
    embedding_text = " ".join(
        part for part in [domain, source, " ".join(tags), raw_text, outcome] if part
    )
    return MemoryFrame(
        id=f"event:{event_id}",
        type=_memory_type_for_source(source),
        domain=domain,
        tags=tuple(tags),
        context=_summary_text(raw_text, limit=500),
        outcome=_summary_text(outcome, limit=240),
        hooks=tuple(hooks),
        embedding_text=_summary_text(embedding_text, limit=1000),
    )


def _upsert_memory_row(
    conn: sqlite3.Connection,
    event_id: int,
    source: str,
    raw_text: str,
    meta: dict[str, Any],
    embedding: Sequence[float] | None,
) -> None:
    frame = _memory_frame_for_event(event_id, source, raw_text, meta)
    cur = conn.execute(
        """
        INSERT INTO memories (
          event_id, memory_key, memory_type, source, domain,
          tags_json, context, outcome, hooks_json, embedding_text, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(memory_key) DO UPDATE SET
          source=excluded.source,
          domain=excluded.domain,
          tags_json=excluded.tags_json,
          context=excluded.context,
          outcome=excluded.outcome,
          hooks_json=excluded.hooks_json,
          embedding_text=excluded.embedding_text
        """,
        (
            event_id,
            frame.id,
            frame.type,
            source,
            frame.domain,
            json.dumps(frame.tags, ensure_ascii=False),
            frame.context,
            frame.outcome,
            json.dumps(frame.hooks, ensure_ascii=False),
            frame.embedding_text,
            _now_iso(),
        ),
    )
    memory_id = int(cur.lastrowid or conn.execute(
        "SELECT id FROM memories WHERE memory_key=?", (frame.id,)
    ).fetchone()[0])
    if embedding is None:
        return
    blob = _db.pack_vector(embedding)
    conn.execute(
        "INSERT OR REPLACE INTO memory_embeddings (memory_id, embedding) VALUES (?, ?)",
        (memory_id, blob),
    )
    conn.execute(
        "INSERT OR REPLACE INTO vec_memories (rowid, embedding) VALUES (?, ?)",
        (memory_id, blob),
    )


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
    def _op() -> int:
        try:
            captured_at = _now_iso()
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
            _upsert_memory_row(conn, event_id, source, raw_text, meta or {}, embedding)
            _append_event_metadata(conn, event_id, meta or {}, created_at=captured_at)
            return event_id
        except sqlite3.Error as e:
            raise DBError(f"failed to write event (source={source!r}): {e}") from e
    return _run_write(conn, _op)


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
    _validate_optional_score("mood", mood)
    _validate_optional_score("energy", energy)
    _validate_optional_score("productivity", productivity)
    _validate_optional_confidence("conf_mood", c_mood)
    _validate_optional_confidence("conf_energy", c_energy)
    _validate_optional_confidence("conf_productivity", c_productivity)
    def _op() -> int:
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
                "structured_id": rating_id,
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
    return _run_write(conn, _op)


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
    def _op() -> int:
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
            meta={
                "structured_id": task_id,
                "task_id": task_id,
                "google_task_id": google_task_id,
                "deadline": deadline_iso,
            },
        )
        return task_id
    return _run_write(conn, _op)


def link_task_event(
    conn: sqlite3.Connection,
    task_id: int,
    google_event_id: str,
    planned_start_iso: str,
    planned_end_iso: str,
) -> int:
    def _op() -> int:
        try:
            cur = conn.execute(
                """
                INSERT INTO task_events
                                    (task_id, google_event_id, planned_start, planned_end)
                                VALUES (?, ?, ?, ?)
                """,
                                (task_id, google_event_id, planned_start_iso, planned_end_iso),
            )
            task_event_id = int(cur.lastrowid)
        except sqlite3.Error as e:
            raise DBError(f"failed to link task_event: {e}") from e

        write_event(
            conn,
            source="task_event",
            raw_text=(
                f"Task event for task #{task_id}: {planned_start_iso} -> {planned_end_iso} "
                f"(google_event_id={google_event_id})"
            ),
            embedding=None,
            meta={
                "structured_id": task_event_id,
                "task_id": task_id,
                "google_event_id": google_event_id,
                "planned_start": planned_start_iso,
                "planned_end": planned_end_iso,
            },
        )
        return task_event_id
    return _run_write(conn, _op)


def update_task_event_plan(
    conn: sqlite3.Connection,
    google_event_id: str,
    planned_start_iso: str,
    planned_end_iso: str,
) -> None:
    def _op() -> None:
        try:
            conn.execute(
                """
                UPDATE task_events
                SET planned_start=?, planned_end=?
                WHERE google_event_id=?
                """,
                (planned_start_iso, planned_end_iso, google_event_id),
            )
        except sqlite3.Error as e:
            raise DBError(f"failed to update task_event plan for {google_event_id!r}: {e}") from e

    _run_write(conn, _op)


def complete_task(
    conn: sqlite3.Connection,
    task_id: int,
    completed_at_iso: str,
) -> None:
    def _op() -> None:
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
    _run_write(conn, _op)


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
    _validate_optional_score("pred_pre_mood", pre[0])
    _validate_optional_score("pred_pre_energy", pre[1])
    _validate_optional_score("pred_pre_productivity", pre[2])
    _validate_optional_score("pred_post_mood", post[0])
    _validate_optional_score("pred_post_energy", post[1])
    _validate_optional_score("pred_post_productivity", post[2])
    _validate_optional_confidence("conf_duration", confidences.get("duration"))
    _validate_optional_confidence("conf_pre_mood", confidences.get("pre_mood"))
    _validate_optional_confidence("conf_pre_energy", confidences.get("pre_energy"))
    _validate_optional_confidence("conf_pre_productivity", confidences.get("pre_productivity"))
    _validate_optional_confidence("conf_post_mood", confidences.get("post_mood"))
    _validate_optional_confidence("conf_post_energy", confidences.get("post_energy"))
    _validate_optional_confidence("conf_post_productivity", confidences.get("post_productivity"))
    def _op() -> int:
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
                "structured_id": prediction_id,
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
    return _run_write(conn, _op)


def write_residual(
    conn: sqlite3.Connection,
    prediction_id: int,
    duration_actual_min: float | None,
    duration_residual_min: float | None,
    pre_residuals: tuple[float | None, float | None, float | None],
    post_residuals: tuple[float | None, float | None, float | None],
    embedding: Sequence[float] | None,
) -> int:
    def _op() -> int:
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
                "structured_id": residual_id,
                "residual_id": residual_id,
                "prediction_id": prediction_id,
                "duration_actual_min": duration_actual_min,
                "duration_residual_min": duration_residual_min,
                "pre": pre_residuals,
                "post": post_residuals,
            },
        )
        return residual_id
    return _run_write(conn, _op)


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


def event_has_metadata_key(
    conn: sqlite3.Connection,
    event_id: int,
    key: str,
) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM event_metadata
        WHERE event_id=? AND key=?
        LIMIT 1
        """,
        (event_id, key),
    ).fetchone()
    return row is not None


def append_event_metadata(
    conn: sqlite3.Connection,
    event_id: int,
    key: str,
    value: Any,
) -> None:
    """Append one metadata row for an existing event.

    This preserves append-only semantics: no updates, no deletes.
    """
    def _op() -> None:
        try:
            exists = conn.execute(
                "SELECT 1 FROM events WHERE id=? LIMIT 1",
                (event_id,),
            ).fetchone()
            if exists is None:
                raise DBError(f"cannot append metadata: event id {event_id} does not exist")
            conn.execute(
                "INSERT INTO event_metadata (event_id, key, value, created_at) VALUES (?, ?, ?, ?)",
                (event_id, key, _meta_value_text(value), _now_iso()),
            )
        except sqlite3.Error as e:
            raise DBError(f"failed to append metadata for event {event_id}: {e}") from e
    _run_write(conn, _op)


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
