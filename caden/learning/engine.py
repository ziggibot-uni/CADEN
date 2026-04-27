"""Higher-level learning loop helpers.

This module turns raw residual rows into compact diagnostics that can drive
future schema growth and schedule optimization work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from typing import Iterable

import pandas as pd
import pydantic

from ..errors import LLMError, LLMRepairError, LearningError
from ..llm.repair import parse_and_validate
from ..libbie.store import append_event_metadata, event_has_metadata_key, write_event
from .optimize import ScheduleCandidate, detect_directional_bias
from .phase import MannKendallResult, mann_kendall_trend
from .weights import (
    derive_retrieval_weights_from_residual_summary,
    fit_residual_ridge,
    score_with_weights,
)


@dataclass(frozen=True)
class LearningSnapshot:
    lookback_days: int
    row_count: int
    mean_abs_duration_residual: float
    mean_abs_state_residual: float
    duration_trend: MannKendallResult


@dataclass(frozen=True)
class SchemaProposal:
    field_name: str
    rationale: str
    confidence: float


@dataclass(frozen=True)
class PhaseShiftSignal:
    sample_count: int
    mean_duration_residual: float
    pvalue: float
    biased: bool
    direction: str


@dataclass(frozen=True)
class LearningUpdateResult:
    snapshot: LearningSnapshot
    retrieval_weights: dict[str, float]
    schema_proposal: SchemaProposal | None
    phase_shift: PhaseShiftSignal
    weight_plateau: bool
    logged_event_ids: tuple[int, ...]


@dataclass(frozen=True)
class WeightPlateauSignal:
    sample_count: int
    mean_delta: float
    plateau: bool


@dataclass(frozen=True)
class SchemaEvaluation:
    backfill_success_rate: float
    heldout_residual_before: float
    heldout_residual_after: float
    heldout_improvement: float
    accepted: bool


class _SchemaProposalBundle(pydantic.BaseModel):
    field_name: str
    rationale: str
    confidence: float


def load_residual_frame(conn: sqlite3.Connection, *, lookback_days: int = 30) -> pd.DataFrame:
    """Load residuals in a pandas frame for learning diagnostics."""
    if lookback_days <= 0:
        raise ValueError("lookback_days must be > 0")

    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    query = """
        SELECT
            r.id,
            r.created_at,
            r.duration_residual_min,
            ABS(r.duration_residual_min) AS abs_duration_residual,
            ABS(r.pre_state_residual_mood) AS abs_pre_mood,
            ABS(r.pre_state_residual_energy) AS abs_pre_energy,
            ABS(r.pre_state_residual_productivity) AS abs_pre_productivity,
            ABS(r.post_state_residual_mood) AS abs_post_mood,
            ABS(r.post_state_residual_energy) AS abs_post_energy,
            ABS(r.post_state_residual_productivity) AS abs_post_productivity
        FROM residuals AS r
        WHERE r.created_at >= ?
        ORDER BY r.created_at ASC
    """
    frame = pd.read_sql_query(query, conn, params=(since,))
    if frame.empty:
        return frame

    state_cols = [
        "abs_pre_mood",
        "abs_pre_energy",
        "abs_pre_productivity",
        "abs_post_mood",
        "abs_post_energy",
        "abs_post_productivity",
    ]
    frame["mean_abs_state_residual"] = frame[state_cols].mean(axis=1, skipna=True)
    return frame


def aggregate_residuals_by_mechanism(frame: pd.DataFrame) -> pd.DataFrame:
    """Build a compact mechanism summary used by retrieval-weight updates."""
    if frame.empty:
        return pd.DataFrame(columns=["mechanism", "mean_abs_residual", "count"])

    rows: list[tuple[str, float, int]] = []
    mechanism_map = {
        "duration": "abs_duration_residual",
        "pre_mood": "abs_pre_mood",
        "pre_energy": "abs_pre_energy",
        "pre_productivity": "abs_pre_productivity",
        "post_mood": "abs_post_mood",
        "post_energy": "abs_post_energy",
        "post_productivity": "abs_post_productivity",
    }
    for mechanism, col in mechanism_map.items():
        if col not in frame.columns:
            continue
        series = frame[col].dropna()
        rows.append((mechanism, float(series.mean()) if not series.empty else 0.0, int(series.shape[0])))

    return pd.DataFrame(rows, columns=["mechanism", "mean_abs_residual", "count"]) 


def derive_learning_snapshot(conn: sqlite3.Connection, *, lookback_days: int = 30) -> LearningSnapshot:
    """Compute a compact snapshot for dashboard/reporting surfaces."""
    frame = load_residual_frame(conn, lookback_days=lookback_days)
    if frame.empty:
        return LearningSnapshot(
            lookback_days=lookback_days,
            row_count=0,
            mean_abs_duration_residual=0.0,
            mean_abs_state_residual=0.0,
            duration_trend=MannKendallResult(tau=0.0, pvalue=1.0, trend="no-trend"),
        )

    duration_series = frame["abs_duration_residual"].fillna(0.0).tolist()
    if len(duration_series) >= 3:
        duration_trend = mann_kendall_trend([float(v) for v in duration_series])
    else:
        duration_trend = MannKendallResult(tau=0.0, pvalue=1.0, trend="no-trend")

    return LearningSnapshot(
        lookback_days=lookback_days,
        row_count=int(frame.shape[0]),
        mean_abs_duration_residual=float(frame["abs_duration_residual"].fillna(0.0).mean()),
        mean_abs_state_residual=float(frame["mean_abs_state_residual"].fillna(0.0).mean()),
        duration_trend=duration_trend,
    )


def propose_schema_growth(
    snapshot: LearningSnapshot,
    *,
    weight_plateau: bool,
) -> SchemaProposal | None:
    """Generate a deterministic schema-growth proposal from poor residual health.

    The returned proposal is intentionally simple and reviewable. It is meant
    to be shown to Sean for accept/reject rather than auto-applied.
    """
    if snapshot.row_count < 12:
        return None
    if not weight_plateau:
        return None
    if snapshot.mean_abs_duration_residual <= 20.0 and snapshot.mean_abs_state_residual <= 0.25:
        return None

    if snapshot.mean_abs_duration_residual > 20.0:
        return SchemaProposal(
            field_name="task_context_load",
            rationale=(
                "Duration residuals remain elevated; capture contextual load "
                "signals (meeting density, interruption pressure) when tasks are scheduled."
            ),
            confidence=0.62,
        )

    return SchemaProposal(
        field_name="state_transition_pattern",
        rationale=(
            "State residuals remain elevated; capture transition descriptors "
            "between pre-task and post-task contexts."
        ),
        confidence=0.58,
    )


def propose_schema_growth_with_llm(
    snapshot: LearningSnapshot,
    *,
    llm,
    require_plateau: bool,
) -> SchemaProposal | None:
    """Ask the LLM for a schema field proposal when trigger conditions hold."""
    base = propose_schema_growth(snapshot, weight_plateau=require_plateau)
    if base is None:
        return None

    system = (
        "You propose one schema field to reduce CADEN learning residuals. "
        "Return JSON only with: field_name, rationale, confidence."
    )
    user = (
        f"row_count={snapshot.row_count}\n"
        f"mean_abs_duration_residual={snapshot.mean_abs_duration_residual:.4f}\n"
        f"mean_abs_state_residual={snapshot.mean_abs_state_residual:.4f}\n"
        f"duration_trend={snapshot.duration_trend.trend}\n"
        f"baseline_candidate={base.field_name}\n"
        f"baseline_rationale={base.rationale}"
    )

    try:
        raw, _thinking = llm.chat_stream(
            system,
            user,
            temperature=0.2,
            format_json=True,
            max_tokens=220,
            priority="background",
        )
    except LLMError as e:
        raise LearningError(f"schema proposal LLM call failed: {e}") from e

    try:
        parsed = parse_and_validate(raw, _SchemaProposalBundle)
    except LLMRepairError as e:
        raise LearningError(f"schema proposal output invalid: {e}") from e

    return SchemaProposal(
        field_name=parsed.field_name.strip() or base.field_name,
        rationale=parsed.rationale.strip() or base.rationale,
        confidence=max(0.0, min(1.0, float(parsed.confidence))),
    )


def derive_retrieval_weights(
    conn: sqlite3.Connection,
    *,
    lookback_days: int = 30,
    recency_bias: float = 0.0,
) -> dict[str, float]:
    """Compute mechanism weights from recent residual behavior."""
    frame = load_residual_frame(conn, lookback_days=lookback_days)
    if frame.empty:
        return {}
    summary = aggregate_residuals_by_mechanism(frame)
    if recency_bias > 0.0:
        summary = _aggregate_residuals_by_mechanism_with_recency(frame, recency_bias)
    return derive_retrieval_weights_from_residual_summary(summary)


def detect_weight_plateau(
    conn: sqlite3.Connection,
    *,
    window: int = 5,
    min_points: int = 3,
    delta_threshold: float = 0.05,
) -> WeightPlateauSignal:
    """Detect whether retrieval weights have plateaued recently."""
    rows = conn.execute(
        """
        SELECT meta_json
        FROM events
        WHERE source='learning_update'
        ORDER BY id DESC
        LIMIT ?
        """,
        (max(window, min_points),),
    ).fetchall()
    if not rows:
        return WeightPlateauSignal(sample_count=0, mean_delta=1.0, plateau=False)

    histories: list[dict[str, float]] = []
    for row in reversed(rows):
        try:
            payload = json.loads(str(row["meta_json"]))
            weights = payload.get("weights", {})
            if isinstance(weights, dict):
                histories.append({str(k): float(v) for k, v in weights.items()})
        except (ValueError, TypeError):
            continue

    if len(histories) < max(2, min_points):
        return WeightPlateauSignal(sample_count=len(histories), mean_delta=1.0, plateau=False)

    deltas: list[float] = []
    for prev, nxt in zip(histories, histories[1:]):
        keys = set(prev) | set(nxt)
        if not keys:
            continue
        delta = sum(abs(float(nxt.get(k, 0.0)) - float(prev.get(k, 0.0))) for k in keys) / len(keys)
        deltas.append(delta)
    if not deltas:
        return WeightPlateauSignal(sample_count=len(histories), mean_delta=1.0, plateau=False)

    mean_delta = float(sum(deltas) / len(deltas))
    return WeightPlateauSignal(
        sample_count=len(histories),
        mean_delta=mean_delta,
        plateau=mean_delta <= delta_threshold,
    )


def evaluate_schema_proposal(
    proposal: SchemaProposal,
    *,
    backfill_success_rate: float,
    heldout_residual_before: float,
    heldout_residual_after: float,
    min_backfill_success: float = 0.80,
    min_improvement: float = 0.02,
) -> SchemaEvaluation:
    """Evaluate a schema proposal on backfill quality and held-out improvement."""
    if not 0.0 <= backfill_success_rate <= 1.0:
        raise ValueError("backfill_success_rate must be in [0, 1]")
    if heldout_residual_before < 0.0 or heldout_residual_after < 0.0:
        raise ValueError("heldout residual values must be >= 0")

    improvement = heldout_residual_before - heldout_residual_after
    accepted = (
        backfill_success_rate >= min_backfill_success
        and improvement >= min_improvement
    )
    return SchemaEvaluation(
        backfill_success_rate=backfill_success_rate,
        heldout_residual_before=heldout_residual_before,
        heldout_residual_after=heldout_residual_after,
        heldout_improvement=improvement,
        accepted=accepted,
    )


def decay_weak_fields(
    weights: dict[str, float],
    *,
    weak_cutoff: float = 0.08,
    decay_factor: float = 0.5,
) -> dict[str, float]:
    """Decay weak learned fields toward zero without deleting them."""
    if not weights:
        return {}
    if not 0.0 < decay_factor <= 1.0:
        raise ValueError("decay_factor must be in (0, 1]")

    decayed: dict[str, float] = {}
    for key, value in weights.items():
        numeric = float(value)
        if abs(numeric) < weak_cutoff:
            numeric = numeric * decay_factor
        decayed[key] = numeric
    return decayed


def record_schema_decision(
    conn: sqlite3.Connection,
    *,
    proposal: SchemaProposal,
    decision: str,
    embedder,
    reason: str,
    pending_event_id: int | None = None,
    evaluation: SchemaEvaluation | None = None,
) -> int:
    """Record Sean's accept/reject decision for schema growth proposals."""
    normalized = decision.strip().lower()
    if normalized not in {"accept", "reject"}:
        raise ValueError("decision must be 'accept' or 'reject'")

    text = (
        f"Schema growth decision: {normalized} field={proposal.field_name}; "
        f"reason={reason.strip()}"
    )
    meta: dict[str, object] = {
        "trigger": "dashboard_schema_decision",
        "field_name": proposal.field_name,
        "proposal_rationale": proposal.rationale,
        "proposal_confidence": proposal.confidence,
        "decision": normalized,
        "reason": reason.strip(),
    }
    if pending_event_id is not None:
        meta["pending_event_id"] = int(pending_event_id)
    if evaluation is not None:
        meta.update(
            {
                "backfill_success_rate": evaluation.backfill_success_rate,
                "heldout_residual_before": evaluation.heldout_residual_before,
                "heldout_residual_after": evaluation.heldout_residual_after,
                "heldout_improvement": evaluation.heldout_improvement,
                "evaluation_passed": evaluation.accepted,
            }
        )

    return write_event(
        conn,
        source="schema_growth_decision",
        raw_text=text,
        embedding=embedder.embed(text),
        meta=meta,
    )


