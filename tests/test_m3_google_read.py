import pytest
from datetime import datetime, timedelta, timezone

from caden.ui.app import CadenApp
from caden.google_sync.calendar import CalendarEvent
from caden.ui import dashboard as dashboard_module
from caden.ui.dashboard import Dashboard, day_window_utc
from caden.google_sync.tasks import GTask
from caden.libbie.store import write_task, link_task_event
from caden.util.timefmt import format_display_time


def test_dashboard_day_window_uses_5am_local_boundary():
    eastern = timezone(timedelta(hours=-4))

    before_boundary = datetime(2026, 4, 30, 8, 30, tzinfo=timezone.utc)
    start_utc, end_utc = day_window_utc(before_boundary, local_tz=eastern)
    assert start_utc.astimezone(eastern) == datetime(2026, 4, 29, 5, 0, tzinfo=eastern)
    assert end_utc.astimezone(eastern) == datetime(2026, 4, 30, 5, 0, tzinfo=eastern)

    after_boundary = datetime(2026, 4, 30, 10, 30, tzinfo=timezone.utc)
    start_utc, end_utc = day_window_utc(after_boundary, local_tz=eastern)
    assert start_utc.astimezone(eastern) == datetime(2026, 4, 30, 5, 0, tzinfo=eastern)
    assert end_utc.astimezone(eastern) == datetime(2026, 5, 1, 5, 0, tzinfo=eastern)

@pytest.mark.asyncio
async def test_m3_google_read(mock_services):
    class MockCalendar:
        def list_window(self, start, end):
            return [
                CalendarEvent(
                    id="event1",
                    summary="Test Event Today",
                    start=datetime(2026, 4, 30, 20, 0, tzinfo=timezone.utc), # Make sure it's in the future
                    end=datetime(2026, 4, 30, 23, 0, tzinfo=timezone.utc),
                    raw={}
                )
            ]
            
    mock_services.calendar = MockCalendar()
    
    app = CadenApp(mock_services)
    async with app.run_test() as pilot:
        # Give Dashboard time to fetch and render
        await pilot.pause(0.5)
        
        # Test Event Today should be inside the layout's textual body
        from caden.ui.dashboard import TaskItem
        items = list(app.query(TaskItem))
        
        text = " ".join([str(item._text) for item in items])
        assert "Test Event Today" in text, f"Mocked event not rendered on main dashboard. Items available: {text}"


@pytest.mark.asyncio
async def test_dashboard_today_panel_mixes_labeled_tasks_and_events_in_chronological_order(mock_services):
    now = datetime.now(timezone.utc)
    first_event = now + timedelta(hours=1)
    task_due = now + timedelta(hours=2)
    second_event = now + timedelta(hours=3)

    class MockCalendar:
        def list_window(self, start, end):
            return [
                CalendarEvent(
                    id="evt_late",
                    summary="Later event",
                    start=second_event,
                    end=second_event + timedelta(minutes=30),
                    raw={},
                ),
                CalendarEvent(
                    id="evt_early",
                    summary="Early event",
                    start=first_event,
                    end=first_event + timedelta(minutes=30),
                    raw={},
                ),
            ]

    class MockTasks:
        def list_open(self):
            return [
                GTask(
                    id="task_mid",
                    title="Middle task",
                    due=task_due,
                    status="needsAction",
                    completed_at=None,
                    raw={},
                )
            ]

    mock_services.calendar = MockCalendar()
    mock_services.tasks = MockTasks()

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.6)

        from caden.ui.dashboard import SidePanel, TaskItem

        today_panel = list(app.query(SidePanel))[0]
        items = list(today_panel.query(TaskItem))
        texts = [item._text for item in items]

    assert len(texts) >= 3
    assert "[event] Early event" in texts[0]
    assert "[task] Middle task" in texts[1]
    assert "[event] Later event" in texts[2]


@pytest.mark.asyncio
async def test_dashboard_next_7_days_panel_includes_future_events_and_tasks(mock_services):
    now = datetime.now(timezone.utc)
    future_event = now + timedelta(days=5, hours=2)
    future_task_due = now + timedelta(days=6, hours=4)

    class MockCalendar:
        def list_window(self, start, end):
            return [
                CalendarEvent(
                    id="evt_future",
                    summary="Future calendar event",
                    start=future_event,
                    end=future_event + timedelta(hours=1),
                    raw={},
                )
            ]

    class MockTasks:
        def list_open(self):
            return [
                GTask(
                    id="task_future",
                    title="Future open task",
                    due=future_task_due,
                    status="needsAction",
                    completed_at=None,
                    raw={},
                )
            ]

    mock_services.calendar = MockCalendar()
    mock_services.tasks = MockTasks()

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.6)

        from caden.ui.dashboard import SidePanel, TaskItem

        week_panel = list(app.query(SidePanel))[1]
        texts = [item._text for item in list(week_panel.query(TaskItem))]

    assert any("[event] Future calendar event" in text for text in texts)
    assert any("[task] Future open task" in text for text in texts)


