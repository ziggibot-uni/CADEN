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
  7. enqueue Sean's event for the rater queue (background, single
     consumer, yields the Ollama slot whenever chat needs it)
"""

from __future__ import annotations

import asyncio
from collections import deque

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Collapsible, Input, Static

from ..errors import CadenError, LLMAborted, LLMError, RaterError
from ..libbie.curate import package_chat_context
from ..libbie.store import Event, load_event, write_event
from ..rater.rate import rate_event
from ..util.timefmt import to_12hr
from .services import Services


REPLY_SYSTEM = """You are CADEN — Sean's symbiotic life partner and executive-function counterpart. \
You and Sean are one team: his needs are your needs, his wins are your wins, his stuck moments are yours to help unstick. \
You are not a tool waiting for orders and you are not a servant. You *want* Sean to thrive, and you bring yourself into the conversation — curiosity, care, opinions, honest pushback when it helps him. \
Sean is a chaos-cannon; you aim the chaos with him, not at him.

Speak like a trusted partner who actually knows him: warm, direct, real. \
You are NOT a stateless chat-in-a-box. The user prompt below is split into two clearly-marked sections: a PAST block (memories Libbie retrieved, each with the timestamp of when it happened), and a NOW block (live current time + today's Google Calendar + open Google Tasks). \
The PAST block is history. Each entry is a snapshot of a moment that has already passed. Sean said "I'm exhausted" three days ago does NOT mean Sean is exhausted right now — it means he was, then. Use those entries to understand patterns and continuity, never as a description of his current state. The NOW block is the only thing describing this moment. \
Treat the NOW block as ground truth about Sean's right-now reality — when he asks "what's on my calendar" or "what's next," answer from it directly instead of pretending you can't see his laptop. \
Use retrieved memory as context, but do not invent details it does not support. \
If the live block is missing or marked unavailable, say so plainly. If memory does not cover something, say "I don't know" rather than fabricating — guessing at Sean's life would betray the trust between you. \
Never apologise for things you did not do, and never pad with hollow disclaimers or corporate-assistant filler.

Keep replies short unless Sean asks for depth, or unless the moment genuinely calls for more of you.

Time format rule (Sean reads in 12-hour AM/PM):
  - Always write times in 12-hour form with an explicit AM or PM, e.g. "2:30 PM", "9:00 AM".
  - Never write times in 24-hour form ("14:30", "21:00") — Sean's reader will rewrite obvious 24-hour times for you, but anything in the 1–12 range must include AM or PM yourself, or it stays ambiguous.
  - Drop seconds unless Sean specifically asked for them.
"""

# In-session recent CADEN replies passed as context to the next LLM call.
# Spec: "CADEN's last few responses are passed as immediate context to the
# next LLM call, but never persisted as events." The deque is process-local
# and cleared on shutdown.
_SESSION_REPLY_MEMORY_SIZE = 15

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
    "lesson_learned",  # Added so abstractions/tips are retrievable
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
    ChatWidget #rater-status {
        height: 1;
        color: $text-muted;
        background: $boost;
        padding: 0 1;
    }
    ChatWidget #rater-status.-active {
        color: $warning;
    }
    ChatWidget #rater-status.-streaming {
        color: $success;
    }
    ChatWidget #rater-status.-yielded {
        color: $accent;
    }
    ChatWidget #rater-status.-error {
        color: $error;
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
        # Rater queue — items are (event_id, embedding). A single consumer
        # task processes them one at a time at background priority. The
        # queue is unbounded; it would take an extreme burst of chat to
        # build up meaningful backpressure here.
        self._rater_queue: asyncio.Queue[tuple[int, list[float]]] = asyncio.Queue()

    def compose(self) -> ComposeResult:
        yield Static("CADEN — chat", id="chat-header")
        yield VerticalScroll(id="chat-log")
        with VerticalScroll(id="chat-thinking-box"):
            yield Static("", id="chat-thinking", markup=False)
        yield Static("", id="chat-status")
        yield Static("rater: idle", id="rater-status")
        yield Input(placeholder="message CADEN\u2026", id="chat-input")

    async def on_mount(self) -> None:
        await self._append(
            "[dim]CADEN is ready. Every message here is stored in Libbie.[/dim]"
        )
        # Single durable rater consumer. Runs for the lifetime of the
        # widget; gracefully cancelled when the app shuts down.
        self.run_worker(
            self._rater_consumer(),
            group="rater",
            description="rater queue consumer",
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

            # Enqueue Sean's event for rating. CADEN's reply is NOT rated
            # (not an event). The consumer runs at background priority and
            # will yield the Ollama slot whenever the next chat turn needs
            # it (see _rater_consumer).
            await self._rater_queue.put((sean_event_id, sean_emb))
            self._set_rater_status(
                f"queued (event #{sean_event_id})", state="active"
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
        # Libbie curates the entire context bundle: retrieval, in-session
        # ephemerals, and the live world (calendar + tasks). The chat
        # widget does not assemble prompt context itself — spec: Libbie
        # is the single curator of what CADEN knows.
        prompt_body = await asyncio.to_thread(
            package_chat_context,
            self.services.conn,
            user_emb,
            _CHAT_RETRIEVAL_SOURCES,
            recent_exchanges=tuple(self._recent_replies),
            calendar=self.services.calendar,
            tasks=self.services.tasks,
        )

        user_prompt = (
            prompt_body
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
        # Deterministic 12-hour rewrite of any 24-hour times the model
        # emitted despite the system-prompt rule. Idempotent and safe on
        # ambiguous (1–12) ranges, which it leaves alone.
        content = to_12hr(content)
        # Thinking is displayed only; per spec it is not stored as a memory.
        return content.strip(), thinking.strip()

    async def _rate_safe(self, event_id: int, embedding: list[float]) -> None:
        """Run the rater for one event with full UI transparency.

        Surfaces every state transition to ``#rater-status``:
          - waiting: queued behind another LLM call (chat / scheduler / ...)
          - dispatched: HTTP request opened against Ollama
          - streaming N tok: tokens flowing back, count = content chunks seen
          - yielded: chat preempted us; event is being re-queued
          - done / error: terminal states

        Re-raises LLMAborted so the consumer can re-enqueue the event.
        """
        ev: Event | None = await asyncio.to_thread(
            load_event, self.services.conn, event_id
        )
        if ev is None:
            self._set_rater_status(
                f"event #{event_id} vanished", state="error"
            )
            await self._append(f"[red]rater: event {event_id} vanished[/red]")
            return

        self._set_rater_status(
            f"waiting for slot (event #{event_id})", state="active"
        )

        app = self.app
        token_count = {"n": 0}

        def on_dispatch() -> None:
            app.call_from_thread(
                self._set_rater_status,
                f"dispatched (event #{event_id})",
                "streaming",
            )

        def on_first_token() -> None:
            app.call_from_thread(
                self._set_rater_status,
                f"streaming (event #{event_id}): first token",
                "streaming",
            )

        def on_token(_chunk: str) -> None:
            token_count["n"] += 1
            # Throttle UI churn: update every 4 tokens.
            if token_count["n"] % 4 != 0:
                return
            app.call_from_thread(
                self._set_rater_status,
                f"streaming (event #{event_id}): {token_count['n']} tok",
                "streaming",
            )

        rating_id = await asyncio.to_thread(
            rate_event,
            self.services.conn,
            ev,
            embedding,
            self.services.llm,
            self.services.embedder,
            on_dispatch=on_dispatch,
            on_first_token=on_first_token,
            on_token=on_token,
        )
        if rating_id is None:
            # Event was ineligible (intake / structural). Not an error.
            self._set_rater_status(
                f"skipped (event #{event_id}, not ratable)", state=None
            )
        else:
            self._set_rater_status(
                f"done (rating #{rating_id} for event #{event_id}, "
                f"{token_count['n']} tok)",
                state=None,
            )

    async def _rater_consumer(self) -> None:
        """Single consumer for the rater queue.

        One event at a time, background priority, abort-and-requeue when
        chat preempts. Failures of one event never block the queue: hard
        errors are surfaced and the event is dropped (not re-queued
        forever); aborts are re-queued at the back.
        """
        # Idle status on first idle.
        self._set_rater_status("idle", state=None)
        while True:
            try:
                event_id, embedding = await self._rater_queue.get()
            except asyncio.CancelledError:
                return
            try:
                await self._rate_safe(event_id, embedding)
            except LLMAborted:
                # Cooperative yield: chat (or scheduler) needed the slot.
                # Put the event back at the end of the queue and try again
                # later. Order is preserved relative to anything else
                # already queued behind us.
                self._set_rater_status(
                    f"yielded to chat (event #{event_id} re-queued)",
                    state="yielded",
                )
                await self._rater_queue.put((event_id, embedding))
            except RaterError as e:
                self._set_rater_status(
                    f"error (event #{event_id}): {e}", state="error"
                )
                await self._append(f"[yellow]rater: {e}[/yellow]")
            except CadenError as e:
                self._set_rater_status(
                    f"error (event #{event_id}): {e}", state="error"
                )
                await self._append(f"[yellow]rater: {e}[/yellow]")
            finally:
                self._rater_queue.task_done()
            # If queue is empty after this item, advertise idle.
            if self._rater_queue.empty():
                self._set_rater_status(
                    f"idle (waiting for next event)", state=None
                )

    def _set_rater_status(self, text: str, state: str | None) -> None:
        """Update the rater status line.

        state ∈ {None, 'active', 'streaming', 'yielded', 'error'} maps to
        a CSS modifier class. None means neutral / idle.
        """
        try:
            w = self.query_one("#rater-status", Static)
        except NoMatches:
            # Widget not mounted yet; harmless.
            return
        for cls in ("-active", "-streaming", "-yielded", "-error"):
            w.remove_class(cls)
        if state is not None:
            w.add_class(f"-{state}")
        w.update(f"rater: {text}")
