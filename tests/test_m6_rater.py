import pytest
import sqlite3
import json
from caden.libbie.store import write_event, load_event
from caden.rater.rate import rate_event
from caden.ui.services import Services
from caden.llm.client import OllamaClient
from caden.llm.embed import Embedder

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

    # Need 5 events for BOOTSTRAP_RETRIEVAL_MIN_K
    for i in range(5):
        write_event(db_conn, "intake_self_knowledge", f"dummy knowledge {i}", [0.1]*768)

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
    
    # 2. Capture an intake_self_knowledge event, ensure it's not rated
    # Since write_event doesn't trigger rating directly, we simulate the logic in poll/tasks:
    # We load it and attempt to rate it. Wait, rate_event itself refuses to rate?
    knowledge_event_id = write_event(db_conn, "intake_self_knowledge", "I like eggs", [0.1]*768)
    evt2 = load_event(db_conn, knowledge_event_id)
    
    # According to CADEN_libbie.md, only events that don't have embeddings gets rated? 
    # Actually wait, ratable events are handled via background or explicit call.
    # If the user means "assert it's not rated automatically", that's because background tasks 
    # check if the event matches caden_owned or not?
    # CADEN_buildBrief.md says: 
    # "capture an intake_self_knowledge event; assert no ratings row created."
    
    # If we call rate_event on intake_self_knowledge, does it return None? Let's check rate.py
    rate2_id = rate_event(db_conn, evt2, [0.1]*768, llm, embedder)
    assert rate2_id is None, "Ratings should NOT be generated for intake_self_knowledge events!"
