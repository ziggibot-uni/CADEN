import pytest
import sqlite3
import json
from types import SimpleNamespace
from caden.libbie.store import write_event, load_event, write_rating, write_task, link_task_event
from caden.rater.rate import NON_RATABLE_SOURCES, RatingBundle, rate_event
from caden.errors import LLMError, RaterError
from caden.ui.services import Services
from caden.llm.client import OllamaClient
from caden.llm.embed import Embedder
from caden.learning.schema import CadenContext, Ligand, RecallPacket

@pytest.mark.asyncio
async def test_m6_rater(db_conn, httpx_mock):
    # Rater depends on external LLMs + embeddings
    llm = OllamaClient("http://127.0.0.1:11434", "llama3.1:8b")
    embedder = Embedder("http://127.0.0.1:11434", "nomic-embed-text", 768)

    messy_json = """```json
{"mood": 0.5, "energy": 0.5, "productivity": 0.9, "confidence": {"mood": 0.8, "energy": 0.8, "productivity": 0.2}, "rationale": "test reason"}
```
"""
    stream_response = json.dumps({
        "model": "llama3.1:8b",
        "message": {"role": "assistant", "content": messy_json},
        "done": True,
        "done_reason": "stop"
    }) + "\n"
    
    # Mock LLM and Embedder HTTP requests
    httpx_mock.add_response(url="http://127.0.0.1:11434/api/embeddings", json={"embedding": [0.1] * 768}, is_reusable=True)
    httpx_mock.add_response(url="http://127.0.0.1:11434/api/chat", text=stream_response, is_reusable=True)

    for i in range(5):
        write_event(db_conn, "sean_chat", f"dummy knowledge {i}", [0.1]*768)

    # 1. Capture a chat event, rate it
    chat_event_id = write_event(db_conn, "sean_chat", "I had a productive morning", [0.1]*768)
    chat_evt = load_event(db_conn, chat_event_id)
    rating_id = rate_event(db_conn, chat_evt, [0.1]*768, llm, embedder)
    
    # Assert ratings row created with all six fields
    assert rating_id is not None, "Rating not created for chat event!"
    cur = db_conn.cursor()
    row = cur.execute("SELECT mood, energy, productivity, conf_mood, conf_energy, conf_productivity FROM ratings WHERE id=?", (rating_id,)).fetchone()
    assert row is not None
    assert row["mood"] == 0.5
    assert row["energy"] == 0.5
    assert row["productivity"] == 0.9
    assert row["conf_mood"] == 0.8
    assert row["conf_energy"] == 0.8
    assert row["conf_productivity"] == 0.2
    
    # 2. Capture a structural event, ensure it's not rated
    knowledge_event_id = write_event(db_conn, "prediction", "predicted next state", [0.1]*768)
    evt2 = load_event(db_conn, knowledge_event_id)
    rate2_id = rate_event(db_conn, evt2, [0.1]*768, llm, embedder)
    assert rate2_id is None, "Ratings should NOT be generated for structural events!"


@pytest.mark.asyncio
async def test_m6_rater_preserves_unknown_axes_as_null(db_conn, httpx_mock):
    llm = OllamaClient("http://127.0.0.1:11434", "llama3.1:8b")
    embedder = Embedder("http://127.0.0.1:11434", "nomic-embed-text", 768)

    messy_json = """```json
{"mood": null, "energy": 0.25, "productivity": null, "confidence": {"mood": null, "energy": 0.6, "productivity": null}, "rationale": "Only energy is supported by the retrieved context."}
```
"""
    stream_response = json.dumps({
        "model": "llama3.1:8b",
        "message": {"role": "assistant", "content": messy_json},
        "done": True,
        "done_reason": "stop"
    }) + "\n"

    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/embeddings",
        json={"embedding": [0.1] * 768},
        is_reusable=True,
    )
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/chat",
        text=stream_response,
        is_reusable=True,
    )

    write_event(db_conn, "sean_chat", "Sean sometimes crashes after social overload", [0.1] * 768)
    event_id = write_event(db_conn, "sean_chat", "I am not sure how I feel, just restless.", [0.1] * 768)
    evt = load_event(db_conn, event_id)

    rating_id = rate_event(db_conn, evt, [0.1] * 768, llm, embedder)
    assert rating_id is not None

    row = db_conn.cursor().execute(
        "SELECT mood, energy, productivity, conf_mood, conf_energy, conf_productivity FROM ratings WHERE id=?",
        (rating_id,),
    ).fetchone()
    assert row is not None
    assert row["mood"] is None
    assert row["energy"] == 0.25
    assert row["productivity"] is None
    assert row["conf_mood"] is None
    assert row["conf_energy"] == 0.6
    assert row["conf_productivity"] is None


