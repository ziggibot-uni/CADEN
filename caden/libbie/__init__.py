"""Libbie — CADEN's memory layer.

Single sqlite database with the sqlite-vec extension providing vector search.
Libbie owns every write and every read of memory. She is the only module
that touches the DB.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Sequence

from ..errors import DBError
from ..learning.schema import CadenContext, RecallPacket
from . import retrieve as _retrieve
from .store import append_event_metadata, write_event


def capture(
	conn: sqlite3.Connection,
	source: str,
	raw_text: str,
	*,
	embedder,
	meta: dict[str, Any] | None = None,
	timestamp: str | None = None,
) -> int:
	"""Capture one event through Libbie's canonical write path."""
	embedding = embedder.embed(raw_text)
	return write_event(
		conn,
		source=source,
		raw_text=raw_text,
		embedding=embedding,
		meta=meta,
		timestamp=timestamp,
	)


def recall(
	conn: sqlite3.Connection,
	query: str,
	*,
	embedder,
	sources: Sequence[str] | None = None,
	recent_exchanges: Iterable[tuple[str, str]] = (),
	k: int | None = None,
) -> tuple[CadenContext, tuple[RecallPacket, ...]]:
	"""Retrieve CADEN-facing recalled memories for a query."""
	_ligand, context, _ranked = _retrieve.recall_packets_for_task(
		conn,
		query,
		embedder,
		sources=sources,
		recent_exchanges=recent_exchanges,
		k=k,
	)
	return context, context.recalled_memories


def surface(
	conn: sqlite3.Connection,
	context_text: str,
	*,
	embedder,
	sources: Sequence[str] | None = None,
	k: int = 5,
) -> tuple[RecallPacket, ...]:
	"""Proactively surface memories for the current context."""
	_ctx, packets = recall(
		conn,
		context_text,
		embedder=embedder,
		sources=sources,
		recent_exchanges=(),
		k=k,
	)
	return packets


def surface_on_meaningful_change(
	conn: sqlite3.Connection,
	*,
	previous_context_text: str,
	current_context_text: str,
	embedder,
	sources: Sequence[str] | None = None,
	k: int = 5,
	min_change_ratio: float = 0.4,
) -> tuple[RecallPacket, ...]:
	"""Surface recall packets only when the context change is materially new."""
	if not 0.0 <= min_change_ratio <= 1.0:
		raise DBError("min_change_ratio must be in [0, 1]")
	if previous_context_text.strip() == current_context_text.strip():
		return ()

	def _tokens(text: str) -> set[str]:
		return {
			tok
			for tok in (part.strip().lower() for part in text.split())
			if len(tok) >= 3
		}

	prev_tokens = _tokens(previous_context_text)
	curr_tokens = _tokens(current_context_text)
	union = prev_tokens | curr_tokens
	if not union:
		return ()
	change_ratio = 1.0 - (len(prev_tokens & curr_tokens) / len(union))
	if change_ratio < min_change_ratio:
		return ()

	curr_packets = surface(
		conn,
		current_context_text,
		embedder=embedder,
		sources=sources,
		k=k,
	)
	return curr_packets


def annotate(
	conn: sqlite3.Connection,
	event_id: int,
	metadata_patch: dict[str, Any],
) -> None:
	"""Append metadata rows for an event.

	Annotation is append-only. Existing metadata is never overwritten.
	"""
	if not metadata_patch:
		return
	for key, value in metadata_patch.items():
		append_event_metadata(conn, event_id, str(key), value)


def link(
	conn: sqlite3.Connection,
	event_id_a: int,
	event_id_b: int,
	relation: str,
	*,
	embedder=None,
) -> int:
	"""Record an explicit relation between two events.

	The link itself is captured as an event so relationship history stays
	queryable in the same memory system.
	"""
	rel = relation.strip()
	if not rel:
		raise DBError("relation must not be empty")

	raw_text = f"Link event #{event_id_a} -> event #{event_id_b} ({rel})"
	embedding = embedder.embed(raw_text) if embedder is not None else None
	return write_event(
		conn,
		source="memory_link",
		raw_text=raw_text,
		embedding=embedding,
		meta={
			"linked_to": event_id_b,
			"left_event_id": event_id_a,
			"right_event_id": event_id_b,
			"relation": rel,
			"trigger": "libbie_link",
		},
	)


def search_web(
	conn: sqlite3.Connection,
	query: str,
	*,
	searxng,
	embedder,
	limit: int = 5,
) -> tuple[int, ...]:
	"""Search public web sources via SearXNG and capture findings in Libbie."""
	q = query.strip()
	if not q:
		raise DBError("search query must not be empty")

	hits = searxng.search(q, limit=limit)
	ids: list[int] = []
	for hit in hits:
		raw_text = f"Web knowledge: {hit.summary_text()}"
		ids.append(
			write_event(
				conn,
				source="web_knowledge",
				raw_text=raw_text,
				embedding=embedder.embed(raw_text),
				meta={
					"query": q,
					"title": hit.title,
					"url": hit.url,
					"engine": hit.engine,
					"trigger": "searxng",
					"domain": "external_knowledge",
				},
			)
		)
	return tuple(ids)


__all__ = [
	"annotate",
	"capture",
	"link",
	"recall",
	"search_web",
	"surface",
	"surface_on_meaningful_change",
]
