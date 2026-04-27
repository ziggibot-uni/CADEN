import asyncio

import pytest

from textual.widgets import Input, Static, TabPane

from caden.errors import LLMAborted, LLMError
from caden.ui.app import CadenApp
from caden.ui.chat import ChatWidget, _CHAT_RETRIEVAL_SOURCES, _SESSION_REPLY_MEMORY_SIZE
from caden.ui.dashboard import Dashboard


def test_session_reply_memory_cap_matches_v0():
    assert _SESSION_REPLY_MEMORY_SIZE == 4


def test_chat_retrieval_defensively_excludes_caden_chat_source():
    assert "caden_chat" not in _CHAT_RETRIEVAL_SOURCES


@pytest.mark.asyncio
async def test_chat_mount_starts_named_rater_worker(mock_services, monkeypatch):
    captured: dict[str, object] = {}

    def fake_run_worker(self, awaitable, *, group=None, description=None, **kwargs):
        captured["group"] = group
        captured["description"] = description
        awaitable.close()
        return None

    monkeypatch.setattr(ChatWidget, "run_worker", fake_run_worker)

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)

    assert captured == {"group": "rater", "description": "rater queue consumer"}


@pytest.mark.asyncio
async def test_chat_submit_starts_named_chat_worker(mock_services, monkeypatch):
    captured: dict[str, object] = {}

    def fake_run_worker(self, awaitable, *, group=None, description=None, **kwargs):
        captured["group"] = group
        captured["description"] = description
        awaitable.close()
        return None

    monkeypatch.setattr(ChatWidget, "run_worker", fake_run_worker)

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)
        chat = app.query_one(ChatWidget)
        inp = chat.query_one("#chat-input", Input)
        inp.value = "hello"
        await inp.action_submit()
        await pilot.pause(0.1)

    assert captured == {"group": "chat", "description": "chat round trip"}


@pytest.mark.asyncio
async def test_session_reply_deque_is_process_local_context_only(mock_services, monkeypatch):
    captured: dict[str, object] = {}

    def fake_package_chat_context(conn, user_text, sources, **kwargs):
        captured["sources"] = sources
        captured["recent_exchanges"] = kwargs["recent_exchanges"]
        return "PACKAGED"

    monkeypatch.setattr("caden.ui.chat.package_chat_context", fake_package_chat_context)

    class _LLM:
        def chat_stream(self, system, user, **kwargs):
            captured["prompt"] = user
            return "CADEN reply", ""

        def close(self) -> None:
            return None

    mock_services.llm = _LLM()
    app = CadenApp(mock_services)

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)
        chat = app.query_one(ChatWidget)
        chat._recent_replies.append(("sean asked", "caden replied"))

        reply, thinking = await chat._compose_reply("new question", [0.1] * 768)

    assert reply == "CADEN reply"
    assert thinking == ""
    assert captured["sources"] == _CHAT_RETRIEVAL_SOURCES
    assert captured["recent_exchanges"] == (("sean asked", "caden replied"),)
    assert "PACKAGED" in captured["prompt"]


@pytest.mark.asyncio
async def test_chat_blocking_steps_offload_via_to_thread(mock_services, monkeypatch):
    calls: list[tuple[object, tuple[object, ...]]] = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append((func, args))
        return func(*args, **kwargs)

    monkeypatch.setattr("caden.ui.chat.asyncio.to_thread", fake_to_thread)

    def fake_package_chat_context(*args, **kwargs):
        return "PACKAGED"

    monkeypatch.setattr("caden.ui.chat.package_chat_context", fake_package_chat_context)

    class _LLM:
        def chat_stream(self, system, user, **kwargs):
            return "CADEN reply", ""

        def close(self):
            return None

    mock_services.llm = _LLM()
    app = CadenApp(mock_services)

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)
        chat = app.query_one(ChatWidget)
        await chat._embed("hello")
        await chat._write("sean_chat", "hello", [0.1] * 768)
        await chat._compose_reply("hello", [0.1] * 768)

    called_names = [getattr(func, "__name__", "") for func, _args in calls]
    assert "embed" in called_names
    assert "write_event" in called_names
    assert "fake_package_chat_context" in called_names
    assert len(called_names) >= 4


