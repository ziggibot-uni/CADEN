"""Project Manager domain service."""

from __future__ import annotations

from dataclasses import dataclass
import re
import sqlite3
from typing import Sequence

from ..errors import ProjectManagerError
from ..libbie import projects
from ..libbie.store import append_event_metadata


_ENTRY_TYPES = ("todo", "what_if", "update", "comment")
_TOKEN_RE = re.compile(r"[a-z0-9_]{4,}", re.IGNORECASE)
_STOPWORDS = {
    "that", "this", "with", "from", "have", "will", "should", "could",
    "would", "about", "there", "their", "project", "task", "today",
}


@dataclass(frozen=True)
class ProjectEntryResult:
    event_id: int
    project_id: str
    project_name: str
    entry_type: str
    text: str
    google_task_id: str | None = None


class ProjectManagerService:
    def __init__(self, conn: sqlite3.Connection, embedder, tasks_client=None) -> None:
        self._conn = conn
        self._embedder = embedder
        self._tasks = tasks_client

    @staticmethod
    def entry_types() -> tuple[str, ...]:
        return _ENTRY_TYPES

    def list_projects(self) -> list[projects.ProjectSummary]:
        return projects.list_projects(self._conn)

    def list_entries(self, project_id: str, *, limit: int = 200) -> list[projects.ProjectEntry]:
        return projects.list_project_entries(self._conn, project_id, limit=limit)

    def add_entry(self, *, project_name: str, entry_type: str, text: str) -> ProjectEntryResult:
        clean_type = entry_type.strip().lower().replace("-", "_")
        if clean_type not in _ENTRY_TYPES:
            raise ValueError(f"unsupported entry_type {entry_type!r}")
        emb: Sequence[float] = self._embedder.embed(text)
        row = projects.write_project_entry(
            self._conn,
            project_name=project_name,
            entry_type=clean_type,
            text=text,
            embedding=emb,
        )
        google_task_id: str | None = None
        if clean_type == "todo":
            if self._tasks is None:
                raise ProjectManagerError(
                    "project-manager TODO entries require configured Google Tasks client"
                )
            title = text.strip().splitlines()[0].strip() or "(untitled TODO)"
            notes = (
                text.strip()
                + "\n\n"
                + "---\n"
                + f"caden_event_id: {row.event_id}\n"
                + f"project_id: {row.project_id}\n"
                + f"project_name: {row.project_name}\n"
                + "entry_type: todo"
            )
            try:
                gtask = self._tasks.create(title=title, due=None, notes=notes)
            except Exception as e:
                raise ProjectManagerError(f"project-manager TODO google task create failed: {e}") from e
            google_task_id = gtask.id
            append_event_metadata(self._conn, row.event_id, "google_task_id", google_task_id)
            append_event_metadata(self._conn, row.event_id, "linked_to", google_task_id)

        return ProjectEntryResult(
            event_id=row.event_id,
            project_id=row.project_id,
            project_name=row.project_name,
            entry_type=row.entry_type,
            text=row.text,
            google_task_id=google_task_id,
        )

    def propose_projects_from_clusters(self, *, limit: int = 3) -> tuple[str, ...]:
        rows = self._conn.execute(
            """
            SELECT e.raw_text
            FROM events AS e
            LEFT JOIN event_metadata AS pm
              ON pm.event_id = e.id
             AND pm.key = 'project_id'
            WHERE e.source IN ('sean_chat', 'thought_dump')
              AND pm.event_id IS NULL
            ORDER BY e.id DESC
            LIMIT 200
            """
        ).fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            text = str(row["raw_text"] or "").lower()
            tokens = [
                tok
                for tok in _TOKEN_RE.findall(text)
                if tok not in _STOPWORDS
            ]
            for i in range(len(tokens) - 1):
                key = f"{tokens[i]}_{tokens[i + 1]}"
                counts[key] = counts.get(key, 0) + 1
        ranked = [
            name
            for name, n in sorted(counts.items(), key=lambda item: item[1], reverse=True)
            if n >= 2
        ]
        return tuple(ranked[: max(0, int(limit))])