@pytest.mark.asyncio
async def test_dashboard_next_7_days_panel_uses_same_5am_boundary_as_today(mock_services, monkeypatch):
    fixed_now = datetime(2026, 4, 30, 8, 30, tzinfo=timezone.utc)
    captured_windows: list[tuple[datetime, datetime]] = []

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now
            return fixed_now.astimezone(tz)

    class MockCalendar:
        def list_window(self, start, end):
            captured_windows.append((start, end))
            return []

    class MockTasks:
        def list_open(self):
            return []

    monkeypatch.setattr(dashboard_module, "datetime", _FixedDateTime)
    mock_services.calendar = MockCalendar()
    mock_services.tasks = MockTasks()

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.6)

    assert len(captured_windows) >= 2
    start_today, end_today = day_window_utc(fixed_now)
    assert captured_windows[0] == (start_today, end_today)
    assert captured_windows[1] == (start_today, start_today + timedelta(days=7))


@pytest.mark.asyncio
async def test_dashboard_next_7_days_panel_orders_tasks_inline_with_events_by_start_and_due_time(mock_services):
    now = datetime.now(timezone.utc)
    first_event = now + timedelta(days=1, hours=1)
    task_due = now + timedelta(days=1, hours=2)
    second_event = now + timedelta(days=1, hours=3)

    class MockCalendar:
        def list_window(self, start, end):
            return [
                CalendarEvent(
                    id="evt_late_week",
                    summary="Week later event",
                    start=second_event,
                    end=second_event + timedelta(minutes=30),
                    raw={},
                ),
                CalendarEvent(
                    id="evt_early_week",
                    summary="Week early event",
                    start=first_event,
                    end=first_event + timedelta(minutes=30),
                    raw={},
                ),
            ]

    class MockTasks:
        def list_open(self):
            return [
                GTask(
                    id="task_mid_week",
                    title="Week middle task",
                    due=task_due,
                    status="needsAction",
                    completed_at=None,
                    raw={},
                )
            ]

    mock_services.calendar = MockCalendar()
    mock_services.tasks = MockTasks()

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.6)

        from caden.ui.dashboard import SidePanel, TaskItem

        week_panel = list(app.query(SidePanel))[1]
        texts = [item._text for item in list(week_panel.query(TaskItem))]

    assert len(texts) >= 3
    assert "[event] Week early event" in texts[0]
    assert "[task] Week middle task" in texts[1]
    assert "[event] Week later event" in texts[2]


@pytest.mark.asyncio
async def test_dashboard_today_panel_includes_linked_caden_scheduled_work_without_duplicate_task_row(mock_services):
    now = datetime.now(timezone.utc)
    task_id = write_task(
        mock_services.conn,
        description="Linked scheduled work",
        deadline_iso=(now + timedelta(days=1)).isoformat(),
        google_task_id="g_linked",
        embedding=[0.1] * 768,
    )
    link_task_event(
        mock_services.conn,
        task_id=task_id,
        google_event_id="evt_linked",
        planned_start_iso=(now + timedelta(hours=1)).isoformat(),
        planned_end_iso=(now + timedelta(hours=2)).isoformat(),
    )

    class MockCalendar:
        def list_window(self, start, end):
            return [
                CalendarEvent(
                    id="evt_linked",
                    summary="CADEN scheduled focus block",
                    start=now + timedelta(hours=1),
                    end=now + timedelta(hours=2),
                    raw={},
                )
            ]

    class MockTasks:
        def list_open(self):
            return [
                GTask(
                    id="g_linked",
                    title="Linked scheduled work",
                    due=now + timedelta(hours=1, minutes=30),
                    status="needsAction",
                    completed_at=None,
                    raw={},
                )
            ]

    mock_services.calendar = MockCalendar()
    mock_services.tasks = MockTasks()

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.6)

        from caden.ui.dashboard import SidePanel, TaskItem

        today_panel = list(app.query(SidePanel))[0]
        texts = [item._text for item in list(today_panel.query(TaskItem))]

    assert len(texts) == 1
    assert "[task] CADEN scheduled focus block" in texts[0]


@pytest.mark.asyncio
async def test_dashboard_renders_google_times_in_local_timezone_from_utc_inputs(mock_services):
    event_start = datetime(2026, 4, 30, 18, 0, tzinfo=timezone.utc)
    event_end = event_start + timedelta(hours=1)
    expected_stamp = format_display_time(event_start, include_weekday=True)

    class MockCalendar:
        def list_window(self, start, end):
            return [
                CalendarEvent(
                    id="evt_local",
                    summary="UTC sourced event",
                    start=event_start,
                    end=event_end,
                    raw={},
                )
            ]

    class MockTasks:
        def list_open(self):
            return []

    mock_services.calendar = MockCalendar()
    mock_services.tasks = MockTasks()

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.6)

        from caden.ui.dashboard import SidePanel, TaskItem

        today_panel = list(app.query(SidePanel))[0]
        texts = [item._text for item in list(today_panel.query(TaskItem))]

    assert any(expected_stamp in text for text in texts)
    assert any("UTC sourced event" in text for text in texts)