@pytest.mark.asyncio
async def test_chat_rating_offloads_event_load_and_rating_via_to_thread(mock_services, monkeypatch):
    calls: list[tuple[object, tuple[object, ...]]] = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append((func, args))
        return func(*args, **kwargs)

    def fake_load_event(conn, event_id):
        return object()

    def fake_rate_event(conn, ev, embedding, llm, embedder, **kwargs):
        return 91

    monkeypatch.setattr("caden.ui.chat.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr("caden.ui.chat.load_event", fake_load_event)
    monkeypatch.setattr("caden.ui.chat.rate_event", fake_rate_event)

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)
        chat = app.query_one(ChatWidget)
        await chat._rate_safe(17, [0.1] * 768)

    called_names = [getattr(func, "__name__", "") for func, _args in calls]
    assert called_names == ["fake_load_event", "fake_rate_event"]


@pytest.mark.asyncio
async def test_chat_why_enrichment_offloads_generation_via_to_thread(mock_services, monkeypatch):
    calls: list[tuple[object, tuple[object, ...]]] = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append((func, args))
        return True

    monkeypatch.setattr("caden.ui.chat.asyncio.to_thread", fake_to_thread)

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)
        chat = app.query_one(ChatWidget)
        await chat._why_safe(42)

    called_names = [getattr(func, "__name__", "") for func, _args in calls]
    assert called_names == ["generate_why_for_event"]


@pytest.mark.asyncio
async def test_chat_why_enrichment_failure_is_best_effort(mock_services, monkeypatch):
    async def fake_to_thread(func, *args, **kwargs):
        raise LLMError("why down")

    monkeypatch.setattr("caden.ui.chat.asyncio.to_thread", fake_to_thread)

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)
        chat = app.query_one(ChatWidget)
        await chat._why_safe(77)
        await pilot.pause(0.1)
        messages = [widget.render().plain for widget in app.query("#chat-log Static")]

    assert any("why enrichment failed for event #77" in message for message in messages)


@pytest.mark.asyncio
async def test_chat_banner_describes_chat_persistence(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        messages = list(app.query("#chat-log Static"))

    plain_texts = [widget.render().plain for widget in messages]

    assert any("Sean and CADEN messages here are stored in Libbie" in text for text in plain_texts)
    assert all("Every message here is stored in Libbie" not in text for text in plain_texts)


@pytest.mark.asyncio
async def test_rater_consumer_requeues_aborted_background_work(mock_services, monkeypatch):
    app = CadenApp(mock_services)

    async with app.run_test() as pilot:
        await pilot.pause(0.2)
        chat = app.query_one(ChatWidget)
        attempts: list[int] = []
        completed = asyncio.Event()

        async def fake_rate_safe(event_id: int, embedding: list[float]) -> None:
            attempts.append(event_id)
            if len(attempts) == 1:
                raise LLMAborted("yield to foreground")
            completed.set()

        monkeypatch.setattr(chat, "_rate_safe", fake_rate_safe)

        await chat._rater_queue.put((17, [0.1] * 768))
        await asyncio.wait_for(completed.wait(), timeout=1)
        await pilot.pause(0.1)

    assert attempts == [17, 17]
    assert chat._rater_queue.empty()


@pytest.mark.asyncio
async def test_task_like_chat_message_does_not_create_tasks_or_schedule_work(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.3)
        chat = app.query_one(ChatWidget)
        inp = chat.query_one("#chat-input", Input)
        inp.value = "remind me tomorrow at 5pm to submit the taxes"
        await inp.action_submit()
        await pilot.pause(0.8)

        messages = [widget.render().plain for widget in app.query("#chat-log Static")]

    task_count = mock_services.conn.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"]
    task_event_count = mock_services.conn.execute("SELECT COUNT(*) AS n FROM task_events").fetchone()["n"]
    prediction_count = mock_services.conn.execute("SELECT COUNT(*) AS n FROM predictions").fetchone()["n"]
    sean_chat_count = mock_services.conn.execute(
        "SELECT COUNT(*) AS n FROM events WHERE source='sean_chat'"
    ).fetchone()["n"]

    assert any("sean  remind me tomorrow at 5pm to submit the taxes" in text for text in messages)
    assert any("caden Mock response" in text for text in messages)
    assert task_count == 0
    assert task_event_count == 0
    assert prediction_count == 0
    assert sean_chat_count == 1


@pytest.mark.asyncio
async def test_dashboard_chat_events_always_store_project_id_as_null(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.3)
        chat = app.query_one(ChatWidget)
        inp = chat.query_one("#chat-input", Input)
        inp.value = "capture this in dashboard chat"
        await inp.action_submit()
        await pilot.pause(0.8)

    row = mock_services.conn.execute(
        "SELECT event_id, value FROM event_metadata WHERE key='project_id' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    assert row is not None
    assert row["value"] == "null"


@pytest.mark.asyncio
async def test_session_reply_deque_starts_empty_for_a_new_widget_lifecycle(mock_services):
    first_app = CadenApp(mock_services)

    async with first_app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)
        first_chat = first_app.query_one(ChatWidget)
        first_chat._recent_replies.append(("sean", "old reply"))
        assert len(first_chat._recent_replies) == 1

    second_app = CadenApp(mock_services)
    async with second_app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)
        second_chat = second_app.query_one(ChatWidget)
        assert len(second_chat._recent_replies) == 0


