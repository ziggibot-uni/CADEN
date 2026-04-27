import pytest
from datetime import datetime, timedelta, timezone
import httpx
import json

from caden.ui.app import CadenApp
from caden.ui.add_task import AddTaskScreen
from caden.google_sync.calendar import CalendarEvent
from caden.google_sync.tasks import GTask
from caden.errors import SchedulerError
from caden.libbie.store import link_task_event, write_task
from caden.scheduler.schedule import ExistingEvent
from caden.llm.client import OllamaClient
from caden.llm.embed import Embedder


def _future_local_dt(days_ahead: int, hour: int, minute: int = 0) -> datetime:
    return (datetime.now().astimezone() + timedelta(days=days_ahead)).replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )


def _llm_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def _input_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


@pytest.mark.asyncio
async def test_m4_addtask_requires_deadline_before_submitting(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.5)
        await app.action_add_task()
        await pilot.pause(0.5)

        modal = app.screen
        assert isinstance(modal, AddTaskScreen)

        from textual.widgets import Button, Input, Static

        inputs = list(modal.query(Input))
        inputs[0].value = "Task with no deadline"
        inputs[1].value = ""

        modal.query_one("#ok", Button).press()
        await pilot.pause(0.2)

        status = modal.query_one("#status", Static)
        assert "deadline is required" in status.render().plain

    task_count = mock_services.conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
    assert task_count == 0


@pytest.mark.asyncio
async def test_m4_addtask_requires_description_before_submitting(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.5)
        await app.action_add_task()
        await pilot.pause(0.5)

        modal = app.screen
        assert isinstance(modal, AddTaskScreen)

        from textual.widgets import Button, Input, Static

        inputs = list(modal.query(Input))
        inputs[0].value = ""
        inputs[1].value = _input_ts(_future_local_dt(1, 17))

        modal.query_one("#ok", Button).press()
        await pilot.pause(0.2)

        status = modal.query_one("#status", Static)
        assert "description is required" in status.render().plain

    task_count = mock_services.conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
    assert task_count == 0


def test_add_task_reads_calendar_between_now_and_deadline_and_tags_caden_owned_events(mock_services):
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    deadline = now + timedelta(days=2)
    owned_start = now + timedelta(hours=3)
    owned_end = owned_start + timedelta(hours=1)
    external_start = now + timedelta(hours=5)
    external_end = external_start + timedelta(hours=1)
    seen: dict[str, datetime] = {}

    task_id = write_task(
        mock_services.conn,
        description="Existing CADEN block",
        deadline_iso=deadline.isoformat(),
        google_task_id="owned-task",
        embedding=[0.1] * 768,
    )
    link_task_event(
        mock_services.conn,
        task_id=task_id,
        google_event_id="owned_evt_1",
        planned_start_iso=owned_start.isoformat(),
        planned_end_iso=owned_end.isoformat(),
    )

    class MockCalendar:
        def list_window(self, start, end):
            seen["start"] = start
            seen["end"] = end
            return [
                CalendarEvent(
                    id="owned_evt_1",
                    summary="Existing CADEN block",
                    start=owned_start,
                    end=owned_end,
                    raw={},
                ),
                CalendarEvent(
                    id="external_evt_1",
                    summary="Doctor appointment",
                    start=external_start,
                    end=external_end,
                    raw={},
                ),
            ]

    mock_services.calendar = MockCalendar()
    screen = AddTaskScreen(mock_services)

    gathered = screen._gather_existing(deadline, now)

    assert seen == {"start": now, "end": deadline}
    assert gathered == [
        ExistingEvent(
            google_event_id="owned_evt_1",
            summary="Existing CADEN block",
            start=owned_start,
            end=owned_end,
            caden_owned=True,
        ),
        ExistingEvent(
            google_event_id="external_evt_1",
            summary="Doctor appointment",
            start=external_start,
            end=external_end,
            caden_owned=False,
        ),
    ]


