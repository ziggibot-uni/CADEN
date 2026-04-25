"""Retrieval over Libbie's memory.

The *form* of retrieval is: embedding similarity via sqlite-vec plus optional
metadata filters (source, time window). The weights inside this form are
intended to become learned (spec: retrieval is learned from residuals).
For v0 the weights are uniform — that is the mechanism, waiting for residuals
to shape it.

No ranking heuristics are hand-coded. We return the top-k nearest neighbours
by cosine distance and let callers decide what to do with them.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Sequence

from ..errors import DBError
from . import db as _db
from .store import Event, _safe_json


@dataclass(frozen=True)
class RetrievedEvent:
    event: Event
    distance: float


def search(
    conn: sqlite3.Connection,
    query_embedding: Sequence[float],
    k: int = 10,
    sources: Sequence[str] | None = None,
) -> list[RetrievedEvent]:
    """Return the k nearest events by cosine distance. Smaller distance == closer."""
    if k <= 0:
        return []
    blob = _db.pack_vector(query_embedding)
    # sqlite-vec kNN: MATCH + LIMIT returns nearest vectors; we join back to events.
    try:
        rows = conn.execute(
            """
            SELECT e.id, e.timestamp, e.source, e.raw_text, e.meta_json, v.distance
            FROM vec_events AS v
            JOIN events AS e ON e.id = v.rowid
            WHERE v.embedding MATCH ?
              AND k = ?
            ORDER BY v.distance
            """,
            (blob, k * 4 if sources else k),
        ).fetchall()
    except sqlite3.Error as e:
        raise DBError(f"vector search failed: {e}") from e

    results: list[RetrievedEvent] = []
    for r in rows:
        if sources and r["source"] not in sources:
            continue
        results.append(
            RetrievedEvent(
                event=Event(
                    id=r["id"], timestamp=r["timestamp"], source=r["source"],
                    raw_text=r["raw_text"], meta=_safe_json(r["meta_json"]),
                ),
                distance=float(r["distance"]),
            )
        )
        if len(results) >= k:
            break
    return results
