import pytest

from caden.errors import LLMError
from caden.libbie.store import write_event
from caden.libbie.why import generate_why_for_event


class _WhyLLM:
    def chat_stream(self, system, user, **kwargs):
        return '{"why": "captured to preserve the concrete context for later reasoning"}', ""


class _BadWhyLLM:
    def chat_stream(self, system, user, **kwargs):
        raise LLMError("down")


def test_generate_why_for_event_appends_metadata_row(db_conn):
    event_id = write_event(
        db_conn,
        "sean_chat",
        "I need one concrete next step now.",
        [0.1] * 768,
        meta={"trigger": "chat_send"},
    )

    enriched = generate_why_for_event(db_conn, event_id, _WhyLLM())

    assert enriched is True
    row = db_conn.execute(
        "SELECT value FROM event_metadata WHERE event_id=? AND key='why' ORDER BY id DESC LIMIT 1",
        (event_id,),
    ).fetchone()
    assert row is not None
    assert "concrete context" in row["value"]


def test_generate_why_for_event_skips_when_why_already_exists(db_conn):
    event_id = write_event(
        db_conn,
        "sean_chat",
        "I already have a why.",
        [0.1] * 768,
        meta={"why": "existing why"},
    )

    enriched = generate_why_for_event(db_conn, event_id, _WhyLLM())

    assert enriched is False
    rows = db_conn.execute(
        "SELECT value FROM event_metadata WHERE event_id=? AND key='why' ORDER BY id ASC",
        (event_id,),
    ).fetchall()
    assert [row["value"] for row in rows] == ["existing why"]


def test_generate_why_for_event_propagates_llm_failure(db_conn):
    event_id = write_event(
        db_conn,
        "sean_chat",
        "Failure path should be surfaced to worker.",
        [0.1] * 768,
        meta={"trigger": "chat_send"},
    )

    with pytest.raises(LLMError, match="down"):
        generate_why_for_event(db_conn, event_id, _BadWhyLLM())
