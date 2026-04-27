"""Retrieval over Libbie's memory.

The active retrieval path is memory-first: vector similarity over curated
memory rows, filtered by source when requested, then reranked with one
documented compactness policy. When memories are otherwise similarly relevant,
shorter memories are preferred so the local model wastes less context window.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Iterable, Sequence

from ..errors import DBError
from ..learning.schema import CadenContext, Ligand, RecallPacket
from . import db as _db


@dataclass(frozen=True)
class RetrievedMemory:
    memory_id: int
    memory_key: str
    source: str
    event_id: int | None
    summary: str
    reason: str
    relevance: str
    score: float


_TOKEN_RE = re.compile(r"[a-z0-9_]{3,}", re.IGNORECASE)
_STOPWORDS = {
    "the", "and", "for", "that", "with", "this", "from", "have", "what",
    "when", "your", "just", "into", "then", "they", "them", "been", "were",
    "will", "would", "could", "should", "about", "there", "their", "while",
}


def _tokenize(text: str, *, limit: int = 8) -> tuple[str, ...]:
    seen: list[str] = []
    for match in _TOKEN_RE.findall(text.lower()):
        if match in _STOPWORDS or match in seen:
            continue
        seen.append(match)
        if len(seen) >= limit:
            break
    return tuple(seen)


def build_ligand(task: str, recent_exchanges: Iterable[tuple[str, str]] = ()) -> Ligand:
    text = " ".join([task, *[item for pair in recent_exchanges for item in pair]])
    tokens = _tokenize(text, limit=6)
    token_set = set(tokens)
    if token_set & {"code", "coding", "python", "bug", "test", "tests"}:
        domain = "coding"
    elif token_set & {"calendar", "task", "tasks", "schedule", "deadline", "today"}:
        domain = "planning"
    else:
        domain = "general"
    risk = tuple(
        token for token in tokens
        if token in {"stuck", "blocked", "urgent", "overwhelmed", "late", "uncertain"}
    )
    return Ligand(
        domain=domain,
        intent=" ".join(task.split())[:180] or "current task",
        themes=tokens,
        risk=risk,
        outcome_focus="useful next response",
    )


def _score_reason(similarity: float, hook_match: float, tag_overlap: float) -> str:
    return (
        f"semantic={similarity:.2f}, hooks={hook_match:.2f}, tags={tag_overlap:.2f}"
    )


def _relevance_for_score(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _length_penalty(text: str) -> float:
    return len(text) / 1000.0 * 0.1


def render_recall_packets(
    packets: Sequence[RecallPacket],
    *,
    include_reason: bool = True,
) -> str:
    if not packets:
        return "(no recalled memories)"
    lines: list[str] = []
    for index, packet in enumerate(packets, start=1):
        reason = ""
        if include_reason and packet.reason:
            reason = f" [{packet.reason}]"
        lines.append(f"{index}. ({packet.relevance}) {packet.summary}{reason}")
    return "\n".join(lines)


def recall_packets_for_task(
    conn: sqlite3.Connection,
    task: str,
    embedder,
    *,
    sources: Sequence[str] | None = None,
    recent_exchanges: Iterable[tuple[str, str]] = (),
    k: int | None = None,
) -> tuple[Ligand, CadenContext, list[RetrievedMemory]]:
    ligand = build_ligand(task, recent_exchanges)
    query_text = task.strip() + "\n" + ligand.compact_text()
    query_embedding = embedder.embed(query_text)
    return recall_packets_for_query(
        conn,
        task,
        query_embedding,
        ligand=ligand,
        sources=sources,
        k=k,
    )


def recall_packets_for_query(
    conn: sqlite3.Connection,
    task: str,
    query_embedding: Sequence[float],
    *,
    ligand: Ligand | None = None,
    sources: Sequence[str] | None = None,
    recent_exchanges: Iterable[tuple[str, str]] = (),
    k: int | None = None,
) -> tuple[Ligand, CadenContext, list[RetrievedMemory]]:
    ligand = ligand or build_ligand(task, recent_exchanges)
    effective_k: int
    if k is None:
        try:
            if sources:
                placeholders = ",".join("?" * len(sources))
                count_row = conn.execute(
                    f"SELECT COUNT(*) AS n FROM memories WHERE source IN ({placeholders})",
                    tuple(sources),
                ).fetchone()
            else:
                count_row = conn.execute("SELECT COUNT(*) AS n FROM memories").fetchone()
        except sqlite3.Error as e:
            raise DBError(f"memory vector search failed: {e}") from e
        effective_k = int(count_row["n"] or 0) if count_row is not None else 0
        effective_k = max(effective_k, 1)
    else:
        effective_k = max(int(k), 1)

    blob = _db.pack_vector(query_embedding)
    fetch_k = effective_k
    try:
        rows = conn.execute(
            """
            SELECT m.id, m.memory_key, m.event_id, m.source, m.tags_json, m.hooks_json,
                   m.context, m.outcome, m.embedding_text, v.distance
            FROM vec_memories AS v
            JOIN memories AS m ON m.id = v.rowid
            WHERE v.embedding MATCH ?
              AND k = ?
            ORDER BY v.distance
            """,
            (blob, fetch_k),
        ).fetchall()
    except sqlite3.Error as e:
        raise DBError(f"memory vector search failed: {e}") from e

    query_tags = set(_tokenize(task + " " + ligand.compact_text(), limit=12))
    retrieved: list[RetrievedMemory] = []
    for row in rows:
        if sources and row["source"] not in sources:
            continue
        try:
            tags = tuple(json.loads(row["tags_json"]))
        except (TypeError, ValueError):
            tags = ()
        try:
            hooks = tuple(json.loads(row["hooks_json"]))
        except (TypeError, ValueError):
            hooks = ()
        tag_set = {str(tag).lower() for tag in tags}
        hook_text = " ".join(str(hook).lower() for hook in hooks)
        tag_overlap = len(query_tags & tag_set) / max(1, len(query_tags))
        hook_match = 0.0
        if query_tags:
            hook_match = sum(1 for tag in query_tags if tag in hook_text) / len(query_tags)
        similarity = 1.0 / (1.0 + float(row["distance"]))
        summary = str(row["outcome"] or row["context"] or row["embedding_text"]).strip()
        score = similarity - _length_penalty(summary)
        retrieved.append(
            RetrievedMemory(
                memory_id=int(row["id"]),
                memory_key=str(row["memory_key"]),
                source=str(row["source"]),
                event_id=int(row["event_id"]) if row["event_id"] is not None else None,
                summary=summary,
                reason=_score_reason(similarity, hook_match, tag_overlap),
                relevance=_relevance_for_score(score),
                score=score,
            )
        )
    retrieved.sort(key=lambda item: item.score, reverse=True)
    top = retrieved[:effective_k]
    packets = tuple(
        RecallPacket(
            mem_id=item.memory_key,
            summary=item.summary,
            relevance=item.relevance,
            reason=item.reason,
        )
        for item in top
    )
    context = CadenContext(task=task, recalled_memories=packets)
    return ligand, context, top
