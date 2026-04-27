"""Project-oriented memory helpers backed by Libbie events.

This keeps Project Manager data in the same event/memory pipeline rather than
creating a siloed storage path.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import sqlite3
from typing import Sequence

from ..errors import DBError
from .store import write_event


_PROJECT_ID_RE = re.compile(r"[^a-z0-9_]+")


@dataclass(frozen=True)
class ProjectSummary:
    project_id: str
    project_name: str
    created_at: str
    last_touched_at: str
    entry_count: int


@dataclass(frozen=True)
class ProjectEntry:
    event_id: int
    timestamp: str
    project_id: str
    project_name: str
    entry_type: str
    text: str


def normalize_project_id(name: str) -> str:
    cleaned = _PROJECT_ID_RE.sub("_", name.strip().lower()).strip("_")
    if not cleaned:
        raise ValueError("project name must not be empty")
    return cleaned


def write_project_entry(
    conn: sqlite3.Connection,
    *,
    project_name: str,
    entry_type: str,
    text: str,
    embedding: Sequence[float],
) -> ProjectEntry:
    if not text.strip():
        raise ValueError("project entry text must not be empty")
    if not entry_type.strip():
        raise ValueError("entry_type must not be empty")

    project_id = normalize_project_id(project_name)
    clean_name = project_name.strip()
    clean_type = entry_type.strip().lower().replace("-", "_")
    body = text.strip()
    raw_text = f"[{clean_name}/{clean_type}] {body}"

    event_id = write_event(
        conn,
        source="project_entry",
        raw_text=raw_text,
        embedding=embedding,
        meta={
            "project_id": project_id,
            "project_name": clean_name,
            "entry_type": clean_type,
            "trigger": "project_manager_submit",
        },
    )
    row = conn.execute(
        "SELECT timestamp FROM events WHERE id=?",
        (event_id,),
    ).fetchone()
    if row is None:
        raise DBError(f"project entry event {event_id} missing after write")

    return ProjectEntry(
        event_id=event_id,
        timestamp=str(row["timestamp"]),
        project_id=project_id,
        project_name=clean_name,
        entry_type=clean_type,
        text=body,
    )


def list_projects(conn: sqlite3.Connection) -> list[ProjectSummary]:
    rows = conn.execute(
        """
        SELECT
            pid.value AS project_id,
            COALESCE(MAX(CASE WHEN pname.key='project_name' THEN pname.value END), pid.value) AS project_name,
            MIN(e.timestamp) AS created_at,
            MAX(e.timestamp) AS last_touched_at,
            COUNT(*) AS entry_count
        FROM events AS e
        JOIN event_metadata AS pid
          ON pid.event_id = e.id
         AND pid.key = 'project_id'
        LEFT JOIN event_metadata AS pname
          ON pname.event_id = e.id
         AND pname.key = 'project_name'
        WHERE e.source = 'project_entry'
        GROUP BY pid.value
        ORDER BY last_touched_at DESC
        """
    ).fetchall()
    return [
        ProjectSummary(
            project_id=str(row["project_id"]),
            project_name=str(row["project_name"]),
            created_at=str(row["created_at"]),
            last_touched_at=str(row["last_touched_at"]),
            entry_count=int(row["entry_count"]),
        )
        for row in rows
    ]


def list_project_entries(
    conn: sqlite3.Connection,
    project_id: str,
    *,
    limit: int = 200,
) -> list[ProjectEntry]:
    rows = conn.execute(
        """
        SELECT
            e.id,
            e.timestamp,
            e.raw_text,
            et.value AS entry_type,
            pname.value AS project_name
        FROM events AS e
        JOIN event_metadata AS pid
          ON pid.event_id = e.id
         AND pid.key = 'project_id'
        LEFT JOIN event_metadata AS et
          ON et.event_id = e.id
         AND et.key = 'entry_type'
        LEFT JOIN event_metadata AS pname
          ON pname.event_id = e.id
         AND pname.key = 'project_name'
        WHERE e.source = 'project_entry'
          AND pid.value = ?
        ORDER BY e.id DESC
        LIMIT ?
        """,
        (project_id, int(limit)),
    ).fetchall()
    entries = [
        ProjectEntry(
            event_id=int(row["id"]),
            timestamp=str(row["timestamp"]),
            project_id=project_id,
            project_name=str(row["project_name"] or project_id),
            entry_type=str(row["entry_type"] or "comment"),
            text=str(row["raw_text"]),
        )
        for row in rows
    ]
    entries.reverse()
    return entries
