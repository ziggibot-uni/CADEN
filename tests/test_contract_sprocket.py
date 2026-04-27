from __future__ import annotations

import pytest

from caden.errors import SprocketError
from caden.ui.app import CadenApp
from caden.ui.sprocket import SprocketPane
from caden.sprocket.service import SprocketService
from textual.widgets import Button, Input, Static
from textual.widgets import TabPane


class _Embedder:
    def embed(self, text: str):
        return [0.1] * 768


class _LLM:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str, **kwargs) -> str:
        self.calls.append((system, user))
        return "1. Build\n2. Validate\n3. Report"


def test_sprocket_build_brief_rejects_empty_query(db_conn):
    service = SprocketService(db_conn, _LLM(), _Embedder())

    with pytest.raises(SprocketError, match="sprocket query must not be empty"):
        service.build_brief("   ")


def test_sprocket_build_brief_uses_libbie_recall_pipeline(db_conn, monkeypatch):
    seen: dict[str, object] = {}

    class _Context:
        recalled_memories = [
            type(
                "_Packet",
                (),
                {
                    "mem_id": "mem_1",
                    "summary": "Prior build solved similar problem.",
                    "relevance": "high",
                    "reason": "semantic=1.0",
                },
            )()
        ]

    monkeypatch.setattr(
        "caden.sprocket.service.recall_packets_for_task",
        lambda conn, q, embedder, **kwargs: (
            seen.update({"query": q, "kwargs": kwargs})
            or (None, _Context(), [])
        ),
    )
    monkeypatch.setattr(
        "caden.sprocket.service.render_recall_packets",
        lambda packets, include_reason=True: "PACKAGED-BRIEF",
    )

    service = SprocketService(db_conn, _LLM(), _Embedder())
    brief = service.build_brief("Add project timeline widget")

    assert brief.query == "Add project timeline widget"
    assert brief.memory_excerpt == "PACKAGED-BRIEF"
    assert seen["kwargs"]["k"] == 12
    assert "project_entry" in seen["kwargs"]["sources"]


