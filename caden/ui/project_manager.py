"""Project Manager tab UI."""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Static

from ..project_manager.service import ProjectManagerService
from .services import Services


class ProjectManagerPane(Vertical):
    DEFAULT_CSS = """
    ProjectManagerPane {
        height: 1fr;
        background: #0f1115;
        color: white;
        padding: 1;
    }
    ProjectManagerPane #pm-body {
        height: 1fr;
    }
    ProjectManagerPane #pm-left {
        width: 28;
        border: solid #2d557a;
        padding: 0 1;
    }
    ProjectManagerPane #pm-main {
        width: 1fr;
        border: solid #2d557a;
        padding: 0 1;
    }
    ProjectManagerPane #pm-project-list,
    ProjectManagerPane #pm-log,
    ProjectManagerPane #pm-related {
        height: 1fr;
        border: solid #334154;
        margin-top: 1;
        background: #11161d;
    }
    ProjectManagerPane #pm-types {
        height: 3;
        margin-top: 1;
    }
    ProjectManagerPane #pm-types Button {
        margin-right: 1;
        min-width: 10;
    }
    ProjectManagerPane #pm-status {
        height: 1;
        color: #cdd5df;
        margin-top: 1;
    }
    """

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._pm = ProjectManagerService(services.conn, services.embedder, services.tasks)
        self._active_project_id: str | None = None
        self._active_project_name: str | None = None
        self._entry_type = "comment"

    def compose(self) -> ComposeResult:
        yield Static("Project Manager", id="pm-title")
        with Horizontal(id="pm-body"):
            with Vertical(id="pm-left"):
                yield Input(placeholder="Project name", id="pm-project-input")
                yield Button("Open / Create", id="pm-open-project", variant="primary")
                yield VerticalScroll(id="pm-project-list")
            with Vertical(id="pm-main"):
                yield Static("No project selected", id="pm-active-project")
                with Horizontal(id="pm-types"):
                    yield Button("TODO", id="pm-type-todo")
                    yield Button("What-if", id="pm-type-what_if")
                    yield Button("Update", id="pm-type-update")
                    yield Button("Comment", id="pm-type-comment", variant="primary")
                yield Input(placeholder="Write entry and press Enter", id="pm-entry-input")
                yield VerticalScroll(id="pm-log")
                yield Static("Related entries", id="pm-related-title")
                yield VerticalScroll(id="pm-related")
                yield Static("", id="pm-status")

    def on_mount(self) -> None:
        self.run_worker(self._refresh_projects(), group="pm-refresh")

    async def _refresh_projects(self) -> None:
        rows = self._pm.list_projects()
        pane = self.query_one("#pm-project-list", VerticalScroll)
        await pane.remove_children()
        if not rows:
            await pane.mount(Static("(no projects yet)"))
            return
        for project in rows:
            label = f"{project.project_name} ({project.entry_count})"
            await pane.mount(Button(label, id=f"pm-project-{project.project_id}"))

    async def _refresh_entries(self) -> None:
        log = self.query_one("#pm-log", VerticalScroll)
        await log.remove_children()
        if not self._active_project_id:
            await log.mount(Static("(select or create a project first)"))
            return
        entries = self._pm.list_entries(self._active_project_id, limit=120)
        if not entries:
            await log.mount(Static("(no entries yet)"))
            return
        for entry in entries:
            await log.mount(Static(f"[{entry.entry_type}] {entry.text}"))
        log.scroll_end(animate=False)

    async def _refresh_related_entries(self) -> None:
        related = self.query_one("#pm-related", VerticalScroll)
        await related.remove_children()
        if not self._active_project_id:
            await related.mount(Static("(select or create a project first)"))
            return

        others = [
            row
            for row in self._pm.list_projects()
            if row.project_id != self._active_project_id
        ]
        if not others:
            await related.mount(Static("(no related entries)"))
            return

        shown = 0
        for project in others:
            entries = self._pm.list_entries(project.project_id, limit=1)
            if not entries:
                continue
            entry = entries[-1]
            await related.mount(
                Static(f"{project.project_name}: [{entry.entry_type}] {entry.text}")
            )
            shown += 1
            if shown >= 3:
                break

        if shown == 0:
            await related.mount(Static("(no related entries)"))

    def _set_status(self, text: str) -> None:
        self.query_one("#pm-status", Static).update(text)

    async def _open_project(self, name: str) -> None:
        clean = name.strip()
        if not clean:
            self._set_status("project name required")
            return

        project_id = self._infer_project_id(clean)
        self._active_project_id = project_id
        self._active_project_name = clean
        self.query_one("#pm-active-project", Static).update(f"Project: {clean}")
        self._set_status(f"active project: {clean}")
        await self._refresh_entries()
        await self._refresh_related_entries()

    def _infer_project_id(self, name: str) -> str:
        from ..libbie.projects import normalize_project_id

        return normalize_project_id(name)

    async def _save_entry(self) -> None:
        if not self._active_project_name:
            self._set_status("select a project first")
            return
        entry_input = self.query_one("#pm-entry-input", Input)
        text = (entry_input.value or "").strip()
        if not text:
            return

        entry_input.value = ""
        self._set_status("saving…")
        result = await asyncio.to_thread(
            self._pm.add_entry,
            project_name=self._active_project_name,
            entry_type=self._entry_type,
            text=text,
        )
        if result.google_task_id:
            self._set_status(f"saved {self._entry_type} entry (task {result.google_task_id})")
        else:
            self._set_status(f"saved {self._entry_type} entry")
        await self._refresh_projects()
        await self._refresh_entries()
        await self._refresh_related_entries()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "pm-project-input":
            await self._open_project(event.value or "")
            return
        if event.input.id == "pm-entry-input":
            await self._save_entry()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "pm-open-project":
            name = self.query_one("#pm-project-input", Input).value or ""
            await self._open_project(name)
            return
        if button_id.startswith("pm-type-"):
            self._entry_type = button_id.replace("pm-type-", "", 1)
            self._set_status(f"entry type: {self._entry_type}")
            return
        if button_id.startswith("pm-project-"):
            self._active_project_id = button_id.replace("pm-project-", "", 1)
            self._active_project_name = event.button.label.plain.split("(")[0].strip()
            self.query_one("#pm-active-project", Static).update(
                f"Project: {self._active_project_name}"
            )
            await self._refresh_entries()
            await self._refresh_related_entries()
