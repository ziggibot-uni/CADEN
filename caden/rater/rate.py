"""Rate a single event on mood / energy / productivity via the LLM.

The rater is prohibited from inventing numbers when it has no evidence.
When retrieval turns up fewer than MIN_CONTEXT events with prior ratings,
the rater is instructed to emit null for the axes it cannot justify; the
framework stores those as NULL, truthfully.
"""

from __future__ import annotations

import sqlite3
from typing import Sequence

from ..config import (
    BOOTSTRAP_RETRIEVAL_MIN_K,
    BOOTSTRAP_RETRIEVAL_TOP_K,
    BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS,
    log_bootstrap_use,
)
from ..errors import RaterError, LLMError, LLMRepairError
from ..libbie import retrieve
from ..libbie.store import Event, write_rating
from ..llm.client import OllamaClient
from ..llm.embed import Embedder
from ..llm.repair import parse_and_validate
import pydantic

class ConfidenceVals(pydantic.BaseModel):
    mood: float | None = None
    energy: float | None = None
    productivity: float | None = None

class RatingBundle(pydantic.BaseModel):
    mood: float | None = None
    energy: float | None = None
    productivity: float | None = None
    confidence: ConfidenceVals = pydantic.Field(default_factory=ConfidenceVals)
    rationale: str | None = ""

# Sources the rater is NOT allowed to process. Intake events are meta-content
# about Sean, not events Sean experienced (spec: "Intake and the rater").
INTAKE_SOURCES: frozenset[str] = frozenset({
    "intake_self_knowledge",
    "intake_code_pattern",
})

# Sources the rater is also not meant to rate: structural / bookkeeping events
# that have no felt experience attached.
NON_RATABLE_SOURCES: frozenset[str] = frozenset({
    "bootstrap_value_used",
    "rating",          # rating a rating is nonsense
    "prediction",
    "residual",
})


SYSTEM_PROMPT = """You are CADEN's internal rater. For a single event from Sean's stream, \
estimate three scalars on the range [-1.0, 1.0]:

  - mood:         -1 = deeply bad, 0 = neutral, +1 = great
  - energy:       -1 = exhausted, 0 = neutral, +1 = highly energised
  - productivity: -1 = stuck / averse, 0 = neutral, +1 = flowing / output-rich

You may also emit a confidence on [0.0, 1.0] per axis.

You MUST return JSON with this exact shape:

{
  "mood": number | null,
  "energy": number | null,
  "productivity": number | null,
  "confidence": {
    "mood": number | null,
    "energy": number | null,
    "productivity": number | null
  },
  "rationale": string
}

Rules:
  - If the retrieved context gives you no real signal for an axis, return null
    for that axis. Do not fake a number. Honest "unknown" is the correct answer.
  - Rationale should be short (one or two sentences). It will be stored and
    retrieved later; write for future-you.
  - Do not pad with filler. Do not apologise.
  - Output JSON only. No prose outside the object.
"""


def _format_context(events: Sequence[retrieve.RetrievedEvent]) -> str:
    if not events:
        return "(none)"
    trunc = BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS
    lines: list[str] = []
    for r in events:
        e = r.event
        raw = e.raw_text
        if len(raw) > trunc:
            raw = raw[:trunc] + "…"
        lines.append(
            f"- [{e.timestamp} / {e.source} / dist={r.distance:.3f}] {raw}"
        )
    return "\n".join(lines)


def rate_event(
    conn: sqlite3.Connection,
    event: Event,
    event_embedding: list[float],
    llm: OllamaClient,
    embedder: Embedder,
) -> int | None:
    """Produce a rating for `event`, write it to Libbie, return the rating id.

    Returns None when the event is not eligible for rating (intake, structural).
    Raises RaterError on unrecoverable failure (LLM / repair / DB).
    """
    # Spec: intake events are not rated (they are meta-content about Sean,
    # not events Sean experienced). They still participate in retrieval.
    if event.source in INTAKE_SOURCES or event.source in NON_RATABLE_SOURCES:
        return None

    log_bootstrap_use(conn, "BOOTSTRAP_RETRIEVAL_TOP_K", BOOTSTRAP_RETRIEVAL_TOP_K)
    log_bootstrap_use(
        conn,
        "BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS",
        BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS,
    )

    # Retrieve neighbours that are prior ratings OR prior Sean/task context.
    # 'caden_chat' is deliberately absent (spec: CADEN's replies are not
    # stored as events, so they cannot appear here anyway — listed as a
    # defense in depth).
    neighbours = retrieve.search(
        conn,
        event_embedding,
        k=BOOTSTRAP_RETRIEVAL_TOP_K,
        sources=(
            "rating",
            "sean_chat",
            "task",
            "residual",
            "prediction",
            "intake_self_knowledge",
            "intake_code_pattern",
        ),
    )
    if neighbours and len(neighbours) < BOOTSTRAP_RETRIEVAL_MIN_K:
        raise RaterError(
            f"rater retrieval returned only {len(neighbours)} memories, "
            f"below BOOTSTRAP_RETRIEVAL_MIN_K={BOOTSTRAP_RETRIEVAL_MIN_K}"
        )
    context_block = _format_context(neighbours)

    user_prompt = (
        f"Event to rate (id={event.id}, source={event.source}, ts={event.timestamp}):\n"
        f"---\n{event.raw_text}\n---\n\n"
        f"Relevant past memory from Libbie:\n{context_block}\n\n"
        f"Retrieved context count: {len(neighbours)}.\n"
        f"Rate this event per the system instructions."
    )

    try:
        raw = llm.chat(SYSTEM_PROMPT, user_prompt, temperature=0.2, format_json=True)
    except LLMError as e:
        raise RaterError(f"rater LLM call failed: {e}") from e

    try:
        obj = parse_and_validate(raw, RatingBundle)
        mood = obj.mood
        energy = obj.energy
        productivity = obj.productivity
        c_mood = obj.confidence.mood
        c_energy = obj.confidence.energy
        c_productivity = obj.confidence.productivity
        rationale = obj.rationale.strip() if obj.rationale else ""
    except LLMRepairError as e:
        raise RaterError(f"rater output could not be parsed: {e}") from e

    # The rationale is stored and retrievable, so it gets its own embedding.
    rationale_embedding = None
    if rationale:
        try:
            rationale_embedding = embedder.embed(rationale)
        except Exception as e:
            # embedding failure is loud — do not silently skip.
            raise RaterError(f"failed to embed rating rationale: {e}") from e

    return write_rating(
        conn,
        event_id=event.id,
        mood=mood,
        energy=energy,
        productivity=productivity,
        c_mood=c_mood,
        c_energy=c_energy,
        c_productivity=c_productivity,
        rationale=rationale,
        embedding=rationale_embedding,
    )