def test_rater_uses_libbie_packaged_recall_context(db_conn, monkeypatch):
    class _CapturingLLM:
        def __init__(self):
            self.user = ""

        def chat_stream(self, system, user, **kwargs):
            self.user = user
            return (
                '{"mood": 0.1, "energy": 0.2, "productivity": 0.3, '
                '"confidence": {"mood": 0.4, "energy": 0.5, "productivity": 0.6}, '
                '"rationale": ""}',
                "",
            )

    class _Embedder:
        def embed(self, text: str):
            return [0.1] * 768

    event_id = write_event(db_conn, "sean_chat", "I need one next step.", [0.1] * 768)
    event = load_event(db_conn, event_id)
    llm = _CapturingLLM()

    monkeypatch.setattr(
        "caden.rater.rate.retrieve.recall_packets_for_query",
        lambda *args, **kwargs: (
            Ligand(domain="task", intent="rate this", themes=(), risk=(), outcome_focus="understand"),
            CadenContext(
                task="I need one next step.",
                recalled_memories=[
                    RecallPacket(
                        mem_id="mem_1",
                        summary="Sean benefits from concrete next actions.",
                        relevance="high",
                        reason="semantic=1.0",
                    )
                ],
            ),
            [],
        ),
    )
    monkeypatch.setattr(
        "caden.rater.rate.curate.package_recall_context",
        lambda task_text, recalled_memories: "PACKAGED-BY-LIBBIE",
    )

    rating_id = rate_event(db_conn, event, [0.1] * 768, llm, _Embedder())

    assert rating_id is not None
    assert "PACKAGED-BY-LIBBIE" in llm.user


def test_rater_prompt_keeps_full_focal_event_without_char_cap(db_conn, monkeypatch):
    marker = "RATE-TAIL-DO-NOT-TRUNCATE"
    long_text = "z" * 5000 + marker
    event_id = write_event(db_conn, "sean_chat", long_text, [0.1] * 768)
    event = load_event(db_conn, event_id)

    class _CapturingLLM:
        def __init__(self):
            self.user = ""

        def chat_stream(self, system, user, **kwargs):
            self.user = user
            return (
                '{"mood": 0.1, "energy": 0.2, "productivity": 0.3, '
                '"confidence": {"mood": 0.4, "energy": 0.5, "productivity": 0.6}, '
                '"rationale": "ok"}',
                "",
            )

    class _Embedder:
        def embed(self, text: str):
            return [0.1] * 768

    monkeypatch.setattr(
        "caden.rater.rate.retrieve.recall_packets_for_query",
        lambda *args, **kwargs: (
            Ligand(domain="task", intent="rate this", themes=(), risk=(), outcome_focus="understand"),
            CadenContext(task=long_text, recalled_memories=[]),
            [],
        ),
    )
    monkeypatch.setattr(
        "caden.rater.rate.curate.package_recall_context",
        lambda task_text, recalled_memories: "(none)",
    )

    llm = _CapturingLLM()
    rating_id = rate_event(db_conn, event, [0.1] * 768, llm, _Embedder())

    assert rating_id is not None
    assert marker in llm.user


def test_rater_llm_failure_is_loud_and_chains_original_error(db_conn):
    event_id = write_event(db_conn, "sean_chat", "rate this event", [0.1] * 768)
    event = load_event(db_conn, event_id)

    class _BoomLLM:
        def chat_stream(self, *args, **kwargs):
            raise LLMError("transport down")

    class _Embedder:
        def embed(self, text: str):
            return [0.1] * 768

    with pytest.raises(RaterError, match="rater LLM call failed: transport down") as exc_info:
        rate_event(db_conn, event, [0.1] * 768, _BoomLLM(), _Embedder())
    assert isinstance(exc_info.value.__cause__, LLMError)


