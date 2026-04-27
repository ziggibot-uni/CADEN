from caden.libbie.retrieve import recall_packets_for_query, recall_packets_for_task
from caden.libbie.store import write_event
from caden.learning.schema import RecallPacket


class _MockEmbedder:
    def embed(self, text: str):
        return [0.1] * 768


def test_retrieval_prefers_shorter_memories_when_similarity_ties(db_conn):
    embedding = [0.1] * 768

    short_event_id = write_event(
        db_conn,
        source="residual",
        raw_text="Keep planning notes concise.",
        embedding=embedding,
        meta={"rationale": "Short notes worked."},
    )
    long_event_id = write_event(
        db_conn,
        source="residual",
        raw_text="Keep planning notes concise.",
        embedding=embedding,
        meta={
            "rationale": (
                "This memory says the same thing but uses far more words than necessary, "
                "which should make it lose the tie once the documented compactness penalty "
                "is applied during retrieval ranking."
            )
        },
    )

    _, context, retrieved = recall_packets_for_query(
        db_conn,
        task="plan tomorrow",
        query_embedding=embedding,
        sources=["residual"],
        k=2,
    )

    assert [item.event_id for item in retrieved] == [short_event_id, long_event_id]
    assert context.recalled_memories[0].mem_id == retrieved[0].memory_key
    assert retrieved[0].score > retrieved[1].score


def test_recall_packets_are_the_compact_caden_facing_payload(db_conn):
    embedding = [0.1] * 768
    write_event(
        db_conn,
        source="sean_chat",
        raw_text="Sean should start with the smallest concrete next step.",
        embedding=embedding,
        meta={"domain": "self_knowledge", "trigger": "chat_send"},
    )

    ligand, context, retrieved = recall_packets_for_query(
        db_conn,
        task="what should I do next?",
        query_embedding=embedding,
        sources=["sean_chat"],
        k=1,
    )

    assert ligand.domain
    assert context.task == "what should I do next?"
    assert len(context.recalled_memories) == 1
    packet = context.recalled_memories[0]
    assert packet.mem_id == retrieved[0].memory_key
    assert packet.summary == retrieved[0].summary
    assert packet.relevance in {"high", "medium", "low"}
    assert "semantic=" in packet.reason
    assert "sean_chat" not in packet.summary


def test_ligand_is_transient_and_not_persisted_as_memory(db_conn):
    embedder = _MockEmbedder()
    write_event(
        db_conn,
        source="sean_chat",
        raw_text="I feel stuck and need a clear next step.",
        embedding=[0.1] * 768,
        meta={"trigger": "chat_send"},
    )
    counts_before = db_conn.execute(
        "SELECT (SELECT COUNT(*) FROM events) AS event_count, (SELECT COUNT(*) FROM memories) AS memory_count"
    ).fetchone()

    ligand, context, _retrieved = recall_packets_for_task(
        db_conn,
        "I am blocked on this task",
        embedder,
        sources=["sean_chat"],
        recent_exchanges=[("I am blocked.", "Let's find one move.")],
        k=2,
    )

    counts_after = db_conn.execute(
        "SELECT (SELECT COUNT(*) FROM events) AS event_count, (SELECT COUNT(*) FROM memories) AS memory_count"
    ).fetchone()

    assert ligand.intent == "I am blocked on this task"
    assert context.recalled_memories
    assert counts_after["event_count"] == counts_before["event_count"]
    assert counts_after["memory_count"] == counts_before["memory_count"]


def test_ligand_is_not_part_of_the_public_caden_facing_context_object(db_conn):
    embedder = _MockEmbedder()
    write_event(
        db_conn,
        source="sean_chat",
        raw_text="Sean should choose one concrete next action.",
        embedding=[0.1] * 768,
        meta={"domain": "self_knowledge"},
    )

    ligand, context, _retrieved = recall_packets_for_task(
        db_conn,
        "what should I do next?",
        embedder,
        sources=["sean_chat"],
        k=1,
    )

    serialized = context.to_dict()

    assert ligand.domain
    assert all(isinstance(packet, RecallPacket) for packet in context.recalled_memories)
    assert "ligand" not in serialized
    assert set(serialized.keys()) == {"task", "recalled_memories"}


def test_retrieval_queries_curated_memory_vectors_not_raw_event_vectors(db_conn):
    embedding = [0.1] * 768
    write_event(
        db_conn,
        source="residual",
        raw_text="Use the memory vector table for retrieval.",
        embedding=embedding,
        meta={"rationale": "vec_memories should be the active retrieval path."},
    )
    statements: list[str] = []
    db_conn.set_trace_callback(statements.append)
    try:
        recall_packets_for_query(
            db_conn,
            task="memory retrieval check",
            query_embedding=embedding,
            sources=["residual"],
            k=1,
        )
    finally:
        db_conn.set_trace_callback(None)

    sql = "\n".join(statement.upper() for statement in statements)
    assert "FROM VEC_MEMORIES" in sql
    assert "FROM VEC_EVENTS" not in sql


def test_write_event_captures_raw_event_before_canonical_memory_row(db_conn):
    statements: list[str] = []
    db_conn.set_trace_callback(statements.append)
    try:
        write_event(
            db_conn,
            source="sean_chat",
            raw_text="capture first, then canonicalize",
            embedding=[0.1] * 768,
            meta={"trigger": "chat_send"},
        )
    finally:
        db_conn.set_trace_callback(None)

    normalized = [statement.upper() for statement in statements]
    event_insert = next(i for i, statement in enumerate(normalized) if "INSERT INTO EVENTS" in statement)
    memory_insert = next(i for i, statement in enumerate(normalized) if "INSERT INTO MEMORIES" in statement)
    assert event_insert < memory_insert


def test_recall_defaults_to_all_matching_memories_when_k_is_omitted(db_conn):
    embedding = [0.1] * 768
    for idx in range(5):
        write_event(
            db_conn,
            source="sean_chat",
            raw_text=f"memory #{idx}",
            embedding=embedding,
            meta={"trigger": "chat_send"},
        )

    _ligand, context, retrieved = recall_packets_for_query(
        db_conn,
        task="what should I do next?",
        query_embedding=embedding,
        sources=["sean_chat"],
    )

    assert len(retrieved) == 5
    assert len(context.recalled_memories) == 5
