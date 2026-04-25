"""Chat widget: the middle panel.

Per CADEN_v0.md "Chat events":
  - only Sean's messages are stored as events (with embeddings)
  - CADEN's responses are NOT stored as events — visible in the chat panel
    during the session but ephemeral from a memory standpoint
  - within a session, CADEN's last few replies are passed as immediate
    context to the next LLM call, but never persisted or embedded

What happens when Sean sends a message:
  1. embed Sean's text
  2. write it as an event (source='sean_chat')
  3. retrieve relevant memory for a reply (top-K from Libbie)
  4. ask ollama for a reply (streaming, with reasoning split out)
  5. display the reply + thinking in the panel (no DB write)
  6. remember the reply in an in-process deque for next-turn coherence
  7. kick off a rater call on Sean's event (not on CADEN's output)
"""

from __future__ import annotations

import asyncio
from collections import deque

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Collapsible, Input, Static

from ..config import (
    BOOTSTRAP_RETRIEVAL_MIN_K,
    BOOTSTRAP_RETRIEVAL_TOP_K,
    BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS,
    log_bootstrap_use,
)
from ..errors import CadenError, LLMError
from ..libbie import retrieve
from ..libbie.store import Event, load_event, write_event
from ..rater.rate import rate_event
from .services import Services


REPLY_SYSTEM = """You are CADEN, a local-first personal AI belonging to Sean. \
You respond concisely, honestly, and never apologise for things you did not do. \
Use the retrieved memory below as context, but do not invent details it does not support. \
If you do not know, say "I don't know" rather than fabricating.

Keep replies short unless Sean asks for depth.
"""

# In-session recent CADEN replies passed as context to the next LLM call.
# Spec: "CADEN's last few responses are passed as immediate context to the
# next LLM call, but never persisted as events." The deque is process-local
# and cleared on shutdown.
_SESSION_REPLY_MEMORY_SIZE = 4

# Sources retrieval pulls from for chat replies. Note: 'caden_chat' is
# deliberately absent — CADEN never retrieves its own prior answers as if
# they were ground truth (spec: "keeps memory pristine to Sean's signal").
_CHAT_RETRIEVAL_SOURCES = (
    "sean_chat",
    "rating",
    "task",
    "prediction",
    "residual",
    "intake_self_knowledge",
    "intake_code_pattern",
)


