"""Rate a single event on mood / energy / productivity via the LLM.

The rater is prohibited from inventing numbers when it has no evidence.
When retrieval turns up fewer than MIN_CONTEXT events with prior ratings,
the rater is instructed to emit null for the axes it cannot justify; the
framework stores those as NULL, truthfully.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Callable

from .. import diag
from ..errors import RaterError, LLMAborted, LLMError, LLMRepairError
from ..libbie import curate, retrieve
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


STABILITY_WINDOW_HOURS = 24
STABILITY_MAX_EVENTS = 5
STABILITY_CHECK_ENV = "CADEN_RATER_STABILITY_CHECK"

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


def _rating_user_prompt(event: Event, context_block: str, context_count: int) -> str:
    event_text_block = event.raw_text
    return (
        f"Event to rate (id={event.id}, source={event.source}, ts={event.timestamp}):\n"
        f"---\n{event_text_block}\n---\n\n"
        f"Libbie context:\n{context_block}\n\n"
        f"Retrieved context count: {context_count}.\n"
        f"Rate this event per the system instructions."
    )


def _llm_rate_bundle(
    llm: OllamaClient,
    user_prompt: str,
    *,
    on_dispatch: "Callable[[], None] | None" = None,
    on_first_token: "Callable[[], None] | None" = None,
    on_token: "Callable[[str], None] | None" = None,
) -> RatingBundle:
    first = {"seen": False}

    def _on_open() -> None:
        if on_dispatch is not None:
            on_dispatch()

    def _on_content(chunk: str) -> None:
        if not first["seen"]:
            first["seen"] = True
            if on_first_token is not None:
                on_first_token()
        if on_token is not None:
            on_token(chunk)

    # Streaming + background priority. format_json keeps Ollama in
    # JSON mode (still streamed). max_tokens caps a runaway model so
    # the slot is never held forever — chat preempts via the abort
    # path before that, but this is a belt-and-braces upper bound.
    raw, _thinking = llm.chat_stream(
        SYSTEM_PROMPT,
        user_prompt,
        temperature=0.2,
        format_json=True,
        max_tokens=1024,
        priority="background",
        on_open=_on_open,
        on_content=_on_content,
    )
    return parse_and_validate(raw, RatingBundle)


def _safe_abs_delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    return abs(a - b)


def _run_short_window_stability_check(
    conn: sqlite3.Connection,
    llm: OllamaClient,
    embedder: Embedder,
) -> None:
    """Re-rate recent events for diagnostics only; never persist re-ratings."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STABILITY_WINDOW_HOURS)
    cutoff_iso = cutoff.isoformat(timespec="seconds")
    rows = conn.execute(
        """
        SELECT
          r.id AS rating_id,
          r.event_id AS event_id,
          r.mood AS mood,
          r.energy AS energy,
          r.productivity AS productivity,
          e.timestamp AS event_ts,
          e.source AS event_source,
          e.raw_text AS event_raw_text
        FROM ratings r
        JOIN events e ON e.id = r.event_id
        WHERE e.timestamp >= ?
        ORDER BY r.id DESC
        LIMIT ?
        """,
        (cutoff_iso, STABILITY_MAX_EVENTS),
    ).fetchall()

    if not rows:
        diag.log(
            "RATER STABILITY CHECK",
            "no ratings in the recent window; nothing to compare",
        )
        return

    checks = 0
    mood_deltas: list[float] = []
    energy_deltas: list[float] = []
    productivity_deltas: list[float] = []
    unknown_mismatch = 0

    for row in rows:
        event = Event(
            id=int(row["event_id"]),
            timestamp=str(row["event_ts"]),
            source=str(row["event_source"]),
            raw_text=str(row["event_raw_text"]),
            meta={},
        )
        event_embedding = embedder.embed(event.raw_text)
        _ligand, context, _ranked = retrieve.recall_packets_for_query(
            conn,
            event.raw_text,
            event_embedding,
            sources=(
                "rating",
                "sean_chat",
                "task",
                "residual",
                "prediction",
            ),
        )
        context_block = curate.package_recall_context(
            event.raw_text,
            context.recalled_memories,
        )
        user_prompt = _rating_user_prompt(event, context_block, len(context.recalled_memories))
        bundle = _llm_rate_bundle(llm, user_prompt)

        checks += 1
        old_mood = row["mood"]
        old_energy = row["energy"]
        old_productivity = row["productivity"]
        new_mood = bundle.mood
        new_energy = bundle.energy
        new_productivity = bundle.productivity

        d_mood = _safe_abs_delta(old_mood, new_mood)
        d_energy = _safe_abs_delta(old_energy, new_energy)
        d_productivity = _safe_abs_delta(old_productivity, new_productivity)

        if d_mood is not None:
            mood_deltas.append(d_mood)
        elif (old_mood is None) != (new_mood is None):
            unknown_mismatch += 1

        if d_energy is not None:
            energy_deltas.append(d_energy)
        elif (old_energy is None) != (new_energy is None):
            unknown_mismatch += 1

        if d_productivity is not None:
            productivity_deltas.append(d_productivity)
        elif (old_productivity is None) != (new_productivity is None):
            unknown_mismatch += 1

    def _mean(values: list[float]) -> float | None:
        if not values:
            return None
        return sum(values) / len(values)

    mean_mood = _mean(mood_deltas)
    mean_energy = _mean(energy_deltas)
    mean_productivity = _mean(productivity_deltas)
    diag.log(
        "RATER STABILITY CHECK",
        (
            f"window_hours={STABILITY_WINDOW_HOURS} checked={checks} "
            f"mean_abs_delta_mood={mean_mood} "
            f"mean_abs_delta_energy={mean_energy} "
            f"mean_abs_delta_productivity={mean_productivity} "
            f"unknown_mismatch={unknown_mismatch}\n"
            "re-rated values are diagnostic only and were not persisted"
        ),
    )

