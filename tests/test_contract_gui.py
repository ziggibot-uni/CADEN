import pytest
from datetime import datetime, timedelta, timezone
import asyncio

from textual.widgets import Button, TabbedContent, TabPane

from caden.ui.app import CadenApp
from caden.config import COMPLETION_POLL_SECONDS
from caden.google_sync.calendar import CalendarEvent
from caden.google_sync.tasks import GTask
from caden.libbie.store import link_task_event, write_task
from caden.ui.dashboard import Dashboard, SidePanel
from textual.widgets import Static


@pytest.mark.asyncio
async def test_app_uses_tabbed_root_architecture(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test() as pilot:
        await pilot.pause(0.1)

        tabbed = list(app.query(TabbedContent))
        panes = list(app.query(TabPane))

    assert tabbed, "CADEN root should use a TabbedContent container"
    assert panes, "CADEN apps should be mounted as TabPane instances"


@pytest.mark.asyncio
async def test_completion_poll_uses_documented_60_second_cadence(mock_services, monkeypatch):
    captured = {}

    def fake_set_interval(self, interval, callback, name=None):
        captured["interval"] = interval
        captured["name"] = name
        captured["callback"] = callback
        return None

    monkeypatch.setattr(CadenApp, "set_interval", fake_set_interval)
    mock_services.tasks = object()

    app = CadenApp(mock_services)
    async with app.run_test() as pilot:
        await pilot.pause(0.1)

    assert captured["interval"] == COMPLETION_POLL_SECONDS == 60
    assert captured["name"] == "completion-poll"


@pytest.mark.asyncio
async def test_refresh_action_runs_dashboard_panel_refresh(mock_services, monkeypatch):
    captured = {}

    def fake_run_worker(self, awaitable, *, group=None, **kwargs):
        captured["group"] = group
        captured["awaitable"] = awaitable
        return None

    monkeypatch.setattr(CadenApp, "run_worker", fake_run_worker)

    app = CadenApp(mock_services)
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        app.action_refresh()

    assert captured["group"] == "refresh-panels"
    captured["awaitable"].close()


@pytest.mark.asyncio
async def test_dashboard_completion_button_marks_task_complete_and_refreshes(mock_services, monkeypatch):
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=30)
    end = now + timedelta(minutes=30)

    task_id = write_task(
        mock_services.conn,
        description="Finish the GUI task",
        deadline_iso=(now + timedelta(days=1)).isoformat(),
        google_task_id="g_1",
        embedding=[0.1] * 768,
    )
    link_task_event(
        mock_services.conn,
        task_id=task_id,
        google_event_id="evt_1",
        planned_start_iso=start.isoformat(),
        planned_end_iso=end.isoformat(),
    )
    mock_services.conn.execute(
        "INSERT INTO predictions (task_id, pred_duration_min, created_at) VALUES (?, ?, datetime('now'))",
        (task_id, 60),
    )
    mock_services.conn.commit()

    class MockCalendar:
        def __init__(self):
            self.ended = []

        def list_window(self, window_start, window_end):
            return [
                CalendarEvent(
                    id="evt_1",
                    summary="Finish the GUI task",
                    start=start,
                    end=end,
                    raw={},
                )
            ]

        def set_end_time(self, event_id, when):
            self.ended.append((event_id, when))

    class MockTasks:
        def __init__(self):
            self.completed = False

        def list_open(self):
            if self.completed:
                return []
            return [
                GTask(
                    id="g_1",
                    title="Finish the GUI task",
                    due=end,
                    status="needsAction",
                    completed_at=None,
                    raw={},
                )
            ]

        def mark_completed(self, task_id):
            self.completed = True

        def get(self, task_id):
            status = "completed" if self.completed else "needsAction"
            completed_at = now if self.completed else None
            return GTask(
                id=task_id,
                title="Finish the GUI task",
                due=None,
                status=status,
                completed_at=completed_at,
                raw={},
            )

    notifications = []

    def fake_notify(self, message, *, severity="information", **kwargs):
        notifications.append((message, severity))

    monkeypatch.setattr(CadenApp, "notify", fake_notify)
    mock_services.calendar = MockCalendar()
    mock_services.tasks = MockTasks()

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.6)
        app.query_one("#complete_g_1", Button).press()
        await pilot.pause(0.6)

        buttons = list(app.query("#complete_g_1"))

    assert mock_services.tasks.completed is True
    assert mock_services.calendar.ended == [("evt_1", now)]
    assert notifications == [("1 task(s) completed; residuals stored.", "information")]
    assert not buttons


@pytest.mark.asyncio
async def test_dashboard_shows_documented_google_sync_placeholders_when_booted_chat_only(mock_services):
    mock_services.calendar = None
    mock_services.tasks = None

    app = CadenApp(mock_services)

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.4)
        panels = list(app.query(SidePanel))
        rendered = [
            panel.query_one("#scroll Static").render().plain
            for panel in panels
        ]

    assert len(panels) == 2
    assert rendered == [
        "(Google sync not configured)",
        "(Google sync not configured)",
    ]


