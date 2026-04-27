from datetime import datetime, timezone

import pytest

from caden.errors import DBError, GoogleSyncError
from caden.google_sync.calendar import CalendarEvent
from caden.google_sync.tasks import GTask
from caden.libbie.curate import package_chat_context, package_recall_context
from caden.learning.schema import RecallPacket
from caden.libbie.store import write_event


class _MockEmbedder:
    def embed(self, text: str):
        return [0.1] * 768


class _MockCalendar:
    def list_window(self, start, end):
        return [
            CalendarEvent(
                id="evt_1",
                summary="Deep work block",
                start=datetime(2026, 4, 30, 18, 0, tzinfo=timezone.utc),
                end=datetime(2026, 4, 30, 19, 0, tzinfo=timezone.utc),
                raw={},
            )
        ]


class _MockTasks:
    def list_open(self):
        return [
            GTask(
                id="task_1",
                title="Ship the regression fix",
                due=datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
                status="needsAction",
                completed_at=None,
                raw={},
            )
        ]


def test_package_chat_context_centralizes_thread_memory_and_live_world(db_conn):
    embedder = _MockEmbedder()
    write_event(
        db_conn,
        source="sean_chat",
        raw_text="Sean does better when the next step is concrete and short.",
        embedding=[0.1] * 768,
        meta={"domain": "self_knowledge", "trigger": "chat_send"},
    )

    context = package_chat_context(
        db_conn,
        "what should I do next?",
        sources=["sean_chat"],
        embedder=embedder,
        recent_exchanges=[("I am stuck.", "Let's narrow it to one step.")],
        calendar=_MockCalendar(),
        tasks=_MockTasks(),
    )

    assert "THREAD" in context
    assert "sean: I am stuck." in context
    assert "caden: Let's narrow it to one step." in context
    assert "LIGAND" in context
    assert "@context" in context
    assert "recalled_memories" in context
    assert "Sean does better when the next step is concrete and short." in context
    assert "NOW" in context
    assert "Deep work block" in context
    assert "Ship the regression fix" in context


def test_package_chat_context_uses_compact_recall_packets_instead_of_raw_event_dump(db_conn):
    embedder = _MockEmbedder()
    event_id = write_event(
        db_conn,
        source="sean_chat",
        raw_text="Sean should start with the smallest concrete next step he can finish immediately.",
        embedding=[0.1] * 768,
        meta={"domain": "self_knowledge", "trigger": "chat_send"},
    )
    event_row = db_conn.execute(
        "SELECT timestamp FROM events WHERE id=?",
        (event_id,),
    ).fetchone()

    context = package_chat_context(
        db_conn,
        "what is my next move?",
        sources=["sean_chat"],
        embedder=embedder,
    )

    assert "semantic=" in context
    assert "recalled_memories" in context
    assert event_row["timestamp"] not in context
    assert " / sean_chat]" not in context


def test_package_chat_context_honestly_reports_unavailable_google_sources(db_conn):
    embedder = _MockEmbedder()

    class BrokenCalendar:
        def list_window(self, start, end):
            raise GoogleSyncError("calendar offline")

    class BrokenTasks:
        def list_open(self):
            raise GoogleSyncError("tasks offline")

    context = package_chat_context(
        db_conn,
        "what changed today?",
        sources=["sean_chat"],
        embedder=embedder,
        calendar=BrokenCalendar(),
        tasks=BrokenTasks(),
    )

    assert "calendar: (unavailable: calendar offline)" in context
    assert "tasks: (unavailable: tasks offline)" in context


def test_package_chat_context_fails_loudly_when_memory_lookup_cannot_run(db_conn):
    embedder = _MockEmbedder()
    db_conn.close()

    with pytest.raises(DBError, match="memory vector search failed"):
        package_chat_context(
            db_conn,
            "what should I do next?",
            sources=["sean_chat"],
            embedder=embedder,
        )


def test_package_recall_context_defines_the_shared_caden_facing_memory_shape():
    packet = RecallPacket(
        mem_id="mem_1",
        summary="Sean does better with one concrete next step.",
        relevance="high",
        reason="semantic=1.000 source=sean_chat",
    )

    context = package_recall_context("choose the next step", [packet])

    assert "@context" in context
    assert "task: choose the next step" in context
    assert "recalled_memories" in context
    assert "PAST" in context
    assert "Sean does better with one concrete next step." in context


def test_package_chat_context_does_not_hardcode_fixed_retrieval_k(db_conn, monkeypatch):
    embedder = _MockEmbedder()
    seen_kwargs: dict[str, object] = {}

    class _Ligand:
        domain = "general"
        intent = "test"
        themes = ()
        risk = ()
        outcome_focus = "next step"

        def compact_text(self) -> str:
            return ""

    monkeypatch.setattr(
        "caden.libbie.curate.retrieve.recall_packets_for_task",
        lambda *args, **kwargs: (
            seen_kwargs.update(kwargs)
            or (_Ligand(), type("Ctx", (), {"task": "x", "recalled_memories": []})(), [1, 2, 3])
        ),
    )

    package_chat_context(
        db_conn,
        "what should I do next?",
        sources=["sean_chat"],
        embedder=embedder,
    )

    assert "k" not in seen_kwargs


def test_package_chat_context_keeps_all_live_calendar_and_task_lines_without_fixed_cap(db_conn):
    embedder = _MockEmbedder()

    class ManyCalendar:
        def list_window(self, start, end):
            return [
                CalendarEvent(
                    id=f"evt_{i}",
                    summary=f"Calendar item {i}",
                    start=datetime(2026, 4, 30, 8, 0, tzinfo=timezone.utc),
                    end=datetime(2026, 4, 30, 9, 0, tzinfo=timezone.utc),
                    raw={},
                )
                for i in range(30)
            ]

    class ManyTasks:
        def list_open(self):
            return [
                GTask(
                    id=f"task_{i}",
                    title=f"Task item {i}",
                    due=datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc),
                    status="needsAction",
                    completed_at=None,
                    raw={},
                )
                for i in range(30)
            ]

    context = package_chat_context(
        db_conn,
        "what is everything live right now?",
        sources=["sean_chat"],
        embedder=embedder,
        calendar=ManyCalendar(),
        tasks=ManyTasks(),
    )

    assert "Calendar item 29" in context
    assert "Task item 29" in context