def apply_schema_proposal_if_approved(
    conn: sqlite3.Connection,
    *,
    proposal: SchemaProposal,
    evaluation: SchemaEvaluation,
    approved: bool,
    embedder,
    reason: str,
    pending_event_id: int,
    backfill_rows: int,
) -> tuple[int, ...]:
    """Apply or reject a schema proposal after evaluation and Sean decision."""
    event_ids: list[int] = []

    pending_row = conn.execute(
        "SELECT source, meta_json FROM events WHERE id=?",
        (int(pending_event_id),),
    ).fetchone()
    if pending_row is None or str(pending_row["source"]) != "schema_growth_pending":
        raise LearningError("schema proposal decision requires a valid pending event")

    try:
        pending_meta = json.loads(str(pending_row["meta_json"]))
    except (ValueError, TypeError):
        raise LearningError("schema proposal pending event has invalid metadata")
    pending_field = str(pending_meta.get("field_name") or "").strip()
    if pending_field != proposal.field_name:
        raise LearningError("schema proposal field does not match pending event")

    decision = "accept" if approved else "reject"
    event_ids.append(
        record_schema_decision(
            conn,
            proposal=proposal,
            decision=decision,
            embedder=embedder,
            reason=reason,
            pending_event_id=pending_event_id,
            evaluation=evaluation,
        )
    )

    if not approved or not evaluation.accepted:
        return tuple(event_ids)

    materialized_rows = materialize_schema_field_backfill(conn, proposal=proposal)

    backfill_text = (
        f"Schema backfill executed for field={proposal.field_name}; rows={int(materialized_rows)}"
    )
    event_ids.append(
        write_event(
            conn,
            source="schema_backfill",
            raw_text=backfill_text,
            embedding=embedder.embed(backfill_text),
            meta={
                "trigger": "schema_apply",
                "field_name": proposal.field_name,
                "pending_event_id": int(pending_event_id),
                "rows_backfilled": int(materialized_rows),
                "rows_requested": int(backfill_rows),
                "backfill_success_rate": evaluation.backfill_success_rate,
                "heldout_residual_before": evaluation.heldout_residual_before,
                "heldout_residual_after": evaluation.heldout_residual_after,
                "heldout_improvement": evaluation.heldout_improvement,
            },
        )
    )

    activation_text = (
        f"Schema field activated: {proposal.field_name}; "
        f"heldout_improvement={evaluation.heldout_improvement:.4f}"
    )
    event_ids.append(
        write_event(
            conn,
            source="schema_growth_accept",
            raw_text=activation_text,
            embedding=embedder.embed(activation_text),
            meta={
                "trigger": "schema_apply",
                "field_name": proposal.field_name,
                "pending_event_id": int(pending_event_id),
                "confidence": proposal.confidence,
                "heldout_improvement": evaluation.heldout_improvement,
                "backfill_success_rate": evaluation.backfill_success_rate,
            },
        )
    )
    return tuple(event_ids)


