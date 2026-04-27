"""Residual-driven learning utilities.

These helpers are intentionally small and deterministic wrappers around
battle-tested libraries. They do not encode hand-written rules about Sean.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import pandas as pd
from sklearn.linear_model import Ridge


@dataclass(frozen=True)
class RidgeWeights:
	feature_names: tuple[str, ...]
	intercept: float
	coefficients: tuple[float, ...]
	alpha: float


def validate_learned_parameters(
	weights: RidgeWeights,
	*,
	max_abs_value: float = 1_000_000.0,
) -> None:
	"""Raise loudly when learned parameters diverge to invalid values."""
	values = [weights.intercept, *weights.coefficients]
	for value in values:
		if math.isnan(value) or math.isinf(value):
			raise ValueError(f"learned parameter diverged to non-finite value: {value}")
		if abs(value) > max_abs_value:
			raise ValueError(
				f"learned parameter diverged beyond max_abs_value={max_abs_value}: {value}"
			)


def fit_residual_ridge(
	frame: pd.DataFrame,
	*,
	target: str,
	features: tuple[str, ...] | None = None,
	alpha: float = 1.0,
) -> RidgeWeights:
	"""Fit a Ridge model for residual prediction and return learned weights.

	Missing feature values are filled with 0.0 so sparse cold-start rows stay
	usable. Target rows with NULL are dropped (no supervised signal).
	"""
	if target not in frame.columns:
		raise ValueError(f"target column {target!r} not found")

	if features is None:
		feature_names = tuple(col for col in frame.columns if col != target)
	else:
		feature_names = tuple(features)

	if not feature_names:
		raise ValueError("at least one feature column is required")

	missing = [name for name in feature_names if name not in frame.columns]
	if missing:
		raise ValueError(f"missing feature columns: {missing}")

	work = frame[list(feature_names) + [target]].copy()
	work = work.dropna(subset=[target])
	if work.empty:
		raise ValueError("no rows with non-null target available for fitting")

	x = work[list(feature_names)].fillna(0.0)
	y = work[target].astype(float)

	model = Ridge(alpha=alpha)
	model.fit(x, y)

	learned = RidgeWeights(
		feature_names=feature_names,
		intercept=float(model.intercept_),
		coefficients=tuple(float(v) for v in model.coef_),
		alpha=float(alpha),
	)
	validate_learned_parameters(learned)
	return learned


def score_with_weights(weights: RidgeWeights, features: dict[str, float | None]) -> float:
	"""Score one feature vector using learned Ridge coefficients."""
	total = weights.intercept
	for name, coef in zip(weights.feature_names, weights.coefficients):
		value = features.get(name)
		total += coef * (0.0 if value is None else float(value))
	return total


def derive_retrieval_weights_from_residual_summary(
	residual_summary: pd.DataFrame,
	*,
	min_weight: float = 0.1,
) -> dict[str, float]:
	"""Convert residual summary stats into retrieval mechanism weights.

	Mechanisms with lower mean absolute residual receive higher weight.
	"""
	required = {"mechanism", "mean_abs_residual"}
	if not required.issubset(set(residual_summary.columns)):
		raise ValueError("residual_summary must contain mechanism and mean_abs_residual columns")

	if residual_summary.empty:
		return {}

	frame = residual_summary[["mechanism", "mean_abs_residual"]].copy()
	frame["mean_abs_residual"] = frame["mean_abs_residual"].fillna(0.0).astype(float)
	# Inverse error -> higher score for mechanisms that predict better.
	frame["raw"] = 1.0 / (1.0 + frame["mean_abs_residual"])
	total = float(frame["raw"].sum())
	if total <= 0.0:
		return {str(row["mechanism"]): min_weight for _, row in frame.iterrows()}

	normalized = frame["raw"] / total
	span = max(0.0, 1.0 - float(min_weight))
	weights = min_weight + (normalized * span)
	return {
		str(mech): float(weight)
		for mech, weight in zip(frame["mechanism"], weights, strict=False)
	}
