import sqlite3

import pytest

from caden.errors import DBError
from caden.libbie.db import apply_schema, connect


def test_connect_verifies_sqlite_vec_is_loaded(tmp_path):
    conn = connect(tmp_path / "vec-ok.db")
    try:
        row = conn.execute("SELECT vec_version() AS version").fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["version"]


def test_connect_fails_loudly_when_sqlite_vec_verification_returns_no_version(tmp_path, monkeypatch):
    real_connect = sqlite3.connect

    class FakeConnection:
        def __init__(self, inner):
            self._inner = inner
            self.row_factory = None

        def execute(self, sql, *args, **kwargs):
            if sql == "SELECT vec_version()":
                class _Cursor:
                    def fetchone(self):
                        return (None,)

                return _Cursor()
            return self._inner.execute(sql, *args, **kwargs)

        def enable_load_extension(self, enabled):
            return self._inner.enable_load_extension(enabled)

    monkeypatch.setattr("caden.libbie.db.sqlite3.connect", lambda *args, **kwargs: FakeConnection(real_connect(*args, **kwargs)))
    monkeypatch.setattr("caden.libbie.db.sqlite_vec.load", lambda conn: None)

    with pytest.raises(DBError, match="sqlite-vec reported no version string"):
        connect(tmp_path / "vec-missing.db")


def test_apply_schema_creates_documented_vector_tables_and_pins_embed_dim(tmp_path):
    conn = connect(tmp_path / "schema.db")
    try:
        apply_schema(conn, embed_dim=768)
        names = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE name IN ('vec_events', 'vec_memories', 'schema_info')"
            ).fetchall()
        }
        embed_dim_row = conn.execute("SELECT embed_dim FROM schema_info").fetchone()
    finally:
        conn.close()

    assert names == {"schema_info", "vec_events", "vec_memories"}
    assert embed_dim_row is not None
    assert embed_dim_row["embed_dim"] == 768


def test_single_central_sqlite_db_hosts_raw_curated_structured_and_vector_tables(tmp_path):
    conn = connect(tmp_path / "central.db")
    try:
        apply_schema(conn, embed_dim=768)
        databases = conn.execute("PRAGMA database_list").fetchall()
        table_names = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()

    assert {row["name"] for row in databases} >= {"main"}
    assert {row["name"] for row in databases if row["file"]} == {"main"}
    assert {
        "events",
        "memories",
        "ratings",
        "predictions",
        "residuals",
        "tasks",
        "task_events",
        "vec_events",
        "vec_memories",
    }.issubset(table_names)