@pytest.mark.asyncio
async def test_rater_prompt_includes_focal_event_self_knowledge_and_prior_ratings(db_conn, httpx_mock):
    llm = OllamaClient("http://127.0.0.1:11434", "llama3.1:8b")
    embedder = Embedder("http://127.0.0.1:11434", "nomic-embed-text", 768)

    stream_response = json.dumps({
        "model": "llama3.1:8b",
        "message": {
            "role": "assistant",
            "content": '{"mood": 0.2, "energy": 0.1, "productivity": 0.0, "confidence": {"mood": 0.7, "energy": 0.7, "productivity": 0.7}, "rationale": "Prompt composition test."}'
        },
        "done": True,
        "done_reason": "stop"
    }) + "\n"

    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/embeddings",
        json={"embedding": [0.1] * 768},
        is_reusable=True,
    )
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/chat",
        text=stream_response,
    )

    write_event(
        db_conn,
        "sean_chat",
        "Sean gets overloaded by crowded coffee shops.",
        [0.1] * 768,
        meta={"domain": "self_knowledge", "trigger": "chat_send"},
    )
    prior_event_id = write_event(
        db_conn,
        "sean_chat",
        "A noisy cafe wrecked my focus yesterday.",
        [0.1] * 768,
    )
    write_rating(
        db_conn,
        event_id=prior_event_id,
        mood=-0.4,
        energy=-0.5,
        productivity=-0.6,
        c_mood=0.8,
        c_energy=0.8,
        c_productivity=0.8,
        rationale="Crowded rooms usually tank Sean's energy.",
        embedding=[0.1] * 768,
    )

    focal_event_id = write_event(
        db_conn,
        "sean_chat",
        "This crowded coffee shop is draining me.",
        [0.1] * 768,
    )
    focal_event = load_event(db_conn, focal_event_id)

    rating_id = rate_event(db_conn, focal_event, [0.1] * 768, llm, embedder)
    assert rating_id is not None

    requests = httpx_mock.get_requests(url="http://127.0.0.1:11434/api/chat")
    req_body = json.loads(requests[0].read())
    user_msg = next((m["content"] for m in req_body["messages"] if m["role"] == "user"), "")

    assert "This crowded coffee shop is draining me." in user_msg
    assert "Sean gets overloaded by crowded coffee shops." in user_msg
    assert "Crowded rooms usually tank Sean's energy." in user_msg


@pytest.mark.asyncio
async def test_rating_rationale_feeds_future_retrieval_for_later_events(db_conn, httpx_mock):
    llm = OllamaClient("http://127.0.0.1:11434", "llama3.1:8b")
    embedder = Embedder("http://127.0.0.1:11434", "nomic-embed-text", 768)

    first_response = json.dumps({
        "model": "llama3.1:8b",
        "message": {
            "role": "assistant",
            "content": '{"mood": -0.1, "energy": -0.2, "productivity": 0.0, "confidence": {"mood": 0.8, "energy": 0.8, "productivity": 0.8}, "rationale": "Morning planning usually steadies Sean."}'
        },
        "done": True,
        "done_reason": "stop"
    }) + "\n"
    second_response = json.dumps({
        "model": "llama3.1:8b",
        "message": {
            "role": "assistant",
            "content": '{"mood": 0.1, "energy": 0.2, "productivity": 0.3, "confidence": {"mood": 0.7, "energy": 0.7, "productivity": 0.7}, "rationale": "Retrieved prior rationale helped."}'
        },
        "done": True,
        "done_reason": "stop"
    }) + "\n"

    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/embeddings",
        json={"embedding": [0.1] * 768},
        is_reusable=True,
    )
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/chat",
        text=first_response,
    )
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/chat",
        text=second_response,
    )

    first_event_id = write_event(db_conn, "sean_chat", "I need a planning reset.", [0.1] * 768)
    first_event = load_event(db_conn, first_event_id)
    first_rating_id = rate_event(db_conn, first_event, [0.1] * 768, llm, embedder)
    assert first_rating_id is not None

    second_event_id = write_event(db_conn, "sean_chat", "I need another planning reset.", [0.1] * 768)
    second_event = load_event(db_conn, second_event_id)
    second_rating_id = rate_event(db_conn, second_event, [0.1] * 768, llm, embedder)
    assert second_rating_id is not None

    requests = httpx_mock.get_requests(url="http://127.0.0.1:11434/api/chat")
    second_req_body = json.loads(requests[1].read())
    second_user_msg = next((m["content"] for m in second_req_body["messages"] if m["role"] == "user"), "")

    assert "Morning planning usually steadies Sean." in second_user_msg