def test_add_task_requires_google_write_clients_before_storing_anything(mock_services, monkeypatch):
    deadline = datetime.now(timezone.utc) + timedelta(days=1)
    embed_called = {"value": False}
    plan_called = {"value": False}

    class _Embedder:
        def embed(self, text):
            embed_called["value"] = True
            return [0.1] * 768

        def close(self):
            return None

    def _fail_if_planned(*args, **kwargs):
        plan_called["value"] = True
        raise AssertionError("scheduler should not run before google clients exist")

    mock_services.tasks = None
    mock_services.calendar = None
    mock_services.embedder = _Embedder()
    monkeypatch.setattr("caden.ui.add_task.plan", _fail_if_planned)

    screen = AddTaskScreen(mock_services)

    with pytest.raises(
        SchedulerError,
        match="add-task requires configured Google Tasks and Calendar write clients",
    ):
        screen._execute("Blocked until google is configured", deadline)

    assert embed_called["value"] is False
    assert plan_called["value"] is False
    assert mock_services.conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"] == 0
    assert mock_services.conn.execute("SELECT COUNT(*) AS n FROM task_events").fetchone()["n"] == 0
    assert mock_services.conn.execute("SELECT COUNT(*) AS n FROM predictions").fetchone()["n"] == 0


def test_add_task_requires_default_writable_targets_when_scope_clients_expose_them(mock_services):
    deadline = datetime.now(timezone.utc) + timedelta(days=1)

    class _ScopedTasks:
        writable_task_list_id = ""

    class _ScopedCalendar:
        writable_calendar_id = ""

    mock_services.tasks = _ScopedTasks()
    mock_services.calendar = _ScopedCalendar()

    screen = AddTaskScreen(mock_services)

    with pytest.raises(
        SchedulerError,
        match="default writable Google task list",
    ):
        screen._execute("Needs defaults", deadline)


@pytest.mark.asyncio
async def test_add_task_submit_offloads_execute_via_to_thread(mock_services, monkeypatch):
    calls: list[tuple[object, tuple[object, ...]]] = []
    dismissed: list[bool] = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append((func, args))
        return None

    monkeypatch.setattr("caden.ui.add_task.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr(AddTaskScreen, "dismiss", lambda self, result=False: dismissed.append(result))

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)
        await app.action_add_task()
        await pilot.pause(0.2)

        modal = app.screen
        assert isinstance(modal, AddTaskScreen)

        from textual.widgets import Input

        inputs = list(modal.query(Input))
        inputs[0].value = "Threaded add"
        inputs[1].value = _input_ts(_future_local_dt(1, 17))

        await modal._submit()

    assert len(calls) == 1
    assert getattr(calls[0][0], "__name__", "") == "_execute"
    assert dismissed == [True]

