"""Residual computation on task completion.

On completion we know:
  - the actual end time (= now)
  - thus the actual duration (planned_start .. actual_end)
  - the predicted duration (from the predictions row)

For pre/post state residuals we look at the nearest ratings in a window
around the block boundaries, if any exist. If none exist yet (v0 cold start),
the corresponding residual fields remain NULL — truthful unknown.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

import pandas as pd

from ..config import STATE_RESIDUAL_WINDOW_MIN
from ..errors import SchedulerError
from ..libbie.store import write_residual


def _nearest_rating(
    conn: sqlite3.Connection,
    boundary_iso: str,
    window_min: int,
) -> tuple[float | None, float | None, float | None]:
    row = conn.execute(
        """
        SELECT r.mood, r.energy, r.productivity
        FROM ratings r
        JOIN events e ON e.id = r.event_id
        WHERE ABS(strftime('%s', e.timestamp) - strftime('%s', ?)) <= ?
        ORDER BY ABS(strftime('%s', e.timestamp) - strftime('%s', ?)) ASC
        LIMIT 1
        """,
        (boundary_iso, window_min * 60, boundary_iso),
    ).fetchone()
    if row is None:
        return (None, None, None)
    return (row["mood"], row["energy"], row["productivity"])


def _sub(observed: float | None, predicted: float | None) -> float | None:
    if observed is None or predicted is None:
        return None
    return float(observed) - float(predicted)


def aggregate_residuals_by_mechanism(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return a pandas aggregate of residual strength by mechanism."""
    frame = pd.read_sql_query(
        """
        SELECT
            duration_residual_min,
            pre_state_residual_mood,
            pre_state_residual_energy,
            pre_state_residual_productivity,
            post_state_residual_mood,
            post_state_residual_energy,
            post_state_residual_productivity
        FROM residuals
        """,
        conn,
    )
    if frame.empty:
        return pd.DataFrame(
            columns=["mechanism", "sample_count", "mean_residual", "mean_abs_residual"]
        )

    renamed = frame.rename(
        columns={
            "duration_residual_min": "duration",
            "pre_state_residual_mood": "pre_mood",
            "pre_state_residual_energy": "pre_energy",
            "pre_state_residual_productivity": "pre_productivity",
            "post_state_residual_mood": "post_mood",
            "post_state_residual_energy": "post_energy",
            "post_state_residual_productivity": "post_productivity",
        }
    )
    long_frame = renamed.melt(var_name="mechanism", value_name="residual").dropna(
        subset=["residual"]
    )
    if long_frame.empty:
        return pd.DataFrame(
            columns=["mechanism", "sample_count", "mean_residual", "mean_abs_residual"]
        )

    summary = (
        long_frame.groupby("mechanism", as_index=False)["residual"]
        .agg(
            sample_count="count",
            mean_residual="mean",
            mean_abs_residual=lambda values: values.abs().mean(),
        )
        .sort_values(["mean_abs_residual", "mechanism"], ascending=[False, True], kind="stable")
        .reset_index(drop=True)
    )
    return summary


def compute_and_store(
    conn: sqlite3.Connection,
    prediction_id: int,
    planned_start_iso: str,
    actual_end_iso: str,
) -> int:
    """Compute residuals for a completed task and write them. Returns residual id."""
    pred = conn.execute(
        """
        SELECT pred_duration_min,
               pred_pre_mood, pred_pre_energy, pred_pre_productivity,
               pred_post_mood, pred_post_energy, pred_post_productivity
        FROM predictions WHERE id=?
        """,
        (prediction_id,),
    ).fetchone()
    if pred is None:
        raise SchedulerError(f"no prediction with id={prediction_id}")

    try:
        start = datetime.fromisoformat(planned_start_iso)
        end = datetime.fromisoformat(actual_end_iso)
    except ValueError as e:
        raise SchedulerError(f"bad iso timestamps for residual: {e}") from e

    if end < start:
        actual_minutes = None
        duration_residual = None
    else:
        actual_minutes = max(0.0, (end - start).total_seconds() / 60.0)
        duration_residual = actual_minutes - float(pred["pred_duration_min"])

    window = STATE_RESIDUAL_WINDOW_MIN
    observed_pre = _nearest_rating(conn, planned_start_iso, window)
    observed_post = _nearest_rating(conn, actual_end_iso, window)

    pre_res = (
        _sub(observed_pre[0], pred["pred_pre_mood"]),
        _sub(observed_pre[1], pred["pred_pre_energy"]),
        _sub(observed_pre[2], pred["pred_pre_productivity"]),
    )
    post_res = (
        _sub(observed_post[0], pred["pred_post_mood"]),
        _sub(observed_post[1], pred["pred_post_energy"]),
        _sub(observed_post[2], pred["pred_post_productivity"]),
    )

    return write_residual(
        conn,
        prediction_id=prediction_id,
        duration_actual_min=actual_minutes,
        duration_residual_min=duration_residual,
        pre_residuals=pre_res,
        post_residuals=post_res,
        embedding=None,  # residual rows are numeric; the mirrored event text is what gets retrieved
    )
