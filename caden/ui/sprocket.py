"""Sprocket tab UI."""

from __future__ import annotations

import asyncio
import re

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Static

from ..sprocket.service import SprocketService
from .services import Services


class SprocketPane(Vertical):
    DEFAULT_CSS = """
    SprocketPane {
        height: 1fr;
        background: #0f1115;
        color: white;
        padding: 1;
    }
    SprocketPane #s-body {
        height: 1fr;
    }
    SprocketPane #s-left {
        width: 28;
        border: solid #2d557a;
        padding: 0 1;
    }
    SprocketPane #s-main {
        width: 1fr;
        border: solid #2d557a;
        padding: 0 1;
    }
    SprocketPane #s-log {
        height: 1fr;
        border: solid #334154;
        margin-top: 1;
        background: #11161d;
    }
    SprocketPane #s-status {
        height: 1;
        color: #cdd5df;
        margin-top: 1;
    }
    """

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._sprocket = SprocketService(
            services.conn,
            services.llm,
            services.embedder,
            searxng=services.searxng,
        )
        self._apps: list[str] = ["Dashboard", "Project Manager", "Sprocket"]
        self._active_app_name: str = "Sprocket"

    def compose(self) -> ComposeResult:
        yield Static("Sprocket", id="s-title")
        with Horizontal(id="s-body"):
            with Vertical(id="s-left"):
                yield Static("Apps", id="s-apps-title")
                yield Input(placeholder="App name", id="s-app-input")
                yield Button("Select / Create", id="s-app-open", variant="primary")
                yield VerticalScroll(id="s-app-list")
            with Vertical(id="s-main"):
                yield Static("Editing app: Sprocket", id="s-active-app")
                yield Input(placeholder="Ask Sprocket to build/plan something", id="s-input")
                yield Button("Generate plan", id="s-generate", variant="primary")
                yield VerticalScroll(id="s-log")
                yield Static("", id="s-status")

    def on_mount(self) -> None:
        self.run_worker(self._refresh_app_list(), group="sprocket-app-list")

    async def _refresh_app_list(self) -> None:
        pane = self.query_one("#s-app-list", VerticalScroll)
        await pane.remove_children()
        for app_name in self._apps:
            slug = _slug(app_name)
            await pane.mount(Button(app_name, id=f"s-app-{slug}"))

    async def _select_or_create_app(self, name: str) -> None:
        clean = name.strip()
        if not clean:
            self._set_status("app name required")
            return
        if clean not in self._apps:
            self._apps.append(clean)
            self._apps = sorted(set(self._apps), key=str.lower)
            module_path = f"caden/ui/{_slug(clean)}.py"
            self._sprocket.propose_integration(app_name=clean, module_path=module_path)
            tab_id = f"sprocket-app-{_slug(clean)}"
            created = await self.app.register_sprocket_app_tab(app_name=clean, tab_id=tab_id)
            if created:
                self._set_status(f"created app: {clean}")
            else:
                self._set_status(f"selected app: {clean}")
            await self._refresh_app_list()
        else:
            self._set_status(f"selected app: {clean}")

        self._active_app_name = clean
        self.query_one("#s-active-app", Static).update(f"Editing app: {clean}")

    def _set_status(self, text: str) -> None:
        self.query_one("#s-status", Static).update(text)

    async def _append_log(self, text: str) -> None:
        log = self.query_one("#s-log", VerticalScroll)
        await log.mount(Static(text))
        log.scroll_end(animate=False)

    async def _run_plan(self, query: str) -> None:
        clean = query.strip()
        if not clean:
            return
        self._set_status("building brief…")
        await self._append_log(f"sean> {clean}")
        plan = await asyncio.to_thread(self._sprocket.propose_plan, clean)
        await self._append_log("brief>\n" + plan.brief.memory_excerpt)
        await self._append_log("plan>\n" + plan.plan_text)
        self._set_status("plan ready")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "s-app-input":
            await self._select_or_create_app(event.value or "")
            self.query_one("#s-app-input", Input).value = ""
            return
        if event.input.id != "s-input":
            return
        query = event.value or ""
        self.query_one("#s-input", Input).value = ""
        self.run_worker(self._run_plan(query), group="sprocket-plan")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "s-generate":
            query = self.query_one("#s-input", Input).value or ""
            self.query_one("#s-input", Input).value = ""
            self.run_worker(self._run_plan(query), group="sprocket-plan")
            return
        if button_id == "s-app-open":
            name = self.query_one("#s-app-input", Input).value or ""
            self.query_one("#s-app-input", Input).value = ""
            await self._select_or_create_app(name)
            return
        if button_id.startswith("s-app-"):
            await self._select_or_create_app(event.button.label.plain)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return cleaned.strip("-") or "app"
