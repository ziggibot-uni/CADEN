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
from alembic import command
from alembic.config import Config

from ..errors import DBError


# ---- serialisation helpers ---------------------------------------------------

def pack_vector(vec: Sequence[float]) -> bytes:
    """Pack a float sequence into the float32 little-endian bytes sqlite-vec wants."""
    return struct.pack(f"{len(vec)}f", *[float(x) for x in vec])


def unpack_vector(blob: bytes) -> list[float]:
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


# ---- connection --------------------------------------------------------------

def connect(db_path: Path) -> sqlite3.Connection:
    """Open the DB, load sqlite-vec.

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
    """Run Alembic migrations to ensure the DB schema is up to date."""
    # Alembic expects a path to its config file.
    import os
    alembic_ini_path = Path(__file__).parent / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini_path))
    alembic_cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    
    # We pass the open connection to Alembic so we don't have to worry about paths
    try:
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        
        # Check an internal marker if we need to enforce embed_dim initially.
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_info (
                embed_dim INTEGER NOT NULL
            )
            """
        )
        row = cur.execute("SELECT embed_dim FROM schema_info").fetchone()
        if row is not None:
            if row["embed_dim"] != embed_dim:
                raise DBError(
                    f"embed_dim mismatch: db was initialised with {row['embed_dim']}, "
                    f"config asks for {embed_dim}. choose one and do not change it silently."
                )
        else:
            cur.execute(f"INSERT INTO schema_info (embed_dim) VALUES ({embed_dim})")
            
        import sqlalchemy
        
        # In SQLAlchemy 2.0, connection strings are used differently. We wrap sqlite3 conn. 
        engine = sqlalchemy.create_engine("sqlite://", creator=lambda: conn)
        with engine.connect() as sqla_conn:
            alembic_cfg.attributes['connection'] = sqla_conn
            command.upgrade(alembic_cfg, "head")
        
        # After migrations, ensure the sqlite-vec virtual table is present.
        # Alembic doesn't natively handle SQLite virtual tables smoothly always.
        cur.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_events USING vec0(
                embedding float[{embed_dim}]
            );
            """
        )
    except Exception as e:
        raise DBError(f"failed to apply schema migrations: {e}") from e