@pytest.mark.asyncio
async def test_m4_addtask(tmp_caden_home, db_conn, mock_services, httpx_mock, monkeypatch):
    scheduled_start = _future_local_dt(1, 14)
    scheduled_end = scheduled_start + timedelta(hours=1)
    deadline = _future_local_dt(2, 15)

    class MockCalendar:
        def __init__(self):
            self.created = []
        def list_window(self, start, end):
            return []
        def create_event(self, summary, start, end, description=""):
            self.created.append({"summary": summary, "start": start, "end": end, "description": description})
            return CalendarEvent(
                id=f"evt_{len(self.created)}",
                summary=summary,
                start=start,
                end=end,
                raw={}
            )

    class MockTasks:
        def __init__(self):
            self.created = []
        def create(self, title, notes="", due=""):
            self.created.append({"title": title, "notes": notes})
            return GTask(id=f"task_{len(self.created)}", title=title, due=due, status="needsAction", completed_at=None, raw={})

    mock_calendar = MockCalendar()
    mock_tasks = MockTasks()
    mock_services.calendar = mock_calendar
    mock_services.tasks = mock_tasks
    mock_services.llm = OllamaClient("http://127.0.0.1:11434", "llama3.1:8b")
    mock_services.embedder = Embedder("http://127.0.0.1:11434", "nomic-embed-text", 768)

    predict_response = json.dumps({
        "model": "llama3.1:8b",
        "message": {
            "role": "assistant",
            "content": '```json\n{"predicted_duration_min": 60, "pre": {"mood": 0.5, "energy": 0.5, "productivity": 0.5}, "post": {"mood": 0.6, "energy": 0.4, "productivity": 0.7}, "rationale": "It will take an hour.", "confidence": {"duration": 0.9, "pre_mood": 0.8, "pre_energy": 0.8, "pre_productivity": 0.8, "post_mood": 0.7, "post_energy": 0.7, "post_productivity": 0.7}}\n```'
        },
        "done": True,
    }) + "\n"
    
    schedule_response = json.dumps({
        "model": "llama3.1:8b",
        "message": {
            "role": "assistant",
            "content": (
                "```json\n"
                f'{{"start": "{_llm_ts(scheduled_start)}", "end": "{_llm_ts(scheduled_end)}", '
                '"moves": [], "rationale": "Looks free."}}\n```'
            )
        },
        "done": True,
    }) + "\n"

    def llm_route(request: httpx.Request):
        body = json.loads(request.read())
        user_msg = next((m["content"] for m in body["messages"] if m["role"] == "user"), "")
        if "PREDICTION" in user_msg or "predict" in body["messages"][0]["content"].lower():
            return httpx.Response(200, text=predict_response)
        else:
            return httpx.Response(200, text=schedule_response)

    httpx_mock.add_callback(llm_route, url="http://127.0.0.1:11434/api/chat", is_reusable=True)
    httpx_mock.add_response(url="http://127.0.0.1:11434/api/embeddings", json={"embedding": [0.1] * 768}, is_reusable=True)

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot: # increase screen size to prevent OutOfBounds
        # Give Dashboard time to fetch and render
        await pilot.pause(1)

        # Trigger Add Task directly to be sure
        await app.action_add_task()
        await pilot.pause(1)

        # Fill out the modal form
        modal = app.screen
        assert isinstance(modal, AddTaskScreen)

        # We must navigate to the inputs. First is task description.
        from textual.widgets import Input
        inputs = list(modal.query(Input))
        inputs[0].value = "Write a brand new test"
        inputs[1].value = _input_ts(deadline)
        
        # Submit the form by finding the submit button
        from textual.widgets import Button
        btn = modal.query_one("#ok", Button)
        btn.press()
        
        # Wait a bit longer for all background LLM / API calls to finish
        await pilot.pause(2.5)

    assert len(mock_tasks.created) == 1, "Google Task should be created"
    assert len(mock_calendar.created) == 1, "Google Calendar Event should be created"
    assert mock_tasks.created[0]["title"] == "Write a brand new test"
    assert "2:00 pm" in mock_tasks.created[0]["notes"]
    assert "3:00 pm" in mock_tasks.created[0]["notes"]
    assert "14:00" not in mock_tasks.created[0]["notes"]
    assert "2:00 pm" in mock_calendar.created[0]["description"]
    assert "3:00 pm" in mock_calendar.created[0]["description"]
    assert "14:00" not in mock_calendar.created[0]["description"]
    
    # Assert DB state
    cur = mock_services.conn.cursor()
    
    # task row
    task_id = cur.execute("SELECT id FROM tasks").fetchone()
    assert task_id is not None, "DB missing task row"
    
    # task_events row
    te_row = cur.execute("SELECT id FROM task_events WHERE task_id=?", (task_id[0],)).fetchone()
    assert te_row is not None, "DB missing task_events row"
    
    # prediction row
    pred_row = cur.execute("SELECT id FROM predictions").fetchone()
    assert pred_row is not None, "DB missing predictions row"

    full_prediction = cur.execute(
        """
        SELECT pred_pre_mood, pred_pre_energy, pred_pre_productivity,
               pred_post_mood, pred_post_energy, pred_post_productivity,
               conf_duration,
               conf_pre_mood, conf_pre_energy, conf_pre_productivity,
               conf_post_mood, conf_post_energy, conf_post_productivity
        FROM predictions
        WHERE id=?
        """,
        (pred_row["id"],),
    ).fetchone()
    assert full_prediction is not None
    assert full_prediction["pred_pre_mood"] == 0.5
    assert full_prediction["pred_pre_energy"] == 0.5
    assert full_prediction["pred_pre_productivity"] == 0.5
    assert full_prediction["pred_post_mood"] == 0.6
    assert full_prediction["pred_post_energy"] == 0.4
    assert full_prediction["pred_post_productivity"] == 0.7
    assert full_prediction["conf_duration"] == 0.9
    assert full_prediction["conf_pre_mood"] == 0.8
    assert full_prediction["conf_pre_energy"] == 0.8
    assert full_prediction["conf_pre_productivity"] == 0.8
    assert full_prediction["conf_post_mood"] == 0.7
    assert full_prediction["conf_post_energy"] == 0.7
    assert full_prediction["conf_post_productivity"] == 0.7

    mirrored = cur.execute(
        "SELECT id FROM events WHERE source='prediction' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert mirrored is not None, "Prediction bundles must also be mirrored into events"

    memory_row = cur.execute(
        "SELECT source, context FROM memories WHERE event_id=?",
        (mirrored["id"],),
    ).fetchone()
    assert memory_row is not None, "Prediction bundles must also become curated memories"
    assert memory_row["source"] == "prediction"
    assert "Prediction for task" in memory_row["context"]


@pytest.mark.asyncio
async def test_m4_addtask_creates_a_single_scheduled_block(
    tmp_caden_home, db_conn, mock_services, httpx_mock
):
    block_start = _future_local_dt(1, 14)
    block_end = block_start + timedelta(hours=2, minutes=30)
    deadline = _future_local_dt(2, 15)

    class MockCalendar:
        def __init__(self):
            self.created = []
        def list_window(self, start, end):
            return []
        def create_event(self, summary, start, end, description=""):
            self.created.append(
                {
                    "summary": summary,
                    "start": start,
                    "end": end,
                    "description": description,
                }
            )
            return CalendarEvent(
                id=f"evt_{len(self.created)}",
                summary=summary,
                start=start,
                end=end,
                raw={},
            )

    class MockTasks:
        def __init__(self):
            self.created = []
        def create(self, title, notes="", due=""):
            self.created.append({"title": title, "notes": notes, "due": due})
            return GTask(
                id=f"task_{len(self.created)}",
                title=title,
                due=due,
                status="needsAction",
                completed_at=None,
                raw={},
            )

    mock_calendar = MockCalendar()
    mock_tasks = MockTasks()
    mock_services.calendar = mock_calendar
    mock_services.tasks = mock_tasks
    mock_services.llm = OllamaClient("http://127.0.0.1:11434", "llama3.1:8b")
    mock_services.embedder = Embedder("http://127.0.0.1:11434", "nomic-embed-text", 768)

    predict_response = json.dumps({
        "model": "llama3.1:8b",
        "message": {
            "role": "assistant",
            "content": '```json\n{"predicted_duration_min": 150, "pre": {"mood": null, "energy": 0.1, "productivity": null}, "post": {"mood": 0.2, "energy": -0.1, "productivity": 0.5}, "rationale": "Two focused sessions should finish it.", "confidence": {"duration": 0.7, "pre_mood": null, "pre_energy": 0.4, "pre_productivity": null, "post_mood": 0.5, "post_energy": 0.5, "post_productivity": 0.6}}\n```'
        },
        "done": True,
    }) + "\n"

    schedule_response = json.dumps({
        "model": "llama3.1:8b",
        "message": {
            "role": "assistant",
            "content": (
                "```json\n"
                f'{{"start": "{_llm_ts(block_start)}", "end": "{_llm_ts(block_end)}", '
                '"moves": [], "rationale": "One focused block should finish it before the deadline."}}\n```'
            )
        },
        "done": True,
    }) + "\n"

    def llm_route(request: httpx.Request):
        body = json.loads(request.read())
        user_msg = next((m["content"] for m in body["messages"] if m["role"] == "user"), "")
        if "prediction bundle" in user_msg.lower():
            return httpx.Response(200, text=predict_response)
        return httpx.Response(200, text=schedule_response)

    httpx_mock.add_callback(
        llm_route,
        url="http://127.0.0.1:11434/api/chat",
        is_reusable=True,
    )
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/embeddings",
        json={"embedding": [0.1] * 768},
        is_reusable=True,
    )

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(1)
        await app.action_add_task()
        await pilot.pause(1)

        modal = app.screen
        assert isinstance(modal, AddTaskScreen)

        from textual.widgets import Button
        from textual.widgets import Input

        inputs = list(modal.query(Input))
        inputs[0].value = "Write the single-block regression test"
        inputs[1].value = _input_ts(deadline)

        btn = modal.query_one("#ok", Button)
        btn.press()
        await pilot.pause(2.5)

    assert len(mock_tasks.created) == 1, "Google Task should be created once"
    assert len(mock_calendar.created) == 1, "Single-block scheduling should create one calendar event"
    assert mock_calendar.created[0]["summary"] == "Write the single-block regression test"

    cur = mock_services.conn.cursor()
    task_event_rows = cur.execute(
        "SELECT planned_start, planned_end FROM task_events ORDER BY id"
    ).fetchall()
    assert len(task_event_rows) == 1, "DB should persist one task_event row per task"
    assert task_event_rows[0]["planned_start"] == block_start.astimezone(timezone.utc).isoformat(timespec="seconds")
    assert task_event_rows[0]["planned_end"] == block_end.astimezone(timezone.utc).isoformat(timespec="seconds")

    prediction_row = cur.execute(
        "SELECT pred_duration_min, pred_pre_mood, pred_post_productivity FROM predictions ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert prediction_row is not None, "Split scheduling should still emit a prediction bundle"
    assert prediction_row["pred_duration_min"] == 150
    assert prediction_row["pred_pre_mood"] is None
    assert prediction_row["pred_post_productivity"] == 0.5


@pytest.mark.asyncio
async def test_m4_addtask_applies_displacements_for_caden_owned_blocks(
    tmp_caden_home, db_conn, mock_services, httpx_mock
):
    existing_start_local = _future_local_dt(1, 14)
    existing_end_local = existing_start_local + timedelta(hours=1)
    moved_start_local = existing_end_local
    moved_end_local = moved_start_local + timedelta(hours=1)
    deadline = _future_local_dt(2, 15)
    existing_start_utc = existing_start_local.astimezone(timezone.utc)
    existing_end_utc = existing_end_local.astimezone(timezone.utc)

    class MockCalendar:
        def __init__(self):
            self.created = []
            self.rescheduled = []

        def list_window(self, start, end):
            return [
                CalendarEvent(
                    id="owned_evt_1",
                    summary="Existing CADEN block",
                    start=existing_start_utc,
                    end=existing_end_utc,
                    raw={},
                )
            ]

        def create_event(self, summary, start, end, description=""):
            self.created.append({"summary": summary, "start": start, "end": end})
            return CalendarEvent(
                id=f"evt_{len(self.created)}",
                summary=summary,
                start=start,
                end=end,
                raw={},
            )

        def reschedule(self, event_id, new_start, new_end):
            self.rescheduled.append(
                {"event_id": event_id, "new_start": new_start, "new_end": new_end}
            )

    class MockTasks:
        def __init__(self):
            self.created = []

        def create(self, title, notes="", due=""):
            self.created.append({"title": title, "notes": notes, "due": due})
            return GTask(
                id=f"task_{len(self.created)}",
                title=title,
                due=due,
                status="needsAction",
                completed_at=None,
                raw={},
            )

    existing_task_id = write_task(
        db_conn,
        description="Existing scheduled task",
        deadline_iso=deadline.astimezone(timezone.utc).isoformat(),
        google_task_id="google-existing-task",
        embedding=[0.1] * 768,
    )
    link_task_event(
        db_conn,
        task_id=existing_task_id,
        google_event_id="owned_evt_1",
        planned_start_iso=existing_start_utc.isoformat(),
        planned_end_iso=existing_end_utc.isoformat(),
    )

    mock_calendar = MockCalendar()
    mock_tasks = MockTasks()
    mock_services.calendar = mock_calendar
    mock_services.tasks = mock_tasks
    mock_services.llm = OllamaClient("http://127.0.0.1:11434", "llama3.1:8b")
    mock_services.embedder = Embedder("http://127.0.0.1:11434", "nomic-embed-text", 768)

    predict_response = json.dumps({
        "model": "llama3.1:8b",
        "message": {
            "role": "assistant",
            "content": '```json\n{"predicted_duration_min": 60, "pre": {"mood": 0.0, "energy": 0.1, "productivity": 0.0}, "post": {"mood": 0.2, "energy": -0.1, "productivity": 0.3}, "rationale": "Moving the earlier block frees the slot.", "confidence": {"duration": 0.8, "pre_mood": 0.5, "pre_energy": 0.5, "pre_productivity": 0.4, "post_mood": 0.5, "post_energy": 0.4, "post_productivity": 0.5}}\n```'
        },
        "done": True,
    }) + "\n"

    schedule_response = json.dumps({
        "model": "llama3.1:8b",
        "message": {
            "role": "assistant",
            "content": (
                "```json\n"
                f'{{"start": "{_llm_ts(existing_start_local)}", "end": "{_llm_ts(existing_end_local)}", '
                f'"moves": [{{"google_event_id": "owned_evt_1", "new_start": "{_llm_ts(moved_start_local)}", '
                f'"new_end": "{_llm_ts(moved_end_local)}"}}], '
                '"rationale": "Move the existing CADEN block one hour later, then use its old slot."}}\n```'
            )
        },
        "done": True,
    }) + "\n"

    def llm_route(request: httpx.Request):
        body = json.loads(request.read())
        user_msg = next((m["content"] for m in body["messages"] if m["role"] == "user"), "")
        if "prediction bundle" in user_msg.lower():
            return httpx.Response(200, text=predict_response)
        return httpx.Response(200, text=schedule_response)

    httpx_mock.add_callback(
        llm_route,
        url="http://127.0.0.1:11434/api/chat",
        is_reusable=True,
    )
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/embeddings",
        json={"embedding": [0.1] * 768},
        is_reusable=True,
    )

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(1)
        await app.action_add_task()
        await pilot.pause(1)

        modal = app.screen
        assert isinstance(modal, AddTaskScreen)

        from textual.widgets import Button
        from textual.widgets import Input

        inputs = list(modal.query(Input))
        inputs[0].value = "New task needing a moved block"
        inputs[1].value = _input_ts(deadline)

        modal.query_one("#ok", Button).press()
        await pilot.pause(2.5)

    assert len(mock_calendar.rescheduled) == 1, "CADEN-owned overlaps should be rescheduled"
    move = mock_calendar.rescheduled[0]
    assert move["event_id"] == "owned_evt_1"
    assert move["new_start"].astimezone(timezone.utc).isoformat(timespec="seconds") == moved_start_local.astimezone(timezone.utc).isoformat(timespec="seconds")
    assert move["new_end"].astimezone(timezone.utc).isoformat(timespec="seconds") == moved_end_local.astimezone(timezone.utc).isoformat(timespec="seconds")

    moved_row = mock_services.conn.cursor().execute(
        "SELECT planned_start, planned_end FROM task_events WHERE google_event_id='owned_evt_1'"
    ).fetchone()
    assert moved_row is not None
    assert moved_row["planned_start"] == move["new_start"].astimezone(timezone.utc).isoformat(timespec="seconds")
    assert moved_row["planned_end"] == move["new_end"].astimezone(timezone.utc).isoformat(timespec="seconds")
