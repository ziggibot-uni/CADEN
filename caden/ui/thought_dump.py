"""Thought Dump tab UI.

Minimal abyss for explicit thought capture:
- no auto-capture
- no history rendering
- optional hide mode is visual-only
"""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Input, Static

from ..errors import CadenError
from ..libbie.store import load_event, write_event
from ..libbie.why import generate_why_for_event
from ..rater.rate import rate_event
from .services import Services


class ThoughtDumpPane(Vertical):
    DEFAULT_CSS = """
    ThoughtDumpPane {
        height: 1fr;
        background: #0f1115;
        color: white;
        padding: 1;
    }
    ThoughtDumpPane #td-input {
        margin-top: 1;
    }
    ThoughtDumpPane #td-actions {
        height: 3;
        margin-top: 1;
    }
    ThoughtDumpPane #td-actions Button {
        margin-right: 1;
        min-width: 12;
    }
    ThoughtDumpPane #td-preview {
        height: 3;
        margin-top: 1;
        border: solid #334154;
        background: #11161d;
        padding: 0 1;
    }
    ThoughtDumpPane #td-status {
        height: 1;
        color: #cdd5df;
        margin-top: 1;
    }
    """

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._hide_mode = False

    def compose(self) -> ComposeResult:
        yield Static("Thought Dump", id="td-title")
        yield Input(placeholder="Type a thought and press Commit", id="td-input")
        with Horizontal(id="td-actions"):
            yield Button("Commit", id="td-commit", variant="primary")
            yield Button("Hide: OFF", id="td-hide")
        yield Static("", id="td-preview")
        yield Static("", id="td-status")

    def _set_status(self, text: str) -> None:
        self.query_one("#td-status", Static).update(text)

    def _cipher_text(self, text: str) -> str:
        return "".join("*" if not ch.isspace() else ch for ch in text)

    def _render_preview(self) -> None:
        raw = self.query_one("#td-input", Input).value or ""
        preview = self._cipher_text(raw) if self._hide_mode else raw
        self.query_one("#td-preview", Static).update(preview)

    def _apply_hide_mode(self) -> None:
        try:
            inp = self.query_one("#td-input", Input)
            inp.password = self._hide_mode
            self._render_preview()
        except Exception as e:
            self.app.bell()
            self.app.notify(f"thought-dump hide render failed: {e}", severity="error")

    async def on_mount(self) -> None:
        self._apply_hide_mode()

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "td-input":
            return
        self._render_preview()

    async def _post_commit(self, event_id: int, emb: list[float]) -> None:
        try:
            ev = await asyncio.to_thread(load_event, self._services.conn, event_id)
            if ev is not None:
                await asyncio.to_thread(
                    rate_event,
                    self._services.conn,
                    ev,
                    emb,
                    self._services.llm,
                    self._services.embedder,
                )
        except Exception as e:
            self.app.notify(f"thought-dump rating failed for event #{event_id}: {e}", severity="error")

        try:
            await asyncio.to_thread(
                generate_why_for_event,
                self._services.conn,
                event_id,
                self._services.llm,
            )
        except Exception as e:
            self.app.notify(f"thought-dump why failed for event #{event_id}: {e}", severity="error")

    async def _commit(self) -> None:
        inp = self.query_one("#td-input", Input)
        text = inp.value or ""
        if not text.strip():
            self._set_status("thought required")
            return

        self._set_status("capturing…")
        try:
            emb = await asyncio.to_thread(self._services.embedder.embed, text)
            event_id = await asyncio.to_thread(
                write_event,
                self._services.conn,
                "thought_dump",
                text,
                emb,
                {"trigger": "thought_dump_commit"},
                None,
            )
        except CadenError as e:
            self.app.bell()
            self.app.notify(f"thought-dump commit failed: {e}", severity="error")
            self._set_status("commit failed")
            return

        inp.value = ""
        self._render_preview()
        self._set_status(f"captured event #{event_id}")
        self.run_worker(self._post_commit(event_id, emb), group=f"td-post-{event_id}")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "td-commit":
            await self._commit()
            return
        if button_id == "td-hide":
            self._hide_mode = not self._hide_mode
            event.button.label = "Hide: ON" if self._hide_mode else "Hide: OFF"
            self._apply_hide_mode()
