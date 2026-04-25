"""Sqlite + sqlite-vec connection, schema, and migrations for Libbie.

The event table is the canonical memory: every meaningful thing that happens
to CADEN is written there. Structured tables (ratings, predictions, residuals,
tasks, task_events) exist only for fast typed access; their contents are also
mirrored into events so retrieval sees the whole story.

Vectors live in a sqlite-vec virtual table keyed to events.id. We store
embeddings as raw float32 bytes and let sqlite-vec do cosine similarity.
"""

from __future__ import annotations

import sqlite3
import struct
from pathlib import Path
from typing import Sequence

import sqlite_vec

from ..errors import DBError

SCHEMA_VERSION = 1


# ---- serialisation helpers ---------------------------------------------------

def pack_vector(vec: Sequence[float]) -> bytes:
    """Pack a float sequence into the float32 little-endian bytes sqlite-vec wants."""
    return struct.pack(f"{len(vec)}f", *[float(x) for x in vec])


def unpack_vector(blob: bytes) -> list[float]:
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


# ---- connection --------------------------------------------------------------

def connect(db_path: Path) -> sqlite3.Connection:
    """Open the DB, load sqlite-vec, and apply the schema.

    Raises DBError loudly if anything is off — this is a boot-time check.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # check_same_thread=False: the UI uses asyncio.to_thread to keep the
        # event loop free during LLM / embedder calls, and the same conn gets
        # touched from worker threads. WAL mode plus our serialized callers
        # make that safe.
        conn = sqlite3.connect(
            str(db_path), isolation_level=None, check_same_thread=False
        )
    except sqlite3.Error as e:
        raise DBError(f"could not open sqlite database at {db_path}: {e}") from e

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except (sqlite3.Error, AttributeError) as e:
        raise DBError(
            f"could not load sqlite-vec extension: {e}. "
            f"This usually means the installed sqlite3 was compiled without "
            f"load_extension support. Use a python built against a sqlite that allows extensions."
        ) from e

    # Verify sqlite-vec is really present and functional.
    try:
        row = conn.execute("SELECT vec_version()").fetchone()
    except sqlite3.Error as e:
        raise DBError(f"sqlite-vec loaded but vec_version() failed: {e}") from e
    if row is None or not row[0]:
        raise DBError("sqlite-vec reported no version string")

    return conn


# ---- schema ------------------------------------------------------------------

def apply_schema(conn: sqlite3.Connection, embed_dim: int) -> None:
    """Apply the v0 schema. Idempotent per SCHEMA_VERSION."""
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_info (
                version INTEGER PRIMARY KEY,
                embed_dim INTEGER NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        row = cur.execute("SELECT version, embed_dim FROM schema_info").fetchone()
        if row is not None:
            if row["version"] != SCHEMA_VERSION:
                raise DBError(
                    f"schema version mismatch: db has v{row['version']}, "
                    f"code expects v{SCHEMA_VERSION}. migrations are not yet implemented."
                )
            if row["embed_dim"] != embed_dim:
                raise DBError(
                    f"embed_dim mismatch: db was initialised with {row['embed_dim']}, "
                    f"config asks for {embed_dim}. choose one and do not change it silently."
                )
            return

        cur.executescript(
            f"""
            CREATE TABLE events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,          -- ISO-8601 UTC
                source      TEXT NOT NULL,         -- e.g. sean_chat, caden_chat, rating, prediction, residual, task, calendar
                raw_text    TEXT NOT NULL,
                meta_json   TEXT NOT NULL DEFAULT '{{}}'
            );
            CREATE INDEX events_source_ts ON events(source, timestamp);
            CREATE INDEX events_ts ON events(timestamp);

            -- One row per event that has an embedding. event_id is a plain FK
            -- so the sqlite-vec virtual table below can be rebuilt from this.
            CREATE TABLE event_embeddings (
                event_id INTEGER PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
                embedding BLOB NOT NULL
            );

            -- sqlite-vec virtual table. rowid == events.id
            CREATE VIRTUAL TABLE vec_events USING vec0(
                embedding float[{embed_dim}]
            );

            CREATE TABLE ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                mood REAL,
                energy REAL,
                productivity REAL,
                confidence_mood REAL,
                confidence_energy REAL,
                confidence_productivity REAL,
                rationale TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX ratings_event ON ratings(event_id);

            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                google_task_id TEXT UNIQUE,
                description TEXT NOT NULL,
                deadline TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',       -- open | complete | cancelled
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT
            );

            CREATE TABLE task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                google_event_id TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL,
                planned_start TEXT NOT NULL,
                planned_end TEXT NOT NULL,
                actual_end TEXT,
                UNIQUE (task_id, chunk_index)
            );
            CREATE INDEX task_events_task ON task_events(task_id);

            CREATE TABLE predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                google_event_id TEXT,
                predicted_duration_min REAL NOT NULL,
                pred_pre_mood REAL, pred_pre_energy REAL, pred_pre_productivity REAL,
                pred_post_mood REAL, pred_post_energy REAL, pred_post_productivity REAL,
                confidence_duration REAL,
                confidence_pre_mood REAL, confidence_pre_energy REAL, confidence_pre_productivity REAL,
                confidence_post_mood REAL, confidence_post_energy REAL, confidence_post_productivity REAL,
                rationale TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX predictions_task ON predictions(task_id);

            CREATE TABLE residuals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                prediction_id INTEGER NOT NULL REFERENCES predictions(id) ON DELETE CASCADE,
                duration_actual_min REAL,
                duration_residual_min REAL,
                pre_mood_residual REAL, pre_energy_residual REAL, pre_productivity_residual REAL,
                post_mood_residual REAL, post_energy_residual REAL, post_productivity_residual REAL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX residuals_prediction ON residuals(prediction_id);

            INSERT INTO schema_info (version, embed_dim) VALUES ({SCHEMA_VERSION}, {embed_dim});
            """
        )
    except sqlite3.Error as e:
        raise DBError(f"failed to apply schema: {e}") from e
