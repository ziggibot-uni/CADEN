from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from googleapiclient.errors import HttpError

from caden.errors import GoogleSyncError
from caden.google_sync.calendar import CalendarClient
from caden.google_sync.tasks import TasksClient


def test_calendar_list_and_create_fail_loudly_on_runtime_http_errors(monkeypatch):
    service = _CalendarService(
        list_exc=_http_error(500, "calendar list boom"),
        insert_exc=_http_error(500, "calendar insert boom"),
    )
    monkeypatch.setattr("caden.google_sync.calendar.build", lambda *args, **kwargs: service)
    client = CalendarClient(credentials=object())
    start = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    end = datetime(2026, 4, 26, 13, 0, tzinfo=timezone.utc)

    with pytest.raises(GoogleSyncError, match="Calendar list failed"):
        client.list_window(start, end)

    with pytest.raises(GoogleSyncError, match="Calendar insert failed"):
        client.create_event("Focus", start, end)


def test_google_sync_runtime_errors_preserve_original_http_error_as_cause(monkeypatch):
    boom = _http_error(500, "calendar insert boom")
    service = _CalendarService(insert_exc=boom)
    monkeypatch.setattr("caden.google_sync.calendar.build", lambda *args, **kwargs: service)
    client = CalendarClient(credentials=object())
    start = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    end = datetime(2026, 4, 26, 13, 0, tzinfo=timezone.utc)

    with pytest.raises(GoogleSyncError, match="Calendar insert failed") as exc_info:
        client.create_event("Focus", start, end)

    assert exc_info.value.__cause__ is boom


def test_calendar_patch_failures_are_loud_except_documented_not_found_tolerance(monkeypatch):
    service = _CalendarService(patch_exc=_http_error(500, "calendar patch boom"))
    monkeypatch.setattr("caden.google_sync.calendar.build", lambda *args, **kwargs: service)
    client = CalendarClient(credentials=object())
    new_end = datetime(2026, 4, 26, 13, 0, tzinfo=timezone.utc)

    with pytest.raises(GoogleSyncError, match="Calendar patch failed"):
        client.set_end_time("evt-1", new_end)

    with pytest.raises(GoogleSyncError, match="Calendar reschedule failed"):
        client.reschedule("evt-1", new_end, new_end)


def test_tasks_create_list_get_and_patch_fail_loudly_on_runtime_http_errors(monkeypatch):
    service = _TasksService(
        insert_exc=_http_error(500, "tasks insert boom"),
        list_exc=_http_error(500, "tasks list boom"),
        get_exc=_http_error(500, "tasks get boom"),
        patch_exc=_http_error(500, "tasks patch boom"),
    )
    monkeypatch.setattr("caden.google_sync.tasks.build", lambda *args, **kwargs: service)
    client = TasksClient(credentials=object())
    due = datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc)

    with pytest.raises(GoogleSyncError, match="Tasks insert failed"):
        client.create("Write the draft", due)

    with pytest.raises(GoogleSyncError, match="Tasks list failed"):
        client.list_open()

    with pytest.raises(GoogleSyncError, match="Tasks get failed for task-1"):
        client.get("task-1")

    with pytest.raises(GoogleSyncError, match="Tasks mark_completed failed for task-1"):
        client.mark_completed("task-1")


def test_tasks_and_calendar_404_paths_keep_documented_remote_delete_tolerance(monkeypatch):
    calendar_service = _CalendarService(patch_exc=_http_error(404, "gone"))
    tasks_service = _TasksService(get_exc=_http_error(404, "gone"), patch_exc=_http_error(404, "gone"))
    monkeypatch.setattr("caden.google_sync.calendar.build", lambda *args, **kwargs: calendar_service)
    monkeypatch.setattr("caden.google_sync.tasks.build", lambda *args, **kwargs: tasks_service)

    calendar = CalendarClient(credentials=object())
    tasks = TasksClient(credentials=object())
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)

    calendar.set_end_time("evt-404", now)
    calendar.reschedule("evt-404", now, now)
    deleted = tasks.get("task-404")
    tasks.mark_completed("task-404")

    assert deleted.id == "task-404"
    assert deleted.status == "completed"


def _http_error(status: int, reason: str) -> HttpError:
    return HttpError(resp=SimpleNamespace(status=status, reason=reason), content=b"{}")