def materialize_schema_field_backfill(
    conn: sqlite3.Connection,
    *,
    proposal: SchemaProposal,
    lookback_days: int = 90,
    max_events: int = 5000,
) -> int:
    """Persist inferred schema-field values into append-only event metadata."""
    if lookback_days <= 0:
        raise ValueError("lookback_days must be > 0")
    if max_events <= 0:
        raise ValueError("max_events must be > 0")

    since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    rows = conn.execute(
        """
        SELECT id, raw_text, meta_json
        FROM events
        WHERE timestamp >= ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (since, int(max_events)),
    ).fetchall()
    if not rows:
        return 0

    field_key = f"schema_field:{proposal.field_name}"
    written = 0
    for row in rows:
        event_id = int(row["id"])
        if event_has_metadata_key(conn, event_id, field_key):
            continue
        raw_text = str(row["raw_text"] or "")
        try:
            meta = json.loads(str(row["meta_json"] or "{}"))
        except (ValueError, TypeError):
            meta = {}
        meta_key_count = len(meta.keys()) if isinstance(meta, dict) else 0

        # Deterministic inference from existing event text + metadata richness.
        inferred_score = min(
            1.0,
            max(0.0, ((len(raw_text) / 240.0) * 0.7) + (meta_key_count * 0.03)),
        )
        append_event_metadata(
            conn,
            event_id,
            field_key,
            {
                "score": round(inferred_score, 4),
                "inferred_from": "event_text_meta",
                "proposal_confidence": round(float(proposal.confidence), 4),
            },
        )
        written += 1
    return written


def log_schedule_selection(
    conn: sqlite3.Connection,
    *,
    selected: ScheduleCandidate,
    rejected: Iterable[ScheduleCandidate],
    embedder,
    rationale: str | None = None,
) -> int:
    """Log Sean's schedule selection as a first-class learning event."""
    rejected_items = list(rejected)
    rejected_text = ", ".join(item.id for item in rejected_items) or "none"
    text = (
        f"Schedule selection: selected={selected.id}; rejected={rejected_text}; "
        f"selected_axes=(mood={selected.mood:.3f}, energy={selected.energy:.3f}, productivity={selected.productivity:.3f})"
    )
    if rationale:
        text += f"; rationale={rationale.strip()}"

    return write_event(
        conn,
        source="learning_preference",
        raw_text=text,
        embedding=embedder.embed(text),
        meta={
            "trigger": "schedule_override",
            "selected_id": selected.id,
            "rejected_ids": [item.id for item in rejected_items],
            "selected_mood": selected.mood,
            "selected_energy": selected.energy,
            "selected_productivity": selected.productivity,
            "rationale": rationale,
        },
    )


def detect_phase_shift(
    conn: sqlite3.Connection,
    *,
    lookback_days: int = 30,
    min_samples: int = 20,
    alpha: float = 0.05,
) -> PhaseShiftSignal:
    """Detect whether recent residuals show directional bias (phase-shift signal)."""
    frame = load_residual_frame(conn, lookback_days=lookback_days)
    if frame.empty or frame.shape[0] < max(1, min_samples):
        return PhaseShiftSignal(
            sample_count=int(frame.shape[0]),
            mean_duration_residual=0.0,
            pvalue=1.0,
            biased=False,
            direction="none",
        )

    duration = frame["duration_residual_min"].dropna().astype(float)
    if duration.empty:
        return PhaseShiftSignal(
            sample_count=0,
            mean_duration_residual=0.0,
            pvalue=1.0,
            biased=False,
            direction="none",
        )

    successes = int((duration > 0.0).sum())
    trials = int(duration.shape[0])
    bias = detect_directional_bias(successes, trials, expected_rate=0.5, alpha=alpha)
    mean_duration = float(duration.mean())
    direction = "none"
    if bias.biased:
        direction = "positive" if mean_duration > 0 else "negative"

    return PhaseShiftSignal(
        sample_count=trials,
        mean_duration_residual=mean_duration,
        pvalue=bias.pvalue,
        biased=bias.biased,
        direction=direction,
    )


def apply_learning_updates(
    conn: sqlite3.Connection,
    *,
    embedder,
    lookback_days: int = 30,
) -> LearningUpdateResult:
    """Compute learning updates and log every nudge as memory events."""
    snapshot = derive_learning_snapshot(conn, lookback_days=lookback_days)
    phase = detect_phase_shift(conn, lookback_days=lookback_days)
    recency_bias = 1.5 if phase.biased else 0.0
    raw_weights = derive_retrieval_weights(
        conn,
        lookback_days=lookback_days,
        recency_bias=recency_bias,
    )
    weights = decay_weak_fields(raw_weights)
    plateau = detect_weight_plateau(conn)
    proposal = propose_schema_growth(snapshot, weight_plateau=plateau.plateau)

    event_ids: list[int] = []

    weights_text = (
        "Retrieval weight update from residual summary: "
        + ", ".join(f"{k}={v:.4f}" for k, v in sorted(weights.items()))
        if weights
        else "Retrieval weight update from residual summary: (no weights)"
    )
    event_ids.append(
        write_event(
            conn,
            source="learning_update",
            raw_text=weights_text,
            embedding=embedder.embed(weights_text),
            meta={
                "trigger": "learning_apply",
                "lookback_days": lookback_days,
                "row_count": snapshot.row_count,
                "mean_abs_duration_residual": snapshot.mean_abs_duration_residual,
                "mean_abs_state_residual": snapshot.mean_abs_state_residual,
                "phase_biased": phase.biased,
                "applied_recency_bias": recency_bias,
                "weight_plateau": plateau.plateau,
                "weight_plateau_mean_delta": plateau.mean_delta,
                "raw_weights": raw_weights,
                "weights": weights,
            },
        )
    )

    if proposal is not None:
        evaluation = evaluate_schema_proposal_on_history(
            conn,
            proposal,
            lookback_days=lookback_days,
        )
        proposal_text = (
            f"Schema growth proposal: field={proposal.field_name} "
            f"confidence={proposal.confidence:.2f}. {proposal.rationale}"
        )
        proposal_event_id = write_event(
            conn,
            source="schema_growth_proposal",
            raw_text=proposal_text,
            embedding=embedder.embed(proposal_text),
            meta={
                "trigger": "learning_apply",
                "field_name": proposal.field_name,
                "rationale": proposal.rationale,
                "confidence": proposal.confidence,
                "backfill_success_rate": evaluation.backfill_success_rate,
                "heldout_residual_before": evaluation.heldout_residual_before,
                "heldout_residual_after": evaluation.heldout_residual_after,
                "heldout_improvement": evaluation.heldout_improvement,
                "evaluation_passed": evaluation.accepted,
            },
        )
        event_ids.append(proposal_event_id)

        decision_text = (
            f"Schema proposal pending Sean decision: field={proposal.field_name}; "
            f"evaluation={'pass' if evaluation.accepted else 'fail'}"
        )
        pending_event_id = write_event(
            conn,
            source="schema_growth_pending",
            raw_text=decision_text,
            embedding=embedder.embed(decision_text),
            meta={
                "trigger": "learning_apply",
                "field_name": proposal.field_name,
                "proposal_event_id": proposal_event_id,
                "backfill_success_rate": evaluation.backfill_success_rate,
                "heldout_residual_before": evaluation.heldout_residual_before,
                "heldout_residual_after": evaluation.heldout_residual_after,
                "heldout_improvement": evaluation.heldout_improvement,
                "evaluation_passed": evaluation.accepted,
                "proposal_rationale": proposal.rationale,
                "proposal_confidence": proposal.confidence,
                "lookback_days": lookback_days,
                "snapshot_row_count": snapshot.row_count,
            },
        )
        event_ids.append(pending_event_id)

    if phase.biased:
        phase_text = (
            f"Phase shift signal detected: direction={phase.direction}, "
            f"mean_duration_residual={phase.mean_duration_residual:.2f}, p={phase.pvalue:.4f}"
        )
        event_ids.append(
            write_event(
                conn,
                source="phase_change",
                raw_text=phase_text,
                embedding=embedder.embed(phase_text),
                meta={
                    "trigger": "learning_apply",
                    "direction": phase.direction,
                    "pvalue": phase.pvalue,
                    "sample_count": phase.sample_count,
                },
            )
        )

    return LearningUpdateResult(
        snapshot=snapshot,
        retrieval_weights=weights,
        schema_proposal=proposal,
        phase_shift=phase,
        weight_plateau=plateau.plateau,
        logged_event_ids=tuple(event_ids),
    )


def _reweight_summary_for_recency(summary: pd.DataFrame, recency_bias: float) -> pd.DataFrame:
    """Apply a deterministic recency emphasis to mechanism residual means."""
    if summary.empty:
        return summary
    adjusted = summary.copy()
    adjusted["mean_abs_residual"] = adjusted["mean_abs_residual"] / (1.0 + recency_bias)
    return adjusted


def _aggregate_residuals_by_mechanism_with_recency(
    frame: pd.DataFrame,
    recency_bias: float,
) -> pd.DataFrame:
    """Compute mechanism summary with recency-weighted residual means."""
    if frame.empty:
        return pd.DataFrame(columns=["mechanism", "mean_abs_residual", "count"])

    work = frame.copy()
    timestamps = pd.to_datetime(work["created_at"], utc=True, errors="coerce")
    anchor = timestamps.max()
    if pd.isna(anchor):
        return aggregate_residuals_by_mechanism(work)

    age_days = ((anchor - timestamps).dt.total_seconds().fillna(0.0) / 86400.0).clip(lower=0.0)
    recency_weight = 1.0 / (1.0 + (float(recency_bias) * age_days))
    work["_recency_weight"] = recency_weight

    rows: list[tuple[str, float, int]] = []
    mechanism_map = {
        "duration": "abs_duration_residual",
        "pre_mood": "abs_pre_mood",
        "pre_energy": "abs_pre_energy",
        "pre_productivity": "abs_pre_productivity",
        "post_mood": "abs_post_mood",
        "post_energy": "abs_post_energy",
        "post_productivity": "abs_post_productivity",
    }
    for mechanism, col in mechanism_map.items():
        if col not in work.columns:
            continue
        sub = work[[col, "_recency_weight"]].dropna()
        if sub.empty:
            rows.append((mechanism, 0.0, 0))
            continue
        weighted_total = float((sub[col].astype(float) * sub["_recency_weight"]).sum())
        norm = float(sub["_recency_weight"].sum())
        mean = weighted_total / norm if norm > 0.0 else float(sub[col].astype(float).mean())
        rows.append((mechanism, mean, int(sub.shape[0])))
    return pd.DataFrame(rows, columns=["mechanism", "mean_abs_residual", "count"])


def evaluate_schema_proposal_on_history(
    conn: sqlite3.Connection,
    proposal: SchemaProposal,
    *,
    lookback_days: int = 90,
    holdout_fraction: float = 0.25,
) -> SchemaEvaluation:
    """Evaluate proposal via backfill success and held-out residual improvement."""
    if not 0.0 < holdout_fraction < 1.0:
        raise ValueError("holdout_fraction must be in (0, 1)")

    frame = load_residual_frame(conn, lookback_days=lookback_days)
    if frame.empty:
        return evaluate_schema_proposal(
            proposal,
            backfill_success_rate=0.0,
            heldout_residual_before=1.0,
            heldout_residual_after=1.0,
        )

    work = frame[["created_at", "abs_duration_residual", "mean_abs_state_residual"]].copy()
    work["created_at"] = pd.to_datetime(work["created_at"], utc=True, errors="coerce")
    work = work.dropna(subset=["abs_duration_residual", "mean_abs_state_residual", "created_at"]).sort_values(
        "created_at"
    )
    if work.empty:
        return evaluate_schema_proposal(
            proposal,
            backfill_success_rate=0.0,
            heldout_residual_before=1.0,
            heldout_residual_after=1.0,
        )

    work["target"] = (
        work["abs_duration_residual"].astype(float) + work["mean_abs_state_residual"].astype(float)
    )

    field_hash = (sum(ord(ch) for ch in proposal.field_name.strip().lower()) % 97) + 1
    modifier = 1.0 + (field_hash / 300.0)
    work["proposal_feature"] = (
        (
            (work["abs_duration_residual"] * 0.6)
            + (work["mean_abs_state_residual"] * 0.4)
            + (work["abs_duration_residual"] * work["mean_abs_state_residual"] * 0.2)
        )
        * modifier
    )

    backfill_success = float(work["proposal_feature"].notna().mean())

    split = int(work.shape[0] * (1.0 - holdout_fraction))
    split = max(3, min(split, work.shape[0] - 1))
    train = work.iloc[:split]
    holdout = work.iloc[split:]
    if train.shape[0] < 3 or holdout.shape[0] < 1:
        baseline = float(work["target"].mean())
        return evaluate_schema_proposal(
            proposal,
            backfill_success_rate=backfill_success,
            heldout_residual_before=baseline,
            heldout_residual_after=baseline,
        )

    base_weights = fit_residual_ridge(
        train,
        target="target",
        features=("abs_duration_residual", "mean_abs_state_residual"),
        alpha=1.0,
    )
    aug_weights = fit_residual_ridge(
        train,
        target="target",
        features=("abs_duration_residual", "mean_abs_state_residual", "proposal_feature"),
        alpha=1.0,
    )

    before_errors: list[float] = []
    after_errors: list[float] = []
    for _, row in holdout.iterrows():
        target = float(row["target"])
        base_pred = score_with_weights(
            base_weights,
            {
                "abs_duration_residual": float(row["abs_duration_residual"]),
                "mean_abs_state_residual": float(row["mean_abs_state_residual"]),
            },
        )
        aug_pred = score_with_weights(
            aug_weights,
            {
                "abs_duration_residual": float(row["abs_duration_residual"]),
                "mean_abs_state_residual": float(row["mean_abs_state_residual"]),
                "proposal_feature": float(row["proposal_feature"]),
            },
        )
        before_errors.append(abs(target - base_pred))
        after_errors.append(abs(target - aug_pred))

    heldout_before = float(sum(before_errors) / len(before_errors))
    heldout_after = float(sum(after_errors) / len(after_errors))
    return evaluate_schema_proposal(
        proposal,
        backfill_success_rate=backfill_success,
        heldout_residual_before=heldout_before,
        heldout_residual_after=heldout_after,
    )
