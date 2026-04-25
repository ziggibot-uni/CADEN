import pytest
from datetime import datetime, timezone
import httpx
import json

from caden.ui.app import CadenApp
from caden.ui.add_task import AddTaskScreen
from caden.google_sync.calendar import CalendarEvent
from caden.google_sync.tasks import GTask
from caden.llm.client import OllamaClient
from caden.llm.embed import Embedder

@pytest.mark.asyncio
async def test_m4_addtask(tmp_caden_home, db_conn, mock_services, httpx_mock, monkeypatch):
    class MockCalendar:
        def __init__(self):
            self.created = []
        def list_window(self, start, end):
            return []
        def create_event(self, summary, start, end, description=""):
            self.created.append({"summary": summary, "start": start, "end": end})
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
            "content": '```json\n{"predicted_duration_min": 60, "pre": {"mood": 0.5, "energy": 0.5, "productivity": 0.5}, "post": {"mood": 0.6, "energy": 0.4, "productivity": 0.7}, "rationale": "It will take an hour.", "confidence": {"duration_min": 0.9, "pre_mood": 0.8, "pre_energy": 0.8, "pre_productivity": 0.8, "post_mood": 0.7, "post_energy": 0.7, "post_productivity": 0.7}}\n```'
        },
        "done": True,
    }) + "\n"
    
    schedule_response = json.dumps({
        "model": "llama3.1:8b",
        "message": {
            "role": "assistant",
            "content": '```json\n{"start": "2026-04-26 14:00", "end": "2026-04-26 15:00", "moves": [], "rationale": "Looks free."}\n```'
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
        inputs[1].value = "2026-04-27T15:00" # deadline
        
        # Submit the form by finding the submit button
        from textual.widgets import Button
        btn = modal.query_one("#ok", Button)
        btn.press()
        
        # Wait a bit longer for all background LLM / API calls to finish
        await pilot.pause(2.5)

    assert len(mock_tasks.created) == 1, "Google Task should be created"
    assert len(mock_calendar.created) == 1, "Google Calendar Event should be created"
    assert mock_tasks.created[0]["title"] == "Write a brand new test"
    
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