@pytest.mark.asyncio
async def test_rater_starts_unknown_then_later_events_can_retrieve_observations(db_conn, httpx_mock):
    llm = OllamaClient("http://127.0.0.1:11434", "llama3.1:8b")
    embedder = Embedder("http://127.0.0.1:11434", "nomic-embed-text", 768)

    first_response = json.dumps({
        "model": "llama3.1:8b",
        "message": {
            "role": "assistant",
            "content": '{"mood": null, "energy": null, "productivity": null, "confidence": {"mood": null, "energy": null, "productivity": null}, "rationale": "No real signal yet."}'
        },
        "done": True,
        "done_reason": "stop"
    }) + "\n"
    second_response = json.dumps({
        "model": "llama3.1:8b",
        "message": {
            "role": "assistant",
            "content": '{"mood": 0.3, "energy": 0.2, "productivity": 0.1, "confidence": {"mood": 0.7, "energy": 0.7, "productivity": 0.7}, "rationale": "Prior observations now give some signal."}'
        },
        "done": True,
        "done_reason": "stop"
    }) + "\n"

    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/embeddings",
        json={"embedding": [0.1] * 768},
        is_reusable=True,
    )
    httpx_mock.add_response(url="http://127.0.0.1:11434/api/chat", text=first_response)
    httpx_mock.add_response(url="http://127.0.0.1:11434/api/chat", text=second_response)

    first_event_id = write_event(db_conn, "sean_chat", "I feel hard to read right now.", [0.1] * 768)
    first_event = load_event(db_conn, first_event_id)
    first_rating_id = rate_event(db_conn, first_event, [0.1] * 768, llm, embedder)
    assert first_rating_id is not None

    first_row = db_conn.cursor().execute(
        "SELECT mood, energy, productivity FROM ratings WHERE id=?",
        (first_rating_id,),
    ).fetchone()
    assert first_row is not None
    assert first_row["mood"] is None
    assert first_row["energy"] is None
    assert first_row["productivity"] is None

    second_event_id = write_event(db_conn, "sean_chat", "I still feel hard to read right now.", [0.1] * 768)
    second_event = load_event(db_conn, second_event_id)
    second_rating_id = rate_event(db_conn, second_event, [0.1] * 768, llm, embedder)
    assert second_rating_id is not None

    requests = httpx_mock.get_requests(url="http://127.0.0.1:11434/api/chat")
    second_req_body = json.loads(requests[1].read())
    second_user_msg = next((m["content"] for m in second_req_body["messages"] if m["role"] == "user"), "")
    assert "No real signal yet." in second_user_msg


def test_rater_fails_loudly_on_unrecoverable_malformed_llm_output(db_conn):
    class _BadLLM:
        def chat_stream(self, system, user, **kwargs):
            return '{"mood": 0.1, "confidence": 0.8}', ""

    class _Embedder:
        def embed(self, text: str):
            return [0.1] * 768

    event_id = write_event(db_conn, "sean_chat", "This output shape should fail.", [0.1] * 768)
    event = load_event(db_conn, event_id)

    with pytest.raises(RaterError, match="rater output could not be parsed"):
        rate_event(db_conn, event, [0.1] * 768, _BadLLM(), _Embedder())