def rate_event(
    conn: sqlite3.Connection,
    event: Event,
    event_embedding: list[float],
    llm: OllamaClient,
    embedder: Embedder,
    *,
    on_dispatch: "Callable[[], None] | None" = None,
    on_first_token: "Callable[[], None] | None" = None,
    on_token: "Callable[[str], None] | None" = None,
) -> int | None:
    """Produce a rating for `event`, write it to Libbie, return the rating id.

    Returns None when the event is not eligible for rating (structural).
    Raises RaterError on unrecoverable failure (LLM / repair / DB).
    Re-raises LLMAborted unchanged so the caller can re-queue this event;
    the rater never holds the slot when chat needs it.

    The optional callbacks let the UI surface rater state in real time:
      - on_dispatch: HTTP request started (we got past the priority gate
        and Ollama is now streaming for us)
      - on_first_token: first content byte arrived (proof of life)
      - on_token: every content chunk (UI progress / token counter)
    """
    if event.source in NON_RATABLE_SOURCES:
        return None

    # The focal event is rated directly; supporting memory should come from
    # Libbie's curated recall layer rather than raw-event snippets.
    _ligand, context, _ranked = retrieve.recall_packets_for_query(
        conn,
        event.raw_text,
        event_embedding,
        sources=(
            "rating",
            "sean_chat",
            "task",
            "residual",
            "prediction",
        ),
    )
    context_block = curate.package_recall_context(event.raw_text, context.recalled_memories)
    user_prompt = _rating_user_prompt(event, context_block, len(context.recalled_memories))

    try:
        obj = _llm_rate_bundle(
            llm,
            user_prompt,
            on_dispatch=on_dispatch,
            on_first_token=on_first_token,
            on_token=on_token,
        )
    except LLMRepairError as e:
        raise RaterError(f"rater output could not be parsed: {e}") from e
    except LLMAborted:
        # Bubble up unchanged: this is not a failure, it's cooperative
        # yielding. The caller (chat queue) will re-enqueue this event.
        raise
    except LLMError as e:
        raise RaterError(f"rater LLM call failed: {e}") from e

    try:
        mood = obj.mood
        energy = obj.energy
        productivity = obj.productivity
        c_mood = obj.confidence.mood
        c_energy = obj.confidence.energy
        c_productivity = obj.confidence.productivity
        rationale = obj.rationale.strip() if obj.rationale else ""
    except Exception as e:
        raise RaterError(f"rater output bundle invalid: {e}") from e

    # The rationale is stored and retrievable, so it gets its own embedding.
    rationale_embedding = None
    if rationale:
        try:
            rationale_embedding = embedder.embed(rationale)
        except Exception as e:
            # embedding failure is loud — do not silently skip.
            raise RaterError(f"failed to embed rating rationale: {e}") from e

    rating_id = write_rating(
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

    # Optional diagnostic only. Re-ratings never mutate persisted history.
    if os.environ.get(STABILITY_CHECK_ENV) == "1":
        try:
            _run_short_window_stability_check(conn, llm, embedder)
        except LLMAborted:
            # Never fail foreground behavior for optional diagnostics.
            diag.log("RATER STABILITY CHECK", "aborted by higher-priority foreground work")
        except Exception as e:
            diag.log("RATER STABILITY CHECK FAILED", str(e))

    return rating_id
