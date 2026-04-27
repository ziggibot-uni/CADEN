from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from caden.errors import LearningError
from caden.learning.engine import (
    apply_schema_proposal_if_approved,
    decay_weak_fields,
    detect_weight_plateau,
    derive_learning_snapshot,
    derive_retrieval_weights,
    evaluate_schema_proposal,
    evaluate_schema_proposal_on_history,
    load_residual_frame,
    log_schedule_selection,
    materialize_schema_field_backfill,
    propose_schema_growth_with_llm,
    propose_schema_growth,
    record_schema_decision,
    SchemaProposal,
)
from caden.learning.optimize import ScheduleCandidate
from caden.libbie.store import write_task


def _seed_residuals(db_conn, *, count: int, duration_residual_min: int) -> None:
    task_id = write_task(
        db_conn,
        description="Learning engine seed task",
        deadline_iso=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        google_task_id="g_learning_seed",
        embedding=[0.1] * 768,
    )
    prediction_id = db_conn.execute(
        "INSERT INTO predictions (task_id, pred_duration_min, created_at) VALUES (?, ?, datetime('now'))",
        (task_id, 60),
    ).lastrowid
    for idx in range(count):
        db_conn.execute(
            """
            INSERT INTO residuals (
                prediction_id,
                duration_actual_min,
                duration_residual_min,
                pre_state_residual_mood,
                pre_state_residual_energy,
                pre_state_residual_productivity,
                post_state_residual_mood,
                post_state_residual_energy,
                post_state_residual_productivity,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prediction_id,
                60 + duration_residual_min,
                duration_residual_min,
                0.1,
                0.2,
                0.3,
                0.2,
                0.1,
                0.0,
                (datetime.now(timezone.utc) - timedelta(minutes=count - idx)).isoformat(),
            ),
        )
    db_conn.commit()


def test_learning_engine_load_residual_frame_validates_lookback(db_conn):
    with pytest.raises(ValueError, match="lookback_days must be > 0"):
        load_residual_frame(db_conn, lookback_days=0)


def test_learning_engine_snapshot_and_weight_derivation_from_residuals(db_conn):
    _seed_residuals(db_conn, count=6, duration_residual_min=-20)

    snapshot = derive_learning_snapshot(db_conn, lookback_days=30)
    weights = derive_retrieval_weights(db_conn, lookback_days=30)

    assert snapshot.row_count == 6
    assert snapshot.mean_abs_duration_residual > 0
    assert snapshot.mean_abs_state_residual > 0
    assert isinstance(weights, dict)
    assert "duration" in weights


def test_learning_engine_recency_weighted_refit_prefers_recent_signal(db_conn):
    task_id = write_task(
        db_conn,
        description="Recency weighting seed task",
        deadline_iso=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        google_task_id="g_learning_recency_seed",
        embedding=[0.1] * 768,
    )
    prediction_id = db_conn.execute(
        "INSERT INTO predictions (task_id, pred_duration_min, created_at) VALUES (?, ?, datetime('now'))",
        (task_id, 60),
    ).lastrowid

    old_time = (datetime.now(timezone.utc) - timedelta(days=28)).isoformat()
    new_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    db_conn.execute(
        """
        INSERT INTO residuals (
            prediction_id,
            duration_actual_min,
            duration_residual_min,
            pre_state_residual_mood,
            pre_state_residual_energy,
            pre_state_residual_productivity,
            post_state_residual_mood,
            post_state_residual_energy,
            post_state_residual_productivity,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (prediction_id, 140, 80, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, old_time),
    )
    db_conn.execute(
        """
        INSERT INTO residuals (
            prediction_id,
            duration_actual_min,
            duration_residual_min,
            pre_state_residual_mood,
            pre_state_residual_energy,
            pre_state_residual_productivity,
            post_state_residual_mood,
            post_state_residual_energy,
            post_state_residual_productivity,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (prediction_id, 65, 5, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, new_time),
    )
    db_conn.commit()

    no_bias = derive_retrieval_weights(db_conn, lookback_days=30, recency_bias=0.0)
    with_bias = derive_retrieval_weights(db_conn, lookback_days=30, recency_bias=1.5)

    assert with_bias["duration"] > no_bias["duration"]


def test_learning_engine_schema_proposal_requires_enough_signal(db_conn):
    _seed_residuals(db_conn, count=5, duration_residual_min=-5)
    small_snapshot = derive_learning_snapshot(db_conn, lookback_days=30)
    assert propose_schema_growth(small_snapshot, weight_plateau=True) is None

    _seed_residuals(db_conn, count=15, duration_residual_min=-45)
    strong_snapshot = derive_learning_snapshot(db_conn, lookback_days=30)
    proposal = propose_schema_growth(strong_snapshot, weight_plateau=True)

    assert proposal is not None
    assert proposal.field_name in {"task_context_load", "state_transition_pattern"}
    assert proposal.confidence > 0


def test_learning_engine_schema_growth_requires_weight_plateau(db_conn):
    _seed_residuals(db_conn, count=20, duration_residual_min=-45)
    snapshot = derive_learning_snapshot(db_conn, lookback_days=30)

    assert propose_schema_growth(snapshot, weight_plateau=False) is None


def test_learning_engine_detect_weight_plateau_from_stable_updates(db_conn):
    for _ in range(4):
        db_conn.execute(
            """
            INSERT INTO events (source, raw_text, meta_json, timestamp)
            VALUES ('learning_update', 'stable', ?, datetime('now'))
            """,
            ('{"weights": {"duration": 0.5, "pre_mood": 0.5}}',),
        )
    db_conn.commit()

    signal = detect_weight_plateau(db_conn)

    assert signal.sample_count >= 3
    assert signal.plateau is True
    assert signal.mean_delta <= 0.05


def test_learning_engine_logs_schedule_selection_as_learning_event(db_conn):
    class _Embedder:
        def embed(self, text: str):
            return [0.1] * 768

    event_id = log_schedule_selection(
        db_conn,
        selected=ScheduleCandidate(id="opt_a", mood=0.7, energy=0.6, productivity=0.5),
        rejected=[
            ScheduleCandidate(id="opt_b", mood=0.9, energy=0.3, productivity=0.4),
            ScheduleCandidate(id="opt_c", mood=0.4, energy=0.7, productivity=0.4),
        ],
        embedder=_Embedder(),
        rationale="Energy consistency mattered more.",
    )

    row = db_conn.execute(
        "SELECT source, raw_text FROM events WHERE id=?",
        (event_id,),
    ).fetchone()
    assert row is not None
    assert row["source"] == "learning_preference"
    assert "selected=opt_a" in row["raw_text"]


def test_learning_engine_evaluates_schema_proposal_with_backfill_and_heldout_signal():
    proposal = SchemaProposal(
        field_name="task_context_load",
        rationale="Need missing context features",
        confidence=0.62,
    )

    evaluation = evaluate_schema_proposal(
        proposal,
        backfill_success_rate=0.91,
        heldout_residual_before=0.42,
        heldout_residual_after=0.34,
    )

    assert evaluation.accepted is True
    assert evaluation.backfill_success_rate == pytest.approx(0.91)
    assert evaluation.heldout_improvement == pytest.approx(0.08)


def test_learning_engine_evaluates_schema_proposal_on_real_history(db_conn):
    _seed_residuals(db_conn, count=24, duration_residual_min=-45)
    proposal = SchemaProposal(
        field_name="task_context_load",
        rationale="Need missing context features",
        confidence=0.62,
    )

    evaluation = evaluate_schema_proposal_on_history(
        db_conn,
        proposal,
        lookback_days=30,
    )

    assert evaluation.backfill_success_rate > 0.0
    assert evaluation.heldout_residual_before >= 0.0
    assert evaluation.heldout_residual_after >= 0.0


def test_learning_engine_decays_weak_fields_toward_zero_without_deleting():
    decayed = decay_weak_fields(
        {
            "duration": 0.50,
            "weak_hint": 0.04,
        },
        weak_cutoff=0.08,
        decay_factor=0.5,
    )

    assert decayed["duration"] == pytest.approx(0.50)
    assert decayed["weak_hint"] == pytest.approx(0.02)


def test_learning_engine_records_schema_veto_decision_as_event(db_conn):
    class _Embedder:
        def embed(self, text: str):
            return [0.1] * 768

    proposal = SchemaProposal(
        field_name="task_context_load",
        rationale="Need missing context features",
        confidence=0.62,
    )
    event_id = record_schema_decision(
        db_conn,
        proposal=proposal,
        decision="reject",
        embedder=_Embedder(),
        reason="Not enough confidence for rollout yet.",
    )

    row = db_conn.execute(
        "SELECT source, raw_text FROM events WHERE id=?",
        (event_id,),
    ).fetchone()
    assert row is not None
    assert row["source"] == "schema_growth_decision"
    assert "reject field=task_context_load" in row["raw_text"]


def test_learning_engine_generates_schema_proposal_via_llm(db_conn):
    class _LLM:
        def chat_stream(self, system, user, **kwargs):
            return (
                '{"field_name": "task_context_load", "rationale": "Meeting density appears missing.", "confidence": 0.73}',
                "",
            )

    _seed_residuals(db_conn, count=20, duration_residual_min=-45)
    snapshot = derive_learning_snapshot(db_conn, lookback_days=30)

    proposal = propose_schema_growth_with_llm(
        snapshot,
        llm=_LLM(),
        require_plateau=True,
    )

    assert proposal is not None
    assert proposal.field_name == "task_context_load"
    assert proposal.confidence == pytest.approx(0.73)


def test_learning_engine_applies_approved_schema_with_backfill_and_activation_events(db_conn):
    class _Embedder:
        def embed(self, text: str):
            return [0.1] * 768

    proposal = SchemaProposal(
        field_name="task_context_load",
        rationale="Need context load signal",
        confidence=0.62,
    )
    evaluation = evaluate_schema_proposal(
        proposal,
        backfill_success_rate=0.90,
        heldout_residual_before=0.50,
        heldout_residual_after=0.42,
    )

    pending_event_id = db_conn.execute(
        """
        INSERT INTO events (source, raw_text, meta_json, timestamp)
        VALUES ('schema_growth_pending', 'pending', ?, datetime('now'))
        """,
        ('{"field_name": "task_context_load", "evaluation_passed": true}',),
    ).lastrowid
    db_conn.commit()

    event_ids = apply_schema_proposal_if_approved(
        db_conn,
        proposal=proposal,
        evaluation=evaluation,
        approved=True,
        embedder=_Embedder(),
        reason="Looks good; proceed.",
        pending_event_id=int(pending_event_id),
        backfill_rows=120,
    )

    sources = {
        row["source"]
        for row in db_conn.execute(
            "SELECT source FROM events WHERE id IN ({})".format(
                ",".join("?" for _ in event_ids)
            ),
            event_ids,
        ).fetchall()
    }
    assert "schema_growth_decision" in sources
    assert "schema_backfill" in sources
    assert "schema_growth_accept" in sources

    materialized = db_conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM event_metadata
        WHERE key='schema_field:task_context_load'
        """
    ).fetchone()
    assert materialized is not None
    assert int(materialized["n"]) >= 1


def test_learning_engine_schema_apply_requires_valid_pending_event(db_conn):
    class _Embedder:
        def embed(self, text: str):
            return [0.1] * 768

    proposal = SchemaProposal(
        field_name="task_context_load",
        rationale="Need context load signal",
        confidence=0.62,
    )
    evaluation = evaluate_schema_proposal(
        proposal,
        backfill_success_rate=0.90,
        heldout_residual_before=0.50,
        heldout_residual_after=0.42,
    )

    with pytest.raises(LearningError, match="pending event"):
        apply_schema_proposal_if_approved(
            db_conn,
            proposal=proposal,
            evaluation=evaluation,
            approved=True,
            embedder=_Embedder(),
            reason="Looks good; proceed.",
            pending_event_id=999999,
            backfill_rows=120,
        )


def test_learning_engine_materializes_schema_field_backfill_as_event_metadata(db_conn):
    class _Embedder:
        def embed(self, text: str):
            return [0.1] * 768

    event_id = db_conn.execute(
        """
        INSERT INTO events (source, raw_text, meta_json, timestamp)
        VALUES ('sean_chat', 'Need better context signal', '{"trigger":"chat_send"}', datetime('now'))
        """
    ).lastrowid
    db_conn.commit()

    proposal = SchemaProposal(
        field_name="task_context_load",
        rationale="Need context load signal",
        confidence=0.62,
    )
    written = materialize_schema_field_backfill(
        db_conn,
        proposal=proposal,
        lookback_days=30,
        max_events=100,
    )

    assert written >= 1
    row = db_conn.execute(
        """
        SELECT value
        FROM event_metadata
        WHERE event_id=? AND key='schema_field:task_context_load'
        ORDER BY id DESC
        LIMIT 1
        """,
        (int(event_id),),
    ).fetchone()
    assert row is not None
    assert '"inferred_from": "event_text_meta"' in row["value"]