def test_rater_optional_stability_check_is_diagnostic_only_and_non_persistent(db_conn, monkeypatch):
    monkeypatch.setenv("CADEN_RATER_STABILITY_CHECK", "1")
    logs: list[tuple[str, str]] = []

    class _LLM:
        def __init__(self) -> None:
            self.calls = 0

        def chat_stream(self, system, user, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return (
                    '{"mood": 0.1, "energy": 0.2, "productivity": 0.3, '
                    '"confidence": {"mood": 0.6, "energy": 0.6, "productivity": 0.6}, '
                    '"rationale": "primary"}',
                    "",
                )
            return (
                '{"mood": 0.9, "energy": 0.9, "productivity": 0.9, '
                '"confidence": {"mood": 0.7, "energy": 0.7, "productivity": 0.7}, '
                '"rationale": "diagnostic rerate"}',
                "",
            )

    class _Embedder:
        def embed(self, text: str):
            return [0.1] * 768

    monkeypatch.setattr(
        "caden.rater.rate.retrieve.recall_packets_for_query",
        lambda *args, **kwargs: (
            Ligand(domain="test", intent="rate", themes=(), risk=(), outcome_focus="understand"),
            CadenContext(task="x", recalled_memories=[]),
            [],
        ),
    )
    monkeypatch.setattr(
        "caden.rater.rate.curate.package_recall_context",
        lambda task_text, recalled_memories: "(none)",
    )
    monkeypatch.setattr("caden.rater.rate.diag.log", lambda section, body: logs.append((section, body)))

    event_id = write_event(db_conn, "sean_chat", "check stability diagnostics", [0.1] * 768)
    event = load_event(db_conn, event_id)

    before = db_conn.execute("SELECT COUNT(*) AS c FROM ratings").fetchone()["c"]
    rating_id = rate_event(db_conn, event, [0.1] * 768, _LLM(), _Embedder())
    after = db_conn.execute("SELECT COUNT(*) AS c FROM ratings").fetchone()["c"]

    assert rating_id is not None
    assert after == before + 1
    row = db_conn.execute(
        "SELECT mood, energy, productivity FROM ratings WHERE id=?",
        (rating_id,),
    ).fetchone()
    assert row is not None
    assert row["mood"] == 0.1
    assert row["energy"] == 0.2
    assert row["productivity"] == 0.3
    assert any(
        section == "RATER STABILITY CHECK" and "not persisted" in body
        for section, body in logs
    )


def test_rater_optional_stability_check_failure_is_best_effort(db_conn, monkeypatch):
    monkeypatch.setenv("CADEN_RATER_STABILITY_CHECK", "1")
    logs: list[tuple[str, str]] = []

    class _LLM:
        def __init__(self) -> None:
            self.calls = 0

        def chat_stream(self, system, user, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return (
                    '{"mood": 0.2, "energy": 0.1, "productivity": 0.0, '
                    '"confidence": {"mood": 0.6, "energy": 0.6, "productivity": 0.6}, '
                    '"rationale": "primary"}',
                    "",
                )
            raise LLMError("stability rerate failed")

    class _Embedder:
        def embed(self, text: str):
            return [0.1] * 768

    monkeypatch.setattr(
        "caden.rater.rate.retrieve.recall_packets_for_query",
        lambda *args, **kwargs: (
            Ligand(domain="test", intent="rate", themes=(), risk=(), outcome_focus="understand"),
            CadenContext(task="x", recalled_memories=[]),
            [],
        ),
    )
    monkeypatch.setattr(
        "caden.rater.rate.curate.package_recall_context",
        lambda task_text, recalled_memories: "(none)",
    )
    monkeypatch.setattr("caden.rater.rate.diag.log", lambda section, body: logs.append((section, body)))

    event_id = write_event(db_conn, "sean_chat", "stability failure should not fail rating", [0.1] * 768)
    event = load_event(db_conn, event_id)

    rating_id = rate_event(db_conn, event, [0.1] * 768, _LLM(), _Embedder())

    assert rating_id is not None
    count = db_conn.execute("SELECT COUNT(*) AS c FROM ratings WHERE id=?", (rating_id,)).fetchone()["c"]
    assert count == 1
    assert any(section == "RATER STABILITY CHECK FAILED" for section, _ in logs)


@pytest.mark.parametrize(
    ("source", "build_event"),
    [
        ("sean_chat", lambda conn: write_event(conn, "sean_chat", "Chat events still need rating.", [0.1] * 768)),
        ("task", lambda conn: _event_id_for_source_after(conn, "task", lambda: write_task(conn, "Write the report", "2026-05-01T17:00:00+00:00", "g_task_1", [0.1] * 768))),
        ("task_event", lambda conn: _event_id_for_source_after(conn, "task_event", lambda: _create_task_event(conn))),
        ("web_knowledge", lambda conn: write_event(conn, "web_knowledge", "Knowledge from the web may still affect Sean.", [0.1] * 768)),
        ("caden_log", lambda conn: write_event(conn, "caden_log", "CADEN logged a notable behavior transition.", [0.1] * 768)),
        ("scheduler_lesson", lambda conn: write_event(conn, "scheduler_lesson", "Late afternoon deep work usually slips.", [0.1] * 768)),
    ],
)
def test_rater_rates_each_documented_non_structural_event_source_with_libbie_retrieval(
    db_conn, monkeypatch, source, build_event
):
    calls: list[tuple[str, tuple[str, ...], list[float]]] = []

    class _LLM:
        def __init__(self) -> None:
            self.user_messages: list[str] = []

        def chat_stream(self, system, user, **kwargs):
            self.user_messages.append(user)
            return (
                '{"mood": 0.2, "energy": 0.1, "productivity": 0.3, '
                '"confidence": {"mood": 0.6, "energy": 0.6, "productivity": 0.6}, '
                '"rationale": "Representative source path works."}',
                "",
            )

    class _Embedder:
        def embed(self, text: str):
            return [0.1] * 768

    def _fake_recall(conn, query, embedding, *, sources):
        calls.append((query, sources, embedding))
        return (
            Ligand(domain="test", intent="rate", themes=(), risk=(), outcome_focus="understand"),
            CadenContext(task=query, recalled_memories=[]),
            [],
        )

    monkeypatch.setattr("caden.rater.rate.retrieve.recall_packets_for_query", _fake_recall)
    monkeypatch.setattr("caden.rater.rate.curate.package_recall_context", lambda task_text, recalled_memories: "PACKAGED-BY-LIBBIE")

    event_id = build_event(db_conn)
    event = load_event(db_conn, event_id)
    llm = _LLM()

    rating_id = rate_event(db_conn, event, [0.1] * 768, llm, _Embedder())

    assert rating_id is not None
    assert calls == [
        (
            event.raw_text,
            ("rating", "sean_chat", "task", "residual", "prediction"),
            [0.1] * 768,
        )
    ]
    assert "PACKAGED-BY-LIBBIE" in llm.user_messages[0]


@pytest.mark.parametrize("source", sorted(NON_RATABLE_SOURCES))
def test_rater_skips_only_documented_structural_event_sources(db_conn, monkeypatch, source):
    called = {"retrieval": False, "llm": False}

    class _LLM:
        def chat_stream(self, system, user, **kwargs):
            called["llm"] = True
            return "{}", ""

    class _Embedder:
        def embed(self, text: str):
            return [0.1] * 768

    monkeypatch.setattr(
        "caden.rater.rate.retrieve.recall_packets_for_query",
        lambda *args, **kwargs: called.__setitem__("retrieval", True),
    )

    event_id = write_event(db_conn, source, f"Structural event {source}", [0.1] * 768)
    event = load_event(db_conn, event_id)

    assert rate_event(db_conn, event, [0.1] * 768, _LLM(), _Embedder()) is None
    assert called == {"retrieval": False, "llm": False}


def _event_id_for_source_after(conn, source: str, writer) -> int:
    before = conn.execute("SELECT COALESCE(MAX(id), 0) AS max_id FROM events").fetchone()["max_id"]
    writer()
    row = conn.execute(
        "SELECT id FROM events WHERE source=? AND id>? ORDER BY id ASC LIMIT 1",
        (source, before),
    ).fetchone()
    assert row is not None
    return row["id"]


def _create_task_event(conn) -> int:
    task_id = write_task(conn, "Block off focus time", "2026-05-01T17:00:00+00:00", "g_task_2", [0.1] * 768)
    return link_task_event(
        conn,
        task_id,
        "g_evt_2",
        "2026-05-01T15:00:00+00:00",
        "2026-05-01T16:00:00+00:00",
    )


def test_rater_routes_raw_llm_output_through_shared_repair_layer(db_conn, monkeypatch):
    captured: dict[str, object] = {}

    class _LLM:
        def chat_stream(self, system, user, **kwargs):
            return "MESSY RAW RATING OUTPUT", ""

    class _Embedder:
        def embed(self, text: str):
            return [0.1] * 768

    def _fake_parse(raw, model):
        captured["raw"] = raw
        captured["model"] = model
        return RatingBundle.model_validate(
            {
                "mood": 0.1,
                "energy": 0.2,
                "productivity": 0.3,
                "confidence": {"mood": 0.4, "energy": 0.5, "productivity": 0.6},
                "rationale": "repair path used",
            }
        )

    monkeypatch.setattr("caden.rater.rate.parse_and_validate", _fake_parse)

    event_id = write_event(db_conn, "sean_chat", "Route this through repair.", [0.1] * 768)
    event = load_event(db_conn, event_id)

    rating_id = rate_event(db_conn, event, [0.1] * 768, _LLM(), _Embedder())

    assert rating_id is not None
    assert captured == {"raw": "MESSY RAW RATING OUTPUT", "model": RatingBundle}