@pytest.mark.asyncio
async def test_dashboard_region_has_nonzero_height_in_live_layout(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.3)
        dashboard = app.query_one(Dashboard)
        assert dashboard.region.height > 10


@pytest.mark.asyncio
async def test_dashboard_renders_visible_core_labels_and_controls(mock_services):
    mock_services.calendar = None
    mock_services.tasks = None

    app = CadenApp(mock_services)

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.4)
        dashboard = app.query_one(Dashboard)
        chat = dashboard.query_one("#chat-header", Static).render().plain
        today = list(dashboard.query(SidePanel))[0].query_one("#title", Static).render().plain
        week = list(dashboard.query(SidePanel))[1].query_one("#title", Static).render().plain
        add_task = app.query_one("#add-task", Button).label.plain

    assert chat == "CADEN — chat"
    assert today == "Today"
    assert week == "Next 7 days"
    assert add_task == "+ add task"


@pytest.mark.asyncio
async def test_app_clock_renders_detroit_time_in_12_hour_format(mock_services, monkeypatch):
    fixed_now = datetime(2026, 4, 27, 3, 30, tzinfo=timezone.utc)

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr("caden.ui.app.datetime", _FixedDateTime)
    app = CadenApp(mock_services)

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause(0.1)
        clock = app.query_one("#app-clock", Static).render().plain

    assert clock == "11:30 pm"


@pytest.mark.asyncio
async def test_app_poll_completions_offloads_blocking_poll_once_via_to_thread(mock_services, monkeypatch):
    calls: list[tuple[object, tuple[object, ...]]] = []

    async def fake_to_thread(func, *args):
        calls.append((func, args))
        return []

    monkeypatch.setattr("caden.ui.app.asyncio.to_thread", fake_to_thread)
    mock_services.tasks = object()
    mock_services.calendar = object()

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 24)) as pilot:
        await app._poll_completions()
        await pilot.pause(0.1)

    assert len(calls) == 1
    assert calls[0][0].__name__ == "poll_once"
    assert calls[0][1] == (mock_services.conn, mock_services.tasks, mock_services.calendar)


@pytest.mark.asyncio
async def test_dashboard_refresh_panels_offloads_google_reads_via_to_thread(mock_services, monkeypatch):
    now = datetime.now(timezone.utc)
    calls: list[tuple[object, tuple[object, ...]]] = []

    class MockCalendar:
        def list_window(self, window_start, window_end):
            return []

    class MockTasks:
        def list_open(self):
            return []

    async def fake_to_thread(func, *args):
        calls.append((func, args))
        return func(*args)

    monkeypatch.setattr("caden.ui.dashboard.asyncio.to_thread", fake_to_thread)
    mock_services.calendar = MockCalendar()
    mock_services.tasks = MockTasks()

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)
        dashboard = app.query_one(Dashboard)
        calls.clear()
        await dashboard.refresh_panels()

    called_names = [getattr(func, "__name__", "") for func, _args in calls]
    assert called_names.count("list_window") == 2
    assert "list_open" in called_names


@pytest.mark.asyncio
async def test_dashboard_complete_task_offloads_blocking_google_calls_via_to_thread(mock_services, monkeypatch):
    calls: list[tuple[object, tuple[object, ...]]] = []

    class MockTasks:
        def mark_completed(self, task_id):
            return None

    async def fake_to_thread(func, *args):
        calls.append((func, args))
        if getattr(func, "__name__", "") == "poll_once":
            return [1]
        return func(*args)

    monkeypatch.setattr("caden.ui.dashboard.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr(CadenApp, "notify", lambda self, message, *, severity="information", **kwargs: None)
    mock_services.tasks = MockTasks()
    mock_services.calendar = object()

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)
        dashboard = app.query_one(Dashboard)
        await dashboard._complete_task("g_1")
        await pilot.pause(0.1)

    called_names = [getattr(func, "__name__", "") for func, _args in calls]
    assert "mark_completed" in called_names
    assert "poll_once" in called_names


@pytest.mark.asyncio
async def test_app_shutdown_cancels_owned_background_workers(mock_services):
    cancelled = asyncio.Event()

    class _SentinelDashboard(Dashboard):
        def on_mount(self) -> None:
            self.run_worker(self._sentinel(), group="refresh-panels")

        async def _sentinel(self) -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    class _SentinelApp(CadenApp):
        def _dashboard(self) -> Dashboard:
            return self.query_one(_SentinelDashboard)

        def compose(self):
            from textual.containers import Horizontal
            from textual.widgets import Footer, Static, TabbedContent, TabPane

            with Horizontal(id="app-header"):
                yield Static("CADEN", id="app-title")
                yield Static("", id="app-clock")
            with TabbedContent(initial="dashboard"):
                with TabPane("Dashboard", id="dashboard"):
                    yield _SentinelDashboard(self.services)
            yield Footer()

    app = _SentinelApp(mock_services)

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)

    await asyncio.wait_for(cancelled.wait(), timeout=1)