@pytest.mark.asyncio
async def test_app_exposes_dashboard_project_manager_sprocket_and_thought_dump_tabs(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)
        panes = list(app.query(TabPane))
        chats = list(app.query(ChatWidget))

    pane_ids = {pane.id for pane in panes}
    assert pane_ids == {"dashboard", "project-manager", "thought-dump", "sprocket"}
    # Dashboard remains the single chat surface.
    assert len(chats) == 1


@pytest.mark.asyncio
async def test_v0_scope_integrates_dashboard_chat_and_libbie_memory(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.3)
        dashboard = app.query_one(Dashboard)
        chat = dashboard.query_one(ChatWidget)
        inp = chat.query_one("#chat-input", Input)
        inp.value = "scope contract message"
        await inp.action_submit()
        await pilot.pause(0.8)

    event_row = mock_services.conn.execute(
        "SELECT source, raw_text FROM events WHERE source='sean_chat' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    memory_row = mock_services.conn.execute(
        "SELECT source FROM memories WHERE source='sean_chat' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    assert dashboard is not None
    assert chat is not None
    assert event_row is not None
    assert event_row["raw_text"] == "scope contract message"
    assert memory_row is not None


@pytest.mark.asyncio
async def test_cmd_012_chat_reasoning_invokes_llm_chat_stream(mock_services, monkeypatch):
    called = {"chat_stream": 0}

    class _LLM:
        def chat_stream(self, system, user, **kwargs):
            called["chat_stream"] += 1
            return "CADEN reply", ""

        def close(self) -> None:
            return None

    mock_services.llm = _LLM()

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)
        chat = app.query_one(ChatWidget)
        inp = chat.query_one("#chat-input", Input)
        inp.value = "reason with LLM"
        await inp.action_submit()
        await pilot.pause(0.6)

    assert called["chat_stream"] >= 1


@pytest.mark.asyncio
async def test_cmd_055_chat_can_capture_web_knowledge_for_later_reuse(mock_services, monkeypatch):
    class _Hit:
        title = "Python docs"
        url = "https://docs.python.org"
        content = "dataclass defaults"
        engine = "duckduckgo"

        def summary_text(self) -> str:
            return "Python docs -- dataclass defaults -- https://docs.python.org"

    class _Searxng:
        def search(self, query: str, *, limit: int = 5):
            return [_Hit()]

        def close(self):
            return None

    class _LLM:
        def chat_stream(self, system, user, **kwargs):
            return "CADEN reply", ""

        def close(self):
            return None

    # Force first recall pass to appear empty, then use real recall after web capture.
    real_recall = __import__("caden.libbie", fromlist=["recall"]).recall
    state = {"n": 0}

    def _recall(conn, query, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return type("_Ctx", (), {"recalled_memories": ()})(), ()
        return real_recall(conn, query, **kwargs)

    monkeypatch.setattr("caden.ui.chat.recall", _recall)
    mock_services.searxng = _Searxng()
    mock_services.llm = _LLM()

    app = CadenApp(mock_services)
    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.2)
        chat = app.query_one(ChatWidget)
        inp = chat.query_one("#chat-input", Input)
        inp.value = "what is dataclass default_factory"
        await inp.action_submit()
        await pilot.pause(0.8)

    row = mock_services.conn.execute(
        "SELECT source FROM events WHERE source='web_knowledge' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    assert row["source"] == "web_knowledge"


@pytest.mark.asyncio
async def test_cmd_047_chat_persists_both_sean_and_caden_messages_to_libbie(mock_services):
    app = CadenApp(mock_services)

    async with app.run_test(size=(80, 40)) as pilot:
        await pilot.pause(0.3)
        chat = app.query_one(ChatWidget)
        inp = chat.query_one("#chat-input", Input)
        inp.value = "store this full conversation"
        await inp.action_submit()
        await pilot.pause(0.9)

    sean_row = mock_services.conn.execute(
        "SELECT source FROM events WHERE source='sean_chat' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    caden_row = mock_services.conn.execute(
        "SELECT source FROM events WHERE source='caden_chat' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    assert sean_row is not None
    assert caden_row is not None
    assert sean_row["source"] == "sean_chat"
    assert caden_row["source"] == "caden_chat"