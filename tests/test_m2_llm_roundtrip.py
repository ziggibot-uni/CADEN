import pytest
import json
from caden.config import load
from caden.ui.services import Services
from caden.llm.client import OllamaClient
from caden.llm.embed import Embedder
from caden.rater.rate import rate_event, RatingBundle
from caden.libbie.store import write_event, load_event

@pytest.mark.asyncio
async def test_m2_llm_roundtrip(tmp_caden_home, db_conn, httpx_mock, monkeypatch):
    # Setup real clients pointing to mocked httpx
    cfg = load()
    llm = OllamaClient(cfg.ollama_url, cfg.ollama_model)
    embedder = Embedder(cfg.ollama_url, cfg.embed_model, cfg.embed_dim)

    # 1. Mock the embedder endpoint
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/embeddings",
        json={"embedding": [0.1] * 768}
    )

    messy_json = """```json
{"mood": 0.5, "energy": null, "productivity": 0.9, "confidence": {"mood": 0.8, "energy": null, "productivity": 0.2}, "rationale": "test reason"}
```
"""
    stream_response = json.dumps({
        "model": "llama3.1:8b",
        "message": {"role": "assistant", "content": messy_json},
        "done": True,
        "done_reason": "stop"
    }) + "\n"
    
    # 2. Mock the chat streaming endpoint with messy JSON
    httpx_mock.add_response(
        url="http://127.0.0.1:11434/api/chat",
        text=stream_response
    )

    # Insert 5 events to satisfy BOOTSTRAP_RETRIEVAL_MIN_K
    write_event(db_conn, "intake_self_knowledge", "Sean likes tests 1", [0.1]*768)
    write_event(db_conn, "intake_self_knowledge", "Sean likes tests 2", [0.1]*768)
    write_event(db_conn, "intake_self_knowledge", "Sean likes tests 3", [0.1]*768)
    write_event(db_conn, "intake_self_knowledge", "Sean likes tests 4", [0.1]*768)
    write_event(db_conn, "intake_self_knowledge", "Sean likes tests 5", [0.1]*768)
    
    # Insert the event to be rated
    event_id = write_event(db_conn, "sean_chat", "This is a test event", [0.1]*768)
    evt = load_event(db_conn, event_id)

    # Run the rater
    rating_id = rate_event(db_conn, evt, [0.1]*768, llm, embedder)
    
    assert rating_id is not None, "Rater should have produced a rating"
    
    # Assert retrieval was fed into the prompt
    requests = httpx_mock.get_requests(url="http://127.0.0.1:11434/api/chat")
    assert len(requests) == 1
    req_body = json.loads(requests[0].read())
    messages = req_body["messages"]
    user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")
    
    assert "Sean likes tests" in user_msg, "Retrieval was not fed into the prompt"
    
    # Assert repair layer worked cleanly and saved valid data
    cur = db_conn.cursor()
    rating_row = cur.execute("SELECT mood, productivity, rationale FROM ratings WHERE id=?", (rating_id,)).fetchone()
    assert rating_row["mood"] == 0.5
    assert rating_row["productivity"] == 0.9
    assert rating_row["rationale"] == "test reason"

