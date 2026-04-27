import pandas as pd
import pytest

from caden.learning.optimize import (
    ScheduleCandidate,
    detect_directional_bias,
    infer_preference_weights,
    pareto_frontier,
    rank_frontier_with_preferences,
)
from caden.learning.phase import mann_kendall_trend
from caden.libbie.store import write_task
from caden.learning.weights import (
    RidgeWeights,
    derive_retrieval_weights_from_residual_summary,
    fit_residual_ridge,
    score_with_weights,
    validate_learned_parameters,
)
from caden.scheduler.residual import aggregate_residuals_by_mechanism


def test_fit_residual_ridge_learns_weights_from_residual_frame():
    frame = pd.DataFrame(
        [
            {"x1": 0.0, "x2": 1.0, "target": 1.0},
            {"x1": 1.0, "x2": 0.0, "target": 2.0},
            {"x1": 2.0, "x2": 1.0, "target": 4.0},
            {"x1": 3.0, "x2": 1.0, "target": 6.0},
        ]
    )

    weights = fit_residual_ridge(frame, target="target", alpha=1.0)

    assert weights.feature_names == ("x1", "x2")
    assert len(weights.coefficients) == 2

    scored = score_with_weights(weights, {"x1": 2.5, "x2": 1.0})
    assert isinstance(scored, float)


def test_fit_residual_ridge_rejects_missing_target():
    frame = pd.DataFrame([{"x": 1.0}])
    with pytest.raises(ValueError, match="target column"):
        fit_residual_ridge(frame, target="missing")


def test_mann_kendall_trend_detects_increasing_sequence():
    result = mann_kendall_trend([1.0, 2.0, 3.0, 4.0, 5.0])

    assert result.trend == "increasing"
    assert result.tau > 0
    assert result.pvalue < 0.05


def test_mann_kendall_trend_detects_no_trend_in_flat_sequence():
    result = mann_kendall_trend([2.0, 2.0, 2.0, 2.0, 2.0])

    assert result.trend == "no-trend"
    assert result.pvalue >= 0.05


def test_detect_directional_bias_uses_binomtest():
    result = detect_directional_bias(successes=90, trials=100, expected_rate=0.5)

    assert result.biased is True
    assert result.pvalue < 0.05


def test_detect_directional_bias_rejects_invalid_counts():
    with pytest.raises(ValueError, match="between 0 and trials"):
        detect_directional_bias(successes=11, trials=10)


def test_validate_learned_parameters_fails_loudly_on_non_finite_or_exploded_values():
    with pytest.raises(ValueError, match="non-finite"):
        validate_learned_parameters(
            RidgeWeights(
                feature_names=("x",),
                intercept=float("nan"),
                coefficients=(0.1,),
                alpha=1.0,
            )
        )

    with pytest.raises(ValueError, match="beyond max_abs_value"):
        validate_learned_parameters(
            RidgeWeights(
                feature_names=("x",),
                intercept=0.0,
                coefficients=(2_000_000.0,),
                alpha=1.0,
            )
        )


def test_derive_retrieval_weights_moves_weight_toward_lower_residual_mechanisms():
    summary = pd.DataFrame(
        [
            {"mechanism": "mood", "mean_abs_residual": 0.1},
            {"mechanism": "energy", "mean_abs_residual": 0.8},
        ]
    )

    weights = derive_retrieval_weights_from_residual_summary(summary)

    assert set(weights.keys()) == {"mood", "energy"}
    assert weights["mood"] > weights["energy"]


def test_aggregate_residuals_by_mechanism_produces_residual_quality_frame(db_conn):
    task_id = write_task(
        db_conn,
        description="Residual quality contract",
        deadline_iso="2026-05-01T12:00:00+00:00",
        google_task_id="g_residual_contract",
        embedding=[0.1] * 768,
    )
    pred_row = db_conn.execute(
        "INSERT INTO predictions (task_id, pred_duration_min, created_at) VALUES (?, 40, datetime('now'))",
        (task_id,),
    )
    prediction_id = int(pred_row.lastrowid)

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
        ) VALUES (?, 30, -10, 0.2, 0.1, -0.3, 0.4, -0.2, 0.5, datetime('now'))
        """
        ,
        (prediction_id,),
    )
    db_conn.commit()

    frame = aggregate_residuals_by_mechanism(db_conn)

    assert not frame.empty
    assert set(frame.columns) == {
        "mechanism",
        "sample_count",
        "mean_residual",
        "mean_abs_residual",
    }


def test_active_optimization_uses_pareto_frontier_for_three_axis_balance():
    candidates = [
        ScheduleCandidate(id="a", mood=0.7, energy=0.3, productivity=0.6),
        ScheduleCandidate(id="b", mood=0.6, energy=0.6, productivity=0.6),
        ScheduleCandidate(id="c", mood=0.5, energy=0.5, productivity=0.5),
    ]

    frontier = pareto_frontier(candidates)
    ids = {item.id for item in frontier}

    assert "c" not in ids
    assert ids == {"a", "b"}


def test_active_optimization_ranks_pareto_candidates_by_revealed_preferences():
    candidate_a = ScheduleCandidate(id="a", mood=0.8, energy=0.2, productivity=0.6)
    candidate_b = ScheduleCandidate(id="b", mood=0.4, energy=0.8, productivity=0.6)
    candidate_c = ScheduleCandidate(id="c", mood=0.6, energy=0.6, productivity=0.6)

    overrides = [
        (candidate_b, candidate_a),
        (candidate_b, candidate_c),
    ]
    preferences = infer_preference_weights(overrides)
    ranked = rank_frontier_with_preferences([candidate_a, candidate_b], preferences)

    assert preferences["energy"] > preferences["mood"]
    assert ranked[0].id == "b"


def test_active_optimization_does_not_invent_fixed_weights_without_signal():
    candidate_a = ScheduleCandidate(id="a", mood=0.6, energy=0.6, productivity=0.6)
    candidate_b = ScheduleCandidate(id="b", mood=0.6, energy=0.6, productivity=0.6)

    # No revealed preference signal: no synthetic fixed objective should be created.
    preferences = infer_preference_weights([(candidate_a, candidate_b)])
    ranked = rank_frontier_with_preferences([candidate_a, candidate_b], preferences)

    assert preferences == {}
    assert [item.id for item in ranked] == ["a", "b"]
