"""Emit a prediction bundle at scheduling time.

Per spec: every scheduled task gets a paired bundle of predictions
(duration + pre/post mood/energy/productivity + confidences), stored as both
a predictions row and a mirrored event. When retrieval is too thin to
justify a number, the LLM is instructed to emit null; the framework writes
NULL, truthfully.
"""

from __future__ import annotations

import sqlite3

from ..config import (
    BOOTSTRAP_FIRST_SCHEDULE_CONFIDENCE,
    BOOTSTRAP_RETRIEVAL_TOP_K,
    BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS,
    log_bootstrap_use,
)
from ..errors import SchedulerError, LLMError, LLMRepairError
from ..libbie import retrieve
from ..libbie.store import write_prediction
from ..llm.client import OllamaClient
from ..llm.embed import Embedder
from ..llm.repair import parse_and_validate
import pydantic

class NestedAxis(pydantic.BaseModel):
    mood: float | None = None
    energy: float | None = None
    productivity: float | None = None

class ConfidenceValues(pydantic.BaseModel):
    duration: float | None = None
    pre_mood: float | None = None
    pre_energy: float | None = None
    pre_productivity: float | None = None
    post_mood: float | None = None
    post_energy: float | None = None
    post_productivity: float | None = None

class PredictionBundle(pydantic.BaseModel):
    predicted_duration_min: float
    pre: NestedAxis
    post: NestedAxis
    confidence: ConfidenceValues = pydantic.Field(default_factory=ConfidenceValues)
    rationale: str | None = ""


SYSTEM_PROMPT = """You are CADEN's prediction engine. Given a task description and the \
scheduled block, predict:

  - predicted_duration_min: how many minutes Sean will actually spend on it
  - pre: Sean's mood / energy / productivity just before the block starts
  - post: Sean's mood / energy / productivity just after the block ends
  - a confidence on [0.0, 1.0] for each scalar you emit

Return JSON with this shape (all numeric fields may be null if you cannot
justify a number from the retrieved memory — honest unknown is correct):

{
  "predicted_duration_min": number,
  "pre":  {"mood": number|null, "energy": number|null, "productivity": number|null},
  "post": {"mood": number|null, "energy": number|null, "productivity": number|null},
  "confidence": {
    "duration":       number|null,
    "pre_mood":       number|null,
    "pre_energy":     number|null,
    "pre_productivity": number|null,
    "post_mood":      number|null,
    "post_energy":    number|null,
    "post_productivity": number|null
  },
  "rationale": string
}

Rules:
  - Scalars are on [-1.0, 1.0] like the rater's.
  - predicted_duration_min must be a positive number.
  - Do not fabricate. Null is the right answer when Libbie's context is thin.
  - JSON only, no prose outside the object.
"""


def emit_prediction(
    conn: sqlite3.Connection,
    task_id: int,
    description: str,
    description_embedding: list[float],
    planned_start_iso: str,
    planned_end_iso: str,
    google_event_id: str | None,
    llm: OllamaClient,
    embedder: Embedder,
) -> int:
    """Compute and store a prediction bundle. Returns prediction id."""
    log_bootstrap_use(conn, "BOOTSTRAP_RETRIEVAL_TOP_K", BOOTSTRAP_RETRIEVAL_TOP_K)
    log_bootstrap_use(
        conn,
        "BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS",
        BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS,
    )

    neighbours = retrieve.search(
        conn,
        description_embedding,
        k=BOOTSTRAP_RETRIEVAL_TOP_K,
        sources=(
            "rating",
            "residual",
            "prediction",
            "sean_chat",
            "task",
            "intake_self_knowledge",
            "intake_code_pattern",
        ),
    )
    trunc = BOOTSTRAP_RETRIEVAL_TRUNCATE_CHARS
    ctx_lines = [
        f"- [{r.event.timestamp} / {r.event.source} / dist={r.distance:.3f}] "
        f"{(r.event.raw_text[:trunc] + '…') if len(r.event.raw_text) > trunc else r.event.raw_text}"
        for r in neighbours
    ] or ["(none)"]

    user_prompt = (
        f"Task id={task_id}\n"
        f"Description: {description}\n"
        f"Scheduled block: {planned_start_iso} → {planned_end_iso}\n\n"
        f"Relevant memory:\n" + "\n".join(ctx_lines) + "\n\n"
        f"Emit a prediction bundle per the system instructions."
    )

    try:
        raw = llm.chat(SYSTEM_PROMPT, user_prompt, temperature=0.2, format_json=True)
    except LLMError as e:
        raise SchedulerError(f"prediction LLM call failed: {e}") from e

    try:
        obj = parse_and_validate(raw, PredictionBundle)
        dur = obj.predicted_duration_min
        if dur <= 0:
            raise LLMRepairError(f"predicted_duration_min must be > 0, got {dur}")
            
        pre = (obj.pre.mood, obj.pre.energy, obj.pre.productivity)
        post = (obj.post.mood, obj.post.energy, obj.post.productivity)

        confidences = {
            "duration": obj.confidence.duration,
            "pre_mood": obj.confidence.pre_mood,
            "pre_energy": obj.confidence.pre_energy,
            "pre_productivity": obj.confidence.pre_productivity,
            "post_mood": obj.confidence.post_mood,
            "post_energy": obj.confidence.post_energy,
            "post_productivity": obj.confidence.post_productivity,
        }
        rationale = obj.rationale.strip() if obj.rationale else ""
    except LLMRepairError as e:
        raise SchedulerError(f"prediction output could not be parsed: {e}") from e

    # Spec: when there is no relevant history, this is a first-time schedule.
    # Prediction bundle is emitted with confidence = BOOTSTRAP_FIRST_SCHEDULE_CONFIDENCE
    # across all axes. We floor any LLM-supplied confidences at this level when
    # retrieval was empty — honest low confidence, not a fabricated high one.
    if not neighbours:
        log_bootstrap_use(
            conn,
            "BOOTSTRAP_FIRST_SCHEDULE_CONFIDENCE",
            BOOTSTRAP_FIRST_SCHEDULE_CONFIDENCE,
        )
        confidences = {
            k: BOOTSTRAP_FIRST_SCHEDULE_CONFIDENCE
            for k in confidences
        }

    rationale_emb = embedder.embed(rationale) if rationale else None

    return write_prediction(
        conn,
        task_id=task_id,
        google_event_id=google_event_id,
        predicted_duration_min=dur,
        pre=pre,
        post=post,
        confidences=confidences,
        rationale=rationale,
        embedding=rationale_emb,
    )
