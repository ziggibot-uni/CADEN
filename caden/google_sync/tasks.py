"""Google Tasks client — create tasks, read status, detect completion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from ..errors import GoogleSyncError


@dataclass(frozen=True)
class GTask:
    id: str
    title: str
    due: datetime | None
    status: str   # "needsAction" | "completed"
    completed_at: datetime | None
    raw: dict


class TasksClient:
    def __init__(self, credentials, task_list_id: str = "@default") -> None:
        try:
            self.service = build("tasks", "v1", credentials=credentials, cache_discovery=False)
        except Exception as e:
            raise GoogleSyncError(f"failed to build Tasks service: {e}") from e
        self.task_list_id = task_list_id

    def create(self, title: str, due: datetime, notes: str = "") -> GTask:
        body = {
            "title": title,
            "due": due.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "notes": notes,
        }
        try:
            t = self.service.tasks().insert(tasklist=self.task_list_id, body=body).execute()
        except HttpError as e:
            raise GoogleSyncError(f"Tasks insert failed: {e}") from e
        return _to_task(t)

    def list_open(self) -> list[GTask]:
        try:
            resp = (
                self.service.tasks()
                .list(tasklist=self.task_list_id, showCompleted=False, maxResults=100)
                .execute()
            )
        except HttpError as e:
            raise GoogleSyncError(f"Tasks list failed: {e}") from e
        return [_to_task(t) for t in resp.get("items", [])]

    def get(self, task_id: str) -> GTask:
        try:
            t = self.service.tasks().get(tasklist=self.task_list_id, task=task_id).execute()
        except HttpError as e:
            if e.resp.status in (404, 410):
                return GTask(
                    id=task_id,
                    title="(deleted on remote)",
                    due=None,
                    status="completed",
                    completed_at=datetime.now(timezone.utc),
                    raw={},
                )
            raise GoogleSyncError(f"Tasks get failed for {task_id}: {e}") from e
        return _to_task(t)

    def mark_completed(self, task_id: str) -> None:
        try:
            self.service.tasks().patch(
                tasklist=self.task_list_id,
                task=task_id,
                body={"status": "completed"},
            ).execute()
        except HttpError as e:
            if e.resp.status in (404, 410):
                return
            raise GoogleSyncError(f"Tasks mark_completed failed for {task_id}: {e}") from e


def _to_task(t: dict) -> GTask:
    due = _parse(t.get("due"))
    completed_at = _parse(t.get("completed"))
    return GTask(
        id=t["id"],
        title=t.get("title") or "(no title)",
        due=due,
        status=t.get("status") or "needsAction",
        completed_at=completed_at,
        raw=t,
    )


def _parse(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