class ChatWidget(Vertical):
    DEFAULT_CSS = """
    ChatWidget {
        layout: vertical;
        height: 100%;
    }
    ChatWidget #chat-log {
        height: 1fr;
        border: solid $accent;
        padding: 0 1;
    }
    ChatWidget #chat-log Static.msg {
        margin: 0 0 1 0;
    }
    ChatWidget #chat-log Collapsible {
        margin: 0 0 1 0;
        background: $boost;
    }
    ChatWidget #chat-thinking-box {
        height: 8;
        border: round $surface;
        padding: 0 1;
        background: $boost;
        display: none;
    }
    ChatWidget #chat-thinking-box.-active {
        display: block;
    }
    ChatWidget #chat-thinking {
        color: $text-muted;
    }
    ChatWidget #chat-status {
        height: 1;
        color: $text-muted;
    }
    ChatWidget #chat-input {
        dock: bottom;
        margin-top: 1;
    }
    ChatWidget #chat-header {
        height: 1;
        color: $accent;
    }
    """

    def __init__(self, services: Services) -> None:
        super().__init__()
        self.services = services
        # Session-only memory of CADEN's recent replies. Not persisted.
        self._recent_replies: deque[tuple[str, str]] = deque(
            maxlen=_SESSION_REPLY_MEMORY_SIZE
        )

    def compose(self) -> ComposeResult:
        yield Static("CADEN — chat", id="chat-header")
        yield VerticalScroll(id="chat-log")
        with VerticalScroll(id="chat-thinking-box"):
            yield Static("", id="chat-thinking", markup=False)
        yield Static("", id="chat-status")
        yield Input(placeholder="message CADEN\u2026", id="chat-input")

    async def on_mount(self) -> None:
        await self._append(
            "[dim]CADEN is ready. Every message here is stored in Libbie.[/dim]"
        )

    def _set_status(self, text: str) -> None:
        self.query_one("#chat-status", Static).update(text)

    async def _append(self, item) -> None:
        log = self.query_one("#chat-log", VerticalScroll)
        widget: Widget
        if isinstance(item, str):
            widget = Static(item, classes="msg", markup=True)
        else:
            widget = item
        await log.mount(widget)
        log.scroll_end(animate=False)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = (event.value or "").strip()
        if not text:
            return
        inp = self.query_one("#chat-input", Input)
        inp.value = ""
        await self._append(f"[bold cyan]sean[/bold cyan]  {text}")
        self.run_worker(
            self._handle_message(text),
            exclusive=True,
            group="chat",
            description="chat round trip",
        )

    async def _handle_message(self, text: str) -> None:
        try:
            self._set_status("[dim]embedding\u2026[/dim]")
            sean_emb = await self._embed(text)
            sean_event_id = await self._write("sean_chat", text, sean_emb)

            self._set_status("[dim]CADEN is thinking\u2026[/dim]")
            reply, thinking = await self._compose_reply(text, sean_emb)

            # Park the thinking in a collapsible above the reply so Sean can
            # click it open later. Empty thinking means a non-reasoning turn.
            # IMPORTANT: thinking is displayed only, never stored as an event
            # (spec: only Sean's messages enter memory).
            if thinking:
                coll = Collapsible(
                    Static(thinking, markup=False),
                    title="thinking",
                    collapsed=True,
                )
                await self._append(coll)
            await self._append(f"[bold green]caden[/bold green] {reply}")

            # Remember the reply in-process for next-turn coherence. No DB
            # write, no embedding — ephemeral by design.
            self._recent_replies.append((text, reply))

            # Rate Sean's event. CADEN's reply is NOT rated (not an event).
            self.run_worker(
                self._rate_safe(sean_event_id, sean_emb),
                group="rating",
                description=f"rate event {sean_event_id}",
            )
        except CadenError as e:
            await self._append(f"[bold red]error[/bold red] {e}")
        finally:
            self._hide_thinking_box()
            self._set_status("")

    def _show_thinking_box(self) -> None:
        self.query_one("#chat-thinking", Static).update("")
        self.query_one("#chat-thinking-box", VerticalScroll).add_class("-active")

    def _hide_thinking_box(self) -> None:
        self.query_one("#chat-thinking-box", VerticalScroll).remove_class("-active")

    async def _embed(self, text: str) -> list[float]:
        # Embedder does a blocking HTTP call; keep the event loop free.
        return await asyncio.to_thread(self.services.embedder.embed, text)

    async def _write(self, source: str, text: str, emb: list[float]) -> int:
        return await asyncio.to_thread(
            write_event, self.services.conn, source, text, emb, None, None
        )

    async def _compose_reply(
        self, user_text: str, user_emb: list[float]
    ) -> tuple[str, str]:
        # Log bootstrap values on first use (per spec: gates, not rules).
        await asyncio.to_thread(
            log_bootstrap_use,
            self.services.conn,
            "BOOTSTRAP_RETRIEVAL_TOP_K",
            BOOTSTRAP_RETRIEVAL_TOP_K,
        )
        await asyncio.to_thread(
            log_bootstrap_use,
            self.services.conn,
            "BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS",
            BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS,
        )

        neighbours = await asyncio.to_thread(
            retrieve.search,
            self.services.conn,
            user_emb,
            BOOTSTRAP_RETRIEVAL_TOP_K,
            _CHAT_RETRIEVAL_SOURCES,
        )
        if neighbours and len(neighbours) < BOOTSTRAP_RETRIEVAL_MIN_K:
            # Spec: if effective K drops below the floor, fail loudly.
            raise LLMError(
                f"chat retrieval returned only {len(neighbours)} memories, "
                f"below BOOTSTRAP_RETRIEVAL_MIN_K={BOOTSTRAP_RETRIEVAL_MIN_K}; "
                f"broaden sources or inspect the index."
            )
        trunc = BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS
        ctx_lines = [
            f"- [{r.event.timestamp} / {r.event.source}] "
            f"{(r.event.raw_text[:trunc] + '…') if len(r.event.raw_text) > trunc else r.event.raw_text}"
            for r in neighbours
        ] or ["(no prior memory yet)"]

        # Session-only reply memory: passed as context, never embedded.
        if self._recent_replies:
            ctx_lines.append("")
            ctx_lines.append("Recent in-session exchanges (ephemeral, not stored):")
            for prior_user, prior_reply in self._recent_replies:
                pu = prior_user[:trunc]
                pr = prior_reply[:trunc]
                ctx_lines.append(f"  sean: {pu}")
                ctx_lines.append(f"  caden: {pr}")

        user_prompt = (
            "Retrieved memory from Libbie (most relevant first):\n"
            + "\n".join(ctx_lines)
            + f"\n\nSean just said:\n{user_text}\n\nReply."
        )

        app = self.app
        think_box = self.query_one("#chat-thinking-box", VerticalScroll)
        think_static = self.query_one("#chat-thinking", Static)
        self._show_thinking_box()
        state = {"think": "", "content": ""}

        def _push_thinking() -> None:
            think_static.update(state["think"])
            think_box.scroll_end(animate=False)

        def on_thinking(chunk: str) -> None:
            state["think"] += chunk
            app.call_from_thread(_push_thinking)

        def on_content(chunk: str) -> None:
            state["content"] += chunk
            preview = state["content"].replace("\n", " ")
            if len(preview) > 120:
                preview = "\u2026" + preview[-120:]
            app.call_from_thread(
                self._set_status, f"[green]answering: {preview}[/green]"
            )

        content, thinking = await asyncio.to_thread(
            lambda: self.services.llm.chat_stream(
                REPLY_SYSTEM,
                user_prompt,
                temperature=0.5,
                on_content=on_content,
                on_thinking=on_thinking,
            )
        )
        # Thinking is displayed only; per spec it is not stored as a memory.
        return content.strip(), thinking.strip()

    async def _rate_safe(self, event_id: int, embedding: list[float]) -> None:
        ev: Event | None = await asyncio.to_thread(
            load_event, self.services.conn, event_id
        )
        if ev is None:
            await self._append(f"[red]rater: event {event_id} vanished[/red]")
            return
        try:
            await asyncio.to_thread(
                rate_event,
                self.services.conn,
                ev,
                embedding,
                self.services.llm,
                self.services.embedder,
            )
        except CadenError as e:
            await self._append(f"[yellow]rater: {e}[/yellow]")