def test_sprocket_propose_plan_persists_attempt_event(db_conn, monkeypatch):
    monkeypatch.setattr(
        SprocketService,
        "build_brief",
        lambda self, q: type("_Brief", (), {"query": q, "memory_excerpt": "brief context"})(),
    )

    llm = _LLM()
    service = SprocketService(db_conn, llm, _Embedder())
    plan = service.propose_plan("Build a small PM analytics tab")

    assert "Build" in plan.plan_text
    assert len(llm.calls) == 1
    assert "brief context" in llm.calls[0][1]

    row = db_conn.execute(
        "SELECT id, source, raw_text FROM events WHERE source='sprocket_attempt' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["source"] == "sprocket_attempt"
    assert "Build a small PM analytics tab" in row["raw_text"]

    metadata = {
        (r["key"], r["value"])
        for r in db_conn.execute(
            "SELECT key, value FROM event_metadata WHERE event_id=?",
            (row["id"],),
        ).fetchall()
    }
    assert ("trigger", "sprocket_plan") in metadata
    assert ("query", "Build a small PM analytics tab") in metadata


@pytest.mark.asyncio
async def test_sprocket_pane_exposes_chat_input_and_generate_action(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause(0.2)
        app.action_focus_sprocket()
        await pilot.pause(0.2)

        pane = app.query_one(SprocketPane)
        assert pane.query_one("#s-input", Input) is not None
        assert pane.query_one("#s-generate", Button) is not None


@pytest.mark.asyncio
async def test_cmd_066_sprocket_left_nav_can_select_or_create_app_and_register_tab(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(110, 40)) as pilot:
        await pilot.pause(0.2)
        app.action_focus_sprocket()
        await pilot.pause(0.2)

        pane = app.query_one(SprocketPane)
        app_input = pane.query_one("#s-app-input", Input)
        app_input.value = "Focus Lab"
        await app_input.action_submit()
        await pilot.pause(0.3)

        active = pane.query_one("#s-active-app", Static).render().plain
        assert "Editing app: Focus Lab" in active
        assert app.query_one("#sprocket-app-focus-lab", TabPane) is not None

    row = mock_services.conn.execute(
        "SELECT source FROM events WHERE source='sprocket_integration_proposal' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["source"] == "sprocket_integration_proposal"


def test_cmd_070_sprocket_vector_searches_each_emitted_thought_and_resurfaces_related_context(db_conn, monkeypatch):
    thought_queries: list[str] = []

    class _Context:
        def __init__(self, summary: str):
            self.recalled_memories = [
                type("_Packet", (), {"mem_id": "m1", "summary": summary, "relevance": "high", "reason": "semantic=1.0"})()
            ]

    def fake_recall(conn, query, embedder, **kwargs):
        thought_queries.append(query)
        return None, _Context(f"related to {query}"), []

    monkeypatch.setattr(
        SprocketService,
        "build_brief",
        lambda self, q: type("_Brief", (), {"query": q, "memory_excerpt": "brief memory"})(),
    )
    monkeypatch.setattr(SprocketService, "_derive_thoughts", lambda self, q: ["draft parser", "validate parser"])
    monkeypatch.setattr("caden.sprocket.service.recall_packets_for_task", fake_recall)
    monkeypatch.setattr(
        "caden.sprocket.service.render_recall_packets",
        lambda packets, include_reason=True: packets[0].summary,
    )

    llm = _LLM()
    service = SprocketService(db_conn, llm, _Embedder())
    plan = service.propose_plan("Build parser tooling")

    assert "Build" in plan.plan_text
    assert thought_queries == ["draft parser", "validate parser"]
    user_prompt = llm.calls[0][1]
    assert "Thought retrieval" in user_prompt
    assert "related to draft parser" in user_prompt
    assert "related to validate parser" in user_prompt

    count = db_conn.execute(
        "SELECT COUNT(*) AS n FROM events WHERE source='sprocket_thought'"
    ).fetchone()["n"]
    assert count == 2


def test_cmd_069_sprocket_learns_from_failure_and_changes_prompting_strategy(db_conn, monkeypatch):
    monkeypatch.setattr(
        SprocketService,
        "build_brief",
        lambda self, q: type("_Brief", (), {"query": q, "memory_excerpt": "(no recalled memories)"})(),
    )
    monkeypatch.setattr(SprocketService, "_resurface_related_for_thoughts", lambda self, q: [])

    llm = _LLM()
    service = SprocketService(db_conn, llm, _Embedder())
    service.record_attempt_outcome(
        source="sandbox",
        attempt_count=3,
        success=False,
        quality_score=0.2,
    )

    plan = service.propose_plan("Build robust retry flow")

    assert "Build" in plan.plan_text
    system_prompt = llm.calls[0][0]
    assert "Failure lessons to avoid repeating" in system_prompt
    assert "sandbox" in system_prompt

    attempt = db_conn.execute(
        "SELECT id FROM events WHERE source='sprocket_attempt' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert attempt is not None
    metadata = {
        row["key"]: row["value"]
        for row in db_conn.execute(
            "SELECT key, value FROM event_metadata WHERE event_id=?",
            (attempt["id"],),
        ).fetchall()
    }
    assert metadata["approach"] == "from_scratch_with_strict_verification"
    assert str(metadata["used_failure_lessons"]).lower() in {"1", "true"}


def test_cmd_071_system_prompt_includes_recent_intent_implementation_outcome_summaries(db_conn, monkeypatch):
    monkeypatch.setattr(
        SprocketService,
        "build_brief",
        lambda self, q: type("_Brief", (), {"query": q, "memory_excerpt": "brief memory"})(),
    )
    monkeypatch.setattr(SprocketService, "_resurface_related_for_thoughts", lambda self, q: [])

    llm = _LLM()
    service = SprocketService(db_conn, llm, _Embedder())
    service.record_intent_implementation_outcome(
        intent="Add parser tab",
        implementation="created tab scaffold and tests",
        outcome="passed",
        success=True,
    )

    plan = service.propose_plan("Improve parser planning")

    assert "Build" in plan.plan_text
    system_prompt = llm.calls[0][0]
    assert "Recent intent / implementation / outcome summaries" in system_prompt
    assert "Add parser tab" in system_prompt
