from datetime import datetime, timezone

import pytest

from caden.errors import CadenError
from caden.libbie.store import link_task_event, write_task
from caden.ui.app import CadenApp
from caden.ui.edit_task import EditTaskScreen


class _Execute:
    def __init__(self, func):
        self._func = func

    def execute(self):
        return self._func()


class _CalendarEventsAPI:
    def __init__(self):
        self.updated = []

    def get(self, calendarId, eventId):
        return _Execute(
            lambda: {
                "id": eventId,
                "summary": "Old title",
                "description": "Starts at 14:30",
                "start": {"dateTime": datetime(2026, 4, 30, 14, 0, tzinfo=timezone.utc).isoformat()},
                "end": {"dateTime": datetime(2026, 4, 30, 15, 0, tzinfo=timezone.utc).isoformat()},
            }
        )

    def update(self, calendarId, eventId, body):
        return _Execute(lambda: self.updated.append((calendarId, eventId, body)) or body)


class _CalendarService:
    def __init__(self):
        self._events = _CalendarEventsAPI()

    def events(self):
        return self._events


class _TasksAPI:
    def __init__(self):
        self.updated = []

    def get(self, tasklist, task):
        return _Execute(lambda: {"id": task, "title": "Old task", "notes": "Starts at 14:30"})

    def update(self, tasklist, task, body):
        return _Execute(lambda: self.updated.append((tasklist, task, body)) or body)


class _TasksService:
    def __init__(self):
        self._tasks = _TasksAPI()

    def tasks(self):
        return self._tasks


class _FailingCalendarEventsAPI(_CalendarEventsAPI):
    def update(self, calendarId, eventId, body):
        return _Execute(lambda: (_ for _ in ()).throw(RuntimeError("calendar write blew up")))


def test_edit_task_save_updates_google_records_and_local_task_event(mock_services):
    task_id = write_task(
        mock_services.conn,
        description="Old task",
        deadline_iso=datetime(2026, 5, 1, tzinfo=timezone.utc).isoformat(),
        google_task_id="task_1",
        embedding=[0.1] * 768,
    )
    link_task_event(
        mock_services.conn,
        task_id=task_id,
        google_event_id="event_1",
        planned_start_iso=datetime(2026, 4, 30, 14, 0, tzinfo=timezone.utc).isoformat(),
        planned_end_iso=datetime(2026, 4, 30, 15, 0, tzinfo=timezone.utc).isoformat(),
    )

    calendar_service = _CalendarService()
    tasks_service = _TasksService()
    mock_services.calendar = type(
        "CalendarClientStub",
        (),
        {"service": calendar_service, "calendar_id": "primary"},
    )()
    mock_services.tasks = type(
        "TasksClientStub",
        (),
        {"service": tasks_service, "task_list_id": "@default"},
    )()

    screen = EditTaskScreen(
        mock_services,
        g_task_id="task_1",
        g_event_id="event_1",
        summary="Old title",
    )

    new_start = datetime(2026, 4, 30, 16, 0, tzinfo=timezone.utc)
    new_end = datetime(2026, 4, 30, 17, 30, tzinfo=timezone.utc)
    screen._save("New title", new_start, new_end, "Meet at 14:30")

    calendar_update = calendar_service._events.updated[0][2]
    assert calendar_update["summary"] == "New title"
    assert "2:30 pm" in calendar_update["description"]
    assert calendar_update["start"]["dateTime"] == new_start.isoformat()
    assert calendar_update["end"]["dateTime"] == new_end.isoformat()

    task_update = tasks_service._tasks.updated[0][2]
    assert task_update["title"] == "New title"
    assert "2:30 pm" in task_update["notes"]

    task_event = mock_services.conn.execute(
        "SELECT planned_start, planned_end FROM task_events WHERE google_event_id='event_1'"
    ).fetchone()
    assert task_event is not None
    assert task_event["planned_start"] == new_start.isoformat(timespec="seconds")
    assert task_event["planned_end"] == new_end.isoformat(timespec="seconds")


def test_edit_task_save_fails_loudly_when_paired_calendar_event_update_fails(mock_services):
    task_id = write_task(
        mock_services.conn,
        description="Old task",
        deadline_iso=datetime(2026, 5, 1, tzinfo=timezone.utc).isoformat(),
        google_task_id="task_1",
        embedding=[0.1] * 768,
    )
    link_task_event(
        mock_services.conn,
        task_id=task_id,
        google_event_id="event_1",
        planned_start_iso=datetime(2026, 4, 30, 14, 0, tzinfo=timezone.utc).isoformat(),
        planned_end_iso=datetime(2026, 4, 30, 15, 0, tzinfo=timezone.utc).isoformat(),
    )

    calendar_service = type("CalendarServiceStub", (), {"events": lambda self: _FailingCalendarEventsAPI()})()
    mock_services.calendar = type(
        "CalendarClientStub",
        (),
        {"service": calendar_service, "calendar_id": "primary"},
    )()
    mock_services.tasks = None

    screen = EditTaskScreen(
        mock_services,
        g_task_id="task_1",
        g_event_id="event_1",
        summary="Old title",
    )

    new_start = datetime(2026, 4, 30, 16, 0, tzinfo=timezone.utc)
    new_end = datetime(2026, 4, 30, 17, 30, tzinfo=timezone.utc)

    with pytest.raises(CadenError, match="Calendar update failed: calendar write blew up") as exc_info:
        screen._save("New title", new_start, new_end, "Meet at 14:30")

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert str(exc_info.value.__cause__) == "calendar write blew up"


@pytest.mark.asyncio
async def test_edit_task_submit_offloads_save_via_to_thread(mock_services, monkeypatch):
    calls: list[tuple[object, tuple[object, ...]]] = []
    dismissed: list[bool] = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append((func, args))
        return None

    monkeypatch.setattr("caden.ui.edit_task.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr(EditTaskScreen, "dismiss", lambda self, result=False: dismissed.append(result))

    app = CadenApp(mock_services)
    screen = EditTaskScreen(mock_services, g_task_id="task_1", g_event_id="event_1", summary="Old title")

    async with app.run_test(size=(80, 40)) as pilot:
        app.push_screen(screen)
        await pilot.pause(0.2)

        screen.query_one("#title").value = "New title"
        screen.query_one("#start").value = "2026-04-30T16:00"
        screen.query_one("#end").value = "2026-04-30T17:30"
        screen.query_one("#desc").value = "Meet at 14:30"

        await screen._submit()

    assert len(calls) == 1
    assert getattr(calls[0][0], "__name__", "") == "_save"
    assert dismissed == [True]


@pytest.mark.asyncio
async def test_edit_task_complete_offloads_completion_via_to_thread(mock_services, monkeypatch):
    calls: list[tuple[object, tuple[object, ...]]] = []
    dismissed: list[bool] = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append((func, args))
        return None

    monkeypatch.setattr("caden.ui.edit_task.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr(EditTaskScreen, "dismiss", lambda self, result=False: dismissed.append(result))

    app = CadenApp(mock_services)
    screen = EditTaskScreen(mock_services, g_task_id="task_1", g_event_id="event_1", summary="Old title")

    async with app.run_test(size=(80, 40)) as pilot:
        app.push_screen(screen)
        await pilot.pause(0.2)
        await screen._complete_task()

    assert len(calls) == 1
    assert getattr(calls[0][0], "__name__", "") == "_do_complete"
    assert dismissed == [True]