from __future__ import annotations

from datetime import datetime, timedelta, timezone

from caden.learning.engine import apply_learning_updates, detect_phase_shift
from caden.libbie.store import write_task


class _Embedder:
    def embed(self, text: str):
        return [0.1] * 768


def _seed_residuals(db_conn, *, count: int, duration_residual_min: int) -> None:
    task_id = write_task(
        db_conn,
        description="Adaptation seed task",
        deadline_iso=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        google_task_id="g_learning_adapt_seed",
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
                0.2,
                0.2,
                0.2,
                0.2,
                0.2,
                0.2,
                (datetime.now(timezone.utc) - timedelta(minutes=count - idx)).isoformat(),
            ),
        )
    db_conn.commit()


def test_learning_detect_phase_shift_from_biased_residual_direction(db_conn):
    _seed_residuals(db_conn, count=24, duration_residual_min=30)

    signal = detect_phase_shift(db_conn, lookback_days=30, min_samples=20)

    assert signal.sample_count >= 20
    assert signal.biased is True
    assert signal.direction == "positive"
    assert signal.pvalue < 0.05


def test_learning_apply_updates_logs_weight_and_schema_events(db_conn):
    _seed_residuals(db_conn, count=30, duration_residual_min=45)

    # Seed stable prior updates so schema growth trigger can require plateau.
    for _ in range(4):
        db_conn.execute(
            """
            INSERT INTO events (source, raw_text, meta_json, timestamp)
            VALUES ('learning_update', 'stable', ?, datetime('now'))
            """,
            ('{"weights": {"duration": 0.5, "pre_mood": 0.5}}',),
        )
    db_conn.commit()

    result = apply_learning_updates(db_conn, embedder=_Embedder(), lookback_days=30)

    assert result.snapshot.row_count >= 30
    assert result.retrieval_weights
    assert result.schema_proposal is not None
    assert result.weight_plateau is True
    assert result.logged_event_ids

    sources = {
        row["source"]
        for row in db_conn.execute(
            "SELECT source FROM events WHERE id IN ({})".format(
                ",".join("?" for _ in result.logged_event_ids)
            ),
            result.logged_event_ids,
        ).fetchall()
    }
    assert "learning_update" in sources
    assert "schema_growth_proposal" in sources
    assert "schema_growth_pending" in sources
    assert "phase_change" in sources

    update_meta = db_conn.execute(
        "SELECT meta_json FROM events WHERE source='learning_update' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert update_meta is not None
    assert '"applied_recency_bias": 1.5' in update_meta["meta_json"]

    proposal_meta = db_conn.execute(
        "SELECT meta_json FROM events WHERE source='schema_growth_proposal' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert proposal_meta is not None
    assert '"backfill_success_rate":' in proposal_meta["meta_json"]
    assert '"heldout_improvement":' in proposal_meta["meta_json"]

    pending_meta = db_conn.execute(
        "SELECT meta_json FROM events WHERE source='schema_growth_pending' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert pending_meta is not None
    assert '"proposal_event_id":' in pending_meta["meta_json"]
    assert '"proposal_confidence":' in pending_meta["meta_json"]
    assert '"lookback_days":' in pending_meta["meta_json"]
