"""Asynchronous best-effort `why` rationale enrichment for captured events.

Capture is immediate and never waits for this path. Callers run this in a
background worker. Missing `why` is permitted; failures are logged loudly and
must not break foreground flow.
"""

from __future__ import annotations

import sqlite3

import pydantic

from .. import diag
from ..errors import LLMError, LLMRepairError
from ..llm.client import OllamaClient
from ..llm.repair import parse_and_validate
from .store import append_event_metadata, event_has_metadata_key, load_event


WHY_META_KEY = "why"


class WhyBundle(pydantic.BaseModel):
    why: str


SYSTEM_PROMPT = """You write one short rationale for why an event should be captured in memory.

Return JSON only:
{
  "why": string
}

Rules:
- 8 to 24 words.
- concrete and specific to the event text.
- no filler, no apology, no markdown.
"""


def generate_why_for_event(
    conn: sqlite3.Connection,
    event_id: int,
    llm: OllamaClient,
) -> bool:
    """Generate and append `why` metadata for one event.

    Returns:
      True if a new `why` row was appended, False if already present.

    Raises:
      LLMError / LLMRepairError for generation/validation failures.
      DBError (from store helpers) for write failures.
    """
    if event_has_metadata_key(conn, event_id, WHY_META_KEY):
        return False

    event = load_event(conn, event_id)
    if event is None:
        raise LLMError(f"cannot generate why: event id {event_id} does not exist")

    user_prompt = (
        f"event_id={event.id}\n"
        f"source={event.source}\n"
        f"timestamp={event.timestamp}\n"
        f"raw_text:\n{event.raw_text}\n"
        "Write why this capture should be remembered."
    )

    raw, _thinking = llm.chat_stream(
        SYSTEM_PROMPT,
        user_prompt,
        temperature=0.1,
        format_json=True,
        max_tokens=128,
        priority="background",
    )

    bundle = parse_and_validate(raw, WhyBundle)
    why_text = bundle.why.strip()
    if not why_text:
        raise LLMRepairError("why was empty")

    append_event_metadata(conn, event.id, WHY_META_KEY, why_text)
    diag.log(
        "WHY ENRICHED",
        f"event_id={event.id} source={event.source}\nwhy={why_text}",
    )
    return True