class _Executable:
    def __init__(self, exc=None, payload=None):
        self._exc = exc
        self._payload = payload if payload is not None else {}

    def execute(self):
        if self._exc is not None:
            raise self._exc
        return self._payload


class _CalendarEvents:
    def __init__(self, list_exc=None, insert_exc=None, patch_exc=None):
        self._list_exc = list_exc
        self._insert_exc = insert_exc
        self._patch_exc = patch_exc

    def list(self, **kwargs):
        return _Executable(exc=self._list_exc)

    def insert(self, **kwargs):
        return _Executable(exc=self._insert_exc)

    def patch(self, **kwargs):
        return _Executable(exc=self._patch_exc)


class _CalendarService:
    def __init__(self, list_exc=None, insert_exc=None, patch_exc=None):
        self._events = _CalendarEvents(list_exc=list_exc, insert_exc=insert_exc, patch_exc=patch_exc)

    def events(self):
        return self._events


class _TasksOperations:
    def __init__(self, insert_exc=None, list_exc=None, get_exc=None, patch_exc=None):
        self._insert_exc = insert_exc
        self._list_exc = list_exc
        self._get_exc = get_exc
        self._patch_exc = patch_exc

    def insert(self, **kwargs):
        return _Executable(exc=self._insert_exc)

    def list(self, **kwargs):
        return _Executable(exc=self._list_exc)

    def get(self, **kwargs):
        return _Executable(exc=self._get_exc)

    def patch(self, **kwargs):
        return _Executable(exc=self._patch_exc)


class _TasksService:
    def __init__(self, insert_exc=None, list_exc=None, get_exc=None, patch_exc=None):
        self._tasks = _TasksOperations(
            insert_exc=insert_exc,
            list_exc=list_exc,
            get_exc=get_exc,
            patch_exc=patch_exc,
        )

    def tasks(self):
        return self._tasks


def test_calendar_client_reads_only_configured_calendars_and_writes_to_default(monkeypatch):
    seen_list_ids: list[str] = []
    seen_insert_ids: list[str] = []

    class _Exec:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class _Events:
        def list(self, **kwargs):
            seen_list_ids.append(kwargs["calendarId"])
            return _Exec({"items": []})

        def insert(self, **kwargs):
            seen_insert_ids.append(kwargs["calendarId"])
            return _Exec(
                {
                    "id": "evt_new",
                    "summary": kwargs["body"].get("summary") or "(no title)",
                    "start": kwargs["body"]["start"],
                    "end": kwargs["body"]["end"],
                }
            )

        def patch(self, **kwargs):
            return _Exec({})

    class _Service:
        def events(self):
            return _Events()

    monkeypatch.setattr("caden.google_sync.calendar.build", lambda *args, **kwargs: _Service())
    client = CalendarClient(
        credentials=object(),
        readable_calendar_ids=("cal_a", "cal_b"),
        writable_calendar_id="cal_write",
    )

    start = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    end = datetime(2026, 4, 26, 13, 0, tzinfo=timezone.utc)
    client.list_window(start, end)
    client.create_event("Focus", start, end)

    assert seen_list_ids == ["cal_a", "cal_b"]
    assert seen_insert_ids == ["cal_write"]


def test_tasks_client_reads_only_configured_lists_and_writes_to_default(monkeypatch):
    seen_list_ids: list[str] = []
    seen_insert_ids: list[str] = []

    class _Exec:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class _Tasks:
        def list(self, **kwargs):
            seen_list_ids.append(kwargs["tasklist"])
            return _Exec({"items": []})

        def insert(self, **kwargs):
            seen_insert_ids.append(kwargs["tasklist"])
            return _Exec({"id": "t_new", "title": kwargs["body"]["title"], "status": "needsAction"})

        def get(self, **kwargs):
            return _Exec({"id": kwargs["task"], "title": "x", "status": "needsAction"})

        def patch(self, **kwargs):
            return _Exec({})

    class _Service:
        def tasks(self):
            return _Tasks()

    monkeypatch.setattr("caden.google_sync.tasks.build", lambda *args, **kwargs: _Service())
    client = TasksClient(
        credentials=object(),
        readable_task_list_ids=("list_a", "list_b"),
        writable_task_list_id="list_write",
    )

    due = datetime(2026, 4, 27, 17, 0, tzinfo=timezone.utc)
    client.list_open()
    client.create("Write", due)

    assert seen_list_ids == ["list_a", "list_b"]
    assert seen_insert_ids == ["list_write"]