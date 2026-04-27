from __future__ import annotations

from datetime import datetime, timezone

import pytest

from caden.errors import ProjectManagerError
from caden.libbie.projects import list_project_entries, list_projects, normalize_project_id
from caden.project_manager.service import ProjectManagerService
from caden.ui.app import CadenApp
from caden.ui.project_manager import ProjectManagerPane
from textual.widgets import Button, Input, Static
from textual.containers import VerticalScroll


class _Embedder:
    def embed(self, text: str):
        return [0.1] * 768


class _Tasks:
    def __init__(self) -> None:
        self.created: list[dict[str, str]] = []

    def create(self, title: str, due=None, notes: str = ""):
        self.created.append({"title": title, "notes": notes})
        return type("_Task", (), {"id": f"g_pm_{len(self.created)}"})()


def test_project_manager_normalizes_project_id():
    assert normalize_project_id(" CS 101 / Final Project ") == "cs_101_final_project"


def test_project_manager_entries_persist_in_libbie_event_pipeline(db_conn):
    service = ProjectManagerService(db_conn, _Embedder())

    first = service.add_entry(
        project_name="Compiler Class",
        entry_type="comment",
        text="Need to refine parser milestones.",
    )
    second = service.add_entry(
        project_name="Compiler Class",
        entry_type="update",
        text="Shifted focus to lexer cleanup.",
    )

    projects = list_projects(db_conn)
    entries = list_project_entries(db_conn, first.project_id)

    assert len(projects) == 1
    assert projects[0].project_id == first.project_id
    assert projects[0].entry_count == 2
    assert [entry.event_id for entry in entries] == [first.event_id, second.event_id]
    assert entries[0].entry_type == "comment"
    assert entries[1].entry_type == "update"


def test_project_manager_todo_requires_google_tasks_client(db_conn):
    service = ProjectManagerService(db_conn, _Embedder(), tasks_client=None)

    with pytest.raises(
        ProjectManagerError,
        match="TODO entries require configured Google Tasks client",
    ):
        service.add_entry(
            project_name="Errands",
            entry_type="todo",
            text="Call the clinic",
        )


def test_project_manager_todo_creates_google_task_and_links_metadata(db_conn):
    tasks = _Tasks()
    service = ProjectManagerService(db_conn, _Embedder(), tasks_client=tasks)

    result = service.add_entry(
        project_name="Errands",
        entry_type="todo",
        text="Call the clinic\nAsk for earliest follow-up slot",
    )

    assert result.google_task_id == "g_pm_1"
    assert len(tasks.created) == 1
    assert tasks.created[0]["title"] == "Call the clinic"
    assert f"caden_event_id: {result.event_id}" in tasks.created[0]["notes"]
    assert f"project_id: {result.project_id}" in tasks.created[0]["notes"]

    metadata = {
        (row["key"], row["value"])
        for row in db_conn.execute(
            "SELECT key, value FROM event_metadata WHERE event_id=?",
            (result.event_id,),
        ).fetchall()
    }
    assert ("google_task_id", "g_pm_1") in metadata
    assert ("linked_to", "g_pm_1") in metadata


@pytest.mark.asyncio
async def test_project_manager_pane_opens_project_and_saves_entry(mock_services):
    mock_services.tasks = _Tasks()
    app = CadenApp(mock_services)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.2)
        app.action_focus_project_manager()
        await pilot.pause(0.2)

        pane = app.query_one(ProjectManagerPane)
        project_input = pane.query_one("#pm-project-input", Input)
        project_input.value = "Research Notes"
        pane.query_one("#pm-open-project", Button).press()
        await pilot.pause(0.2)

        active = pane.query_one("#pm-active-project", Static).render().plain
        assert "Research Notes" in active

        entry_input = pane.query_one("#pm-entry-input", Input)
        entry_input.value = "Capture a first hypothesis"
        await pane._save_entry()
        await pilot.pause(0.4)

    row = mock_services.conn.execute(
        "SELECT source, raw_text FROM events WHERE source='project_entry' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["source"] == "project_entry"
    assert "Capture a first hypothesis" in row["raw_text"]


@pytest.mark.asyncio
async def test_project_manager_pane_exposes_entry_type_buttons_and_project_list(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.2)
        app.action_focus_project_manager()
        await pilot.pause(0.2)

        pane = app.query_one(ProjectManagerPane)
        assert pane.query_one("#pm-project-list", VerticalScroll) is not None
        assert pane.query_one("#pm-type-todo", Button) is not None
        assert pane.query_one("#pm-type-what_if", Button) is not None
        assert pane.query_one("#pm-type-update", Button) is not None
        assert pane.query_one("#pm-type-comment", Button) is not None


@pytest.mark.asyncio
async def test_cmd_058_project_manager_left_nav_is_narrower_than_main_area(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(0.2)
        app.action_focus_project_manager()
        await pilot.pause(0.3)

        pane = app.query_one(ProjectManagerPane)
        left = pane.query_one("#pm-left")
        main = pane.query_one("#pm-main")

        assert left.region.width > 0
        assert main.region.width > 0
        assert left.region.width < main.region.width
