from __future__ import annotations

import pytest

from caden.errors import DBError, WebSearchError
from caden.libbie import (
    annotate,
    capture,
    link,
    recall,
    search_web,
    surface,
    surface_on_meaningful_change,
)


class _Embedder:
    def embed(self, text: str):
        return [0.1] * 768


def test_libbie_capture_and_retrieve_use_single_memory_pipeline(db_conn):
    event_id = capture(
        db_conn,
        source="sean_chat",
        raw_text="Sean works better when tasks have one concrete first action.",
        embedder=_Embedder(),
        meta={"trigger": "chat_send", "domain": "self_knowledge"},
    )

    context, packets = recall(
        db_conn,
        "what should I do first?",
        embedder=_Embedder(),
        sources=("sean_chat",),
        k=3,
    )

    assert event_id > 0
    assert context.task == "what should I do first?"
    assert packets
    assert any("one concrete first action" in packet.summary for packet in packets)


def test_libbie_surface_returns_proactive_recall_packets(db_conn):
    capture(
        db_conn,
        source="project_entry",
        raw_text="Project alpha: split scope into two small milestones.",
        embedder=_Embedder(),
        meta={"trigger": "project_manager_submit"},
    )

    packets = surface(
        db_conn,
        "currently planning project alpha",
        embedder=_Embedder(),
        sources=("project_entry",),
        k=2,
    )

    assert packets
    assert any("Project alpha" in packet.summary for packet in packets)


def test_libbie_surface_on_meaningful_change_only_returns_novel_packets(db_conn):
    capture(
        db_conn,
        source="project_entry",
        raw_text="Project alpha: split scope into two small milestones.",
        embedder=_Embedder(),
        meta={"trigger": "project_manager_submit"},
    )
    capture(
        db_conn,
        source="project_entry",
        raw_text="Project beta: gather stakeholder constraints before scheduling.",
        embedder=_Embedder(),
        meta={"trigger": "project_manager_submit"},
    )

    unchanged = surface_on_meaningful_change(
        db_conn,
        previous_context_text="currently planning project alpha",
        current_context_text="currently planning project alpha",
        embedder=_Embedder(),
        sources=("project_entry",),
        k=3,
        min_change_ratio=0.2,
    )
    changed = surface_on_meaningful_change(
        db_conn,
        previous_context_text="currently planning project alpha",
        current_context_text="currently planning project beta",
        embedder=_Embedder(),
        sources=("project_entry",),
        k=3,
        min_change_ratio=0.2,
    )

    assert unchanged == ()
    assert changed
    assert any("Project beta" in packet.summary for packet in changed)


def test_libbie_annotate_is_append_only(db_conn):
    event_id = capture(
        db_conn,
        source="sean_chat",
        raw_text="Annotate me",
        embedder=_Embedder(),
        meta={"trigger": "chat_send"},
    )

    annotate(db_conn, event_id, {"why": "first why"})
    annotate(db_conn, event_id, {"why": "second why"})

    rows = db_conn.execute(
        "SELECT value FROM event_metadata WHERE event_id=? AND key='why' ORDER BY id",
        (event_id,),
    ).fetchall()

    assert [row["value"] for row in rows] == ["first why", "second why"]


def test_libbie_link_records_relation_as_event(db_conn):
    left = capture(
        db_conn,
        source="sean_chat",
        raw_text="Left event",
        embedder=_Embedder(),
        meta={"trigger": "chat_send"},
    )
    right = capture(
        db_conn,
        source="sean_chat",
        raw_text="Right event",
        embedder=_Embedder(),
        meta={"trigger": "chat_send"},
    )

    link_event_id = link(
        db_conn,
        left,
        right,
        "supports",
        embedder=_Embedder(),
    )

    event = db_conn.execute(
        "SELECT source, raw_text FROM events WHERE id=?",
        (link_event_id,),
    ).fetchone()
    meta = {
        (row["key"], row["value"])
        for row in db_conn.execute(
            "SELECT key, value FROM event_metadata WHERE event_id=?",
            (link_event_id,),
        ).fetchall()
    }

    assert event is not None
    assert event["source"] == "memory_link"
    assert "supports" in event["raw_text"]
    assert ("left_event_id", str(left)) in meta
    assert ("right_event_id", str(right)) in meta
    assert ("relation", "supports") in meta


def test_libbie_link_requires_non_empty_relation(db_conn):
    left = capture(
        db_conn,
        source="sean_chat",
        raw_text="Left",
        embedder=_Embedder(),
        meta={"trigger": "chat_send"},
    )
    right = capture(
        db_conn,
        source="sean_chat",
        raw_text="Right",
        embedder=_Embedder(),
        meta={"trigger": "chat_send"},
    )

    with pytest.raises(DBError, match="relation must not be empty"):
        link(db_conn, left, right, "   ", embedder=_Embedder())


def test_libbie_search_web_captures_results_as_memory_events(db_conn):
    class _Hit:
        def __init__(self, title: str, url: str, content: str, engine: str = "duckduckgo") -> None:
            self.title = title
            self.url = url
            self.content = content
            self.engine = engine

        def summary_text(self) -> str:
            return f"{self.title} -- {self.content} -- {self.url}"

    class _Searxng:
        def search(self, query: str, *, limit: int = 5):
            assert query == "python dataclass defaults"
            return [
                _Hit("Dataclass docs", "https://docs.python.org", "Use default_factory for mutable defaults"),
                _Hit("Example", "https://example.com", "Simple explanation"),
            ]

    ids = search_web(
        db_conn,
        "python dataclass defaults",
        searxng=_Searxng(),
        embedder=_Embedder(),
        limit=2,
    )

    assert len(ids) == 2
    rows = db_conn.execute(
        "SELECT source FROM events WHERE id IN (?, ?)",
        (ids[0], ids[1]),
    ).fetchall()
    assert all(row["source"] == "web_knowledge" for row in rows)


def test_libbie_search_web_requires_non_empty_query(db_conn):
    class _Searxng:
        def search(self, query: str, *, limit: int = 5):
            return []

    with pytest.raises(DBError, match="search query must not be empty"):
        search_web(db_conn, "   ", searxng=_Searxng(), embedder=_Embedder())


def test_libbie_search_web_raises_loudly_without_fallback_on_upstream_failure(db_conn):
    class _Searxng:
        def search(self, query: str, *, limit: int = 5):
            raise WebSearchError("searxng request failed: timeout")

    with pytest.raises(WebSearchError, match="timeout"):
        search_web(
            db_conn,
            "python dataclass defaults",
            searxng=_Searxng(),
            embedder=_Embedder(),
            limit=2,
        )

    count = db_conn.execute(
        "SELECT COUNT(*) AS n FROM events WHERE source='web_knowledge'"
    ).fetchone()["n"]
    assert int(count) == 0
