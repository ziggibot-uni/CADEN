"""Emit a prediction bundle at scheduling time.

Per spec: every scheduled task gets a paired bundle of predictions
(duration + pre/post mood/energy/productivity + confidences), stored as both
a predictions row and a mirrored event. When retrieval is too thin to
justify a number, the LLM is instructed to emit null; the framework writes
NULL, truthfully.
"""

from __future__ import annotations

import sqlite3
from typing import Callable

from ..errors import SchedulerError, LLMError, LLMRepairError
from .. import diag
from ..libbie import curate, retrieve
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
    *,
    on_open: Callable[[], None] | None = None,
    on_thinking: Callable[[str], None] | None = None,
    on_content: Callable[[str], None] | None = None,
) -> int:
    """Compute and store a prediction bundle. Returns prediction id."""
    _ligand, context, _ranked = retrieve.recall_packets_for_query(
        conn,
        description,
        description_embedding,
        sources=(
            "rating",
            "residual",
            "prediction",
            "sean_chat",
            "task",
        ),
    )
    ctx_block = curate.package_recall_context(description, context.recalled_memories)

    desc_block = description

    user_prompt = (
        f"Task id={task_id}\n"
        f"Description: {desc_block}\n"
        f"Scheduled block: {planned_start_iso} → {planned_end_iso}\n\n"
        f"Libbie context:\n{ctx_block}\n\n"
        f"Emit a prediction bundle per the system instructions."
    )

    # Stream the call. format_json=True buffers the entire response and
    # makes the UI feel frozen on a 9B reasoning model; the spec's "LLM
    # Output Handling" section explicitly tolerates JSON wrapped in prose
    # / code fences at the repair layer, so streaming + parse_and_validate
    # is the right shape.
    try:
        raw, _thinking = llm.chat_stream(
            SYSTEM_PROMPT,
            user_prompt,
            temperature=0.2,
            max_tokens=1500,
            repeat_penalty=1.15,
            on_open=on_open,
            on_thinking=on_thinking,
            on_content=on_content,
        )
    except LLMError as e:
        diag.log("prediction ✗ llm error", repr(e))
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
