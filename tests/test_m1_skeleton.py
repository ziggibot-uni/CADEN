import pytest
from caden.ui.app import CadenApp
from textual.widgets import Input
from caden.libbie.db import unpack_vector

@pytest.mark.asyncio
async def test_m1_skeleton(mock_services):
    app = CadenApp(mock_services)
    async with app.run_test() as pilot:
        await pilot.pause(0.2)

        # Find the input box
        inp = app.query_one("#chat-input", Input)
        inp.focus()
        inp.value = "Hello CADEN"

        await pilot.press("enter")

        # Wait a bit for processing
        await pilot.pause(1.0)

    # Check database
    cur = mock_services.conn.cursor()
    row = cur.execute("SELECT id, raw_text FROM events WHERE source='sean_chat'").fetchone()
    assert row is not None, "User message not saved to events"
    assert row["raw_text"] == "Hello CADEN"

    # CADEN replies are ephemeral in v0 and must not be persisted as events.
    caden_rows = cur.execute(
        "SELECT COUNT(*) AS n FROM events WHERE raw_text=?",
        ("Mock response",),
    ).fetchone()
    assert caden_rows["n"] == 0, "CADEN reply should not be saved to events"
    
    event_id = row["id"]
    vec_row = cur.execute("SELECT embedding FROM vec_events WHERE rowid=?", (event_id,)).fetchone()
    assert vec_row is not None, "Embedding not saved"
    embedding = unpack_vector(vec_row["embedding"])
    assert len(embedding) == 768, f"Expected dim 768, got {len(embedding)}"
